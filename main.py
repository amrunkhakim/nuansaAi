import os
import tkinter as tk
from tkinter import scrolledtext, simpledialog
import google.generativeai as genai
import threading

# --- TAMBAHKAN DUA BARIS INI UNTUK MENGHILANGKAN WARNING ---
os.environ['GRPC_VERBOSITY'] = 'ERROR'
os.environ['GLOG_minloglevel'] = '2'
# -----------------------------------------------------------

class ChatApplication:
    def __init__(self, master):
        self.master = master
        master.title("AI Agent GUI")
        master.geometry("700x550")

        # --- Membuat Widget ---
        # 1. Area untuk menampilkan chat
        self.chat_area = scrolledtext.ScrolledText(master, wrap=tk.WORD, state='disabled', font=("Arial", 11))
        self.chat_area.pack(padx=10, pady=10, expand=True, fill='both')

        # 2. Frame untuk input dan tombol
        input_frame = tk.Frame(master)
        input_frame.pack(padx=10, pady=5, fill='x')

        # 3. Kolom input teks
        self.entry_box = tk.Entry(input_frame, font=("Arial", 11))
        self.entry_box.pack(side='left', expand=True, fill='x', ipady=5)
        # Menghubungkan tombol Enter dengan fungsi kirim
        self.entry_box.bind("<Return>", self.send_message)

        # 4. Tombol Kirim
        self.send_button = tk.Button(input_frame, text="Kirim", command=self.send_message, font=("Arial", 10, "bold"))
        self.send_button.pack(side='right', padx=5)

        # --- Inisialisasi AI ---
        self.chat_session = None
        self.initialize_ai()

    def add_message(self, sender, message):
        """Menambahkan pesan ke area chat dengan format yang rapi."""
        self.chat_area.config(state='normal')
        self.chat_area.insert(tk.END, f"{sender}: {message}\n\n")
        self.chat_area.config(state='disabled')
        # Auto-scroll ke pesan terbaru
        self.chat_area.yview(tk.END)

    def initialize_ai(self):
        """Mengambil API Key dan memulai sesi chat dengan AI."""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            self.add_message("Sistem", "Error: API Key Gemini tidak ditemukan.\nHarap atur di file .env Anda dan restart aplikasi.")
            return

        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash-latest')
            # Menambahkan instruksi agar AI selalu membalas dalam Bahasa Indonesia
            self.chat_session = model.start_chat(history=[
                {'role': 'user', 'parts': ['Mulai sekarang, kamu harus selalu membalas dalam Bahasa Indonesia.']},
                {'role': 'model', 'parts': ['Baik, saya mengerti. Saya akan selalu membalas dalam Bahasa Indonesia.']}
            ])
            self.add_message("Sistem", "AI Agent siap. Silakan mulai percakapan.")
        except Exception as e:
            self.add_message("Sistem", f"Gagal memulai sesi AI: {e}")

    def send_message(self, event=None):
        """Mengirim pesan dari pengguna ke AI."""
        user_input = self.entry_box.get()
        if user_input.strip() and self.chat_session:
            self.add_message("Anda", user_input)
            self.entry_box.delete(0, tk.END)
            
            # Menonaktifkan input dan tombol saat AI berpikir
            self.entry_box.config(state='disabled')
            self.send_button.config(state='disabled')

            # Menjalankan AI di thread terpisah agar GUI tidak macet
            thread = threading.Thread(target=self.get_ai_response, args=(user_input,))
            thread.start()

    def get_ai_response(self, user_input):
        """Mendapatkan respons dari AI dan menampilkannya."""
        try:
            response = self.chat_session.send_message(user_input)
            # Menggunakan master.after untuk update GUI dari thread
            self.master.after(0, self.display_ai_response, response.text)
        except Exception as e:
            self.master.after(0, self.display_ai_response, f"Maaf, terjadi kesalahan: {e}")

    def display_ai_response(self, response_text):
        """Fungsi untuk menampilkan respons AI di GUI."""
        self.add_message("AI", response_text)
        # Mengaktifkan kembali input dan tombol
        self.entry_box.config(state='normal')
        self.send_button.config(state='normal')

if __name__ == "__main__":
    # Pastikan file .env ada dan terbaca
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        print("Peringatan: library python-dotenv tidak terinstal. Pastikan GEMINI_API_KEY sudah diatur secara manual.")

    root = tk.Tk()
    app = ChatApplication(root)
    root.mainloop()