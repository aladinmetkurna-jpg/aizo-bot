import os
import logging
import threading
import base64
import time
from datetime import datetime

import telebot
from openai import OpenAI
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-v4-flash-vision-exp")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "700"))
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "40"))
MAX_LEN = 4000

bot_enabled = True
stats = {"msgs": 0, "photos": 0, "users": set(), "errors": 0, "start": datetime.now()}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("Aizo")

if not TELEGRAM_TOKEN: raise RuntimeError("TELEGRAM_TOKEN topilmadi!")
if not DEEPSEEK_API_KEY: raise RuntimeError("DEEPSEEK_API_KEY topilmadi!")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.b.ai/v1")
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)

SYSTEM = """Sening isming Aizo. Sen Shohruxning shaxsiy AI yordamchisisan.
Kim ekaningni so'rashsa: "Men Aizo — Shohruxning AI yordamchisiman."
QOIDALAR:
- Javoblaring QISQA va aniq bo'lsin (2-5 gap).
- Keraksiz kirish so'zlari yozma, to'g'ridan-to'g'ri javobdan boshla.
- O'zbek tilida javob ber. Boshqa tilda yozsa, o'sha tilda javob ber.
- Kod savollarida: ishlaydigan kodni ber, qisqa izoh bilan.
- Rasm yuborilsa, qisqa tahlil ber.
- "Batafsil" desa uzunroq yoz. Aks holda qisqa."""

user_chats = {}
locks = {}
glock = threading.Lock()

def get_lock(uid):
    with glock:
        if uid not in locks:
            locks[uid] = threading.Lock()
        return locks[uid]

def new_chat():
    return [{"role": "system", "content": SYSTEM}]

def trim(msgs):
    if len(msgs) <= MAX_HISTORY + 1:
        return msgs
    return [msgs[0]] + msgs[-MAX_HISTORY:]

def is_admin(uid):
    return ADMIN_ID != 0 and uid == ADMIN_ID

def uptime():
    d = datetime.now() - stats["start"]
    h, r = divmod(int(d.total_seconds()), 3600)
    m, s = divmod(r, 60)
    return f"{h}s {m}d {s}s"

def send_msg(chat_id, text, reply_id=None, is_group=False):
    chunks = []
    while len(text) > MAX_LEN:
        cut = text.rfind("\n", 0, MAX_LEN)
        if cut < 500: cut = text.rfind(" ", 0, MAX_LEN)
        if cut < 500: cut = MAX_LEN
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text: chunks.append(text)
    for i, chunk in enumerate(chunks):
        rid = reply_id if (i == 0 and is_group) else None
        try:
            bot.send_message(chat_id, chunk, reply_to_message_id=rid)
        except Exception as e:
            log.error("send_msg xato: %s", e)

def photo_b64(message):
    try:
        f = bot.get_file(message.photo[-1].file_id)
        data = bot.download_file(f.file_path)
        return base64.b64encode(data).decode()
    except Exception as e:
        log.exception("Rasm xato: %s", e)
        return None

# === ADMIN PANEL ===

def main_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🟢 YOQIQ" if bot_enabled else "🔴 OCHIQ", callback_data="a_status"),
        InlineKeyboardButton("🔴 O'chir" if bot_enabled else "🟢 Yoq", callback_data="a_toggle"),
        InlineKeyboardButton("📊 Statistika", callback_data="a_stats"),
        InlineKeyboardButton("👥 Foydalanuvchilar", callback_data="a_users"),
        InlineKeyboardButton("📢 Broadcast", callback_data="a_broadcast"),
        InlineKeyboardButton("🗑️ Tarixni tozala", callback_data="a_clearall"),
        InlineKeyboardButton("⚙️ Sozlamalar", callback_data="a_settings"),
        InlineKeyboardButton("❌ Yopish", callback_data="a_close"),
    )
    return kb

def back_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("⬅️ Orqaga", callback_data="a_main"))
    return kb

@bot.message_handler(commands=["start"])
def cmd_start(msg):
    uid = msg.chat.id
    user_chats[uid] = new_chat()
    stats["users"].add(uid)
    bot.send_message(uid, "Salom! Men Aizo — Shohruxning AI yordamchisiman.\n\nSavolingizni yozing yoki rasm yuboring.")

@bot.message_handler(commands=["clear"])
def cmd_clear(msg):
    user_chats[msg.chat.id] = new_chat()
    bot.send_message(msg.chat.id, "Suhbat tozalandi.")

@bot.message_handler(commands=["help"])
def cmd_help(msg):
    bot.send_message(msg.chat.id, "/start — yangi suhbat\n/clear — tarixni tozalash\n/help — yordam")

@bot.message_handler(commands=["admin"])
def cmd_admin(msg):
    if not is_admin(msg.chat.id):
        bot.send_message(msg.chat.id, "Ruxsat yo'q.")
        return
    bot.send_message(msg.chat.id, "👨‍💼 Admin Panel", reply_markup=main_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("a_"))
def admin_cb(call):
    global bot_enabled
    uid = call.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(call.id, "Ruxsat yo'q!")
        return
    d = call.data
    cid, mid = call.message.chat.id, call.message.message_id

    if d == "a_main":
        bot.edit_message_text("👨‍💼 Admin Panel", cid, mid, reply_markup=main_kb())
    elif d == "a_status":
        bot.answer_callback_query(call.id, f"Bot: {'YOQIQ' if bot_enabled else 'OCHIQ'}")
    elif d == "a_toggle":
        bot_enabled = not bot_enabled
        s = "yoqildi 🟢" if bot_enabled else "o'chirildi 🔴"
        bot.answer_callback_query(call.id, f"Bot {s}!")
        bot.edit_message_text(f"👨‍💼 Admin Panel\nBot {s}", cid, mid, reply_markup=main_kb())
    elif d == "a_stats":
        t = (f"📊 Statistika\n\n"
             f"👥 Foydalanuvchilar: {len(stats['users'])}\n"
             f"💬 Xabarlar: {stats['msgs']}\n"
             f"🖼 Rasmlar: {stats['photos']}\n"
             f"❌ Xatolar: {stats['errors']}\n"
             f"🕐 Uptime: {uptime()}\n"
             f"🤖 Model: {MODEL_NAME}\n"
             f"⚡ Holat: {'YOQIQ 🟢' if bot_enabled else 'OCHIQ 🔴'}")
        bot.edit_message_text(t, cid, mid, reply_markup=back_kb())
    elif d == "a_users":
        users = list(stats["users"])
        t = f"👥 Jami {len(users)} ta foydalanuvchi\n\nID lar:\n" + "\n".join(str(u) for u in users[-20:])
        bot.edit_message_text(t, cid, mid, reply_markup=back_kb())
    elif d == "a_broadcast":
        bot.edit_message_text("📢 Broadcast uchun:\n\n/broadcast <xabar>", cid, mid, reply_markup=back_kb())
    elif d == "a_clearall":
        n = len(user_chats)
        user_chats.clear()
        bot.answer_callback_query(call.id, f"{n} ta tarix tozalandi!")
        bot.edit_message_text(f"🗑️ {n} ta tarix tozalandi.", cid, mid, reply_markup=back_kb())
    elif d == "a_settings":
        t = (f"⚙️ Sozlamalar\n\n"
             f"Model: {MODEL_NAME}\n"
             f"Max tokens: {MAX_TOKENS}\n"
             f"Max history: {MAX_HISTORY}")
        bot.edit_message_text(t, cid, mid, reply_markup=back_kb())
    elif d == "a_close":
        bot.delete_message(cid, mid)
    bot.answer_callback_query(call.id)

@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(msg):
    if not is_admin(msg.chat.id): return
    text = msg.text.replace("/broadcast", "").strip()
    if not text:
        bot.send_message(msg.chat.id, "Misol: /broadcast Salom!")
        return
    users = list(stats["users"])
    sent = failed = 0
    for u in users:
        if u == ADMIN_ID: continue
        try:
            bot.send_message(u, f"📢 Xabar:\n\n{text}")
            sent += 1
            time.sleep(0.05)
        except:
            failed += 1
    bot.send_message(msg.chat.id, f"✅ Yuborildi: {sent}\n❌ Xato: {failed}")

@bot.message_handler(content_types=["text"], func=lambda m: m.text and not m.text.startswith("/"))
def on_text(msg): process(msg, False)

@bot.message_handler(content_types=["photo"])
def on_photo(msg): process(msg, True)

def process(msg: Message, is_photo: bool):
    global bot_enabled
    uid = msg.chat.id
    is_group = msg.chat.type in ["group", "supergroup"]

    if not bot_enabled and not is_admin(uid):
        bot.send_message(uid, "Bot vaqtincha to'xtatilgan.", reply_to_message_id=msg.message_id if is_group else None)
        return

    stats["users"].add(uid)
    if is_photo: stats["photos"] += 1
    else: stats["msgs"] += 1

    if uid not in user_chats:
        user_chats[uid] = new_chat()

    with get_lock(uid):
        try:
            bot.send_chat_action(uid, "typing")

            if is_photo:
                b64 = photo_b64(msg)
                if not b64:
                    bot.send_message(uid, "Rasm yuklashda xato.", reply_to_message_id=msg.message_id if is_group else None)
                    return
                cap = msg.caption.strip() if msg.caption else "Bu rasmni tahlil qil."
                user_chats[uid].append({"role": "user", "content": [
                    {"type": "text", "text": cap},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]})
            else:
                t = msg.text.strip()
                if not t: return
                user_chats[uid].append({"role": "user", "content": t})

            user_chats[uid] = trim(user_chats[uid])

            resp = client.chat.completions.create(
                model=MODEL_NAME,
                messages=user_chats[uid],
                stream=False,
                max_tokens=MAX_TOKENS
            )

            if not resp.choices: raise RuntimeError("Bo'sh javob")
            ans = resp.choices[0].message.content
            if not ans: raise RuntimeError("Bo'sh javob")

            user_chats[uid].append({"role": "assistant", "content": ans})
            send_msg(uid, ans, msg.message_id, is_group)
            log.info("OK | user=%s | photo=%s", uid, is_photo)

        except Exception as e:
            stats["errors"] += 1
            log.exception("XATO | user=%s", uid)
            if user_chats.get(uid) and user_chats[uid][-1].get("role") == "user":
                user_chats[uid].pop()
            err = str(e).lower()
            if any(x in err for x in ["429", "rate limit", "quota"]):
                m = "API limiti to'ldi. Birozdan keyin urinib ko'ring."
            elif any(x in err for x in ["401", "api key", "unauthorized"]):
                m = "API key xato. Admin bilan bog'laning."
            elif any(x in err for x in ["500", "502", "503"]):
                m = "Server vaqtincha ishlamayapti."
            elif any(x in err for x in ["connection", "timeout"]):
                m = "Tarmoq xatosi. Qayta urinib ko'ring."
            else:
                m = "Xatolik yuz berdi. Qayta urinib ko'ring."
            bot.send_message(uid, m, reply_to_message_id=msg.message_id if is_group else None)

@bot.message_handler(content_types=["video","audio","document","sticker","voice","animation","contact","location"])
def on_other(msg):
    is_group = msg.chat.type in ["group", "supergroup"]
    bot.send_message(msg.chat.id, "Faqat matn va rasm qabul qilaman.", reply_to_message_id=msg.message_id if is_group else None)

if __name__ == "__main__":
    log.info("Aizo ishga tushmoqda... Admin: %s", ADMIN_ID or "Yoq")
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=30)
    except KeyboardInterrupt:
        log.info("To'xtatildi.")
    except Exception:
        log.exception("CRITICAL ERROR")