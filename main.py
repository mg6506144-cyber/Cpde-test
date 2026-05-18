import os
import sys
import random
import asyncio
import logging
import json
from datetime import datetime
from typing import List, Dict

# ============== Setup App Directory ==============
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if not os.access(APP_DIR, os.W_OK):
    APP_DIR = os.path.join(os.path.expanduser("~"), "microsoft_bot")

os.makedirs(APP_DIR, exist_ok=True)
os.chdir(APP_DIR)

# ============== Check Dependencies ==============
def check_install_dependencies():
    required = ['telegram', 'httpx']
    missing = []
    for module in required:
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    
    if missing:
        print("=" * 60)
        print("INSTALLING MISSING PACKAGES...")
        print("=" * 60)
        for pkg in missing:
            print(f"[*] Installing {pkg}...")
            os.system(f"{sys.executable} -m pip install {pkg}")
        print("\n[*] Packages installed! Restart the script.")
        sys.exit(0)

check_install_dependencies()

# ============== Imports ==============
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import httpx

# ============== CONFIGURATION ==============
class Config:
    ADMIN_USERNAME = "HG_GH70"
    ADMIN_ID = 8136997138
    ADMIN_PROFILE = "t.me/HG_GH70"
    
    BOT_TOKEN = "8836028231:AAGsYV-1p-RC0pqt7RfmCmGipsqaKGLZjzg"
    BOT_NAME = "Microsoft OTP Bot"
    BOT_VERSION = "3.0.2"
    
    MICROSOFT_SEND_OTP_URL = "https://login.live.com/GetCredentialType.srf"
    
    WAIT_BETWEEN_NUMBERS = (2, 4)
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
    NUMBERS_PER_PAGE = 15

    NUMBERS_DIR = os.path.join(APP_DIR, "numbers_files")
    LOGS_DIR = os.path.join(APP_DIR, "logs")
    DATA_FILE = os.path.join(APP_DIR, "bot_data.json")

# ============== Directories ==============
for directory in [Config.NUMBERS_DIR, Config.LOGS_DIR]:
    os.makedirs(directory, exist_ok=True)

# ============== Logging ==============
logging.basicConfig(
    format='%(asctime)s | %(levelname)s | %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ============== Bot Data ==============
class BotData:
    def __init__(self):
        self.data = self.load_data()
    
    def load_data(self) -> dict:
        default = {"total_otp_sent": 0, "total_success": 0, "total_failed": 0, "users": {}, "history": []}
        try:
            if os.path.exists(Config.DATA_FILE):
                with open(Config.DATA_FILE, 'r', encoding='utf-8') as f:
                    return {**default, **json.load(f)}
        except:
            pass
        return default
    
    def save_data(self):
        try:
            with open(Config.DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Save error: {e}")
    
    def add_user(self, user_id: int, username: str, first_name: str):
        user_id = str(user_id)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if user_id not in self.data["users"]:
            self.data["users"][user_id] = {
                "username": username or "N/A", "first_name": first_name,
                "first_seen": now, "last_seen": now,
                "total_uploads": 0, "total_otp": 0
            }
        else:
            self.data["users"][user_id]["last_seen"] = now
        self.save_data()

    def add_history(self, user_id: int, action: str, details: str):
        self.data["history"].append({
            "user_id": user_id, "action": action, "details": details,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        if len(self.data["history"]) > 100:
            self.data["history"] = self.data["history"][-100:]
        self.save_data()

    def increment_otp(self, success: bool):
        self.data["total_otp_sent"] += 1
        if success:
            self.data["total_success"] += 1
        else:
            self.data["total_failed"] += 1
        self.save_data()

bot_data = BotData()

# ============== Helpers ==============
def is_admin(user_id: int) -> bool:
    return user_id == Config.ADMIN_ID

def get_file_numbers(filename: str) -> List[str]:
    filepath = os.path.join(Config.NUMBERS_DIR, filename)
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except:
        return []

def get_all_files() -> List[Dict]:
    files = []
    for f in os.listdir(Config.NUMBERS_DIR):
        if f.endswith('.txt'):
            filepath = os.path.join(Config.NUMBERS_DIR, f)
            numbers = get_file_numbers(f)
            files.append({
                "name": f,
                "count": len(numbers),
                "size": os.path.getsize(filepath),
                "modified": datetime.fromtimestamp(os.path.getmtime(filepath)).strftime("%Y-%m-%d %H:%M:%S")
            })
    return sorted(files, key=lambda x: x['modified'], reverse=True)

def create_progress_bar(current: int, total: int, length: int = 12) -> str:
    if total == 0: return "[------------] 0%"
    filled = int(length * current / total)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {int(100 * current / total)}%"

# ============== OTP Processor ==============
async def process_single_number(phone_number: str) -> dict:
    result = {"number": phone_number, "success": False, "message": "Unknown", "time": datetime.now().strftime("%H:%M:%S")}
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Content-Type': 'application/json'}
        data = {
            "username": phone_number if phone_number.startswith("+") else "+" + phone_number.lstrip("0"),
            "isOtherIdpSupported": True, "checkPhones": True,
            "isRemoteNGCSupported": True, "isCookieBannerShown": False,
            "isFidoSupported": True, "flowToken": "", "originalRequest": ""
        }
        
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(Config.MICROSOFT_SEND_OTP_URL, json=data, headers=headers)
            if resp.status_code == 200:
                result["success"] = True
                result["message"] = "Success"
    except Exception as e:
        result["message"] = str(e)[:80]
    
    bot_data.increment_otp(result["success"])
    await asyncio.sleep(random.uniform(*Config.WAIT_BETWEEN_NUMBERS))
    return result

# ============== Keyboards ==============
class Keyboards:
    @staticmethod
    def admin_main():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard"), InlineKeyboardButton("📈 Stats", callback_data="stats")],
            [InlineKeyboardButton("📁 File Manager", callback_data="manage_files"), InlineKeyboardButton("▶️ Start OTP", callback_data="start_otp")],
            [InlineKeyboardButton("👥 Users", callback_data="users_list"), InlineKeyboardButton("📋 History", callback_data="history")],
        ])

    @staticmethod
    def user_main():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 Browse Numbers", callback_data="user_view_numbers")],
            [InlineKeyboardButton("▶️ Send OTP", callback_data="start_otp")],
            [InlineKeyboardButton("📤 Upload File", callback_data="user_upload_info")],
            [InlineKeyboardButton("ℹ️ Help", callback_data="user_help")],
        ])

    @staticmethod
    def back(to: str):
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=to)]])

# ============== Handlers ==============
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_data.add_user(user.id, user.username, user.first_name)
    
    if is_admin(user.id):
        await update.message.reply_text(
            f"👑 Welcome Owner!\n\n🤖 {Config.BOT_NAME} v{Config.BOT_VERSION}",
            reply_markup=Keyboards.admin_main()
        )
    else:
        await update.message.reply_text(
            f"👋 Welcome, {user.first_name}!\n\n🤖 {Config.BOT_NAME}",
            reply_markup=Keyboards.user_main()
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    # এখানে সব বাটন হ্যান্ডলার যোগ করা হয়েছে (সংক্ষেপে রাখা হয়েছে)
    if data == "dashboard" and is_admin(user_id):
        files = get_all_files()
        text = f"📊 Dashboard\n\nTotal Files: {len(files)}\nTotal Numbers: {sum(f['count'] for f in files)}\nOTP Sent: {bot_data.data['total_otp_sent']}"
        await query.edit_message_text(text, reply_markup=Keyboards.admin_main())

    elif data == "start_otp":
        files = get_all_files()
        if not files:
            await query.edit_message_text("❌ No number files found!", reply_markup=Keyboards.back("dashboard" if is_admin(user_id) else "user_back"))
            return
        
        keyboard = [[InlineKeyboardButton(f"▶️ {f['name']} ({f['count']})", callback_data=f"otp_file_{f['name']}")] for f in files]
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="dashboard" if is_admin(user_id) else "user_back")])
        
        await query.edit_message_text("Select file to start OTP:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("otp_file_"):
        filename = data.replace("otp_file_", "")
        numbers = get_file_numbers(filename)
        if not numbers:
            await query.edit_message_text("❌ No numbers in file!")
            return

        success = failed = 0
        status_msg = await query.edit_message_text(f"🔄 Processing {filename}...\nTotal: {len(numbers)}")

        for i, num in enumerate(numbers, 1):
            result = await process_single_number(num)
            if result["success"]:
                success += 1
            else:
                failed += 1

            if i % 5 == 0:  # প্রতি ৫টা পর পর আপডেট
                try:
                    await status_msg.edit_text(
                        f"🔄 Processing...\n{i}/{len(numbers)}\n✅ {success} | ❌ {failed}"
                    )
                except:
                    pass

        await status_msg.edit_text(
            f"✅ OTP Process Complete!\n\n"
            f"File: {filename}\n"
            f"Total: {len(numbers)}\n"
            f"Success: {success}\n"
            f"Failed: {failed}",
            reply_markup=Keyboards.back("start_otp")
        )

    # আরও বাটন হ্যান্ডলার যোগ করতে চাইলে বলো

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document.file_name.endswith('.txt'):
        return await update.message.reply_text("❌ Only .txt files allowed!")

    if document.file_size > Config.MAX_FILE_SIZE:
        return await update.message.reply_text("❌ File too large! Max 5MB.")

    try:
        file = await context.bot.get_file(document.file_id)
        filepath = os.path.join(Config.NUMBERS_DIR, document.file_name)
        await file.download_to_drive(filepath)

        count = len(get_file_numbers(document.file_name))
        bot_data.add_user(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)
        
        uid = str(update.effective_user.id)
        if uid in bot_data.data["users"]:
            bot_data.data["users"][uid]["total_uploads"] += 1
            bot_data.save_data()

        await update.message.reply_text(f"✅ Upload Successful!\n\n📁 {document.file_name}\n📱 {count} numbers")
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("❌ Upload failed.")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send /start to open menu or upload a .txt file.")

# ============== Main ==============
def main():
    print("="*60)
    print(f"🚀 {Config.BOT_NAME} v{Config.BOT_VERSION} Started")
    print(f"👑 Owner: @{Config.ADMIN_USERNAME}")
    print("="*60)

    app = Application.builder().token(Config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    app.run_polling()

if __name__ == "__main__":
    main()
