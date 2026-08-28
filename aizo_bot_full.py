import os
import logging
import threading
import base64
import sqlite3
import time
from datetime import datetime

import telebot
from telebot import types
from openai import OpenAI
from telebot.types import Message


# =========================================================
# SOZLAMALAR
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Admin Telegram ID (Railway Variables ichida ADMIN_ID sifatida qo'shing)
ADMIN_ID = os.getenv("ADMIN_ID")

MODEL_NAME = "deepseek-v4-flash-vision-exp"

MAX_TELEGRAM_LENGTH = 2500

# Javob uzunligi (token). Kichikroq = qisqaroq javob, tezroq javob.
MAX_TOKENS = 700

# Har bir user uchun saqlanadigan suhbat xabarlari soni
MAX_HISTORY_MESSAGES = 40

# Rasm maksimal hajmi (bayt). 10 MB.
MAX_PHOTO_SIZE = 10 * 1024 * 1024

# API xato bo'lsa necha marta qayta urinish
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 2

DB_PATH = "aizo.db"


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("Aizo")


# =========================================================
# ENVIRONMENT TEKSHIRISH
# =========================================================

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN topilmadi!")

if not DEEPSEEK_API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY topilmadi!")

if not ADMIN_ID:
    logger.warning("ADMIN_ID topilmadi! Admin panel ishlamaydi.")
    ADMIN_ID = None
else:
    ADMIN_ID = int(ADMIN_ID)


# =========================================================
# DEEPSEEK CLIENT
# =========================================================

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.b.ai/v1"
)


# =========================================================
# TELEGRAM BOT
# =========================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)


# =========================================================
# DATABASE (SQLite)
# =========================================================

db_lock = threading.Lock()


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_lock:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_seen TEXT,
                last_seen TEXT,
                message_count INTEGER DEFAULT 0,
                is_blocked INTEGER DEFAULT 0
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        cur.execute("""
            INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('maintenance', '0')
        """)

        conn.commit()
        conn.close()


def touch_user(user_id: int):
    now = datetime.utcnow().isoformat()
    with db_lock:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()

        if row is None:
            cur.execute(
                "INSERT INTO users (user_id, first_seen, last_seen, message_count, is_blocked) VALUES (?, ?, ?, 1, 0)",
                (user_id, now, now)
            )
        else:
            cur.execute(
                "UPDATE users SET last_seen = ?, message_count = message_count + 1 WHERE user_id = ?",
                (now, user_id)
            )

        conn.commit()
        conn.close()


def is_user_blocked(user_id: int) -> bool:
    with db_lock:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        return bool(row["is_blocked"]) if row else False


def set_user_blocked(user_id: int, blocked: bool):
    with db_lock:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET is_blocked = ? WHERE user_id = ?",
            (1 if blocked else 0, user_id)
        )
        conn.commit()
        conn.close()


def get_stats():
    with db_lock:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) as c FROM users")
        total_users = cur.fetchone()["c"]

        cur.execute("SELECT COALESCE(SUM(message_count), 0) as c FROM users")
        total_messages = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) as c FROM users WHERE is_blocked = 1")
        blocked_users = cur.fetchone()["c"]

        conn.close()

    return {
        "total_users": total_users,
        "total_messages": total_messages,
        "blocked_users": blocked_users
    }


def get_all_user_ids():
    with db_lock:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE is_blocked = 0")
        rows = cur.fetchall()
        conn.close()
    return [row["user_id"] for row in rows]


def get_setting(key: str, default: str = None):
    with db_lock:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
        row = cur.fetchone()
        conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    with db_lock:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO bot_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value)
        )
        conn.commit()
        conn.close()


def is_maintenance_mode() -> bool:
    return get_setting("maintenance", "0") == "1"


init_db()


# =========================================================
# AIZO SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
Sening isming Aizo. Sen Shohruxning shaxsiy AI yordamchisisan.

Kim ekaningni so'rashsa: "Men Aizo — Shohruxning AI yordamchisiman."

QOIDALAR:
- Javoblaring QISQA va aniq bo'lsin. Odatda 2-5 gap yetarli.
- Kerak bo'lmasa uzun tushuntirish, ortiqcha kirish so'zlari yozma.
- To'g'ridan-to'g'ri javobdan boshla, "albatta", "juda ajoyib savol" kabi keraksiz kirish qilma.
- Asosan o'zbek tilida javob ber. Foydalanuvchi boshqa tilda yozsa, o'sha tilda javob ber.
- Texnik/kod savollarida: ishlaydigan kodni ber, ortiqcha izohsiz. Zarur bo'lgandagina qisqa tushuntirish qo'sh.
- Kodda xato bo'lsa: xatoni qisqa ayt, tuzatilgan kodni ber.
- Foydalanuvchi aniq "batafsil tushuntir" yoki "to'liq yoz" desagina uzunroq javob ber.
- Suhbat tarixini hisobga ol.
- Rasm yuborilsa, qisqa va aniq tahlil ber — batafsil emas.
- Hurmat bilan murojaat qil. O'zingni Shohrux deb ko'rsatma — sen Aizo.
"""


# =========================================================
# USER CHAT HISTORY
# =========================================================

user_chats = {}


# =========================================================
# USER LOCKLARI
# =========================================================

chat_locks = {}
global_lock = threading.Lock()


def get_user_lock(user_id):
    with global_lock:
        if user_id not in chat_locks:
            chat_locks[user_id] = threading.Lock()
        return chat_locks[user_id]


# =========================================================
# YANGI CHAT
# =========================================================

def create_chat():
    return [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]


# =========================================================
# HISTORY LIMIT
# =========================================================

def limit_history(messages):
    if len(messages) <= MAX_HISTORY_MESSAGES + 1:
        return messages

    system_message = messages[0]
    recent_messages = messages[-MAX_HISTORY_MESSAGES:]
    return [system_message, *recent_messages]


# =========================================================
# TELEGRAM XABARINI BO'LISH
# =========================================================

def split_message(text, max_length=MAX_TELEGRAM_LENGTH):
    if not text:
        return ["AI javob qaytarmadi."]

    if len(text) <= max_length:
        return [text]

    chunks = []
    while len(text) > max_length:
        cut = text.rfind("\n", 0, max_length)
        if cut < 1000:
            cut = text.rfind(" ", 0, max_length)
        if cut < 1000:
            cut = max_length

        chunk = text[:cut].strip()
        if chunk:
            chunks.append(chunk)
        text = text[cut:].strip()

    if text:
        chunks.append(text)

    return chunks


# =========================================================
# UZUN JAVOBNI YUBORISH
# =========================================================

def send_long_message(chat_id, text, reply_to_message_id=None, is_group=False):
    chunks = split_message(text)

    for chunk in chunks:
        if is_group:
            bot.send_message(
                chat_id,
                chunk,
                reply_to_message_id=reply_to_message_id
            )
        else:
            bot.send_message(chat_id, chunk)


# =========================================================
# RASMNI BASE64 GA O'TKAZISH
# =========================================================

def get_photo_base64(message: Message):
    """
    Telegramdagi eng katta o'lchamdagi rasmni yuklab,
    base64 string qaytaradi. Hajm juda katta bo'lsa "TOO_LARGE" qaytaradi.
    """
    try:
        photo = message.photo[-1]

        if photo.file_size and photo.file_size > MAX_PHOTO_SIZE:
            logger.warning("Rasm juda katta: %s bayt", photo.file_size)
            return "TOO_LARGE"

        file_info = bot.get_file(photo.file_id)
        downloaded = bot.download_file(file_info.file_path)

        if len(downloaded) > MAX_PHOTO_SIZE:
            return "TOO_LARGE"

        b64 = base64.b64encode(downloaded).decode("utf-8")
        return b64
    except Exception as e:
        logger.exception("Rasm yuklashda xato: %s", e)
        return None


# =========================================================
# ADMIN TEKSHIRISH
# =========================================================

def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID


# =========================================================
# ADMIN PANEL — TUGMALAR
# =========================================================

def admin_main_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 Statistika", callback_data="admin_stats"),
        types.InlineKeyboardButton("📢 Xabar yuborish", callback_data="admin_broadcast"),
    )
    markup.add(
        types.InlineKeyboardButton("🚫 Bloklash", callback_data="admin_block"),
        types.InlineKeyboardButton("✅ Blokdan chiqarish", callback_data="admin_unblock"),
    )

    maintenance_on = is_maintenance_mode()
    maintenance_label = "🔴 Texnik ishlarni o'chirish" if maintenance_on else "🟢 Texnik ishlarni yoqish"
    markup.add(
        types.InlineKeyboardButton(maintenance_label, callback_data="admin_maintenance_toggle")
    )
    markup.add(
        types.InlineKeyboardButton("⬅️ Yopish", callback_data="admin_close")
    )
    return markup


def admin_back_button():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_back"))
    return markup


def admin_panel_text():
    stats = get_stats()
    maintenance_status = "🔴 Yoqilgan" if is_maintenance_mode() else "🟢 O'chirilgan"
    return (
        "🛠 <b>Aizo — Admin panel</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{stats['total_users']}</b>\n"
        f"💬 Xabarlar: <b>{stats['total_messages']}</b>\n"
        f"🚫 Bloklangan: <b>{stats['blocked_users']}</b>\n"
        f"🔧 Texnik ishlar: {maintenance_status}"
    )


# Admin kutayotgan input turi (broadcast matni, block ID va h.k.)
admin_pending_action = {}


# =========================================================
# /ADMIN
# =========================================================

@bot.message_handler(commands=["admin"])
def admin_panel(message):
    user_id = message.chat.id

    if not is_admin(user_id):
        return  # oddiy foydalanuvchiga hech narsa bildirmaymiz

    bot.send_message(
        user_id,
        admin_panel_text(),
        reply_markup=admin_main_menu(),
        parse_mode="HTML"
    )


# =========================================================
# ADMIN CALLBACK QAYTA ISHLASH
# =========================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_callback(call):
    user_id = call.message.chat.id

    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "Ruxsat yo'q.")
        return

    action = call.data

    if action == "admin_stats":
        bot.edit_message_text(
            admin_panel_text(),
            chat_id=user_id,
            message_id=call.message.message_id,
            reply_markup=admin_back_button(),
            parse_mode="HTML"
        )

    elif action == "admin_broadcast":
        admin_pending_action[user_id] = "broadcast"
        bot.edit_message_text(
            "📢 Barcha foydalanuvchilarga yuboriladigan xabar matnini yozing:",
            chat_id=user_id,
            message_id=call.message.message_id,
            reply_markup=admin_back_button()
        )

    elif action == "admin_block":
        admin_pending_action[user_id] = "block"
        bot.edit_message_text(
            "🚫 Bloklamoqchi bo'lgan foydalanuvchining Telegram ID raqamini yuboring:",
            chat_id=user_id,
            message_id=call.message.message_id,
            reply_markup=admin_back_button()
        )

    elif action == "admin_unblock":
        admin_pending_action[user_id] = "unblock"
        bot.edit_message_text(
            "✅ Blokdan chiqarmoqchi bo'lgan foydalanuvchining Telegram ID raqamini yuboring:",
            chat_id=user_id,
            message_id=call.message.message_id,
            reply_markup=admin_back_button()
        )

    elif action == "admin_maintenance_toggle":
        current = is_maintenance_mode()
        set_setting("maintenance", "0" if current else "1")
        new_status = "🔴 Yoqilgan" if not current else "🟢 O'chirilgan"
        bot.answer_callback_query(call.id, f"Texnik ishlar rejimi: {new_status}")

        bot.edit_message_text(
            admin_panel_text(),
            chat_id=user_id,
            message_id=call.message.message_id,
            reply_markup=admin_main_menu(),
            parse_mode="HTML"
        )

    elif action == "admin_back":
        admin_pending_action.pop(user_id, None)
        bot.edit_message_text(
            admin_panel_text(),
            chat_id=user_id,
            message_id=call.message.message_id,
            reply_markup=admin_main_menu(),
            parse_mode="HTML"
        )

    elif action == "admin_close":
        admin_pending_action.pop(user_id, None)
        bot.delete_message(user_id, call.message.message_id)

    bot.answer_callback_query(call.id)


# =========================================================
# ADMIN INPUT QAYTA ISHLASH (broadcast / block / unblock)
# =========================================================

def handle_admin_input(message: Message) -> bool:
    """
    Admin pending action kutayotgan bo'lsa, xabarni shu yerda ishlaydi.
    True qaytarsa — xabar admin uchun ishlangan, oddiy AI ga yubormaslik kerak.
    """
    user_id = message.chat.id

    if not is_admin(user_id):
        return False

    pending = admin_pending_action.get(user_id)
    if not pending:
        return False

    text = message.text.strip() if message.text else ""

    if pending == "broadcast":
        admin_pending_action.pop(user_id, None)

        if not text:
            bot.send_message(user_id, "Bo'sh xabar yuborib bo'lmaydi.")
            return True

        user_ids = get_all_user_ids()
        sent = 0
        failed = 0

        bot.send_message(user_id, f"📤 Yuborilmoqda... ({len(user_ids)} foydalanuvchiga)")

        for uid in user_ids:
            try:
                bot.send_message(uid, text)
                sent += 1
            except Exception:
                failed += 1
            time.sleep(0.05)  # Telegram rate limitidan qochish uchun

        bot.send_message(
            user_id,
            f"✅ Xabar yuborildi.\n\nMuvaffaqiyatli: {sent}\nXato: {failed}"
        )
        return True

    if pending == "block":
        admin_pending_action.pop(user_id, None)

        if not text.isdigit():
            bot.send_message(user_id, "Noto'g'ri ID. Faqat raqam yuboring.")
            return True

        target_id = int(text)
        set_user_blocked(target_id, True)
        bot.send_message(user_id, f"🚫 Foydalanuvchi {target_id} bloklandi.")
        return True

    if pending == "unblock":
        admin_pending_action.pop(user_id, None)

        if not text.isdigit():
            bot.send_message(user_id, "Noto'g'ri ID. Faqat raqam yuboring.")
            return True

        target_id = int(text)
        set_user_blocked(target_id, False)
        bot.send_message(user_id, f"✅ Foydalanuvchi {target_id} blokdan chiqarildi.")
        return True

    return False


# =========================================================
# /START
# =========================================================

@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.chat.id

    try:
        user_chats[user_id] = create_chat()
        touch_user(user_id)

        bot.send_message(
            user_id,
            "Salom!\n\n"
            "Men Aizo — Shohruxning AI yordamchisiman.\n\n"
            "Savolingizni yozing yoki rasm yuboring, yordam beraman."
        )

        logger.info("START | user=%s", user_id)

    except Exception:
        logger.exception("START ERROR | user=%s", user_id)
        bot.send_message(user_id, "Botni ishga tushirishda xatolik yuz berdi.")


# =========================================================
# /CLEAR
# =========================================================

@bot.message_handler(commands=["clear"])
def clear(message):
    user_id = message.chat.id

    try:
        user_chats[user_id] = create_chat()
        bot.send_message(user_id, "Suhbat xotirasi tozalandi.")
        logger.info("CLEAR | user=%s", user_id)

    except Exception:
        logger.exception("CLEAR ERROR | user=%s", user_id)
        bot.send_message(user_id, "Suhbatni tozalashda xatolik yuz berdi.")


# =========================================================
# /HELP
# =========================================================

@bot.message_handler(commands=["help"])
def help_command(message):
    bot.send_message(
        message.chat.id,
        "Aizo yordam\n\n"
        "/start — yangi suhbatni boshlash\n"
        "/clear — suhbat xotirasini tozalash\n"
        "/help — yordam\n\n"
        "Matn yozishingiz yoki rasm yuborishingiz mumkin."
    )


# =========================================================
# TEXT XABARLAR
# =========================================================

@bot.message_handler(
    content_types=["text"],
    func=lambda message: message.text and not message.text.startswith("/")
)
def reply(message):
    # Avval admin panel input kutilyaptimi tekshiramiz
    if handle_admin_input(message):
        return

    process_message(message, is_photo=False)


# =========================================================
# PHOTO (RASM) XABARLAR
# =========================================================

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    process_message(message, is_photo=True)


# =========================================================
# ASOSIY XABAR ISHLOV BERISH FUNKSIYASI
# =========================================================

def process_message(message: Message, is_photo: bool = False):
    user_id = message.chat.id
    is_group = message.chat.type in ["group", "supergroup"]

    # ---------------------------------------------
    # MAINTENANCE REJIMI TEKSHIRISH
    # ---------------------------------------------
    if is_maintenance_mode() and not is_admin(user_id):
        bot.send_message(
            user_id,
            "🔧 Hozirda botimizda texnik ishlar olib borilmoqda.\n"
            "Iltimos, birozdan so'ng qayta urinib ko'ring."
        )
        return

    # ---------------------------------------------
    # BLOKLANGANLIKNI TEKSHIRISH
    # ---------------------------------------------
    if is_user_blocked(user_id):
        return  # bloklangan foydalanuvchiga hech qanday javob yo'q

    touch_user(user_id)

    if user_id not in user_chats:
        user_chats[user_id] = create_chat()

    lock = get_user_lock(user_id)

    with lock:
        try:
            bot.send_chat_action(user_id, "typing")

            # ---------------------------------------------
            # USER XABARINI TAYYORLASH
            # ---------------------------------------------
            if is_photo:
                b64_image = get_photo_base64(message)

                if b64_image == "TOO_LARGE":
                    bot.send_message(
                        user_id,
                        "Bu rasm juda katta. Iltimos, kichikroq rasm yuboring (10 MB dan kam).",
                        reply_to_message_id=message.message_id if is_group else None
                    )
                    return

                if not b64_image:
                    bot.send_message(
                        user_id,
                        "Rasmni yuklab olishda xatolik yuz berdi.",
                        reply_to_message_id=message.message_id if is_group else None
                    )
                    return

                caption = message.caption.strip() if message.caption else "Bu rasmni tahlil qil."

                user_content = [
                    {
                        "type": "text",
                        "text": caption
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64_image}"
                        }
                    }
                ]

                user_chats[user_id].append({
                    "role": "user",
                    "content": user_content
                })

            else:
                user_text = message.text.strip()
                if not user_text:
                    return

                user_chats[user_id].append({
                    "role": "user",
                    "content": user_text
                })

            # ---------------------------------------------
            # HISTORY LIMIT
            # ---------------------------------------------
            user_chats[user_id] = limit_history(user_chats[user_id])

            # ---------------------------------------------
            # DEEPSEEK REQUEST (RETRY BILAN)
            # ---------------------------------------------
            answer = None
            last_error = None

            for attempt in range(MAX_RETRIES + 1):
                try:
                    response = client.chat.completions.create(
                        model=MODEL_NAME,
                        messages=user_chats[user_id],
                        stream=False,
                        max_tokens=MAX_TOKENS
                    )

                    if not response.choices:
                        raise RuntimeError("DeepSeek bo'sh choices qaytardi.")

                    answer = response.choices[0].message.content

                    if not answer:
                        raise RuntimeError("DeepSeek bo'sh javob qaytardi.")

                    break  # muvaffaqiyatli, retry kerak emas

                except Exception as e:
                    last_error = e
                    error_text = str(e).lower()

                    # Auth xatolarida retry qilish shart emas
                    if any(x in error_text for x in ["401", "authentication", "unauthorized", "invalid_api_key"]):
                        raise

                    if attempt < MAX_RETRIES:
                        logger.warning(
                            "Retry %s/%s | user=%s | xato=%s",
                            attempt + 1, MAX_RETRIES, user_id, e
                        )
                        time.sleep(RETRY_DELAY_SECONDS)
                    else:
                        raise

            if answer is None:
                raise last_error or RuntimeError("Noma'lum xatolik.")

            # ---------------------------------------------
            # ASSISTANT JAVOBINI HISTORY'GA QO'SHISH
            # ---------------------------------------------
            user_chats[user_id].append({
                "role": "assistant",
                "content": answer
            })

            # ---------------------------------------------
            # JAVOBNI YUBORISH
            # ---------------------------------------------
            send_long_message(
                chat_id=user_id,
                text=answer,
                reply_to_message_id=message.message_id,
                is_group=is_group
            )

            logger.info(
                "MESSAGE OK | user=%s | chat_type=%s | is_photo=%s",
                user_id,
                message.chat.type,
                is_photo
            )

        except Exception as e:
            logger.exception("DEEPSEEK ERROR | user=%s", user_id)

            # Xato bo'lganida oxirgi user xabarini olib tashlash
            if (
                user_chats.get(user_id)
                and user_chats[user_id][-1].get("role") == "user"
            ):
                user_chats[user_id].pop()

            error_text = str(e).lower()

            # Foydalanuvchiga har doim sodda va bir xil xabar ko'rsatamiz
            user_message = (
                "🔧 Hozirda botimizda texnik ishlar olib borilmoqda.\n"
                "Iltimos, birozdan so'ng qayta urinib ko'ring."
            )

            # Admin bo'lsa, texnik tafsilotni ham qo'shib beramiz
            if is_admin(user_id):
                if any(x in error_text for x in ["401", "api key", "authentication", "unauthorized", "invalid_api_key"]):
                    user_message += "\n\n(Admin: DEEPSEEK_API_KEY noto'g'ri yoki eskirgan.)"
                elif "model" in error_text and any(x in error_text for x in ["not found", "does not exist", "invalid"]):
                    user_message += "\n\n(Admin: MODEL_NAME sozlamasini tekshiring.)"
                elif any(x in error_text for x in ["429", "rate limit", "quota"]):
                    user_message += "\n\n(Admin: API limitiga yetildi.)"

            if is_group:
                bot.send_message(
                    user_id,
                    user_message,
                    reply_to_message_id=message.message_id
                )
            else:
                bot.send_message(user_id, user_message)


# =========================================================
# BOSHQA MEDIA (video, audio va h.k.)
# =========================================================

@bot.message_handler(
    content_types=[
        "video", "audio", "document", "sticker",
        "voice", "animation", "contact", "location"
    ]
)
def unsupported_message(message):
    is_group = message.chat.type in ["group", "supergroup"]

    text = "Hozircha men faqat matn va rasm bilan ishlayman."

    if is_group:
        bot.send_message(
            message.chat.id,
            text,
            reply_to_message_id=message.message_id
        )
    else:
        bot.send_message(message.chat.id, text)


# =========================================================
# BOTNI ISHGA TUSHIRISH
# =========================================================

if __name__ == "__main__":
    logger.info("Aizo — Shohruxning AI yordamchisi ishga tushmoqda...")

    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=30)
    except KeyboardInterrupt:
        logger.info("Aizo to'xtatildi.")
    except Exception:
        logger.exception("BOT CRITICAL ERROR")
