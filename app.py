import os
import json
import time
import secrets
from functools import wraps
import shutil
from moviepy import ImageSequenceClip
from flask import send_file 
from werkzeug.utils import secure_filename
import datetime
import requests # Import the requests library

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

app.config.update(
    SESSION_COOKIE_NAME='google-login-session',
    SESSION_COOKIE_SECURE=False,
    SECRET_KEY=os.urandom(24),
    SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///app.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False
)

db = SQLAlchemy(app)
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

snap = midtransclient.Snap(
    is_production=False,
    server_key=os.getenv("MIDTRANS_SERVER_KEY"),
    client_key=os.getenv("MIDTRANS_CLIENT_KEY")
)

# API Key dan URL untuk GPTGod
GPTGOD_API_KEY = "sk-fIbiejLJvNDCB2kmGoXqFooxPrDchwaI3O7RHvHDk6XNVJ0L"
GPTGOD_BASE_URL = "https://api.gptgod.online/v1/chat/completions"

model = None
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    print("AI Model berhasil diinisialisasi.")
except Exception as e:
    print(f"Error saat inisialisasi AI Model: {e}")


# --- 2. MODEL DATABASE & FUNGSI HELPER ---

class User(db.Model):
    id = db.Column(db.String(100), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    picture = db.Column(db.String(255))
    subscription_plan = db.Column(db.String(50), default='Gratis', nullable=False)
    api_key = db.Column(db.String(255), unique=True, nullable=True)
    # Kolom baru untuk melacak penggunaan token
    tokens_used_today = db.Column(db.Integer, default=0)
    last_request_date = db.Column(db.Date, default=datetime.date.today)


class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100), db.ForeignKey('user.id'), nullable=False)
    conversation_id = db.Column(db.String(255), nullable=False)
    is_positive = db.Column(db.Boolean, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())


def generate_api_key():
    return f"nuansa_{secrets.token_urlsafe(32)}"


def get_user_conversations_dir():
    if 'user_id' in session:
        return os.path.join("users", session['user_id'])
    return None


def get_conversation_title(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            history = json.load(f)
        for message in history:
            if message['role'] == 'user' and not message['parts'][0].startswith('Penting:'):
                title = message['parts'][0]
                return title[:50] + '...' if len(title) > 50 else title
    except Exception:
        pass
    return "Percakapan Baru"


def api_key_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Header 'Authorization: Bearer <API_KEY>' tidak ditemukan"}), 401
        
        key = auth_header.split(' ')[1]
        user = User.query.filter_by(api_key=key).first()

        if not user:
            return jsonify({"error": "Kunci API tidak valid"}), 403
        
        return f(user, *args, **kwargs)
    return decorated_function

# Fungsi helper untuk memanggil GPTGod API
def call_gptgod_api(prompt, model_name="gpt-3.5-turbo"):
    headers = {
        "Authorization": f"Bearer {GPTGOD_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}]
    }
    
    response = requests.post(GPTGOD_BASE_URL, headers=headers, json=data)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


# --- 3. RUTE APLIKASI ---

# Bagian: Otentikasi & Halaman Utama
@app.route('/')
def index():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        # Mengirimkan sisa token ke template
        return render_template('index.html', user=user, tokens_remaining=250000-user.tokens_used_today)
    return redirect(url_for('show_login_page'))


@app.route('/login')
def show_login_page():
    return render_template('login.html')


@app.route('/signin-google')
def signin_google():
    redirect_uri = url_for('auth', _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route('/create_video', methods=['GET', 'POST'])
def create_video():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Rute GET: Tampilkan halaman upload
    if request.method == 'GET':
        return render_template('create_video.html')

    # Rute POST: Proses gambar dan buat video
    if request.method == 'POST':
        # Periksa apakah ada file yang diunggah
        if 'images[]' not in request.files:
            return jsonify({"error": "Tidak ada file gambar yang diunggah"}), 400
        
        files = request.files.getlist('images[]')
        
        # Buat direktori sementara untuk menyimpan gambar yang diunggah
        temp_dir = os.path.join(app.root_path, 'temp_uploads', session['user_id'])
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
            
        saved_image_paths = []
        try:
            for file in files:
                if file.filename == '':
                    continue
                if file and allowed_file(file.filename): # Anda bisa membuat fungsi allowed_file() untuk validasi
                    filename = secure_filename(file.filename)
                    filepath = os.path.join(temp_dir, filename)
                    file.save(filepath)
                    saved_image_paths.append(filepath)
            
            if not saved_image_paths:
                return jsonify({"error": "Tidak ada file gambar yang valid"}), 400
                
            # Urutkan gambar berdasarkan nama file agar urutan video benar
            saved_image_paths.sort()
            
            # Buat video menggunakan MoviePy
            clip = ImageSequenceClip(saved_image_paths, fps=1) # Sesuaikan FPS sesuai keinginan Anda
            
            # Simpan video ke file sementara
            video_output_path = os.path.join(temp_dir, f"video_{int(time.time())}.mp4")
            clip.write_videofile(video_output_path, codec="libx264")
            
            # Mengirimkan video yang telah dibuat sebagai respons
            return send_file(video_output_path, as_attachment=True, download_name="video_baru.mp4")

        except Exception as e:
            app.logger.error(f"Error saat membuat video: {e}")
            return jsonify({"error": f"Terjadi kesalahan internal: {e}"}), 500
        finally:
            # Hapus file dan folder sementara setelah selesai
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)


# Fungsi helper untuk validasi jenis file
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}


@app.route('/auth')
def auth():
    try:
        token = google.authorize_access_token()
        user_info = google.get('userinfo').json()
        
        user = User.query.get(user_info['id'])
        if not user:
            user = User(id=user_info['id'], name=user_info['name'], email=user_info['email'], picture=user_info['picture'])
            db.session.add(user)
        else:
            user.name = user_info['name']
            user.picture = user_info['picture']
        db.session.commit()

        session['user_id'] = user.id
        user_dir = os.path.join("users", user.id)
        if not os.path.exists(user_dir):
            os.makedirs(user_dir)
        return redirect('/')
    except Exception as e:
        app.logger.error(f"Error during Google Auth: {e}")
        return redirect(url_for('show_login_page'))


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('show_login_page'))


# Bagian: Langganan, Pembayaran & Dasbor
@app.route('/pricing')
def pricing():
    if 'user_id' not in session: return redirect(url_for('show_login_page'))
    user = User.query.get(session['user_id'])
    return render_template('pricing.html', user=user, client_key=os.getenv("MIDTRANS_CLIENT_KEY"))


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('show_login_page'))
    user = User.query.get(session['user_id'])
    if user.subscription_plan != 'Pro': return redirect(url_for('pricing'))
    return render_template('dashboard.html', user=user)


@app.route('/regenerate_api_key', methods=['POST'])
def regenerate_api_key():
    if 'user_id' not in session: return redirect(url_for('show_login_page'))
    user = User.query.get(session['user_id'])
    if user and user.subscription_plan == 'Pro':
        user.api_key = generate_api_key()
        db.session.commit()
    return redirect(url_for('dashboard'))


@app.route('/create_transaction', methods=['POST'])
def create_transaction():
    if 'user_id' not in session: return jsonify({"error": "Pengguna tidak login"}), 401
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
        return "Notifikasi diproses.", 200
    except Exception as e:
        return "Error", 500


@app.route('/feedback', methods=['POST'])
def save_feedback():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    try:
        new_feedback = Feedback(
            user_id=session['user_id'],
            conversation_id=data['conversation_id'],
            is_positive=data['is_positive']
        )
        db.session.add(new_feedback)
        db.session.commit()
        return jsonify({"message": "Umpan balik berhasil disimpan"}), 200
    except KeyError:
        return jsonify({"error": "Payload tidak lengkap"}), 400
    except Exception as e:
        app.logger.error(f"Error saat menyimpan umpan balik: {e}")
        return jsonify({"error": "Terjadi kesalahan server"}), 500


# Bagian: API Publik
@app.route('/api/v1/chat', methods=['POST'])
@api_key_required
def api_chat(current_user):
    data = request.json
    if not data or 'prompt' not in data:
        return jsonify({"error": "Body JSON dengan key 'prompt' diperlukan"}), 400
    try:
        response = model.generate_content(data['prompt'])
        return jsonify({"response": response.text})
    except Exception as e:
        return jsonify({"error": "Terjadi kesalahan internal saat memproses permintaan."}), 500


# Bagian: Rute untuk Antarmuka Chat
@app.route('/get_conversations')
def get_conversations():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
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
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    user_dir = get_user_conversations_dir()
    filepath = os.path.join(user_dir, f"{conversation_id}.json")
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f: history = json.load(f)
            return jsonify(history[2:] if len(history) > 2 else [])
        except json.JSONDecodeError:
            return jsonify([])
    return jsonify([])


@app.route('/new_chat', methods=['POST'])
def new_chat():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    return jsonify({'conversation_id': str(int(time.time()))})


@app.route('/chat', methods=['POST'])
def chat():
    if 'user_id' not in session: return Response("Unauthorized", status=401)
    if not model: return Response("Model AI tidak terinisialisasi.", status=500)
    
    user = User.query.get(session['user_id'])
    MAX_DAILY_TOKENS = 250000 # Batasan harian untuk token
    
    # Reset token jika hari sudah berganti
    if user.last_request_date != datetime.date.today():
        user.tokens_used_today = 0
        user.last_request_date = datetime.date.today()
        db.session.commit()

    user_message = request.form.get('message')
    conversation_id = request.form.get('conversation_id')
    image_file = request.files.get('image')
    temperature_str = request.form.get('temperature', '0.7')
    model_choice = request.form.get('model_choice', 'gemini')
    
    try:
        temperature = max(0.0, min(1.0, float(temperature_str)))
    except (ValueError, TypeError):
        temperature = 0.7
    
    user_dir = get_user_conversations_dir()
    filepath = os.path.join(user_dir, f"{conversation_id}.json")
    history = []
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f: history = json.load(f)
        except json.JSONDecodeError: history = []
    
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
        
        # Hitung token sebelum memanggil API (hanya untuk Gemini)
        if model_choice == 'gemini':
            try:
                count_response = genai.GenerativeModel('gemini-1.5-flash-latest').count_tokens(contents)
                tokens_in = count_response.total_tokens
            except Exception as e:
                app.logger.error(f"Error saat menghitung token: {e}")
                tokens_in = 0

            # Cek apakah token masih cukup
            if user.tokens_used_today + tokens_in >= MAX_DAILY_TOKENS:
                return Response("Batas penggunaan harian Anda telah tercapai. Silakan coba lagi besok.", status=429)

            # Perbarui jumlah token yang digunakan di database
            user.tokens_used_today += tokens_in
            db.session.commit()
            
        generation_config = genai.types.GenerationConfig(temperature=temperature)
        
        def stream_response_generator():
            full_response_text = ""

            # Logika untuk memilih API yang akan digunakan
            if model_choice == 'gemini':
                chat_session = model.start_chat(history=history)
                response_stream = chat_session.send_message(contents, stream=True, generation_config=generation_config)
                for chunk in response_stream:
                    if chunk.text:
                        yield chunk.text
                        full_response_text += chunk.text
                
                # Setelah respons selesai, hitung token output dan perbarui (khusus Gemini)
                tokens_out = model.count_tokens(full_response_text).total_tokens
                user.tokens_used_today += tokens_out
                db.session.commit()

            elif model_choice.startswith('gptgod_'):
                # Panggil API GPTGod
                try:
                    # Ambil nama model dari pilihan (misalnya 'gpt-4-all')
                    gptgod_model_name = model_choice.split('_')[1]
                    headers = {
                        "Authorization": f"Bearer {GPTGOD_API_KEY}",
                        "Content-Type": "application/json"
                    }
                    data = {
                        "model": gptgod_model_name,
                        "messages": [{"role": "user", "content": prompt_for_history}]
                    }
                    response = requests.post(GPTGOD_BASE_URL, headers=headers, json=data)
                    response.raise_for_status()
                    
                    response_json = response.json()
                    full_response_text = response_json["choices"][0]["message"]["content"]
                    yield full_response_text

                except requests.exceptions.RequestException as e:
                    full_response_text = f"Terjadi kesalahan dengan GPTGod API: {e}"
                    yield full_response_text
            
            # Simpan riwayat setelah respons selesai
            history.append({'role': 'user', 'parts': [prompt_for_history]})
            history.append({'role': 'model', 'parts': [full_response_text]})
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        
        return Response(stream_response_generator(), mimetype='text/plain')
    
    except Exception as e:
        app.logger.error(f"Error saat memproses permintaan chat: {e}")
        return Response(f"Terjadi kesalahan: {e}", status=500)


@app.route('/get_tokens_remaining')
def get_tokens_remaining():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user = User.query.get(session['user_id'])
    MAX_DAILY_TOKENS = 250000
    tokens_remaining = MAX_DAILY_TOKENS - user.tokens_used_today
    
    return jsonify({'tokens_remaining': tokens_remaining})


# --- 4. MENJALANKAN APLIKASI ---
if __name__ == '__main__':
    with app.app_context():
        try:
            db.create_all()
            print("Database tables created successfully.")
        except Exception as e:
            print(f"Error creating database tables: {e}")
    app.run(host='0.0.0.0', port=5000, debug=True)