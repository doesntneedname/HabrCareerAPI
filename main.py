from flask import Flask, redirect, request, session, jsonify, json
from flask_apscheduler import APScheduler
import requests
import urllib.parse
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your secret key'

scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

CLIENT_ID = 'your client id'
CLIENT_SECRET = 'your client secret'
REDIRECT_URI = 'http://localhost:5000/callback'

AUTH_URL = 'https://career.habr.com/integrations/oauth/authorize'
TOKEN_URL = 'https://career.habr.com/integrations/oauth/token'
API_BASE_URL = 'https://career.habr.com/api/'

WEBHOOK_URL = 'your webhook url'

CACHE_FILE_PATH = '.venv/cached_applies.json'

def load_cache():
    try:
        with open(CACHE_FILE_PATH, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return []
cached_applies = load_cache()

def update_cache(new_ids):
    global cached_applies
    cached_applies.extend(new_ids)
    cached_applies = list(set(cached_applies))
    with open(CACHE_FILE_PATH, 'w') as file:
        json.dump(cached_applies, file)
      
def cleanup_cache():
    try:
        with open(CACHE_FILE_PATH, 'r') as file:
            cached_applies = json.load(file)
        
        if len(cached_applies) > 200:
            cached_applies = cached_applies[:100]
        
        with open(CACHE_FILE_PATH, 'w') as file:
            json.dump(cached_applies, file)
        print("Cache cleanup completed, if needed.")
    except Exception as e:
        print(f"Failed to cleanup cache: {str(e)}")

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
            session['access_token'] = token_info['access_token']
            return redirect('/vacancies')
        except requests.RequestException as e:
            return f"Error: {str(e)}"


@app.route('/vacancies')
def get_vacancies():
    access_token = session.get('access_token')
    if not access_token:
        return redirect('/login')
    
    print(access_token)

    headers = {'Authorization': f"Bearer {access_token}", 'User-Agent': 'Chrome/123.0.0.0'}
    
    current_applies, new_applies = [], []
    vacancies_ids = ['your vacancy id', 'your vacancy id', 'your vacancy id', 'your vacancy id'] #if you have only 1 vacancy, add vacancies_ids = ['your vacancy id'], if more, then add more.

    for vacancy_id in vacancies_ids:
        try:
            response = requests.get(f'{API_BASE_URL}v1/integrations/vacancies/{vacancy_id}/responses?page=1?access_token=${access_token}', headers=headers)
            response.raise_for_status()
            data = response.json()
            current_applies.extend(data['responses'])
        except requests.RequestException as e:
            print(f"Failed to fetch data for vacancy {vacancy_id}: {str(e)}")

    new_applies = [apply for apply in current_applies if apply['id'] not in cached_applies]

    new_apply_ids = [apply['id'] for apply in new_applies]
    update_cache(new_apply_ids)

    for apply in new_applies:
        user_login = apply['user']['login']
        user_name = apply['user']['name']
        experience = apply['user']['experience_total']['months']
        link = ('https://career.habr.com/' + apply['user']['login'])

        try:
            vacancy_response = requests.get(f'{API_BASE_URL}v1/integrations/vacancies/{apply["vacancy_id"]}?access_token=${access_token}', headers=headers)
            vacancy_response.raise_for_status()
            vacancy_data = vacancy_response.json()
            vacancy_title = vacancy_data["vacancy"]["title"]
        except requests.RequestException as e:
            print(f"Failed to fetch vacancy details for {apply['vacancy_id']}: {str(e)}")
            vacancy_title = "Unknown Title" 

        try:
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

            payload = {
                "user_name": user_name,
                "vacancy_title": vacancy_title,
                "experience": experience,
                "email": email,
                "telegram": telegram,
                "link" : link,
                "habr_profile_link": habr_profile_link,
            }
            webhook_response = requests.post(WEBHOOK_URL, json=payload, headers={'Content-Type': 'application/json'})
            webhook_response.raise_for_status()
            print(f"Webhook sent successfully for user {user_login}")
        except requests.RequestException as e:
            print(f"Failed to send webhook or fetch user data for {user_login}: {str(e)}")

    global cached_applies
    cached_applies.extend([apply['id'] for apply in new_applies])
    cached_applies = list(set(cached_applies))

    return jsonify(new_applies)

    
scheduler.add_job(id='Scheduled Task', func=get_vacancies, trigger='interval', seconds=60)

scheduler.add_job(id='cache_cleanup_task', func=cleanup_cache, trigger='interval', hours=24, name='Conditional cache cleanup',replace_existing=True)
if __name__ == '__main__':
    app.run(debug=True)
