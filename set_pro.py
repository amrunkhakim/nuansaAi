from app import app, db, User

# GANTI DENGAN DAFTAR EMAIL YANG INGIN DI-UPGRADE
MY_EMAILS = [
    "amrunkhakim@gmail.com",
    "amrun.dev@gmail.com",
  
]

with app.app_context():
    for email in MY_EMAILS:
        # Cari pengguna berdasarkan email
        user_to_upgrade = User.query.filter_by(email=email).first()

        if user_to_upgrade:
            # Ubah status langganan
            user_to_upgrade.subscription_plan = 'Pro'
            db.session.commit()
            print(f"✅ Pengguna '{user_to_upgrade.name}' dengan email '{email}' berhasil diupgrade ke Pro.")
        else:
            print(f"❌ Pengguna dengan email '{email}' tidak ditemukan di database.")
            print("Pastikan Anda sudah login setidaknya sekali dengan akun tersebut.")