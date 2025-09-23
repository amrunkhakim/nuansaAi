import os
import json
import time
import google.generativeai as genai
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth

load_dotenv()

app = Flask(__name__)
# Konfigurasi sesi untuk mengatasi masalah state di environment http
app.config['SESSION_COOKIE_NAME'] = 'google-login-session'
app.config['SESSION_COOKIE_SECURE'] = False
app.secret_key = os.urandom(24)

oauth = OAuth(app)
# Konfigurasi Authlib yang sudah diperbaiki
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    access_token_url='https://accounts.google.com/o/oauth2/token',
    access_token_params=None,
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    authorize_params=None,
    api_base_url='https://www.googleapis.com/oauth2/v1/',
    userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
    client_kwargs={'scope': 'openid email profile'},
    # --- PERUBAHAN DI SINI ---
    # Kita tetap tidak menggunakan metadata, tetapi kita berikan lokasi JWKS secara manual
    server_metadata_url=None, 
    jwks_uri="https://www.googleapis.com/oauth2/v3/certs"
)
BASE_USERS_DIR = "users"
if not os.path.exists(BASE_USERS_DIR):
    os.makedirs(BASE_USERS_DIR)

model = None
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    print("AI Model berhasil diinisialisasi.")
except Exception as e:
    print(f"Error saat inisialisasi AI Model: {e}")

# --- Rute Utama & Otentikasi ---
@app.route('/')
def index():
    if 'user' in session:
        return render_template('index.html', user=session.get('user'))
    return redirect(url_for('show_login_page'))

@app.route('/login')
def show_login_page():
    return render_template('login.html')

@app.route('/signin-google')
def signin_google():
    redirect_uri = url_for('auth', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth')
def auth():
    token = google.authorize_access_token()
    # Dengan konfigurasi baru, userinfo akan divalidasi dengan benar di sini
    user_info = google.get('userinfo').json()
    session['user'] = user_info
    user_dir = os.path.join(BASE_USERS_DIR, user_info['id'])
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    return redirect('/')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('show_login_page'))

# --- Fungsi Helper & API Chat ---
def get_user_conversations_dir():
    if 'user' in session:
        user_id = session['user']['id']
        return os.path.join(BASE_USERS_DIR, user_id)
    return None

def get_conversation_title(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            history = json.load(f)
            for msg in history:
                if msg['role'] == 'user' and 'selalu membalas dalam Bahasa Indonesia' not in msg['parts'][0]:
                    return msg['parts'][0][:50] + '...'
    except (IOError, json.JSONDecodeError, IndexError):
        pass
    return "Percakapan Baru"

@app.route('/get_conversations')
def get_conversations():
    if 'user' not in session: return jsonify({"error": "Unauthorized"}), 401
    user_dir = get_user_conversations_dir()
    if not user_dir or not os.path.exists(user_dir): return jsonify([])
    
    files = sorted(os.listdir(user_dir), reverse=True)
    conversations = []
    for filename in files:
        if filename.endswith(".json"):
            conversation_id = filename[:-5]
            title = get_conversation_title(os.path.join(user_dir, filename))
            conversations.append({'id': conversation_id, 'title': title})
    return jsonify(conversations)

@app.route('/get_history/<conversation_id>')
def get_history(conversation_id):
    if 'user' not in session: return jsonify({"error": "Unauthorized"}), 401
    user_dir = get_user_conversations_dir()
    filepath = os.path.join(user_dir, f"{conversation_id}.json")
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            history = json.load(f)
            return jsonify(history[2:] if len(history) > 2 else [])
    return jsonify([])

@app.route('/new_chat', methods=['POST'])
def new_chat():
    if 'user' not in session: return jsonify({"error": "Unauthorized"}), 401
    conversation_id = str(int(time.time()))
    return jsonify({'conversation_id': conversation_id})

@app.route('/chat', methods=['POST'])
def chat():
    if 'user' not in session: return jsonify({"error": "Unauthorized"}), 401
    if not model: return jsonify({'error': 'Model AI tidak terinisialisasi.'}), 500

    data = request.json
    user_message = data.get('message')
    conversation_id = data.get('conversation_id')
    user_dir = get_user_conversations_dir()
    filepath = os.path.join(user_dir, f"{conversation_id}.json")
    history = []
    
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []
    else:
        history.extend([
            {'role': 'user', 'parts': ['Penting: Kamu harus selalu membalas setiap pertanyaan dalam Bahasa Indonesia, tanpa kecuali.']},
            {'role': 'model', 'parts': ['Tentu, saya paham. Saya akan selalu membalas dalam Bahasa Indonesia.']}
        ])

    try:
        chat_session = model.start_chat(history=history)
        response = chat_session.send_message(user_message)
        with open(filepath, 'w', encoding='utf-8') as f:
            history_data = [{'role': msg.role, 'parts': [msg.parts[0].text]} for msg in chat_session.history]
            json.dump(history_data, f, indent=2)
        return jsonify({'response': response.text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)