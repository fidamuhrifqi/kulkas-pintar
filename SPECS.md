# Spesifikasi dan Panduan Menjalankan Kulkas Pintar

## Spesifikasi Teknis (Specs)
- **Bahasa Pemrograman:** Python 3.10+
- **Framework Bot:** `python-telegram-bot` (versi 21+)
- **AI / LLM Integration:** `openai` (Python SDK) untuk terhubung dengan MiniMax API (Model yang didukung: MiniMax-M2.5 / MiniMax-M2.7).
- **Database / Penyimpanan:** Penyimpanan lokal berbasis file JSON di dalam folder `data/` (`data/fridge.json`, `data/recipes.json`, `data/history.json`). Sistem tidak memerlukan instalasi database server yang rumit.
- **Process Manager:** Mendukung **PM2** (via `ecosystem.config.js`) untuk proses _deployment_ di server / VPS.

## Struktur Direktori (Modular)
Sistem ini menggunakan struktur _clean code_ (modular) untuk memudahkan pemeliharaan:
- `bot.py`: Berkas utama (entry point) yang hanya berisi inisialisasi aplikasi dan _routing_.
- `handlers/`: Folder berisi logika spesifik Telegram (misalnya antarmuka menu, logika masuk/keluar, dsb).
- `services/`: Folder berisi layanan sistem seperti koneksi ke AI (`ai_service.py`) dan operasi file JSON (`storage.py`).
- `core/`: Folder berisi konstanta inti seperti *Environment Variables* (`config.py`) dan instruksi LLM (`prompts.py`).
- `data/`: Folder tempat disimpannya database lokal JSON (otomatis dibuat jika belum ada).

---

## Panduan Instalasi dan Menjalankan Bot (Run Guide)

### 1. Persiapan Kredensial (Wajib)
Sebelum menjalankan bot, Anda wajib menyiapkan beberapa hal:
1. **Telegram Bot Token:** Buka Telegram, cari **@BotFather**, buat bot baru (ketik `/newbot`), ikuti prosesnya, dan salin Token API yang diberikan.
2. **Telegram User ID:** Cari bot **@userinfobot** di Telegram untuk mengetahui ID angka akun Anda (misal: `123456789`). Ini digunakan agar hanya Anda yang bisa memerintah bot kulkas Anda (keamanan).
3. **MiniMax API Key:** Aplikasi ini secara default menggunakan AI dari MiniMax. Daftar di website MiniMax (atau provider OpenAI-compatible lainnya) untuk mendapatkan API Key Anda.

### 2. Persiapan Lingkungan (Environment)
Pastikan Python sudah terinstall di komputer atau server Anda. Buat *virtual environment* (sangat direkomendasikan):
```bash
python -m venv venv

# Untuk Windows:
venv\Scripts\activate

# Untuk Linux/Mac:
source venv/bin/activate
```

### 3. Instalasi Dependensi
Install semua library Python yang dibutuhkan melalui berkas `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 4. Konfigurasi
Buatlah sebuah file baru bernama `.env` di dalam folder proyek ini.

Anda bisa membuat file `.env` tersebut secara manual atau dengan menyalin dari *template* `.env.example` yang sudah disediakan:
```bash
# Windows (Command Prompt/PowerShell):
copy .env.example .env

# Linux/Mac/GitBash:
cp .env.example .env
```
Setelah dibuat, buka file `.env` tersebut dengan *text editor* dan isi variabel-variabelnya sesuai dengan kredensial yang sudah Anda siapkan di Langkah 1:
- `TELEGRAM_TOKEN`: Masukkan Token Bot Telegram Anda.
- `MINIMAX_API_KEY`: Masukkan API Key MiniMax Anda.
- `ALLOWED_USER_IDS`: Masukkan Telegram User ID Anda.

> **Catatan Penting:** Pastikan Anda memasukkan Telegram ID Anda ke dalam `ALLOWED_USER_IDS` agar bot merespons pesan Anda (ini adalah bentuk keamanan/autentikasi agar bot tidak bisa dipakai sembarang orang).

### 5. Cara Menjalankan Bot

**Cara A: Menjalankan secara manual (untuk Development / Testing)**
Ketikkan perintah berikut di terminal Anda:
```bash
python bot.py
```

**Cara B: Menjalankan menggunakan PM2 (untuk Production / Server VPS)**
Jika bot ingin dibiarkan menyala terus di background VPS Anda, gunakan PM2 (butuh Node.js). 

Sebelum menjalankan PM2, pastikan Anda melakukan 2 hal berikut:
1. **Buat folder `logs`**: PM2 membutuhkan folder ini untuk menyimpan log. Buat foldernya dengan perintah `mkdir logs` (di terminal).
2. **Cek `ecosystem.config.js`**: Pastikan pengaturan `interpreter` di dalam file tersebut sudah sesuai dengan *virtual environment* OS Anda (cek komentar di dalam file tersebut untuk panduan Linux vs Windows).

Setelah siap, jalankan:
```bash
# Jika PM2 belum terinstall:
npm install -g pm2

# Menjalankan bot:
pm2 start ecosystem.config.js

# Melihat log aplikasi:
pm2 logs kulkas-bot
```
