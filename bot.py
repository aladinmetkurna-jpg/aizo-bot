import os
import sys
import logging
import threading
import time
from datetime import datetime

import telebot
from telebot import types
from openai import OpenAI


# =========================================================
# SOZLAMALAR
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

MODEL_NAME = "deepseek-v4-flash"
MAX_TELEGRAM_LENGTH = 4096
MAX_HISTORY_MESSAGES = 40


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("Aizo")


# =========================================================
# ENVIRONMENT
# =========================================================

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN topilmadi!")
if not DEEPSEEK_API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY topilmadi!")
if ADMIN_ID == 0:
    logger.warning("ADMIN_ID o'rnatilmagan!")


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

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="HTML")


# =========================================================
# GLOBAL HOLAT
# =========================================================

bot_running = True
restart_requested = False
maintenance_mode = False
bot_lock = threading.Lock()

admin_states = {}
banned_users = set()
user_notes = {}
user_stats = {}

current_personality = "default"

PERSONALITIES = {
    "default": {
        "name": "Oddiy",
        "prompt": """
Sening isming Aizo.
Sen Shohruxning shaxsiy AI yordamchisisan.
Agar foydalanuvchi "Sen kimsan?", "Kimsan?", "Isming nima?" deb so'rasa:
"Men Aizo — Shohruxning AI yordamchisiman." deb javob ber.
Asosan o'zbek tilida javob ber.
Javoblaring tabiiy, tushunarli va foydali bo'lsin.
Kod so'ralsa to'liq va ishlaydigan kod ber.
O'zingni Shohrux deb ko'rsatma.
"""
    },
    "coder": {
        "name": "Dasturchi",
        "prompt": """
Sening isming Aizo (Dasturchi rejimi).
Sen Shohruxning shaxsiy AI yordamchisisan, asosan dasturlash bo'yicha yordam berasan.
Kodlarni to'liq, ishlaydigan va izohli qilib yoz.
Xatolarni aniq tushuntir.
Asosan o'zbek tilida javob ber, lekin kod va texnik atamalarni o'z holicha qoldir.
"""
    },
    "short": {
        "name": "Qisqa javob",
        "prompt": """
Sening isming Aizo.
Sen Shohruxning shaxsiy AI yordamchisisan.
Javoblarni juda qisqa va aniq ber.
Keraksiz gaplarni aytma.
Asosan o'zbek tilida javob ber.
"""
    }
}


# =========================================================
# USER DATA
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
    prompt = PERSONALITIES[current_personality]["prompt"]
    return [{"role": "system", "content": prompt}]


def limit_history(messages):
    if len(messages) <= MAX_HISTORY_MESSAGES + 1:
        return messages
    return [messages[0], *messages[-MAX_HISTORY_MESSAGES:]]


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


def send_long_message(chat_id, text):
    for chunk in split_message(text):
        bot.send_message(chat_id, chunk)


def update_user_stats(user_id):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if user_id not in user_stats:
        user_stats[user_id] = {
            "messages": 0,
            "first_seen": now,
            "last_seen": now
        }
    user_stats[user_id]["messages"] += 1
    user_stats[user_id]["last_seen"] = now


def notify_admin(text):
    if ADMIN_ID:
        try:
            bot.send_message(ADMIN_ID, f"⚠️ <b>Bot xabari</b>\n\n{text}")
        except Exception:
            pass


def is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID


def is_banned(user_id: int) -> bool:
    return user_id in banned_users


def clear_admin_state(admin_id):
    admin_states.pop(admin_id, None)


# =========================================================
# ADMIN KLAVIATURA
# =========================================================

def get_admin_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)

    kb.add(
        types.InlineKeyboardButton("🟢 Holat", callback_data="adm_status"),
        types.InlineKeyboardButton("📊 Statistika", callback_data="adm_stats"),
    )
    kb.add(
        types.InlineKeyboardButton("📢 Barchaga xabar", callback_data="adm_broadcast"),
        types.InlineKeyboardButton("👤 Bitta userga", callback_data="adm_send_one"),
    )
    kb.add(
        types.InlineKeyboardButton("🚫 Ban", callback_data="adm_ban"),
        types.InlineKeyboardButton("✅ Unban", callback_data="adm_unban"),
    )
    kb.add(
        types.InlineKeyboardButton("📋 Ban ro'yxati", callback_data="adm_banlist"),
        types.InlineKeyboardButton("🔍 Qidiruv", callback_data="adm_search"),
    )
    kb.add(
        types.InlineKeyboardButton("📝 Izoh qo'shish", callback_data="adm_note"),
        types.InlineKeyboardButton("📄 Chat eksport", callback_data="adm_export"),
    )
    kb.add(
        types.InlineKeyboardButton("🛠 Maintenance", callback_data="adm_maintenance"),
        types.InlineKeyboardButton("🎭 Rejim", callback_data="adm_personality"),
    )
    kb.add(
        types.InlineKeyboardButton("👥 So'nggi userlar", callback_data="adm_recent"),
        types.InlineKeyboardButton("🔄 Restart", callback_data="adm_restart"),
    )
    kb.add(
        types.InlineKeyboardButton("🛑 To'xtatish", callback_data="adm_stop"),
        types.InlineKeyboardButton("❌ Yopish", callback_data="adm_cancel"),
    )
    return kb


def get_cancel_keyboard():
    return types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("❌ Bekor qilish", callback_data="adm_cancel")
    )


def send_admin_panel(chat_id):
    status = "🟢 Ishlamoqda" if bot_running else "🔴 To'xtatilgan"
    maint = "🟠 YOQILGAN" if maintenance_mode else "🟢 O'chiq"
    text = (
        f"<b>🛠 Aizo Admin Panel</b>\n\n"
        f"Holat: {status}\n"
        f"Maintenance: {maint}\n"
        f"Rejim: <b>{PERSONALITIES[current_personality]['name']}</b>\n"
        f"Foydalanuvchilar: <b>{len(user_chats)}</b>\n"
        f"Ban: <b>{len(banned_users)}</b>"
    )
    bot.send_message(chat_id, text, reply_markup=get_admin_keyboard())


# =========================================================
# ADMIN PANEL
# =========================================================

@bot.message_handler(commands=["admin", "panel"])
def open_admin_panel(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Bu panel faqat admin uchun.")
        return
    clear_admin_state(message.from_user.id)
    send_admin_panel(message.chat.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_"))
def admin_callback(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ Ruxsat yo'q", show_alert=True)
        return

    data = call.data
    admin_id = call.from_user.id
    chat_id = call.message.chat.id

    if data == "adm_status":
        bot.answer_callback_query(call.id)
        send_admin_panel(chat_id)

    elif data == "adm_stats":
        bot.answer_callback_query(call.id)
        total_messages = sum(u.get("messages", 0) for u in user_stats.values())
        top_users = sorted(user_stats.items(), key=lambda x: x[1].get("messages", 0), reverse=True)[:5]
        top_text = ""
        for i, (uid, st) in enumerate(top_users, 1):
            top_text += f"{i}. <code>{uid}</code> — {st.get('messages', 0)} ta\n"

        bot.send_message(
            chat_id,
            f"<b>📊 Statistika</b>\n\n"
            f"• Foydalanuvchilar: <b>{len(user_chats)}</b>\n"
            f"• Jami xabarlar: <b>{total_messages}</b>\n"
            f"• Ban qilingan: <b>{len(banned_users)}</b>\n"
            f"• Rejim: <b>{PERSONALITIES[current_personality]['name']}</b>\n\n"
            f"<b>Top 5 faol:</b>\n{top_text or 'Hali yoʻq'}"
        )

    elif data == "adm_broadcast":
        admin_states[admin_id] = {"action": "broadcast"}
        bot.answer_callback_query(call.id)
        bot.send_message(
            chat_id,
            "📢 <b>Barchaga xabar</b>\n\nMatn, rasm, video yoki fayl yuboring.",
            reply_markup=get_cancel_keyboard()
        )

    elif data == "adm_send_one":
        admin_states[admin_id] = {"action": "send_one_id"}
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "👤 User ID raqamini yuboring:", reply_markup=get_cancel_keyboard())

    elif data == "adm_ban":
        admin_states[admin_id] = {"action": "ban"}
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "🚫 Ban qilmoqchi bo'lgan User ID ni yuboring:", reply_markup=get_cancel_keyboard())

    elif data == "adm_unban":
        admin_states[admin_id] = {"action": "unban"}
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "✅ Bandan olmoqchi bo'lgan User ID ni yuboring:", reply_markup=get_cancel_keyboard())

    elif data == "adm_banlist":
        bot.answer_callback_query(call.id)
        if not banned_users:
            bot.send_message(chat_id, "Ban ro'yxati bo'sh.")
        else:
            text = "<b>🚫 Ban ro'yxati:</b>\n\n" + "\n".join(f"• <code>{uid}</code>" for uid in banned_users)
            bot.send_message(chat_id, text)

    elif data == "adm_search":
        admin_states[admin_id] = {"action": "search"}
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "🔍 User ID ni yuboring:", reply_markup=get_cancel_keyboard())

    elif data == "adm_note":
        admin_states[admin_id] = {"action": "note_id"}
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "📝 Izoh yozmoqchi bo'lgan User ID ni yuboring:", reply_markup=get_cancel_keyboard())

    elif data == "adm_export":
        admin_states[admin_id] = {"action": "export"}
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "📄 Chatini eksport qilmoqchi bo'lgan User ID ni yuboring:", reply_markup=get_cancel_keyboard())

    elif data == "adm_maintenance":
        global maintenance_mode
        maintenance_mode = not maintenance_mode
        status = "YOQILDI 🟠" if maintenance_mode else "O'CHIRILDI 🟢"
        bot.answer_callback_query(call.id, f"Maintenance {status}")
        bot.send_message(chat_id, f"🛠 Maintenance mode: <b>{status}</b>")
        send_admin_panel(chat_id)

    elif data == "adm_personality":
        bot.answer_callback_query(call.id)
        kb = types.InlineKeyboardMarkup(row_width=1)
        for key, val in PERSONALITIES.items():
            mark = "✅ " if key == current_personality else ""
            kb.add(types.InlineKeyboardButton(f"{mark}{val['name']}", callback_data=f"adm_setpers_{key}"))
        kb.add(types.InlineKeyboardButton("◀️ Orqaga", callback_data="adm_status"))
        bot.send_message(chat_id, "🎭 Rejimni tanlang:", reply_markup=kb)

    elif data.startswith("adm_setpers_"):
        global current_personality
        key = data.replace("adm_setpers_", "")
        if key in PERSONALITIES:
            current_personality = key
            bot.answer_callback_query(call.id, f"Rejim: {PERSONALITIES[key]['name']}")
            bot.send_message(chat_id, f"✅ Rejim o'zgartirildi: <b>{PERSONALITIES[key]['name']}</b>")
        send_admin_panel(chat_id)

    elif data == "adm_recent":
        bot.answer_callback_query(call.id)
        recent = sorted(user_stats.items(), key=lambda x: x[1].get("last_seen", ""), reverse=True)[:15]
        if not recent:
            bot.send_message(chat_id, "Hali foydalanuvchi yo'q.")
        else:
            text = "<b>👥 So'nggi foydalanuvchilar:</b>\n\n"
            for uid, st in recent:
                note = user_notes.get(uid, "")
                note_str = f" | 📝 {note[:30]}" if note else ""
                text += f"• <code>{uid}</code> — {st.get('messages', 0)} xabar | {st.get('last_seen', '-')}{note_str}\n"
            bot.send_message(chat_id, text)

    elif data == "adm_stop":
        global bot_running
        with bot_lock:
            bot_running = False
            bot.answer_callback_query(call.id, "To'xtatilmoqda...")
            bot.send_message(chat_id, "🛑 Bot to'xtatilmoqda...")
            logger.info("ADMIN STOP")
            bot.stop_polling()

    elif data == "adm_restart":
        global restart_requested
        with bot_lock:
            restart_requested = True
            bot_running = False
            bot.answer_callback_query(call.id, "Qayta ishga tushirilmoqda...")
            bot.send_message(chat_id, "🔄 Bot qayta ishga tushirilmoqda...")
            logger.info("ADMIN RESTART")
            bot.stop_polling()

    elif data == "adm_cancel":
        clear_admin_state(admin_id)
        bot.answer_callback_query(call.id, "Bekor qilindi")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        send_admin_panel(chat_id)


# =========================================================
# ADMIN STATE HANDLER
# =========================================================

@bot.message_handler(
    func=lambda m: is_admin(m.from_user.id) and m.from_user.id in admin_states,
    content_types=["text", "photo", "video", "document", "animation"]
)
def admin_state_handler(message):
    admin_id = message.from_user.id
    state = admin_states.get(admin_id)
    if not state:
        return

    action = state.get("action")
    chat_id = message.chat.id

    if action == "broadcast":
        clear_admin_state(admin_id)
        users = list(user_chats.keys())
        total = len(users)
        if total == 0:
            bot.reply_to(message, "📭 Foydalanuvchi yo'q.")
            return

        bot.reply_to(message, f"📢 Yuborilmoqda... ({total} ta)")
        success = failed = 0

        for uid in users:
            try:
                if message.content_type == "text":
                    bot.send_message(uid, message.text)
                elif message.content_type == "photo":
                    bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption)
                elif message.content_type == "video":
                    bot.send_video(uid, message.video.file_id, caption=message.caption)
                elif message.content_type == "document":
                    bot.send_document(uid, message.document.file_id, caption=message.caption)
                elif message.content_type == "animation":
                    bot.send_animation(uid, message.animation.file_id, caption=message.caption)
                success += 1
                time.sleep(0.05)
            except Exception:
                failed += 1

        bot.send_message(chat_id, f"✅ <b>Yakunlandi</b>\nMuvaffaqiyatli: {success}\nXato: {failed}", reply_markup=get_admin_keyboard())

    elif action == "send_one_id":
        if not message.text or not message.text.strip().isdigit():
            bot.reply_to(message, "❌ Faqat raqam yuboring.")
            return
        target = int(message.text.strip())
        admin_states[admin_id] = {"action": "send_one_content", "target": target}
        bot.reply_to(message, f"✅ ID: <code>{target}</code>\nEndi xabar (matn/media) yuboring:")

    elif action == "send_one_content":
        target = state.get("target")
        clear_admin_state(admin_id)
        try:
            if message.content_type == "text":
                bot.send_message(target, message.text)
            elif message.content_type == "photo":
                bot.send_photo(target, message.photo[-1].file_id, caption=message.caption)
            elif message.content_type == "video":
                bot.send_video(target, message.video.file_id, caption=message.caption)
            elif message.content_type == "document":
                bot.send_document(target, message.document.file_id, caption=message.caption)
            bot.reply_to(message, f"✅ <code>{target}</code> ga yuborildi.", reply_markup=get_admin_keyboard())
        except Exception as e:
            bot.reply_to(message, f"❌ Xato: {e}", reply_markup=get_admin_keyboard())

    elif action == "ban":
        if not message.text or not message.text.strip().isdigit():
            bot.reply_to(message, "❌ Faqat raqam yuboring.")
            return
        uid = int(message.text.strip())
        banned_users.add(uid)
        clear_admin_state(admin_id)
        bot.reply_to(message, f"🚫 <code>{uid}</code> ban qilindi.", reply_markup=get_admin_keyboard())
        try:
            bot.send_message(uid, "🚫 Siz botdan ban qilindingiz.")
        except Exception:
            pass

    elif action == "unban":
        if not message.text or not message.text.strip().isdigit():
            bot.reply_to(message, "❌ Faqat raqam yuboring.")
            return
        uid = int(message.text.strip())
        banned_users.discard(uid)
        clear_admin_state(admin_id)
        bot.reply_to(message, f"✅ <code>{uid}</code> bandan olindi.", reply_markup=get_admin_keyboard())

    elif action == "search":
        if not message.text or not message.text.strip().isdigit():
            bot.reply_to(message, "❌ Faqat raqam yuboring.")
            return
        uid = int(message.text.strip())
        clear_admin_state(admin_id)
        st = user_stats.get(uid, {})
        note = user_notes.get(uid, "Yo'q")
        banned = "Ha 🚫" if uid in banned_users else "Yo'q"
        bot.send_message(
            chat_id,
            f"<b>🔍 Natija</b>\n\n"
            f"ID: <code>{uid}</code>\n"
            f"Xabarlar: {st.get('messages', 0)}\n"
            f"Birinchi: {st.get('first_seen', '-')}\n"
            f"Oxirgi: {st.get('last_seen', '-')}\n"
            f"Ban: {banned}\n"
            f"Izoh: {note}",
            reply_markup=get_admin_keyboard()
        )

    elif action == "note_id":
        if not message.text or not message.text.strip().isdigit():
            bot.reply_to(message, "❌ Faqat raqam yuboring.")
            return
        uid = int(message.text.strip())
        admin_states[admin_id] = {"action": "note_text", "target": uid}
        bot.reply_to(message, f"📝 <code>{uid}</code> uchun izoh yozing:")

    elif action == "note_text":
        uid = state.get("target")
        user_notes[uid] = message.text.strip()
        clear_admin_state(admin_id)
        bot.reply_to(message, "✅ Izoh saqlandi.", reply_markup=get_admin_keyboard())

    elif action == "export":
        if not message.text or not message.text.strip().isdigit():
            bot.reply_to(message, "❌ Faqat raqam yuboring.")
            return
        uid = int(message.text.strip())
        clear_admin_state(admin_id)
        chat = user_chats.get(uid)
        if not chat:
            bot.reply_to(message, "Bu userning chat tarixi yo'q.")
            return

        lines = []
        for msg in chat:
