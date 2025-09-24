import os
import json
import time
import google.generativeai as genai
from flask import Flask, render_template, request, Response, session, redirect, url_for
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth
from PIL import Image

load_dotenv()

app = Flask(__name__)
app.config['SESSION_COOKIE_NAME'] = 'google-login-session'
app.config['SESSION_COOKIE_SECURE'] = False
app.secret_key = os.urandom(24)

oauth = OAuth(app)
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

@app.route('/pricing')
def pricing():
    if 'user' not in session:
        return redirect(url_for('show_login_page'))
    return render_template('pricing.html', user=session.get('user'))

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
        for message in history:
            is_system_prompt = message['parts'][0].startswith('Penting: Kamu harus selalu membalas')
            if message['role'] == 'user' and not is_system_prompt:
                title = message['parts'][0]
                return title[:50] + '...' if len(title) > 50 else title
    except (IOError, json.JSONDecodeError, IndexError, KeyError):
        pass
    return "Percakapan Baru"

@app.route('/get_conversations')
def get_conversations():
    if 'user' not in session: return Response("Unauthorized", status=401)
    user_dir = get_user_conversations_dir()
    if not user_dir or not os.path.exists(user_dir): return Response(json.dumps([]), mimetype='application/json')
    
    files = sorted(os.listdir(user_dir), reverse=True)
    conversations = []
    for filename in files:
        if filename.endswith(".json"):
            conversation_id = filename[:-5]
            title = get_conversation_title(os.path.join(user_dir, filename))
            conversations.append({'id': conversation_id, 'title': title})
    return Response(json.dumps(conversations), mimetype='application/json')

@app.route('/get_history/<conversation_id>')
def get_history(conversation_id):
    if 'user' not in session: return Response("Unauthorized", status=401)
    user_dir = get_user_conversations_dir()
    filepath = os.path.join(user_dir, f"{conversation_id}.json")
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            history = json.load(f)
            history_to_show = history[2:] if len(history) > 2 else []
            return Response(json.dumps(history_to_show), mimetype='application/json')
    return Response(json.dumps([]), mimetype='application/json')

@app.route('/new_chat', methods=['POST'])
def new_chat():
    if 'user' not in session: return Response("Unauthorized", status=401)
    conversation_id = str(int(time.time()))
    return Response(json.dumps({'conversation_id': conversation_id}), mimetype='application/json')

@app.route('/chat', methods=['POST'])
def chat():
    if 'user' not in session: return Response("Unauthorized", status=401)
    if not model: return Response("Model AI tidak terinisialisasi.", status=500)

    user_message = request.form.get('message')
    conversation_id = request.form.get('conversation_id')
    image_file = request.files.get('image')

    # [PENGEMBANGAN] Ambil pengaturan temperatur dari frontend
    temperature_str = request.form.get('temperature', '0.7')
    try:
        # Batasi nilai temperature antara 0.0 dan 1.0
        temperature = max(0.0, min(1.0, float(temperature_str)))
    except (ValueError, TypeError):
        temperature = 0.7 # Nilai default jika input tidak valid

    if not user_message and not image_file: return Response("Pesan atau gambar tidak boleh kosong", status=400)
    if not conversation_id: return Response("Conversation ID tidak ditemukan", status=400)

    user_dir = get_user_conversations_dir()
    filepath = os.path.join(user_dir, f"{conversation_id}.json")
    history = []
    
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError: history = []
    
    if not history:
        history.extend([
            {'role': 'user', 'parts': ['Penting: Kamu harus selalu membalas setiap pertanyaan dalam Bahasa Indonesia, tanpa kecuali.']},
            {'role': 'model', 'parts': ['Tentu, saya paham. Saya akan selalu membalas dalam Bahasa Indonesia.']}
        ])
    
    try:
        contents = []
        prompt_for_history = user_message
        if image_file:
            img = Image.open(image_file.stream)
            contents.append(img)
        if user_message:
            contents.append(user_message)
        if image_file and not user_message:
            default_prompt = "Jelaskan gambar ini secara detail."
            contents.append(default_prompt)
            prompt_for_history = default_prompt
        
        # [PENGEMBANGAN] Buat konfigurasi generasi untuk model
        generation_config = genai.types.GenerationConfig(
            temperature=temperature
        )

        def stream_response_generator():
            full_response_text = ""
            chat_session = model.start_chat(history=history)
            
            # [PENGEMBANGAN] Gunakan generation_config saat mengirim pesan
            response_stream = chat_session.send_message(
                contents, 
                stream=True,
                generation_config=generation_config
            )
            
            for chunk in response_stream:
                if chunk.text:
                    yield chunk.text
                    full_response_text += chunk.text

            history.append({'role': 'user', 'parts': [prompt_for_history]})
            history.append({'role': 'model', 'parts': [full_response_text]})
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)

        return Response(stream_response_generator(), mimetype='text/plain')

    except Exception as e:
        app.logger.error(f"Error saat streaming chat: {e}")
        return Response(f"Terjadi kesalahan: {e}", status=500)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)