import os
import json
import time
import secrets

# Import library pihak ketiga
import google.generativeai as genai
import midtransclient
from flask import Flask, render_template, request, Response, session, redirect, url_for, jsonify
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth
from PIL import Image
from flask_sqlalchemy import SQLAlchemy

# --- 1. KONFIGURASI AWAL & INISIALISASI ---

load_dotenv()

app = Flask(__name__)
app.config['SESSION_COOKIE_NAME'] = 'google-login-session'
app.config['SESSION_COOKIE_SECURE'] = False
app.secret_key = os.urandom(24)

# Konfigurasi Database (menggunakan SQLite untuk kemudahan)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "sqlite:///app.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Inisialisasi Klien OAuth (Authlib)
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

# Inisialisasi Klien Midtrans
snap = midtransclient.Snap(
    is_production=False,  # Set True saat sudah live
    server_key=os.getenv("MIDTRANS_SERVER_KEY"),
    client_key=os.getenv("MIDTRANS_CLIENT_KEY")
)

# Inisialisasi Model AI Gemini
model = None
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    print("AI Model berhasil diinisialisasi.")
except Exception as e:
    print(f"Error saat inisialisasi AI Model: {e}")


# --- 2. MODEL DATABASE ---

class User(db.Model):
    id = db.Column(db.String(100), primary_key=True)  # ID dari Google
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    picture = db.Column(db.String(255))
    subscription_plan = db.Column(db.String(50), default='Gratis', nullable=False)
    api_key = db.Column(db.String(255), unique=True, nullable=True)

def generate_api_key():
    return f"nuansa_{secrets.token_urlsafe(32)}"


# --- 3. RUTE APLIKASI ---

# Rute Utama & Otentikasi
@app.route('/')
def index():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        return render_template('index.html', user=user)
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
    
    # Cari atau buat user baru di database
    user = User.query.get(user_info['id'])
    if not user:
        user = User(
            id=user_info['id'], name=user_info['name'],
            email=user_info['email'], picture=user_info['picture']
        )
        db.session.add(user)
    else: # Update info jika berubah (misal, ganti foto profil)
        user.name = user_info['name']
        user.picture = user_info['picture']
    db.session.commit()

    session['user_id'] = user.id
    # Buat direktori untuk history chat berbasis file
    user_dir = os.path.join("users", user.id)
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    return redirect('/')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('show_login_page'))

# Rute Langganan & Pembayaran
@app.route('/pricing')
def pricing():
    if 'user_id' not in session:
        return redirect(url_for('show_login_page'))
    user = User.query.get(session['user_id'])
    return render_template('pricing.html', user=user, client_key=os.getenv("MIDTRANS_CLIENT_KEY"))

@app.route('/create_transaction', methods=['POST'])
def create_transaction():
    if 'user_id' not in session:
        return jsonify({"error": "Pengguna tidak login"}), 401
    
    user = User.query.get(session['user_id'])
    order_id = f"NUANSA-PRO-{user.id}-{int(time.time())}"
    
    transaction_params = {
        'transaction_details': {'order_id': order_id, 'gross_amount': 100000},
        'customer_details': {'first_name': user.name.split(' ')[0], 'email': user.email}
    }
    try:
        transaction = snap.create_transaction(transaction_params)
        return jsonify({'token': transaction['token']})
    except Exception as e:
        app.logger.error(f"Gagal membuat transaksi Midtrans: {e}")
        return jsonify({"error": "Gagal membuat transaksi dengan Midtrans."}), 500

@app.route('/payment_notification', methods=['POST'])
def payment_notification():
    notification_data = request.json
    order_id = notification_data.get('order_id')
    if not order_id: return "Notifikasi tidak valid", 400

    try:
        status_response = snap.transactions.status(order_id)
        transaction_status = status_response.get('transaction_status')
        fraud_status = status_response.get('fraud_status')

        if transaction_status == 'settlement' and fraud_status == 'accept':
            user_id_from_order = order_id.split('-')[2]
            user = User.query.get(user_id_from_order)
            if user:
                user.subscription_plan = 'Pro'
                if not user.api_key:
                    user.api_key = generate_api_key()
                db.session.commit()
                print(f"Pengguna {user.email} telah diupgrade ke Pro.")
        return "Notifikasi diproses.", 200
    except Exception as e:
        print(f"Error memproses notifikasi: {e}")
        return "Error", 500
# Di app.py, di antara rute-rute lain

@app.route('/dashboard')
def dashboard():
    # Pastikan pengguna sudah login
    if 'user_id' not in session:
        return redirect(url_for('show_login_page'))
    
    user = User.query.get(session['user_id'])

    # [PENTING] Lindungi halaman ini hanya untuk pengguna Pro
    if user.subscription_plan != 'Pro':
        return redirect(url_for('pricing'))

    return render_template('dashboard.html', user=user)

@app.route('/regenerate_api_key', methods=['POST'])
def regenerate_api_key():
    if 'user_id' not in session:
        return redirect(url_for('show_login_page'))

    user = User.query.get(session['user_id'])
    if user and user.subscription_plan == 'Pro':
        # Buat kunci baru dan simpan ke database
        user.api_key = generate_api_key()
        db.session.commit()
    
    return redirect(url_for('dashboard'))
# Rute untuk Chat
def get_user_conversations_dir():
    if 'user_id' in session:
        return os.path.join("users", session['user_id'])
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
    if 'user_id' not in session: return Response("Unauthorized", status=401)
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
    if 'user_id' not in session: return Response("Unauthorized", status=401)
    user_dir = get_user_conversations_dir()
    filepath = os.path.join(user_dir, f"{conversation_id}.json")
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            history = json.load(f)
            return jsonify(history[2:] if len(history) > 2 else [])
    return jsonify([])

@app.route('/new_chat', methods=['POST'])
def new_chat():
    if 'user_id' not in session: return Response("Unauthorized", status=401)
    conversation_id = str(int(time.time()))
    return jsonify({'conversation_id': conversation_id})

@app.route('/chat', methods=['POST'])
def chat():
    if 'user_id' not in session: return Response("Unauthorized", status=401)
    if not model: return Response("Model AI tidak terinisialisasi.", status=500)

    user_message = request.form.get('message')
    conversation_id = request.form.get('conversation_id')
    image_file = request.files.get('image')
    temperature_str = request.form.get('temperature', '0.7')
    try:
        temperature = max(0.0, min(1.0, float(temperature_str)))
    except (ValueError, TypeError):
        temperature = 0.7
    
    user_dir = get_user_conversations_dir()
    filepath = os.path.join(user_dir, f"{conversation_id}.json")
    history = []
    
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except json.JSONDecodeError:
            history = []
    
    if not history:
        history.extend([
            {'role': 'user', 'parts': ['Penting: Kamu harus selalu membalas dalam Bahasa Indonesia.']},
            {'role': 'model', 'parts': ['Tentu, saya paham. Saya akan membalas dalam Bahasa Indonesia.']}
        ])
    
    try:
        contents, prompt_for_history = [], user_message
        if image_file: contents.append(Image.open(image_file.stream))
        if user_message: contents.append(user_message)
        if image_file and not user_message:
            default_prompt = "Jelaskan gambar ini secara detail."
            contents.append(default_prompt)
            prompt_for_history = default_prompt
        
        generation_config = genai.types.GenerationConfig(temperature=temperature)

        def stream_response_generator():
            full_response_text = ""
            chat_session = model.start_chat(history=history)
            response_stream = chat_session.send_message(contents, stream=True, generation_config=generation_config)
            
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


# --- 4. MENJALANKAN APLIKASI ---

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Membuat file database dan tabel jika belum ada
    app.run(host='0.0.0.0', port=5000, debug=True)