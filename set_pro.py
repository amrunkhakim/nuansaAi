# set_pro.py
from app import app, db, User

# GANTI DENGAN EMAIL ANDA YANG TERDAFTAR DI APLIKASI
MY_EMAIL = "amrunkhakim@gmail.com" 

with app.app_context():
    # Cari pengguna berdasarkan email
    user_to_upgrade = User.query.filter_by(email=MY_EMAIL).first()

    if user_to_upgrade:
        # Ubah status langganan
        user_to_upgrade.subscription_plan = 'Pro'
        db.session.commit()
        print(f"✅ Pengguna '{user_to_upgrade.name}' dengan email '{MY_EMAIL}' berhasil diupgrade ke Pro.")
    else:
        print(f"❌ Pengguna dengan email '{MY_EMAIL}' tidak ditemukan di database.")
        print("Pastikan Anda sudah login setidaknya sekali dengan akun tersebut.")