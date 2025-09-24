# init_db.py
from app import app, db

print("Mencoba membuat database dan tabel...")

# Jalankan dalam konteks aplikasi untuk membuat semua tabel dari model Anda
with app.app_context():
    db.create_all()

print("Database dan tabel berhasil dibuat di file app.db.")