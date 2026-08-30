import os
import logging
import threading
import base64
import time
import json
from datetime import datetime

import telebot
from openai import OpenAI
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton


# =========================================================
# SOZLAMALAR
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # Railway Variables'ga qo'shing

MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-v4-flash-vision-exp")

MAX_TELEGRAM_LENGTH = 4000
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "40"))

# Bot on/off holati
bot_enabled = True

# Banned userlar
banned_users = set()

# Statistika
stats = {
    "total_messages": 0,
    "total_photos": 0,
    "total_users": set(),
    "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "errors": 0,
}

# Broadcast uchun lock
broadcast_lock = threading.Lock()


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
if ADMIN_ID == 0:
    logger.warning("ADMIN_ID o'rnatilmagan! Admin panel ishlamaydi.")


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

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
Sening isming Aizo. Sen Shohruxning shaxsiy AI yordamchisisan.

Kim ekaningni so'rashsa: "Men Aizo — Shohruxning AI yordamchisiman."

QOIDALAR:
- Javoblaring QISQA va aniq bo'lsin. Odatda 2-5 gap yetarli.
- Kerak bo'lmasa uzun tushuntirish, ortiqcha kirish so'zlari yozma.
- To'g'ridan-to'g'ri javobdan boshla, "albatta", "juda ajoyib savol" kabi keraksiz kirish qilma.
- Asosan o'zbek tilida javob ber. Foydalanuvchi boshqa tilda yozsa, o'sha tilda javob ber.
- Texnik/kod savollarida: ishlaydigan kodni ber, ortiqcha izohsiz.
- Kodda xato bo'lsa: xatoni qisqa ayt, tuzatilgan kodni ber.
- Foydalanuvchi "batafsil tushuntir" yoki "to'liq yoz" desagina uzunroq javob ber.
- Suhbat tarixini hisobga ol.
- Rasm yuborilsa, qisqa va aniq tahlil ber.
- Hurmat bilan murojaat qil. O'zingni Shohrux deb ko'rsatma — sen Aizo.
"""


# =========================================================
# USER CHAT HISTORY
# =========================================================

user_chats = {}
chat_locks = {}
global_lock = threading.Lock()


def get_user_lock(user_id):
    with global_lock:
        if user_id not in chat_locks:
            chat_locks[user_id] = threading.Lock()
        return chat_locks[user_id]


def create_chat():
    return [{"role": "system", "content": SYSTEM_PROMPT}]


def limit_history(messages):
    if len(messages) <= MAX_HISTORY_MESSAGES + 1:
        return messages
    system_message = messages[0]
    recent_messages = messages[-MAX_HISTORY_MESSAGES:]
    return [system_message, *recent_messages]


# =========================================================
# YORDAMCHI FUNKSIYALAR
# =========================================================

def is_admin(user_id):
    return ADMIN_ID != 0 and user_id == ADMIN_ID


def is_banned(user_id):
    return user_id in banned_users


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


def send_long_message(chat_id, text, reply_to_message_id=None, is_group=False):
    chunks = split_message(text)
    for i, chunk in enumerate(chunks):
        rid = reply_to_message_id if (i == 0 and is_group) else None
        try:
            bot.send_message(chat_id, chunk, reply_to_message_id=rid)
        except Exception as e:
            logger.error("send_long_message xato: %s", e)


def get_photo_base64(message: Message):
    try:
        photo = message.photo[-1]
        file_info = bot.get_file(photo.file_id)
        downloaded = bot.download_file(file_info.file_path)
        return base64.b64encode(downloaded).decode("utf-8")
    except Exception as e:
        logger.exception("Rasm yuklashda xato: %s", e)
        return None


def get_uptime():
    start = datetime.strptime(stats["start_time"], "%Y-%m-%d %H:%M:%S")
    diff = datetime.now() - start
    hours, rem = divmod(int(diff.total_seconds()), 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours}s {minutes}d {seconds}s"


# =========================================================
# ADMIN PANEL — KLAVIATURALAR
# =========================================================

def admin_main_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    status = "🟢 Yoqish" if not bot_enabled else "🔴 O'chirish"
    kb.add(
        InlineKeyboardButton("🟢 Bot YOQIQ" if bot_enabled else "🔴 Bot OCHIQ", callback_data="admin_status"),
        InlineKeyboardButton(f"{status}", callback_data="admin_toggle"),
    )
    kb.add(
        InlineKeyboardButton("📊 Statistika", callback_data="admin_stats"),
        InlineKeyboardButton("👥 Foydalanuvchilar", callback_data="admin_users"),
    )
    kb.add(
        InlineKeyboardButton("🚫 Ban ro'yxati", callback_data="admin_banlist"),
        InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
    )
    kb.add(
        InlineKeyboardButton("🗑️ Barcha tarixni tozalash", callback_data="admin_clearall"),
        InlineKeyboardButton("⚙️ Sozlamalar", callback_data="admin_settings"),
    )
    kb.add(
        InlineKeyboardButton("❌ Yopish", callback_data="admin_close"),
    )
    return kb


def back_keyboard():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_main"))
    return kb


def ban_keyboard(user_id):
    kb = InlineKeyboardMarkup(row_width=2)
    if user_id in banned_users:
        kb.add(InlineKeyboardButton(f"✅ Ban'dan chiqarish", callback_data=f"admin_unban_{user_id}"))
    else:
        kb.add(InlineKeyboardButton(f"🚫 Ban qilish", callback_data=f"admin_ban_{user_id}"))
    kb.add(
        InlineKeyboardButton("🗑️ Tarixini tozalash", callback_data=f"admin_clearuser_{user_id}"),
        InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_users"),
    )
    return kb


# =========================================================
# /START
# =========================================================

@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.chat.id
    if is_banned(user_id):
        bot.send_message(user_id, "Siz bloklangansiz.")
        return
    try:
        user_chats[user_id] = create_chat()
        stats["total_users"].add(user_id)
        bot.send_message(
            user_id,
            "Salom!\n\nMen Aizo — Shohruxning AI yordamchisiman.\n\nSavolingizni yozing yoki rasm yuboring."
        )
        logger.info("START | user=%s", user_id)
    except Exception:
        logger.exception("START ERROR | user=%s", user_id)


# =========================================================
# /CLEAR
# =========================================================

@bot.message_handler(commands=["clear"])
def clear(message):
    user_id = message.chat.id
    if is_banned(user_id):
        return
    try:
        user_chats[user_id] = create_chat()
        bot.send_message(user_id, "Suhbat xotirasi tozalandi.")
    except Exception:
        logger.exception("CLEAR ERROR | user=%s", user_id)


# =========================================================
# /HELP
# =========================================================

@bot.message_handler(commands=["help"])
def help_command(message):
    if is_banned(message.chat.id):
        return
    bot.send_message(
        message.chat.id,
        "Aizo yordam\n\n"
        "/start — yangi suhbatni boshlash\n"
        "/clear — suhbat xotirasini tozalash\n"
        "/help — yordam\n\n"
        "Matn yozishingiz yoki rasm yuborishingiz mumkin."
    )


# =========================================================
# /ADMIN
# =========================================================

@bot.message_handler(commands=["admin"])
def admin_panel(message):
    user_id = message.chat.id
    if not is_admin(user_id):
        bot.send_message(user_id, "Sizda ruxsat yo'q.")
        return
    bot.send_message(
        user_id,
        "👨‍💼 Admin Panel\n\nXush kelibsiz, admin!",
        reply_markup=admin_main_keyboard()
    )


# =========================================================
# ADMIN — CALLBACK HANDLER
# =========================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_callback(call):
    global bot_enabled
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "Ruxsat yo'q!")
        return

    data = call.data

    # ---------- Bosh menyu ----------
    if data == "admin_main":
        bot.edit_message_text(
            "👨‍💼 Admin Panel",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=admin_main_keyboard()
        )

    # ---------- Holat ----------
    elif data == "admin_status":
        status = "YOQIQ 🟢" if bot_enabled else "O'CHIQ 🔴"
        bot.answer_callback_query(call.id, f"Bot hozir: {status}")

    # ---------- Yoq/O'chir ----------
    elif data == "admin_toggle":
        bot_enabled = not bot_enabled
        status = "yoqildi 🟢" if bot_enabled else "o'chirildi 🔴"
        bot.answer_callback_query(call.id, f"Bot {status}!")
        bot.edit_message_text(
            f"👨‍💼 Admin Panel\n\nBot {status}!",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=admin_main_keyboard()
        )

    # ---------- Statistika ----------
    elif data == "admin_stats":
        text = (
            f"📊 Statistika\n\n"
            f"👥 Jami foydalanuvchilar: {len(stats['total_users'])}\n"
            f"💬 Jami xabarlar: {stats['total_messages']}\n"
            f"🖼 Jami rasmlar: {stats['total_photos']}\n"
            f"❌ Xatolar: {stats['errors']}\n"
            f"🚫 Bannedlar: {len(banned_users)}\n"
            f"🕐 Uptime: {get_uptime()}\n"
            f"📅 Ishga tushgan: {stats['start_time']}\n"
            f"🤖 Model: {MODEL_NAME}\n"
            f"🔢 Max tokens: {MAX_TOKENS}\n"
            f"📝 Max history: {MAX_HISTORY_MESSAGES}\n"
            f"⚡ Bot holati: {'YOQIQ 🟢' if bot_enabled else 'OCHIQ 🔴'}"
        )
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=back_keyboard()
        )

    # ---------- Foydalanuvchilar ----------
    elif data == "admin_users":
        users = list(stats["total_users"])
        if not users:
            text = "Hali hech kim botdan foydalanmagan."
        else:
            text = f"👥 Foydalanuvchilar ({len(users)} ta)\n\n"
            kb = InlineKeyboardMarkup(row_width=2)
            buttons = []
            for uid in users[-20:]:  # oxirgi 20 ta
                banned_mark = "🚫" if uid in banned_users else "✅"
                buttons.append(
                    InlineKeyboardButton(f"{banned_mark} {uid}", callback_data=f"admin_userinfo_{uid}")
                )
            kb.add(*buttons)
            kb.add(InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_main"))
            bot.edit_message_text(
                text + "Foydalanuvchini tanlang:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=kb
            )
            return

        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=back_keyboard()
        )

    # ---------- User info ----------
    elif data.startswith("admin_userinfo_"):
        uid = int(data.split("_")[-1])
        history_len = len(user_chats.get(uid, [])) - 1
        banned = "🚫 Banned" if uid in banned_users else "✅ Faol"
        text = (
            f"👤 Foydalanuvchi: {uid}\n"
            f"📊 Holat: {banned}\n"
            f"💬 Tarix uzunligi: {history_len} xabar\n"
        )
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=ban_keyboard(uid)
        )

    # ---------- Ban ----------
    elif data.startswith("admin_ban_"):
        uid = int(data.split("_")[-1])
        banned_users.add(uid)
        bot.answer_callback_query(call.id, f"{uid} ban qilindi!")
        # user'ga xabar
        try:
            bot.send_message(uid, "Siz admin tomonidan bloklangansiz.")
        except Exception:
            pass
        bot.edit_message_text(
            f"🚫 {uid} ban qilindi.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=ban_keyboard(uid)
        )

    # ---------- Unban ----------
    elif data.startswith("admin_unban_"):
        uid = int(data.split("_")[-1])
        banned_users.discard(uid)
        bot.answer_callback_query(call.id, f"{uid} ban'dan chiqarildi!")
        try:
            bot.send_message(uid, "Sizning blokirovkangiz olib tashlandi.")
        except Exception:
            pass
        bot.edit_message_text(
            f"✅ {uid} ban'dan chiqarildi.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=ban_keyboard(uid)
        )

    # ---------- User tarixini tozalash ----------
    elif data.startswith("admin_clearuser_"):
        uid = int(data.split("_")[-1])
        user_chats[uid] = create_chat()
        bot.answer_callback_query(call.id, f"{uid} tarixi tozalandi!")
        bot.edit_message_text(
            f"🗑️ {uid} suhbat tarixi tozalandi.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=back_keyboard()
        )

    # ---------- Barcha tarixni tozalash ----------
    elif data == "admin_clearall":
        count = len(user_chats)
        user_chats.clear()
        bot.answer_callback_query(call.id, f"{count} ta tarix tozalandi!")
        bot.edit_message_text(
            f"🗑️ Barcha {count} ta foydalanuvchi tarixi tozalandi.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=back_keyboard()
        )

    # ---------- Ban ro'yxati ----------
    elif data == "admin_banlist":
        if not banned_users:
            text = "🚫 Banned foydalanuvchilar yo'q."
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=back_keyboard()
            )
        else:
            kb = InlineKeyboardMarkup(row_width=2)
            buttons = [
                InlineKeyboardButton(f"🚫 {uid}", callback_data=f"admin_userinfo_{uid}")
                for uid in list(banned_users)
            ]
            kb.add(*buttons)
            kb.add(InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_main"))
            bot.edit_message_text(
                f"🚫 Banned foydalanuvchilar ({len(banned_users)} ta):",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=kb
            )

    # ---------- Broadcast ----------
    elif data == "admin_broadcast":
        bot.edit_message_text(
            "📢 Broadcast xabar\n\nBarcha foydalanuvchilarga xabar yuborish uchun:\n\n/broadcast <xabar matni>",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=back_keyboard()
        )

    # ---------- Sozlamalar ----------
    elif data == "admin_settings":
        text = (
            f"⚙️ Joriy sozlamalar\n\n"
            f"🤖 Model: {MODEL_NAME}\n"
            f"🔢 Max tokens: {MAX_TOKENS}\n"
            f"📝 Max history: {MAX_HISTORY_MESSAGES}\n"
            f"📏 Max message: {MAX_TELEGRAM_LENGTH}\n\n"
            f"Sozlamalarni o'zgartirish uchun Railway Variables'ni tahrirlang."
        )
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=back_keyboard()
        )

    # ---------- Yopish ----------
    elif data == "admin_close":
        bot.delete_message(call.message.chat.id, call.message.message_id)

    bot.answer_callback_query(call.id)


# =========================================================
# /BROADCAST — Adminga yuborish
# =========================================================

@bot.message_handler(commands=["broadcast"])
def broadcast(message):
    user_id = message.chat.id
    if not is_admin(user_id):
        bot.send_message(user_id, "Ruxsat yo'q.")
        return

    text = message.text.replace("/broadcast", "").strip()
    if not text:
        bot.send_message(user_id, "Xabar matni kiritilmagan.\n\nMisol: /broadcast Salom hammaga!")
        return

    users = list(stats["total_users"])
    sent = 0
    failed = 0

    bot.send_message(user_id, f"📢 {len(users)} ta foydalanuvchiga yuborilmoqda...")

    with broadcast_lock:
        for uid in users:
            if uid == ADMIN_ID:
                continue
            try:
                bot.send_message(uid, f"📢 Aizo xabari:\n\n{text}")
                sent += 1
                time.sleep(0.05)  # Flood limitdan himoya
            except Exception as e:
                logger.error("Broadcast xato uid=%s: %s", uid, e)
                failed += 1

    bot.send_message(
        user_id,
        f"✅ Broadcast tugadi!\n\nYuborildi: {sent}\nXato: {failed}"
    )


# =========================================================
# /BAN va /UNBAN — Tezkor buyruqlar
# =========================================================

@bot.message_handler(commands=["ban"])
def ban_user(message):
    if not is_admin(message.chat.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Misol: /ban 123456789")
        return
    try:
        uid = int(parts[1])
        banned_users.add(uid)
        try:
            bot.send_message(uid, "Siz admin tomonidan bloklangansiz.")
        except Exception:
            pass
        bot.send_message(message.chat.id, f"🚫 {uid} ban qilindi.")
    except ValueError:
        bot.send_message(message.chat.id, "Noto'g'ri ID.")


@bot.message_handler(commands=["unban"])
def unban_user(message):
    if not is_admin(message.chat.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Misol: /unban 123456789")
        return
    try:
        uid = int(parts[1])
        banned_users.discard(uid)
        try:
            bot.send_message(uid, "Blokirovkangiz olib tashlandi.")
        except Exception:
            pass
        bot.send_message(message.chat.id, f"✅ {uid} unban qilindi.")
    except ValueError:
        bot.send_message(message.chat.id, "Noto'g'ri ID.")