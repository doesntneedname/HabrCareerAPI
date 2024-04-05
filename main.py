from flask import Flask, redirect, request, session, jsonify, json
from flask_apscheduler import APScheduler
import requests
import urllib.parse
import math

app = Flask(__name__)

scheduler = APScheduler() 
scheduler.init_app(app)
scheduler.start()

CLIENT_ID = 'YOUR CLIENT ID' # Ваш клинент ID (находится в настройках созданного вами приложения на Хабр https://career.habr.com/profile/applications -> "настройки")
CLIENT_SECRET = 'YOUR CLIENT SECRET' # Ваш клиент секрет (находится там же)
REDIRECT_URI = 'http://localhost:5000/callback'# Ссылка возрата (нужно задать в настройках приложения на Хабр, в разделе "редактировать")

AUTH_URL = 'https://career.habr.com/integrations/oauth/authorize' 
TOKEN_URL = 'https://career.habr.com/integrations/oauth/token' 
API_BASE_URL = 'https://career.habr.com/api/' 

WEBHOOK_URL = 'YOUR WEBHOOK URL' # Эту ссылку мы получим после того, как создадим инструмент, который принимает наш вебхук

CACHE_FILE_PATH = '.venv/cached_applies.json' # Путь к файлу с кешем
TOKEN_FILE_PATH = '.venv/access_token.txt' # Путь к файлу с токеном сессии

def load_cache(): # Загрузка кеша, берет кеш из файла и загружает в приложение
    try:
        with open(CACHE_FILE_PATH, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return []
cached_applies = load_cache()

def update_cache(new_ids): # Обновление кеша, обнвляет кеш 
    global cached_applies
    cached_applies.extend(new_ids)
    cached_applies = list(cached_applies)
    with open(CACHE_FILE_PATH, 'w') as file:
        json.dump(cached_applies, file)

      
def cleanup_cache(): # Очистка кеша, очишает последние 100 ID из списка если их накопилось больше 200.
    try:
        with open(CACHE_FILE_PATH, 'r') as file:
            cached_applies = json.load(file)
        
        if len(cached_applies) > 200: # Можно редактировать "200" здесь (при превышении какого значение чистить кеш)
            cached_applies = cached_applies[:100] # Можно редактировать "100" здесь (сколько ID оставить)
          
        with open(CACHE_FILE_PATH, 'w') as file:
            json.dump(cached_applies, file)
        print("Cache cleanup completed, if needed.")
    except Exception as e:
        print(f"Failed to cleanup cache: {str(e)}")

def save_access_token(token): # Сохранение токена в файле .venv/access_token.txt , изначально файл пустой
    with open(TOKEN_FILE_PATH, 'w') as file:
        file.write(token)

def load_access_token(): # Загрузка токена из файла .venv/access_token.txt , изначально файл пустой
    try:
        with open(TOKEN_FILE_PATH, 'r') as file:
            return file.read().strip()
    except FileNotFoundError:
        return None

@app.route('/')
def index():
    return "Login to Habr Career <a href='/login'>Login</a>"


@app.route('/login') 
def login():
    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code'
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    return redirect(auth_url)


@app.route('/callback') 
def callback():
    error = request.args.get('error')
    if error:
        return f"Error: {error}"

    code = request.args.get('code') 
    if code:
        req_body = {
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': REDIRECT_URI,
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET
        }
        try:
            response = requests.post(TOKEN_URL, data=req_body)
            response.raise_for_status()
            token_info = response.json()
            access_token = token_info['access_token']
            save_access_token(access_token) #
            return redirect('/vacancies')
        except requests.RequestException as e:
            return f"Error: {str(e)}"


@app.route('/vacancies') # Функция, которую мы будем вызывать триггером спустя определенное кол-во времени
def get_vacancies():
    access_token = load_access_token() # Загрузка токена, он перманентный, при перезапуске мы получим новый токен
    if not access_token:
        print("Access token is missing")
        return

    headers = {'Authorization': f"Bearer {access_token}", 'User-Agent': 'Chrome/123.0.0.0'}
    
    current_applies, new_applies = [], [] 
    cached_applies = load_cache() # Загрузка кеша

    vacancies_response = requests.get(API_BASE_URL + '/v1/integrations/vacancies/', headers=headers) 
    vacancies = vacancies_response.json()
    vacancies_ids = [val['id'] for val in vacancies['vacancies']]

    for vacancy_id in vacancies_ids: # Цикл просмотра ваших вакансий для получения их ID
        try:
            response = requests.get(f'{API_BASE_URL}v1/integrations/vacancies/{vacancy_id}/responses?page=1?access_token=${access_token}', headers=headers)
            response.raise_for_status()
            data = response.json()
            current_applies.extend(data['responses'])
        except requests.RequestException as e:
            print(f"Failed to fetch data for vacancy {vacancy_id}: {str(e)}")

    new_applies = [apply for apply in current_applies if apply['id'] not in cached_applies] # Фильтрация новых откликов по ID

    new_apply_ids = [apply['id'] for apply in new_applies] # Отбор новых ID для дальнейшего кеширования
    for apply in new_applies:
        user_login = apply['user']['login']
        user_name = apply['user']['name']
        experience = apply['user']['experience_total']['months']
        link = ('https://career.habr.com/' + apply['user']['login'])
        body = apply['body']
             
        experience = int(experience)
        years = experience / 12
        mounths = math.ceil(years * 2) / 2
        mounths = int(mounths)

        try: # Запрос названия вакансии 
            vacancy_response = requests.get(f'{API_BASE_URL}v1/integrations/vacancies/{apply["vacancy_id"]}?access_token=${access_token}', headers=headers)
            vacancy_response.raise_for_status()
            vacancy_data = vacancy_response.json()
            vacancy_title = vacancy_data["vacancy"]["title"]
        except requests.RequestException as e:
            print(f"Failed to fetch vacancy details for {apply['vacancy_id']}: {str(e)}")
            vacancy_title = "Unknown Title" 

        try: # Запрос со страницы пользователя и упаковка данных
            user_response = requests.get(f'{API_BASE_URL}v1/integrations/users/{user_login}?access_token=${access_token}', headers=headers)
            user_response.raise_for_status()
            user_info = user_response.json()
            

            email = user_info['contacts']['emails'][0]['value'] if user_info['contacts']['emails'] else None
            telegram = None
            for messenger in user_info['contacts']['messengers']:
                if messenger['type'] == 'telegram':
                    telegram = messenger['value']
                    break
            habr_profile_link = user_info['url']

            payload = { # Наш груз, то, что нужно будет принять, мы используем Mustache, то есть {{user_name}} будет отображать имя пользователя и тд.
                "user_name": user_name,                     # Имя Фамилия пользователя
                "vacancy_title": vacancy_title,             # Название вакансии, на которую пришел отклик
                "experience": mounths,                      # Опыт работы (в годах с математическим округлением)
                "email": email,                             # Почта пользователя (при наличии)
                "telegram": telegram,                       # ТГ пользователя (при наличии)
                "link" : link,                              # Ссылка на страницу на хабре
                "habr_profile_link": habr_profile_link,     # Ссвлка на указанную пользователем страницу (обычно там кандидаты оставляют резюме или ссылку на свой сайт-визитку) (при наличии)
                "body" : body,                              # Сопроводительное письмо (при наличии)
            }
            webhook_response = requests.post(WEBHOOK_URL, json=payload, headers={'Content-Type': 'application/json'}) # Отправка вебхука
            webhook_response.raise_for_status()
            print(f"Webhook sent successfully for user {user_login}")
        except requests.RequestException as e:
            print(f"Failed to send webhook or fetch user data for {user_login}: {str(e)}")
    update_cache(new_apply_ids) # Обновление кеша
    return (new_applies)



    
scheduler.add_job(id='Scheduled Task', func=get_vacancies, trigger='interval', seconds=1800) # Задачник: обращаться к функции раз в пол часа. то есть каждые пол часа приложение будет проверять новые отклики на ваши вакансии и в случае их нахождения отправлять вам вебхук

scheduler.add_job(id='cache_cleanup_task', func=cleanup_cache, trigger='interval', hours=24, name='Conditional cache cleanup',replace_existing=True) # Задачник: обращаться к функции очистки кеша.

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
