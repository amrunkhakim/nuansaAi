import os
import json
import time
import google.generativeai as genai
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth
from PIL import Image

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
            # Cari pesan pengguna pertama yang bukan prompt sistem
            for msg in history:
                if msg['role'] == 'user' and 'selalu membalas dalam Bahasa Indonesia' not in msg['parts'][0]:
                    # Ambil 50 karakter pertama dari pesan tersebut sebagai judul
                    return msg['parts'][0][:50] + '...'
    except (IOError, json.JSONDecodeError, IndexError, KeyError):
        pass
    # Jika gagal, kembalikan judul default
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
            # Jangan tampilkan 2 pesan sistem pertama di UI
            return jsonify(history[2:] if len(history) > 2 else [])
    return jsonify([])

@app.route('/new_chat', methods=['POST'])
def new_chat():
    if 'user' not in session: return jsonify({"error": "Unauthorized"}), 401
    conversation_id = str(int(time.time()))
    return jsonify({'conversation_id': conversation_id})

# <-- [PERUBAHAN UTAMA] FUNGSI DI BAWAH INI TELAH DIKEMBANGKAN SEPENUHNYA -->
@app.route('/chat', methods=['POST'])
def chat():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if not model:
        return jsonify({'error': 'Model AI tidak terinisialisasi.'}), 500

    # 1. Ambil data dari form-data, bukan lagi dari JSON
    user_message = request.form.get('message')
    conversation_id = request.form.get('conversation_id')
    image_file = request.files.get('image')

    # Validasi input: harus ada pesan teks atau file gambar
    if not user_message and not image_file:
        return jsonify({'error': 'Pesan atau gambar tidak boleh kosong'}), 400
    if not conversation_id:
        return jsonify({'error': 'Conversation ID tidak ditemukan'}), 400

    user_dir = get_user_conversations_dir()
    filepath = os.path.join(user_dir, f"{conversation_id}.json")
    history = []
    
    # Muat history percakapan yang sudah ada
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []
    
    # Jika ini percakapan baru, tambahkan prompt sistem
    if not history:
        history.extend([
            {'role': 'user', 'parts': ['Penting: Kamu harus selalu membalas setiap pertanyaan dalam Bahasa Indonesia, tanpa kecuali.']},
            {'role': 'model', 'parts': ['Tentu, saya paham. Saya akan selalu membalas dalam Bahasa Indonesia.']}
        ])
    
    try:
        # 2. Siapkan konten untuk dikirim ke model Gemini
        contents = []
        prompt_for_history = user_message  # Teks yang akan disimpan di history

        # Jika ada file gambar, proses dengan PIL dan tambahkan ke konten
        if image_file:
            img = Image.open(image_file.stream)
            contents.append(img)
        
        # Jika ada pesan teks, tambahkan ke konten
        if user_message:
            contents.append(user_message)
        
        # Jika hanya gambar yang dikirim, buatkan prompt default
        if image_file and not user_message:
            default_prompt = "Jelaskan gambar ini secara detail."
            contents.append(default_prompt)
            prompt_for_history = default_prompt # Gunakan prompt ini untuk disimpan

        # 3. Mulai sesi chat dan kirim konten
        chat_session = model.start_chat(history=history)
        response = chat_session.send_message(contents)
        
        # 4. Simpan percakapan (teks saja) ke file JSON
        # Logika penyimpanan yang lebih sederhana dan andal
        history.append({'role': 'user', 'parts': [prompt_for_history]})
        history.append({'role': 'model', 'parts': [response.text]})
        
        with open(filepath, 'w', encoding='utf-8') as f:
            # ensure_ascii=False agar karakter non-latin (spt emoji) tersimpan dengan benar
            json.dump(history, f, indent=2, ensure_ascii=False)
            
        return jsonify({'response': response.text})
    except Exception as e:
        app.logger.error(f"Error saat chat: {e}") # Log error untuk debugging
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)