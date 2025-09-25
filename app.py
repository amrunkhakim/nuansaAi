import os
import json
import time
import secrets
from functools import wraps
import shutil
import traceback
from flask import send_file
from werkzeug.utils import secure_filename
import datetime
import requests

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
    SESSION_COOKIE_SECURE=True, # Ubah ke True untuk produksi
    SECRET_KEY=os.getenv("SECRET_KEY", os.urandom(24)),
    SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///app.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False
)

db = SQLAlchemy(app)
oauth = OAuth(app)

# --- 2. MODEL DATABASE & FUNGSI HELPER ---

class User(db.Model):
    id = db.Column(db.String(100), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    picture = db.Column(db.String(255))
    subscription_plan = db.Column(db.String(50), default='Gratis', nullable=False)
    api_key = db.Column(db.String(255), unique=True, nullable=True)
    tokens_used_today = db.Column(db.Integer, default=0)
    last_request_date = db.Column(db.Date, default=datetime.date.today)
    conversations = db.relationship('Conversation', backref='user', lazy=True, cascade="all, delete-orphan")

# --- PERUBAHAN UTAMA: MODEL BARU UNTUK MENYIMPAN RIWAYAT CHAT ---
class Conversation(db.Model):
    id = db.Column(db.String(100), primary_key=True) # Gunakan ID unik seperti timestamp
    user_id = db.Column(db.String(100), db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False, default="Percakapan Baru")
    history = db.Column(db.Text, nullable=False) # Simpan history sebagai JSON string
    created_at = db.Column(db.DateTime, default=db.func.now())

class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100), db.ForeignKey('user.id'), nullable=False)
    conversation_id = db.Column(db.String(255), nullable=False)
    is_positive = db.Column(db.Boolean, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
    redirect_uri=os.getenv('GOOGLE_REDIRECT_URI')
)

snap = midtransclient.Snap(
    is_production=False,
    server_key=os.getenv("MIDTRANS_SERVER_KEY"),
    client_key=os.getenv("MIDTRANS_CLIENT_KEY")
)

GPTGOD_API_KEY = "sk-fIbiejLJvNDCB2kmGoXqFooxPrDchwaI3O7RHvHDk6XNVJ0L"
GPTGOD_BASE_URL = "https://api.gptgod.online/v1/chat/completions"

model = None
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    print("AI Model berhasil diinisialisasi.")
except Exception as e:
    print(f"Error saat inisialisasi AI Model: {e}")


def generate_api_key():
    return f"nuansa_{secrets.token_urlsafe(32)}"

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

# =====================================================================
# --- FITUR: SELF-DIAGNOSIS ERROR DENGAN AI ---
# =====================================================================
def send_developer_alert(traceback_str, ai_analysis):
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("PERINGATAN: DISCORD_WEBHOOK_URL tidak diatur. Melewatkan notifikasi error.")
        return

    message = {
        "content": "🚨 **Internal Server Error Detected!** 🚨",
        "embeds": [
            {
                "title": "AI-Powered Analysis",
                "description": ai_analysis,
                "color": 15158332 # Merah
            },
            {
                "title": "Full Traceback",
                "description": f"```python\n{traceback_str[:1900]}\n```",
                "color": 5814783 # Abu-abu
            }
        ]
    }
    try:
        requests.post(webhook_url, json=message, timeout=10)
    except Exception as e:
        print(f"KRITIS: Gagal mengirim notifikasi developer: {e}")

def analyze_error_with_ai(e):
    error_traceback = traceback.format_exc()
    prompt = f"""
    You are an expert Python Flask developer acting as a Site Reliability Engineer.
    An unhandled exception occurred in my web application. Please analyze the following traceback, 
    explain the root cause in simple Indonesian, and suggest a specific code fix.

    Traceback:
    ---
    {error_traceback}
    ---
    
    Analysis and Solution:
    """
    try:
        if model:
            response = model.generate_content(prompt)
            analysis = response.text
        else:
            analysis = "AI model is not available for analysis."
        send_developer_alert(error_traceback, analysis)
    except Exception as analysis_error:
        print(f"KRITIS: Gagal menganalisis error dengan AI. Alasan: {analysis_error}")
        send_developer_alert(error_traceback, "Analisis AI gagal. Periksa log server segera.")

# --- 3. RUTE APLIKASI ---

@app.route('/')
def index():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if not user:
             session.pop('user_id', None)
             return redirect(url_for('show_login_page'))
        return render_template('index.html', user=user, tokens_remaining=50 - user.tokens_used_today)
    return redirect(url_for('show_login_page'))

@app.route('/login')
def show_login_page():
    return render_template('login.html')

@app.route('/signin-google')
def signin_google():
    # Menggunakan redirect_uri yang sudah didefinisikan secara global
    return google.authorize_redirect(os.getenv('GOOGLE_REDIRECT_URI'))

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
        # --- DIHAPUS: Kode yang menulis ke file system tidak diperlukan lagi ---
        return redirect('/')
    except Exception as e:
        app.logger.error(f"Error during Google Auth: {e}")
        analyze_error_with_ai(e)
        return redirect(url_for('show_login_page'))

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('show_login_page'))

# --- PERUBAHAN: Rute untuk Antarmuka Chat, sekarang menggunakan Database ---

@app.route('/get_conversations')
def get_conversations():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    conversations = Conversation.query.filter_by(user_id=session['user_id']).order_by(Conversation.created_at.desc()).all()
    conv_list = [{'id': c.id, 'title': c.title} for c in conversations]
    return jsonify(conv_list)

@app.route('/get_history/<conversation_id>')
def get_history(conversation_id):
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    
    conv = Conversation.query.filter_by(id=conversation_id, user_id=session['user_id']).first()
    if conv and conv.history:
        try:
            history = json.loads(conv.history)
            # Jangan tampilkan prompt sistem awal
            return jsonify(history[2:] if len(history) > 2 else [])
        except json.JSONDecodeError:
            return jsonify([])
    return jsonify([])

@app.route('/new_chat', methods=['POST'])
def new_chat():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    # ID unik untuk percakapan baru
    conversation_id = str(int(time.time()))
    return jsonify({'conversation_id': conversation_id})

@app.route('/chat', methods=['POST'])
def chat():
    try:
        if 'user_id' not in session: return Response("Unauthorized", status=401)
        if not model: return Response("Model AI tidak terinisialisasi.", status=500)
        
        user = User.query.get(session['user_id'])
        MAX_DAILY_TOKENS = 50 
        
        if user.last_request_date != datetime.date.today():
            user.tokens_used_today = 0
            user.last_request_date = datetime.date.today()
            db.session.commit()

        user_message = request.form.get('message')
        conversation_id = request.form.get('conversation_id')
        image_file = request.files.get('image')
        temperature_str = request.form.get('temperature', '0.7')
        
        try:
            temperature = max(0.0, min(1.0, float(temperature_str)))
        except (ValueError, TypeError):
            temperature = 0.7
        
        # Ambil atau buat percakapan baru di database
        conversation = Conversation.query.filter_by(id=conversation_id, user_id=user.id).first()
        history = []
        is_new_conversation = False
        if not conversation:
            is_new_conversation = True
            history = [
                {'role': 'user', 'parts': ['Penting: Kamu harus selalu membalas dalam Bahasa Indonesia.']},
                {'role': 'model', 'parts': ['Tentu, saya paham. Saya akan membalas dalam Bahasa Indonesia.']}
            ]
            conversation = Conversation(id=conversation_id, user_id=user.id, history=json.dumps(history))
            db.session.add(conversation)
        else:
            history = json.loads(conversation.history)

        contents, prompt_for_history = [], user_message
        if image_file: contents.append(Image.open(image_file.stream))
        if user_message: contents.append(user_message)
        if image_file and not user_message:
            default_prompt = "Jelaskan gambar ini secara detail."
            contents.append(default_prompt)
            prompt_for_history = default_prompt
        
        count_response = genai.GenerativeModel('gemini-1.5-flash-latest').count_tokens(contents)
        tokens_in = count_response.total_tokens

        if user.tokens_used_today + tokens_in >= MAX_DAILY_TOKENS:
            return Response("Batas penggunaan harian Anda telah tercapai. Silakan coba lagi besok.", status=429)

        user.tokens_used_today += tokens_in
        
        generation_config = genai.types.GenerationConfig(temperature=temperature)
        
        def stream_response_generator():
            with app.app_context():
                db.session.add(user)
                db.session.add(conversation)
                
                full_response_text = ""
                chat_session = model.start_chat(history=history)
                response_stream = chat_session.send_message(contents, stream=True, generation_config=generation_config)
                
                for chunk in response_stream:
                    if chunk.text:
                        yield chunk.text
                        full_response_text += chunk.text
                
                tokens_out = model.count_tokens(full_response_text).total_tokens
                user.tokens_used_today += tokens_out
                
                # Update riwayat di database
                history.append({'role': 'user', 'parts': [prompt_for_history]})
                history.append({'role': 'model', 'parts': [full_response_text]})
                
                # Jika percakapan baru, set judul dari prompt pertama
                if is_new_conversation:
                    title = prompt_for_history[:100]
                    conversation.title = title
                
                conversation.history = json.dumps(history, ensure_ascii=False)
                db.session.commit()
        
        return Response(stream_response_generator(), mimetype='text/plain')
    
    except Exception as e:
        app.logger.error(f"Error saat memproses permintaan chat: {e}")
        analyze_error_with_ai(e)
        return Response("Terjadi kesalahan server internal. Tim kami telah diberitahu.", status=500)


# --- Rute lain tidak diubah, bisa ditempelkan di sini jika perlu ---
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
        analyze_error_with_ai(e)
        return jsonify({"error": "Gagal membuat transaksi dengan Midtrans."}), 500

@app.route('/payment_notification', methods=['POST'])
def payment_notification():
    notification_data = request.json
    order_id = notification_data.get('order_id')
    if not order_id: return "Notifikasi tidak valid", 400

    try:
        status_response = snap.transactions.status(order_id)
        if status_response.get('transaction_status') == 'settlement' and status_response.get('fraud_status') == 'accept':
            user_id_from_order = order_id.split('-')[2]
            user = User.query.get(user_id_from_order)
            if user:
                user.subscription_plan = 'Pro'
                if not user.api_key:
                    user.api_key = generate_api_key()
                db.session.commit()
        return "Notifikasi diproses.", 200
    except Exception as e:
        analyze_error_with_ai(e)
        return "Error", 500

@app.route('/feedback', methods=['POST'])
def save_feedback():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    
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
    except Exception as e:
        analyze_error_with_ai(e)
        return jsonify({"error": "Terjadi kesalahan server"}), 500

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
        analyze_error_with_ai(e)
        return jsonify({"error": "Terjadi kesalahan internal saat memproses permintaan."}), 500

@app.route('/get_tokens_remaining')
def get_tokens_remaining():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    
    user = User.query.get(session['user_id'])
    MAX_DAILY_TOKENS = 50
    return jsonify({'tokens_remaining': max(0, MAX_DAILY_TOKENS - user.tokens_used_today)})

# --- 4. MENJALANKAN APLIKASI ---
if __name__ == '__main__':
    with app.app_context():
        try:
            db.create_all()
            print("Database tables created successfully.")
        except Exception as e:
            print(f"Error creating database tables: {e}")
    app.run(host='0.0.0.0', port=5000, debug=True)