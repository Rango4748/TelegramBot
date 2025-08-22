import os
import json
import requests
import logging
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)
import jdatetime  # برای تاریخ شمسی

# ---------- تنظیمات ----------
# اطمینان از وجود دایرکتوری /root/bot
BOT_DIR = "/root/bot"
os.makedirs(BOT_DIR, exist_ok=True)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(os.path.join(BOT_DIR, "bot.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
BOT_TOKEN = "BOT_TOKEN_PLACEHOLDER"  # توکن ربات
ADMIN_ID = ADMIN_ID_PLACEHOLDER  # ایدی تلگرام ادمین
SUPPORT_USERNAME = "SUPPORT_USERNAME_PLACEHOLDER"  # ایدی تلگرام پشتیبانی
DB_FILE = os.path.join(BOT_DIR, "panels.db")
EMAIL, PANEL_ADDRESS, PANEL_USERNAME, PANEL_PASSWORD, PANEL_TYPE = range(5)
DELETE_PANEL, DELETE_PANEL_URL = range(2)
EDIT_PANEL, EDIT_PANEL_SELECT, EDIT_PANEL_FIELD, EDIT_PANEL_VALUE = range(4)
SESSION_CACHE = {}  # کش برای سشن‌ها
SESSION_TIMEOUT = 300  # زمان انقضای سشن: 5 دقیقه (به ثانیه)

# ---------- مدیریت دیتابیس SQLite ----------
def init_db():
    """ایجاد جدول پنل‌ها در SQLite"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS panels (
                url TEXT PRIMARY KEY,
                username TEXT,
                password TEXT,
                type TEXT
            )
        ''')
        conn.commit()
        logger.info(f"Database initialized at {DB_FILE}")
    except sqlite3.OperationalError as e:
        logger.error(f"Error initializing database: {str(e)}")
    finally:
        conn.close()

def load_panels():
    """بارگذاری پنل‌ها از SQLite"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT url, username, password, type FROM panels")
        panels = [
            {"url": row[0], "username": row[1], "password": row[2], "type": row[3]}
            for row in cursor.fetchall()
        ]
        conn.close()
        logger.info(f"Loaded {len(panels)} panels from {DB_FILE}")
        return panels
    except sqlite3.OperationalError as e:
        logger.error(f"Error loading panels: {str(e)}")
        return []

def save_panels(panels):
    """ذخیره پنل‌ها در SQLite با مدیریت خطاها"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM panels")
        for panel in panels:
            cursor.execute(
                "INSERT OR REPLACE INTO panels (url, username, password, type) VALUES (?, ?, ?, ?)",
                (panel['url'], panel['username'], panel['password'], panel['type'])
            )
        conn.commit()
        logger.info(f"Successfully saved {len(panels)} panels to {DB_FILE}")
    except sqlite3.OperationalError as e:
        logger.error(f"Database error while saving panels: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error while saving panels: {str(e)}")
    finally:
        conn.close()

# مقداردهی اولیه دیتابیس
init_db()
PANELS = load_panels()

# ---------- مدیریت کش سشن‌ها ----------
def get_cached_session(panel):
    """گرفتن یا ایجاد سشن برای پنل"""
    url = panel['url']
    current_time = datetime.now().timestamp()
    
    # چک کردن کش
    if url in SESSION_CACHE:
        session, timestamp = SESSION_CACHE[url]
        if current_time - timestamp < SESSION_TIMEOUT:
            logger.info(f"Using cached session for {url}")
            return session
    
    # ایجاد سشن جدید
    logger.info(f"Creating new session for {url}")
    session = requests.Session()
    login_data = {'username': panel['username'], 'password': panel['password']}
    try:
        login_response = session.post(f"{url}/login", json=login_data, timeout=5)
        if login_response.status_code == 200 and login_response.json().get('success', False):
            SESSION_CACHE[url] = (session, current_time)
            return session
        else:
            logger.error(f"Login failed for {url}: {login_response.status_code} - {login_response.text}")
            return None
    except Exception as e:
        logger.error(f"Error logging in to {url}: {str(e)}")
        return None

def cleanup_sessions():
    """پاکسازی سشن‌های منقضی‌شده از کش"""
    current_time = datetime.now().timestamp()
    expired = [url for url, (_, timestamp) in SESSION_CACHE.items() if current_time - timestamp >= SESSION_TIMEOUT]
    for url in expired:
        del SESSION_CACHE[url]
        logger.info(f"Removed expired session for {url}")

# ---------- توابع کمکی ----------
def size_format(size_bytes):
    """فرمت کردن حجم به MB یا GB بر اساس مقدار"""
    if size_bytes < 1024**3:  # کمتر از 1GB
        return f"{size_bytes / (1024**2):.2f} MB"
    return f"{size_bytes / (1024**3):.2f} GB"

def format_time_left(seconds):
    """فرمت کردن زمان باقی‌مانده به روز، ساعت و دقیقه"""
    if seconds <= 0:
        return "منقضی شده"
    days = seconds // (24 * 3600)
    seconds %= (24 * 3600)
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    if days > 0:
        return f"{int(days)} روز و {int(hours)} ساعت و {int(minutes)} دقیقه"
    elif hours > 0:
        return f"{int(hours)} ساعت و {int(minutes)} دقیقه"
    else:
        return f"{int(minutes)} دقیقه"

def extract_email_from_link(link):
    """استخراج ایمیل از لینک VLESS/VMess"""
    try:
        if link.startswith("vless://") or link.startswith("trojan://"):
            if "#" in link:
                return link.split("#")[-1]
        elif link.startswith("vmess://"):
            import base64
            base64_str = link.split("//")[1].split("#")[0].split("?")[0]
            data = json.loads(base64.b64decode(base64_str + "==").decode())
            return data.get("ps") or data.get("email") or None
        return None
    except Exception as e:
        logger.error(f"Error extracting email: {e}")
        return None

def validate_panel(url, username, password, panel_type):
    """اعتبارسنجی پنل قبل از اضافه کردن"""
    session = requests.Session()
    login_data = {'username': username, 'password': password}
    try:
        login_response = session.post(f"{url}/login", json=login_data, timeout=5)
        if login_response.status_code != 200:
            return False, "اتصال به پنل ممکن نیست - آدرس یا پورت را بررسی کنید."
        if not login_response.json().get('success', False):
            return False, "ورود ناموفق - نام کاربری یا رمز عبور اشتباه است."
        
        # تست یک درخواست ساده برای اطمینان از دسترسی
        endpoint = f"{url}/panel/api/inbounds/list" if panel_type == "sanaei" else f"{url}/xui/inbound/list"
        test_response = session.get(endpoint, timeout=5) if panel_type == "sanaei" else session.post(endpoint, timeout=5)
        if test_response.status_code != 200 or not test_response.json().get('success', False):
            return False, "دسترسی به پنل پس از ورود ممکن نیست - نوع پنل را بررسی کنید."
        
        return True, "اتصال به پنل موفقیت‌آمیز بود."
    except requests.exceptions.ConnectionError:
        return False, "اتصال به پنل ممکن نیست - آدرس یا پورت را بررسی کنید."
    except requests.exceptions.Timeout:
        return False, "زمان اتصال به پنل تمام شد - اتصال اینترنت را بررسی کنید."
    except Exception as e:
        logger.error(f"Unexpected error in validate_panel: {str(e)}")
        return False, "خطای نامشخص در اتصال به پنل - لطفاً دوباره تلاش کنید."

def get_panel_by_email(email):
    cleanup_sessions()  # پاکسازی سشن‌های منقضی‌شده
    for panel in PANELS:
        try:
            if 'type' not in panel:
                logger.error(f"Panel {panel['url']} is missing 'type' key")
                continue

            logger.info(f"Trying panel {panel['url']} with type {panel['type']}")
            session = get_cached_session(panel)
            if not session:
                continue

            if panel['type'] == "sanaei":
                endpoint = f"{panel['url']}/panel/api/inbounds/list"
                response = session.get(endpoint, timeout=5)
            elif panel['type'] == "alireza":
                endpoint = f"{panel['url']}/xui/inbound/list"
                response = session.post(endpoint, timeout=5)
            else:
                logger.error(f"Invalid panel type for {panel['url']}: {panel['type']}")
                continue

            if not response.ok or not response.json().get('success', False):
                logger.error(f"Failed to fetch inbounds for {panel['url']}: {response.status_code} - {response.text}")
                continue

            inbounds = response.json().get('obj', [])
            logger.info(f"Inbounds received for {panel['url']}: {len(inbounds)} inbounds")
            
            for inbound in inbounds:
                clients = inbound.get('clientStats', [])
                for client in clients:
                    if client.get('email') == email:
                        logger.info(f"Found user {email} in clientStats: {client}")
                        return client, panel
                
                settings = json.loads(inbound.get("settings", "{}"))
                for client in settings.get("clients", []):
                    if client.get("email") == email:
                        for stat in inbound.get("clientStats", []):
                            if stat.get("email") == email:
                                client["up"] = stat.get("up", 0)
                                client["down"] = stat.get("down", 0)
                                client["total"] = stat.get("total", client.get("totalGB", 0))
                                break
                        else:
                            client["up"] = 0
                            client["down"] = 0
                            client["total"] = client.get("totalGB", 0)
                        logger.info(f"Found user {email} in settings: {client}")
                        return client, panel
        except Exception as e:
            logger.error(f"Error fetching user {email} from {panel['url']}: {str(e)}")
    return None, None

# ---------- ربات ----------
def get_main_keyboard(user_id):
    keyboard = [
        [KeyboardButton("📊 بررسی کاربر"), KeyboardButton("📞 پشتیبانی")]
    ]
    if user_id == ADMIN_ID:
        keyboard.append([
            KeyboardButton("➕ افزودن پنل"),
            KeyboardButton("🗑️ حذف پنل"),
            KeyboardButton("✏️ ویرایش پنل")
        ])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await update.message.reply_text(
        "سلام! از دکمه‌های زیر استفاده کنید:",
        reply_markup=get_main_keyboard(user_id)
    )

# ---------- بررسی کاربر ----------
async def check_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    back_keyboard = [[KeyboardButton("🔙 بازگشت")]]
    reply_markup = ReplyKeyboardMarkup(back_keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        "👤 کاربر گرامی :\nلطفا لینک سرویس خود را ارسال کنید",
        reply_markup=reply_markup
    )
    return EMAIL

async def check_user_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 بازگشت":
        return await cancel(update, context)
    link = update.message.text
    email = extract_email_from_link(link)
    if not email:
        await update.message.reply_text(
            "لینک معتبر نیست! لطفاً لینک VLESS یا VMess معتبر ارسال کنید.",
            reply_markup=get_main_keyboard(update.message.from_user.id)
        )
        return ConversationHandler.END

    client, _ = get_panel_by_email(email)
    if not client:
        await update.message.reply_text(
            f"کاربر با ایمیل {email} در هیچ پنلی پیدا نشد!",
            reply_markup=get_main_keyboard(update.message.from_user.id)
        )
        return ConversationHandler.END

    total = client.get('total', 0)
    up = client.get('up', 0)
    down = client.get('down', 0)
    expiry = client.get('expiryTime', 0)
    
    total_str = size_format(total) if total > 0 else "نامحدود"
    remain = total - (up + down) if total > 0 else 0
    remain_str = size_format(remain) if total > 0 and remain > 0 else "نامحدود" if total > 0 else "0.00 MB"
    if expiry and expiry > 0:
        expiry_dt = datetime.fromtimestamp(expiry / 1000)
        jalali_date = jdatetime.datetime.fromgregorian(datetime=expiry_dt)
        date_str = jalali_date.strftime('%Y-%m-%d %H:%M')
        time_left = format_time_left((expiry_dt - datetime.now()).total_seconds())
    else:
        date_str = "نامحدود"
        time_left = "نامحدود"
    status = "✅ فعال" if client.get('enable', False) else "❌ غیرفعال"

    response = (
        f"👤 نام: {email}\n"
        f"📊 حجم کل: {total_str}\n"
        f"⬇️ دانلود: {size_format(down)}\n"
        f"⬆️ آپلود: {size_format(up)}\n"
        f"🧮 حجم باقی‌مانده: {remain_str}\n"
        f"⏳ تاریخ انقضا: {date_str}\n"
        f"⏳ تایم باقی‌مانده: {time_left}\n"
        f"{status}"
    )
    await update.message.reply_text(response, reply_markup=get_main_keyboard(update.message.from_user.id))
    return ConversationHandler.END

# ---------- افزودن پنل ----------
async def add_panel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text(
            "شما اجازه این کار را ندارید!",
            reply_markup=get_main_keyboard(update.message.from_user.id)
        )
        return ConversationHandler.END
    back_keyboard = [[KeyboardButton("🔙 بازگشت")]]
    reply_markup = ReplyKeyboardMarkup(back_keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        "لطفاً آدرس پنل را وارد کنید (مثال: http://1.2.3.4:2053):",
        reply_markup=reply_markup
    )
    return PANEL_ADDRESS

async def add_panel_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 بازگشت":
        return await cancel(update, context)
    context.user_data['panel_url'] = update.message.text
    back_keyboard = [[KeyboardButton("🔙 بازگشت")]]
    reply_markup = ReplyKeyboardMarkup(back_keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("لطفاً نام کاربری پنل را وارد کنید:", reply_markup=reply_markup)
    return PANEL_USERNAME

async def add_panel_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 بازگشت":
        return await cancel(update, context)
    context.user_data['panel_username'] = update.message.text
    back_keyboard = [[KeyboardButton("🔙 بازگشت")]]
    reply_markup = ReplyKeyboardMarkup(back_keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("لطفاً رمز عبور پنل را وارد کنید:", reply_markup=reply_markup)
    return PANEL_PASSWORD

async def add_panel_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 بازگشت":
        return await cancel(update, context)
    context.user_data['panel_password'] = update.message.text
    panel_type_keyboard = [
        [KeyboardButton("سنایی"), KeyboardButton("علیرضا")],
        [KeyboardButton("🔙 بازگشت")]
    ]
    reply_markup = ReplyKeyboardMarkup(panel_type_keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("لطفا نوع پنل خود را انتخاب کنید :", reply_markup=reply_markup)
    return PANEL_TYPE

async def add_panel_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 بازگشت":
        return await cancel(update, context)
    panel_type = update.message.text
    if panel_type == "سنایی":
        panel_type = "sanaei"
    elif panel_type == "علیرضا":
        panel_type = "alireza"
    elif panel_type == "type 1":
        panel_type = "sanaei"
    elif panel_type == "type 2":
        panel_type = "alireza"
    else:
        panel_type_keyboard = [
            [KeyboardButton("سنایی"), KeyboardButton("علیرضا")],
            [KeyboardButton("🔙 بازگشت")]
        ]
        reply_markup = ReplyKeyboardMarkup(panel_type_keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            "نوع پنل نامعتبر است! لطفاً فقط یکی از گزینه‌های زیر را انتخاب کنید:",
            reply_markup=reply_markup
        )
        return PANEL_TYPE
    
    # اعتبارسنجی پنل
    url = context.user_data['panel_url']
    username = context.user_data['panel_username']
    password = context.user_data['panel_password']
    is_valid, message = validate_panel(url, username, password, panel_type)
    if not is_valid:
        back_keyboard = [[KeyboardButton("🔙 بازگشت")]]
        reply_markup = ReplyKeyboardMarkup(back_keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            f"خطا در افزودن پنل: {message}\nلطفاً دوباره تلاش کنید یا اطلاعات را بررسی کنید.",
            reply_markup=reply_markup
        )
        return PANEL_ADDRESS  # بازگشت به مرحله وارد کردن آدرس
    
    # اگر اعتبارسنجی موفق بود، پنل را اضافه کن
    PANELS.append({
        'url': url,
        'username': username,
        'password': password,
        'type': panel_type
    })
    save_panels(PANELS)
    await update.message.reply_text(
        "پنل با موفقیت اضافه شد!",
        reply_markup=get_main_keyboard(update.message.from_user.id)
    )
    return ConversationHandler.END

# ---------- حذف پنل ----------
async def delete_panel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text(
            "شما اجازه این کار را ندارید!",
            reply_markup=get_main_keyboard(update.message.from_user.id)
        )
        return ConversationHandler.END
    if not PANELS:
        await update.message.reply_text(
            "هیچ پنلی وجود ندارد!",
            reply_markup=get_main_keyboard(update.message.from_user.id)
        )
        return ConversationHandler.END
    keyboard = [
        [InlineKeyboardButton(f"{panel['url']} ({panel['type']})", callback_data=f"delete_panel:{panel['url']}")]
        for panel in PANELS
    ]
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="cancel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "لطفاً پنل مورد نظر برای حذف را انتخاب کنید:",
        reply_markup=reply_markup
    )
    return DELETE_PANEL_URL

async def delete_panel_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.message.reply_text(
            "عملیات لغو شد.",
            reply_markup=get_main_keyboard(update.effective_user.id)
        )
        return ConversationHandler.END
    if query.data.startswith("delete_panel:"):
        url = query.data.split(":", 1)[1]
        global PANELS
        for panel in PANELS:
            if panel['url'] == url:
                PANELS.remove(panel)
                save_panels(PANELS)
                # حذف سشن کش‌شده
                if url in SESSION_CACHE:
                    del SESSION_CACHE[url]
                    logger.info(f"Removed cached session for {url}")
                await query.message.reply_text(
                    f"پنل {url} با موفقیت حذف شد!",
                    reply_markup=get_main_keyboard(update.effective_user.id)
                )
                return ConversationHandler.END
        await query.message.reply_text(
            f"پنل با آدرس {url} پیدا نشد!",
            reply_markup=get_main_keyboard(update.effective_user.id)
        )
        return ConversationHandler.END
    return ConversationHandler.END

# ---------- ویرایش پنل ----------
async def edit_panel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text(
            "شما اجازه این کار را ندارید!",
            reply_markup=get_main_keyboard(update.message.from_user.id)
        )
        return ConversationHandler.END
    if not PANELS:
        await update.message.reply_text(
            "هیچ پنلی وجود ندارد!",
            reply_markup=get_main_keyboard(update.message.from_user.id)
        )
        return ConversationHandler.END
    keyboard = [
        [InlineKeyboardButton(f"{panel['url']} ({panel['type']})", callback_data=f"edit_panel:{panel['url']}")]
        for panel in PANELS
    ]
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="cancel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "لطفاً پنل مورد نظر برای ویرایش را انتخاب کنید:",
        reply_markup=reply_markup
    )
    return EDIT_PANEL_SELECT

async def edit_panel_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.message.reply_text(
            "عملیات لغو شد.",
            reply_markup=get_main_keyboard(update.effective_user.id)
        )
        return ConversationHandler.END
    if query.data.startswith("edit_panel:"):
        url = query.data.split(":", 1)[1]
        context.user_data['edit_panel_url'] = url
        keyboard = [
            [KeyboardButton("آدرس"), KeyboardButton("نام کاربری")],
            [KeyboardButton("رمز عبور"), KeyboardButton("نوع پنل")],
            [KeyboardButton("🔙 بازگشت")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await query.message.reply_text(
            "لطفاً فیلدی که می‌خواهید ویرایش کنید را انتخاب کنید:",
            reply_markup=reply_markup
        )
        return EDIT_PANEL_FIELD
    return ConversationHandler.END

async def edit_panel_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 بازگشت":
        return await cancel(update, context)
    field = update.message.text
    if field not in ["آدرس", "نام کاربری", "رمز عبور", "نوع پنل"]:
        keyboard = [
            [KeyboardButton("آدرس"), KeyboardButton("نام کاربری")],
            [KeyboardButton("رمز عبور"), KeyboardButton("نوع پنل")],
            [KeyboardButton("🔙 بازگشت")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            "فیلد نامعتبر است! لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
            reply_markup=reply_markup
        )
        return EDIT_PANEL_FIELD
    context.user_data['edit_field'] = field
    if field == "نوع پنل":
        panel_type_keyboard = [
            [KeyboardButton("سنایی"), KeyboardButton("علیرضا")],
            [KeyboardButton("🔙 بازگشت")]
        ]
        reply_markup = ReplyKeyboardMarkup(panel_type_keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text("لطفا نوع پنل جدید را انتخاب کنید :", reply_markup=reply_markup)
    else:
        back_keyboard = [[KeyboardButton("🔙 بازگشت")]]
        reply_markup = ReplyKeyboardMarkup(back_keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(f"لطفاً مقدار جدید برای {field} را وارد کنید:")
    return EDIT_PANEL_VALUE

async def edit_panel_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 بازگشت":
        return await cancel(update, context)
    value = update.message.text
    field = context.user_data['edit_field']
    old_url = context.user_data['edit_panel_url']
    global PANELS
    new_panels = []
    for panel in PANELS:
        if panel['url'] == old_url:
            if field == "آدرس":
                panel['url'] = value
            elif field == "نام کاربری":
                panel['username'] = value
            elif field == "رمز عبور":
                panel['password'] = value
            elif field == "نوع پنل":
                if value == "سنایی":
                    panel['type'] = "sanaei"
                elif value == "علیرضا":
                    panel['type'] = "alireza"
                elif value == "type 1":
                    panel['type'] = "sanaei"
                elif value == "type 2":
                    panel['type'] = "alireza"
                else:
                    panel_type_keyboard = [
                        [KeyboardButton("سنایی"), KeyboardButton("علیرضا")],
                        [KeyboardButton("🔙 بازگشت")]
                    ]
                    reply_markup = ReplyKeyboardMarkup(panel_type_keyboard, resize_keyboard=True, one_time_keyboard=True)
                    await update.message.reply_text(
                        "نوع پنل نامعتبر است! لطفاً فقط یکی از گزینه‌های زیر را انتخاب کنید:",
                        reply_markup=reply_markup
                    )
                    return EDIT_PANEL_VALUE
            # اگر آدرس تغییر کرده، سشن قدیمی رو پاک کن
            if field == "آدرس" and old_url in SESSION_CACHE:
                del SESSION_CACHE[old_url]
                logger.info(f"Removed cached session for {old_url}")
        new_panels.append(panel)
    PANELS = new_panels
    save_panels(PANELS)
    await update.message.reply_text(
        f"فیلد {field} برای پنل {old_url} با موفقیت ویرایش شد!",
        reply_markup=get_main_keyboard(update.message.from_user.id)
    )
    return ConversationHandler.END

# ---------- پشتیبانی ----------
async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("ارسال پیام به پشتیبانی", url=f"https://t.me/{SUPPORT_USERNAME[1:]}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "برای تماس با پشتیبانی، روی دکمه زیر کلیک کنید:",
        reply_markup=reply_markup
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    if text == "📊 بررسی کاربر":
        return await check_user_command(update, context)
    elif text == "➕ افزودن پنل":
        return await add_panel_start(update, context)
    elif text == "🗑️ حذف پنل":
        return await delete_panel_start(update, context)
    elif text == "✏️ ویرایش پنل":
        return await edit_panel_start(update, context)
    elif text == "📞 پشتیبانی":
        return await support_command(update, context)
    else:
        await update.message.reply_text(
            "لطفاً از دکمه‌ها استفاده کنید:",
            reply_markup=get_main_keyboard(user_id)
        )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "عملیات لغو شد.",
        reply_markup=get_main_keyboard(update.message.from_user.id)
    )
    return ConversationHandler.END

# ---------- اجرای ربات ----------
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    conv_check = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^📊 بررسی کاربر$'), check_user_command)],
        states={EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_user_email)]},
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex('^🔙 بازگشت$'), cancel)],
    )
    conv_panel = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^➕ افزودن پنل$'), add_panel_start)],
        states={
            PANEL_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_panel_address)],
            PANEL_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_panel_username)],
            PANEL_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_panel_password)],
            PANEL_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_panel_type)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex('^🔙 بازگشت$'), cancel)],
    )
    conv_delete = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^🗑️ حذف پنل$'), delete_panel_start)],
        states={
            DELETE_PANEL_URL: [CallbackQueryHandler(delete_panel_url)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    conv_edit = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^✏️ ویرایش پنل$'), edit_panel_start)],
        states={
            EDIT_PANEL_SELECT: [CallbackQueryHandler(edit_panel_select)],
            EDIT_PANEL_FIELD: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_panel_field)],
            EDIT_PANEL_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_panel_value)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex('^🔙 بازگشت$'), cancel)],
    )
    app.add_handler(conv_check)
    app.add_handler(conv_panel)
    app.add_handler(conv_delete)
    app.add_handler(conv_edit)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("ربات در حال اجراست...")
    app.run_polling()
