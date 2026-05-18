import os
import sys
import time
import random
import asyncio
import logging
import json
import requests
from datetime import datetime
from typing import List, Dict

# ============== Setup App Directory ==============
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if not os.access(APP_DIR, os.W_OK):
    APP_DIR = os.path.join(os.path.expanduser("~"), "microsoft_bot")

if not os.path.exists(APP_DIR):
    os.makedirs(APP_DIR)
os.chdir(APP_DIR)

# ============== Check & Install Dependencies ==============
def check_install_dependencies():
    required = {
        'telegram': 'python-telegram-bot',
        'requests': 'requests'
    }
    
    missing = []
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    
    if missing:
        print("=" * 50)
        print("INSTALLING MISSING PACKAGES...")
        print("=" * 50)
        for package in missing:
            print(f"[*] Installing {package}...")
            os.system(f"{sys.executable} -m pip install {package}")
        print("\n[*] Packages installed successfully!")
        print("[*] Please restart the script...")
        sys.exit(0)

check_install_dependencies()

# ============== Imports ==============
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode

# ============== CONFIGURATION ==============
class Config:
    ADMIN_USERNAME = "HG_GH70"
    ADMIN_ID = 8136997138
    ADMIN_PROFILE = "t.me/HG_GH70"
    
    BOT_TOKEN = "8836028231:AAGsYV-1p-RC0pqt7RfmCmGipsqaKGLZjzg"
    BOT_NAME = "Microsoft OTP Bot"
    BOT_VERSION = "3.0.1"
    
    MICROSOFT_SEND_OTP_URL = "https://login.live.com/GetCredentialType.srf"
    
    WAIT_BETWEEN_NUMBERS = (2, 4)
    
    NUMBERS_DIR = os.path.join(APP_DIR, "numbers_files")
    LOGS_DIR = os.path.join(APP_DIR, "logs")
    DATA_FILE = os.path.join(APP_DIR, "bot_data.json")
    
    NUMBERS_PER_PAGE = 15

# ============== Initialize Directories ==============
for directory in [Config.NUMBERS_DIR, Config.LOGS_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

# ============== Logging Setup ==============
logging.basicConfig(
    format='%(asctime)s | %(levelname)s | %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ============== Bot Data Management ==============
class BotData:
    def __init__(self):
        self.data = self.load_data()
    
    def load_data(self) -> dict:
        default = {
            "total_otp_sent": 0,
            "total_success": 0,
            "total_failed": 0,
            "users": {},
            "history": []
        }
        try:
            if os.path.exists(Config.DATA_FILE):
                with open(Config.DATA_FILE, 'r') as f:
                    return {**default, **json.load(f)}
        except:
            pass
        return default
    
    def save_data(self):
        try:
            with open(Config.DATA_FILE, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save data: {e}")
    
    def add_user(self, user_id: int, username: str, first_name: str):
        user_id = str(user_id)
        if user_id not in self.data["users"]:
            self.data["users"][user_id] = {
                "username": username,
                "first_name": first_name,
                "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_uploads": 0,
                "total_otp": 0
            }
        else:
            self.data["users"][user_id]["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.data["users"][user_id]["username"] = username
        self.save_data()
    
    def add_history(self, user_id: int, action: str, details: str):
        self.data["history"].append({
            "user_id": user_id,
            "action": action,
            "details": details,
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

# ============== Helper Functions ==============
def is_admin(user_id: int) -> bool:
    return user_id == Config.ADMIN_ID

def get_file_numbers(filename: str) -> List[str]:
    filepath = os.path.join(Config.NUMBERS_DIR, filename)
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, 'r') as f:
            return [line.strip() for line in f if line.strip()]
    except:
        return []

def get_all_files() -> List[Dict]:
    files = []
    if not os.path.exists(Config.NUMBERS_DIR):
        return files
    for f in os.listdir(Config.NUMBERS_DIR):
        if f.endswith('.txt'):
            filepath = os.path.join(Config.NUMBERS_DIR, f)
            size = os.path.getsize(filepath)
            modified = datetime.fromtimestamp(os.path.getmtime(filepath))
            numbers = get_file_numbers(f)
            files.append({
                "name": f,
                "size": size,
                "modified": modified.strftime("%Y-%m-%d %H:%M:%S"),
                "count": len(numbers)
            })
    return sorted(files, key=lambda x: x['modified'], reverse=True)

def create_progress_bar(current: int, total: int, length: int = 10) -> str:
    if total == 0:
        return "[----------] 0%"
    filled = int(length * current / total)
    bar = "█" * filled + "░" * (length - filled)
    percentage = int(100 * current / total)
    return f"[{bar}] {percentage}%"

# ============== OTP Processing (Using Requests - No Browser Needed) ==============
async def process_single_number(phone_number: str) -> dict:
    """Send OTP using direct HTTP requests"""
    result = {
        "number": phone_number,
        "success": False,
        "message": "",
        "time": datetime.now().strftime("%H:%M:%S")
    }
    
    try:
        logger.info(f"Processing: {phone_number}")
        
        session = requests.Session()
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Content-Type': 'application/json; charset=UTF-8',
            'Origin': 'https://account.microsoft.com',
            'Referer': 'https://account.microsoft.com/security/',
        }
        
        check_data = {
            "username": f"+2{phone_number}",
            "isOtherIdpSupported": True,
            "checkPhones": True,
            "isRemoteNGCSupported": True,
            "isCookieBannerShown": False,
            "isFidoSupported": True,
            "flowToken": "",
            "originalRequest": ""
        }
        
        response = session.post(
            Config.MICROSOFT_SEND_OTP_URL,
            json=check_data,
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            result["success"] = True
            result["message"] = "OTP Sent Successfully"
            logger.info(f"Success: {phone_number}")
        else:
            result["message"] = f"HTTP {response.status_code}"
            logger.error(f"Failed: {phone_number}")
        
    except requests.exceptions.Timeout:
        result["message"] = "Timeout"
        logger.error(f"Timeout: {phone_number}")
    except requests.exceptions.ConnectionError:
        result["message"] = "Connection Error"
        logger.error(f"Connection: {phone_number}")
    except Exception as e:
        result["message"] = str(e)[:80]
        logger.error(f"Failed: {phone_number}")
    
    bot_data.increment_otp(result["success"])
    await asyncio.sleep(random.uniform(*Config.WAIT_BETWEEN_NUMBERS))
    
    return result

# ============== Keyboard Builders ==============
class Keyboards:
    @staticmethod
    def admin_main():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard"),
             InlineKeyboardButton("📈 Statistics", callback_data="stats")],
            [InlineKeyboardButton("📁 File Manager", callback_data="manage_files"),
             InlineKeyboardButton("📱 View Numbers", callback_data="view_numbers")],
            [InlineKeyboardButton("▶️ Start OTP", callback_data="start_otp"),
             InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
            [InlineKeyboardButton("👥 Users List", callback_data="users_list"),
             InlineKeyboardButton("📋 History", callback_data="history")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="dashboard")]
        ])
    
    @staticmethod
    def user_main():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 Browse Numbers", callback_data="user_view_numbers")],
            [InlineKeyboardButton("▶️ Send OTP", callback_data="start_otp")],
            [InlineKeyboardButton("📤 Upload Numbers File", callback_data="user_upload_info")],
            [InlineKeyboardButton("ℹ️ Help & Info", callback_data="user_help")],
            [InlineKeyboardButton("📊 My Stats", callback_data="user_stats")]
        ])
    
    @staticmethod
    def back_to(callback: str):
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=callback)]])

# ============== Bot Handlers ==============
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_data.add_user(user.id, user.username or "N/A", user.first_name)
    
    if is_admin(user.id):
        welcome_text = (
            "👑 Welcome Back, Owner!\n\n"
            f"🆔 ID: {Config.ADMIN_ID}\n"
            f"👤 Username: @{Config.ADMIN_USERNAME}\n"
            f"🔗 Profile: {Config.ADMIN_PROFILE}\n\n"
            f"🤖 {Config.BOT_NAME} v{Config.BOT_VERSION}\n\n"
            "✅ Full Control Panel Activated\n"
            "📁 Manage files, view numbers, send OTP\n"
            "👥 Monitor users and track activity\n\n"
            "⚡ Mode: Direct API (No Browser)"
        )
        reply_markup = Keyboards.admin_main()
    else:
        welcome_text = (
            f"👋 Welcome, {user.first_name}!\n\n"
            f"🤖 {Config.BOT_NAME}\n\n"
            "📱 Available Features:\n"
            "• Browse phone numbers\n"
            "• Send OTP codes\n"
            "• Upload number lists\n"
            "• Track your activity\n\n"
            f"👑 Owner: @{Config.ADMIN_USERNAME}\n\n"
            "⚡ Fast & Lightweight"
        )
        reply_markup = Keyboards.user_main()
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup
    )
    bot_data.add_history(user.id, "start", "Started the bot")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    bot_data.add_history(user_id, "button_click", data)
    
    # ========== ADMIN HANDLERS ==========
    if data == "dashboard":
        if not is_admin(user_id):
            return await query.edit_message_text("⛔ Access Denied!", reply_markup=Keyboards.back_to("user_back"))
        
        files = get_all_files()
        total_numbers = sum(f['count'] for f in files)
        total_users = len(bot_data.data["users"])
        
        text = (
            "📊 ADMIN DASHBOARD\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Admin: @{Config.ADMIN_USERNAME}\n"
            f"🆔 ID: {Config.ADMIN_ID}\n\n"
            f"📁 Files: {len(files)}\n"
            f"📱 Total Numbers: {total_numbers}\n"
            f"👥 Total Users: {total_users}\n\n"
            f"📤 OTP Sent: {bot_data.data['total_otp_sent']}\n"
            f"✅ Success: {bot_data.data['total_success']}\n"
            f"❌ Failed: {bot_data.data['total_failed']}\n\n"
            f"⚡ Mode: Direct API (No Browser)\n\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await query.edit_message_text(text, reply_markup=Keyboards.admin_main())
    
    elif data == "manage_files":
        if not is_admin(user_id):
            return await query.edit_message_text("⛔ Access Denied!")
        
        keyboard = [
            [InlineKeyboardButton("📤 Upload File", callback_data="upload_file"),
             InlineKeyboardButton("📋 List Files", callback_data="list_files")],
            [InlineKeyboardButton("🗑️ Delete File", callback_data="delete_file_menu"),
             InlineKeyboardButton("📱 View Numbers", callback_data="view_numbers")],
            [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="dashboard")]
        ]
        
        files = get_all_files()
        text = (
            "📁 FILE MANAGER\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📁 Total Files: {len(files)}\n"
            f"📱 Total Numbers: {sum(f['count'] for f in files)}\n\n"
            "Select an action:"
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "upload_file":
        if not is_admin(user_id):
            return await query.edit_message_text("⛔ Access Denied!")
        
        await query.edit_message_text(
            "📤 UPLOAD NUMBERS FILE\n\n"
            "Send a .txt file with phone numbers\n"
            "One number per line\n\n"
            "Example:\n"
            "01001234567\n"
            "01112345678\n"
            "01223456789",
            reply_markup=Keyboards.back_to("manage_files")
        )
    
    elif data == "list_files":
        if not is_admin(user_id):
            return await query.edit_message_text("⛔ Access Denied!")
        
        files = get_all_files()
        if not files:
            return await query.edit_message_text("📁 No files!", reply_markup=Keyboards.back_to("manage_files"))
        
        text = "📋 FILE LIST\n\n"
        for i, f in enumerate(files, 1):
            text += f"{i}. {f['name']} - {f['count']} numbers\n"
        
        keyboard = []
        for f in files:
            keyboard.append([InlineKeyboardButton(f"📱 {f['name']} ({f['count']})", callback_data=f"admin_view_{f['name']}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="manage_files")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "delete_file_menu":
        if not is_admin(user_id):
            return await query.edit_message_text("⛔ Access Denied!")
        
        files = get_all_files()
        if not files:
            return await query.edit_message_text("No files!", reply_markup=Keyboards.back_to("manage_files"))
        
        keyboard = []
        for f in files:
            keyboard.append([InlineKeyboardButton(f"🗑️ Delete {f['name']}", callback_data=f"delete_{f['name']}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="manage_files")])
        
        await query.edit_message_text("🗑️ DELETE FILES\n\nSelect file to delete:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "view_numbers":
        if not is_admin(user_id):
            return await query.edit_message_text("⛔ Access Denied!")
        
        files = get_all_files()
        if not files:
            return await query.edit_message_text("No files!", reply_markup=Keyboards.back_to("manage_files"))
        
        keyboard = []
        for f in files:
            keyboard.append([InlineKeyboardButton(f"📱 {f['name']} ({f['count']})", callback_data=f"admin_view_{f['name']}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="manage_files")])
        
        await query.edit_message_text("📱 VIEW NUMBERS\n\nSelect file:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "users_list":
        if not is_admin(user_id):
            return await query.edit_message_text("⛔ Access Denied!")
        
        users = bot_data.data["users"]
        if not users:
            return await query.edit_message_text("No users yet!", reply_markup=Keyboards.back_to("dashboard"))
        
        text = f"👥 USERS ({len(users)})\n\n"
        for uid, uinfo in list(users.items())[:20]:
            text += f"🆔 {uid} - {uinfo.get('first_name', 'Unknown')}\n"
            text += f"   Uploads: {uinfo.get('total_uploads', 0)} | OTP: {uinfo.get('total_otp', 0)}\n\n"
        
        await query.edit_message_text(text, reply_markup=Keyboards.back_to("dashboard"))
    
    elif data == "history":
        if not is_admin(user_id):
            return await query.edit_message_text("⛔ Access Denied!")
        
        history = bot_data.data["history"][-20:]
        if not history:
            return await query.edit_message_text("No history!", reply_markup=Keyboards.back_to("dashboard"))
        
        text = "📋 RECENT ACTIVITY\n\n"
        for entry in reversed(history):
            text += f"• {entry['user_id']} - {entry['action']}\n  {entry['timestamp']}\n\n"
        
        await query.edit_message_text(text, reply_markup=Keyboards.back_to("dashboard"))
    
    elif data == "stats":
        if not is_admin(user_id):
            return await query.edit_message_text("⛔ Access Denied!")
        
        success_rate = 0
        if bot_data.data['total_otp_sent'] > 0:
            success_rate = (bot_data.data['total_success'] / bot_data.data['total_otp_sent']) * 100
        
        text = (
            "📈 STATISTICS\n\n"
            f"📤 Total OTP: {bot_data.data['total_otp_sent']}\n"
            f"✅ Success: {bot_data.data['total_success']}\n"
            f"❌ Failed: {bot_data.data['total_failed']}\n"
            f"📊 Rate: {success_rate:.1f}%\n\n"
            f"👥 Users: {len(bot_data.data['users'])}\n"
            f"📁 Files: {len(get_all_files())}\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await query.edit_message_text(text, reply_markup=Keyboards.back_to("dashboard"))
    
    elif data == "settings":
        if not is_admin(user_id):
            return await query.edit_message_text("⛔ Access Denied!")
        
        text = (
            "⚙️ SETTINGS\n\n"
            f"🤖 {Config.BOT_NAME} v{Config.BOT_VERSION}\n"
            "⚡ Mode: Direct API (No Browser)\n"
            f"⏱️ Delay: {Config.WAIT_BETWEEN_NUMBERS[0]}-{Config.WAIT_BETWEEN_NUMBERS[1]}s\n\n"
            f"👑 Owner: @{Config.ADMIN_USERNAME}"
        )
        await query.edit_message_text(text, reply_markup=Keyboards.back_to("dashboard"))
    
    # ========== USER HANDLERS ==========
    elif data == "user_back":
        await query.edit_message_text("👋 Main Menu\n\nSelect an option:", reply_markup=Keyboards.user_main())
    
    elif data == "user_view_numbers":
        files = get_all_files()
        if not files:
            return await query.edit_message_text("📱 No numbers yet!", reply_markup=Keyboards.back_to("user_back"))
        
        keyboard = []
        for f in files:
            keyboard.append([InlineKeyboardButton(f"📱 {f['name']} ({f['count']})", callback_data=f"user_browse_{f['name']}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="user_back")])
        
        await query.edit_message_text("📱 AVAILABLE NUMBERS\n\nSelect file:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "user_upload_info":
        await query.edit_message_text(
            "📤 UPLOAD FILE\n\nSend .txt file with numbers\nOne per line\n\nExample:\n01001234567\n01112345678",
            reply_markup=Keyboards.back_to("user_back")
        )
    
    elif data == "user_help":
        text = (
            "ℹ️ HELP\n\n"
            "📱 Browse Numbers - View available numbers\n"
            "▶️ Send OTP - Send verification codes\n"
            "📤 Upload File - Share number lists\n\n"
            f"👑 Owner: @{Config.ADMIN_USERNAME}"
        )
        await query.edit_message_text(text, reply_markup=Keyboards.back_to("user_back"))
    
    elif data == "user_stats":
        uid = str(user_id)
        user_info = bot_data.data["users"].get(uid, {})
        
        text = (
            "📊 YOUR STATS\n\n"
            f"📤 Uploads: {user_info.get('total_uploads', 0)}\n"
            f"📱 OTP Sent: {user_info.get('total_otp', 0)}\n"
            f"📅 First Seen: {user_info.get('first_seen', 'N/A')}"
        )
        await query.edit_message_text(text, reply_markup=Keyboards.back_to("user_back"))
    
    # ========== SHARED HANDLERS ==========
    elif data == "start_otp":
        files = get_all_files()
        if not files:
            return await query.edit_message_text(
                "❌ No files!",
                reply_markup=Keyboards.back_to("dashboard" if is_admin(user_id) else "user_back")
            )
        
        keyboard = []
        for f in files:
            keyboard.append([InlineKeyboardButton(f"▶️ {f['name']} ({f['count']})", callback_data=f"otp_file_{f['name']}")])
        
        back_callback = "dashboard" if is_admin(user_id) else "user_back"
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data=back_callback)])
        
        await query.edit_message_text("▶️ START OTP\n\nSelect file:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    # ========== FILE ACTIONS ==========
    elif data.startswith("delete_"):
        if not is_admin(user_id):
            return await query.edit_message_text("⛔ Access Denied!")
        
        filename = data.replace("delete_", "")
        filepath = os.path.join(Config.NUMBERS_DIR, filename)
        
        if os.path.exists(filepath):
            os.remove(filepath)
            bot_data.add_history(user_id, "delete_file", filename)
            await query.edit_message_text(f"✅ {filename} deleted!", reply_markup=Keyboards.back_to("manage_files"))
        else:
            await query.edit_message_text("❌ File not found!", reply_markup=Keyboards.back_to("manage_files"))
    
    elif data.startswith("admin_view_"):
        if not is_admin(user_id):
            return await query.edit_message_text("⛔ Access Denied!")
        
        filename = data.replace("admin_view_", "")
        if "_p" in filename:
            parts = filename.split("_p")
            filename = parts[0]
            page = int(parts[1])
        else:
            page = 0
        
        numbers = get_file_numbers(filename)
        if not numbers:
            return await query.edit_message_text("No numbers!", reply_markup=Keyboards.back_to("view_numbers"))
        
        total_pages = (len(numbers) + Config.NUMBERS_PER_PAGE - 1) // Config.NUMBERS_PER_PAGE
        start_idx = page * Config.NUMBERS_PER_PAGE
        end_idx = start_idx + Config.NUMBERS_PER_PAGE
        page_numbers = numbers[start_idx:end_idx]
        
        text = f"📱 {filename}\nTotal: {len(numbers)} | Page {page+1}/{total_pages}\n\n"
        for i, num in enumerate(page_numbers, start_idx + 1):
            text += f"{i}. {num}\n"
        
        keyboard = []
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"admin_view_{filename}_p{page-1}"))
        nav_row.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("➡️", callback_data=f"admin_view_{filename}_p{page+1}"))
        keyboard.append(nav_row)
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="view_numbers")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("user_browse_"):
        filename = data.replace("user_browse_", "")
        if "_p" in filename:
            parts = filename.split("_p")
            filename = parts[0]
            page = int(parts[1])
        else:
            page = 0
        
        numbers = get_file_numbers(filename)
        if not numbers:
            return await query.edit_message_text("No numbers!", reply_markup=Keyboards.back_to("user_view_numbers"))
        
        total_pages = (len(numbers) + Config.NUMBERS_PER_PAGE - 1) // Config.NUMBERS_PER_PAGE
        start_idx = page * Config.NUMBERS_PER_PAGE
        end_idx = start_idx + Config.NUMBERS_PER_PAGE
        page_numbers = numbers[start_idx:end_idx]
        
        text = f"📱 {filename}\nTotal: {len(numbers)} | Page {page+1}/{total_pages}\n\n"
        for i, num in enumerate(page_numbers, start_idx + 1):
            text += f"{i}. {num}\n"
        
        keyboard = []
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"user_browse_{filename}_p{page-1}"))
        nav_row.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("➡️", callback_data=f"user_browse_{filename}_p{page+1}"))
        keyboard.append(nav_row)
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="user_view_numbers")])
        keyboard.append([InlineKeyboardButton("🏠 Menu", callback_data="user_back")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("otp_file_"):
        filename = data.replace("otp_file_", "")
        numbers = get_file_numbers(filename)
        
        if not numbers:
            return await query.edit_message_text(
                "❌ No numbers!",
                reply_markup=Keyboards.back_to("dashboard" if is_admin(user_id) else "user_back")
            )
        
        await query.edit_message_text(
            f"🔄 STARTING OTP\n\n"
            f"📁 {filename}\n"
            f"📱 {len(numbers)} numbers\n\n"
            f"⏳ Processing...\n"
            "⚡ Direct API Mode"
        )
        
        success = 0
        failed = 0
        
        for idx, number in enumerate(numbers, 1):
            progress = create_progress_bar(idx, len(numbers))
            
            try:
                await query.edit_message_text(
                    f"🔄 PROCESSING\n\n"
                    f"📱 {number}\n"
                    f"📊 {idx}/{len(numbers)}\n"
                    f"{progress}\n\n"
                    f"✅ {success} | ❌ {failed}"
                )
            except:
                pass
            
            result = await process_single_number(number)
            
            if result["success"]:
                success += 1
            else:
                failed += 1
        
        uid = str(user_id)
        if uid in bot_data.data["users"]:
            bot_data.data["users"][uid]["total_otp"] += len(numbers)
        bot_data.save_data()
        bot_data.add_history(user_id, "otp_process", f"{filename}: {success}/{len(numbers)}")
        
        success_rate = (success / len(numbers) * 100) if len(numbers) > 0 else 0
        text = (
            f"✅ COMPLETE\n\n"
            f"📁 {filename}\n"
            f"📱 Total: {len(numbers)}\n"
            f"✅ Success: {success}\n"
            f"❌ Failed: {failed}\n"
            f"📊 Rate: {success_rate:.1f}%\n\n"
            "⚡ Direct API Mode"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔄 Again", callback_data=f"otp_file_{filename}")],
            [InlineKeyboardButton("🔙 Menu", callback_data="dashboard" if is_admin(user_id) else "user_back")]
        ]
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "noop":
        await query.answer()

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    document = update.message.document
    
    if not document.file_name.endswith('.txt'):
        return await update.message.reply_text("❌ Only .txt files accepted!")
    
    try:
        file = await context.bot.get_file(document.file_id)
        file_path = os.path.join(Config.NUMBERS_DIR, document.file_name)
        
        if os.path.exists(file_path):
            base, ext = os.path.splitext(document.file_name)
            file_path = os.path.join(Config.NUMBERS_DIR, f"{base}_{user.id}{ext}")
        
        await file.download_to_drive(file_path)
        
        numbers = get_file_numbers(os.path.basename(file_path))
        
        uid = str(user.id)
        if uid in bot_data.data["users"]:
            bot_data.data["users"][uid]["total_uploads"] += 1
        else:
            bot_data.add_user(user.id, user.username or "N/A", user.first_name)
            bot_data.data["users"][uid]["total_uploads"] = 1
        bot_data.save_data()
        
        preview = "\n".join([f"• {n}" for n in numbers[:5]])
        if len(numbers) > 5:
            preview += f"\n... +{len(numbers)-5} more"
        
        keyboard = [
            [InlineKeyboardButton("🏠 Menu", callback_data="dashboard" if is_admin(user.id) else "user_back")]
        ]
        
        await update.message.reply_text(
            f"✅ FILE UPLOADED!\n\n"
            f"📁 {os.path.basename(file_path)}\n"
            f"📱 {len(numbers)} numbers\n\n"
            f"📋 Preview:\n{preview}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        bot_data.add_history(user.id, "upload_file", f"{os.path.basename(file_path)}: {len(numbers)} numbers")
        
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        await update.message.reply_text(f"❌ Upload failed: {str(e)[:100]}")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"👋 Welcome to {Config.BOT_NAME}!\n\n"
        "Use /start to access the bot menu.\n"
        "Or send a .txt file with phone numbers.\n\n"
        f"👑 Owner: @{Config.ADMIN_USERNAME}"
    )

# ============== Error Handler ==============
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ An error occurred. Please try again.\n"
                "Use /start to restart the bot."
            )
    except:
        pass

# ============== Main ==============
def main():
    print("\n" + "=" * 50)
    print(f"  {Config.BOT_NAME} v{Config.BOT_VERSION}")
    print("=" * 50)
    print(f"  Mode: Direct API (No Browser)")
    print(f"  Owner: @{Config.ADMIN_USERNAME}")
    print("=" * 50 + "\n")
    
    app = Application.builder().token(Config.BOT_TOKEN).connect_timeout(30).read_timeout(30).build()
    
    # Add error handler
    app.add_error_handler(error_handler)
    
    # Add handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.TEXT, handle_file_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    print("[+] Bot is running (Direct API Mode)...\n")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[!] Bot stopped by user")
    except Exception as e:
        print(f"\n[!] Error: {e}")
        logger.error(f"Main error: {e}", exc_info=True)
