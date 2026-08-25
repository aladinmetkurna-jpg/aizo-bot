import os
import json
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import telebot
from telebot import types
from openai import OpenAI


# =========================================================
# SOZLAMALAR
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

MODEL_NAME = "deepseek-v4-flash"

MAX_TELEGRAM_LENGTH = 4096
MAX_HISTORY_MESSAGES = 40
MAX_WORKERS = 20
FLOOD_SECONDS = 1.0

GROUPS_FILE = "groups.json"
MEMORY_FILE = "memories.json"


# =========================================================
# ENVIRONMENT TEKSHIRISH
# =========================================================

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN topilmadi!")

if not DEEPSEEK_API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY topilmadi!")

if ADMIN_ID == 0:
    raise RuntimeError(
        "ADMIN_ID topilmadi! Railway Variables'ga "
        "ADMIN_ID qo'shing."
    )


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("Aizo")


# =========================================================
# DEEPSEEK CLIENT
# =========================================================

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)


# =========================================================
# TELEGRAM BOT
# =========================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)


# =========================================================
# THREAD POOL
# =========================================================

executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)


# =========================================================
# GLOBAL DATA
# =========================================================

user_chats = {}
user_modes = {}
memories = {}
group_states = {}

last_message_time = {}
waiting_broadcast = set()


# =========================================================
# LOCKLAR
# =========================================================

data_lock = threading.RLock()
file_lock = threading.Lock()

user_locks = {}
user_locks_lock = threading.Lock()


def get_user_lock(user_id):
    with user_locks_lock:
        if user_id not in user_locks:
            user_locks[user_id] = threading.Lock()
        return user_locks[user_id]


# =========================================================
# JSON LOAD / SAVE
# =========================================================

def load_json(filename, default):
    if not os.path.exists(filename):
        return default
    try:
        with open(filename, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        logger.exception("JSON o'qishda xato: %s", filename)
        return default


def save_json(filename, data):
    try:
        with file_lock:
            temp_file = filename + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
            os.replace(temp_file, filename)
    except Exception:
        logger.exception("JSON saqlashda xato: %s", filename)


# =========================================================
# DATA LOAD
# =========================================================

group_states = load_json(GROUPS_FILE, {})
memories = load_json(MEMORY_FILE, {})


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
Sening isming Aizo.

Sen Shohruxning shaxsiy AI yordamchisisan.

Agar foydalanuvchi:

"Sen kimsan?"
"Kimsan?"
"Isming nima?"
"Kimning yordamchisisan?"

yoki shunga o'xshash savol bersa:

"Men Aizo — Shohruxning AI yordamchisiman."

deb javob ber.

Sen Telegram ichida ishlaydigan aqlli AI yordamchisan.

Asosan o'zbek tilida javob ber.

Agar foydalanuvchi boshqa tilda yozsa,
shu tilda javob berishing mumkin.

Javoblaring tabiiy, tushunarli va foydali bo'lsin.

Texnik savollarga aniq va amaliy javob ber.

Kod so'ralsa, imkon qadar to'liq va ishlaydigan kod ber.

Agar foydalanuvchi kod yuborsa:

1. Xatoni top.
2. Sababini tushuntir.
3. Tuzatilgan kodni ber.

Keraksiz uzun javoblar bermagin.

Foydalanuvchiga hurmat bilan murojaat qil.

O'zingni Shohrux deb ko'rsatma.

Sen Aizo — Shohruxning AI yordamchisisan.
"""


# =========================================================
# AI REJIMLARI
# =========================================================

MODES = {
    "normal": """
Oddiy Aizo rejimida ishlagin.
Tabiiy va tushunarli javob ber.
""",
    "programmer": """
Sen professional dasturchi yordamchisan.
Kodlarni to'liq va amaliy yoz.
Xatolarni top va tuzat.
""",
    "teacher": """
Sen o'qituvchi kabi tushuntir.
Murakkab narsalarni sodda tushuntir.
Misollar ber.
""",
    "translator": """
Sen professional tarjimonsan.
Ma'no va kontekstni saqla.
Ortiqcha izoh bermagin.
""",
    "creative": """
Sen kreativ yordamchisan.
G'oyalar, hikoyalar, nomlar va kreativ
matnlar yarat.
""",
    "analyst": """
Sen analitik yordamchisan.
Savolni mantiqan tahlil qil.
Afzallik, kamchilik va xulosalarni ko'rsat.
"""
}


# =========================================================
# CHAT FUNKSIYALARI
# =========================================================

def create_chat(user_id):
    mode = user_modes.get(str(user_id), "normal")
    memory = memories.get(str(user_id), "")

    system_prompt = SYSTEM_PROMPT
    system_prompt += "\n\nHOZIRGI AI REJIMI:\n" + MODES.get(mode, MODES["normal"])

    if memory:
        system_prompt += "\n\nFOYDALANUVCHI HAQIDA SAQLANGAN XOTIRA:\n" + memory

    return [{"role": "system", "content": system_prompt}]


def get_chat(user_id):
    with data_lock:
        if user_id not in user_chats:
            user_chats[user_id] = create_chat(user_id)
        return user_chats[user_id]


def clear_chat(user_id):
    lock = get_user_lock(user_id)
    with lock:
        with data_lock:
            user_chats[user_id] = create_chat(user_id)


def limit_history(messages):
    if len(messages) <= MAX_HISTORY_MESSAGES + 1:
        return messages
    return [messages[0], *messages[-MAX_HISTORY_MESSAGES:]]


# =========================================================
# GROUP FUNKSIYALARI
# =========================================================

def is_group(message):
    return message.chat.type in ("group", "supergroup")


def group_active(chat_id):
    return group_states.get(str(chat_id), True)


def set_group_active(chat_id, active):
    group_states[str(chat_id)] = active
    save_json(GROUPS_FILE, group_states)


# =========================================================
# YORDAMCHI FUNKSIYALAR
# =========================================================

def is_admin(message):
    return message.from_user and message.from_user.id == ADMIN_ID


def get_display_name(message):
    user = message.from_user
    if not user:
        return "Foydalanuvchi"
    if user.username:
        return "@" + user.username
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return full_name if full_name else "Foydalanuvchi"


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


def send_long_message(chat_id, text, reply_markup=None):
    chunks = split_message(text)
    for index, chunk in enumerate(chunks):
        markup = reply_markup if (reply_markup and index == len(chunks) - 1) else None
        bot.send_message(chat_id, chunk, reply_markup=markup)


# =========================================================
# KEYBOARDLAR
# =========================================================

def private_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("Suhbatni tozalash", callback_data="clear_chat"),
        types.InlineKeyboardButton("AI rejimi", callback_data="mode_menu")
    )
    return keyboard


def mode_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("Oddiy", callback_data="mode_normal"),
        types.InlineKeyboardButton("Programmer", callback_data="mode_programmer")
    )
    keyboard.add(
        types.InlineKeyboardButton("Teacher", callback_data="mode_teacher"),
        types.InlineKeyboardButton("Translator", callback_data="mode_translator")
    )
    keyboard.add(
        types.InlineKeyboardButton("Creative", callback_data="mode_creative"),
        types.InlineKeyboardButton("Analyst", callback_data="mode_analyst")
    )
    return keyboard


def admin_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("Statistika", callback_data="admin_stats"),
        types.InlineKeyboardButton("Broadcast", callback_data="admin_broadcast")
    )
    keyboard.add(
        types.InlineKeyboardButton("Xotiralarni tozalash", callback_data="admin_clear"),
        types.InlineKeyboardButton("Admin ID", callback_data="admin_id")
    )
    keyboard.add(
        types.InlineKeyboardButton("Yopish", callback_data="admin_close")
    )
    return keyboard


# =========================================================
# /START
# =========================================================

@bot.message_handler(commands=["start"])
def start_command(message):
    clear_chat(message.chat.id)

    if is_group(message):
        bot.send_message(
            message.chat.id,
            "Aizo ishga tushdi.\n\n"
            "Guruhdagi xabarlarga javob beraman.\n\n"
            "/stop — Aizoni to'xtatish\n"
            "/start_ai — qayta yoqish\n"
            "/status_ai — holatini ko'rish"
        )
    else:
        bot.send_message(
            message.chat.id,
            "Salom!\n\n"
            "Men Aizo — Shohruxning AI yordamchisiman.\n\n"
            "Savolingizni yozing.",
            reply_markup=private_keyboard()
        )


# =========================================================
# /HELP
# =========================================================

@bot.message_handler(commands=["help"])
def help_command(message):
    bot.send_message(
        message.chat.id,
        "Aizo yordam\n\n"
        "/start — yangi suhbat\n"
        "/clear — suhbatni tozalash\n"
        "/memory — xotirani ko'rish\n"
        "/forget — xotirani o'chirish\n"
        "/mode — AI rejimi\n"
        "/summarize — suhbat xulosasi\n\n"
        "Guruh:\n"
        "/stop\n"
        "/start_ai\n"
        "/status_ai\n\n"
        "Admin:\n"
        "/admin"
    )


# =========================================================
# /CLEAR
# =========================================================

@bot.message_handler(commands=["clear"])
def clear_command(message):
    clear_chat(message.chat.id)
    bot.send_message(
        message.chat.id,
        "Suhbat xotirasi tozalandi.",
        reply_markup=None if is_group(message) else private_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data == "clear_chat")
def clear_callback(call):
    clear_chat(call.from_user.id)
    bot.answer_callback_query(call.id, "Suhbat tozalandi.")
    bot.send_message(
        call.from_user.id,
        "Suhbat xotirasi tozalandi.",
        reply_markup=private_keyboard()
    )


# =========================================================
# MODE
# =========================================================

@bot.message_handler(commands=["mode"])
def mode_command(message):
    bot.send_message(
        message.chat.id,
        "AI rejimini tanlang:",
        reply_markup=mode_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data == "mode_menu")
def mode_menu_callback(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.from_user.id,
        "AI rejimini tanlang:",
        reply_markup=mode_keyboard()
    )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith("mode_") and call.data != "mode_menu"
)
def mode_callback(call):
    mode = call.data.replace("mode_", "")
    if mode not in MODES:
        bot.answer_callback_query(call.id, "Noma'lum rejim.")
        return

    user_id = call.from_user.id
    lock = get_user_lock(user_id)
    with lock:
        user_modes[str(user_id)] = mode
        user_chats[user_id] = create_chat(user_id)

    bot.answer_callback_query(call.id, f"{mode} rejimi yoqildi.")
    bot.send_message(
        user_id,
        f"AI rejimi: {mode}\n\nYangi suhbat shu rejimda davom etadi.",
        reply_markup=private_keyboard()
    )


# =========================================================
# /MEMORY  /FORGET
# =========================================================

@bot.message_handler(commands=["memory"])
def memory_command(message):
    memory = memories.get(str(message.chat.id), "")
    if not memory:
        text = "Aizo siz haqingizda saqlangan xotira yo'q."
    else:
        text = "Aizo xotirasi:\n\n" + memory
    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=["forget"])
def forget_command(message):
    user_id = str(message.chat.id)
    memories.pop(user_id, None)
    save_json(MEMORY_FILE, memories)
    clear_chat(message.chat.id)
    bot.send_message(
        message.chat.id,
        "Siz haqingizdagi saqlangan xotira o'chirildi."
    )


# =========================================================
# GURUH BUYRUQLARI
# =========================================================

@bot.message_handler(commands=["stop"])
def stop_command(message):
    if not is_group(message):
        bot.send_message(message.chat.id, "/stop faqat guruhda ishlaydi.")
        return
    if not is_admin(message):
        bot.reply_to(message, "Bu buyruq faqat admin uchun.")
        return

    set_group_active(message.chat.id, False)
    bot.send_message(
        message.chat.id,
        "Aizo to'xtatildi.\n\nQayta yoqish: /start_ai"
    )


@bot.message_handler(commands=["start_ai"])
def start_ai_command(message):
    if not is_group(message):
        bot.send_message(message.chat.id, "/start_ai faqat guruhda ishlaydi.")
        return
    if not is_admin(message):
        bot.reply_to(message, "Bu buyruq faqat admin uchun.")
        return

    set_group_active(message.chat.id, True)
    bot.send_message(message.chat.id, "Aizo yana ishga tushdi.")


@bot.message_handler(commands=["status_ai"])
def status_command(message):
    if not is_group(message):
        bot.send_message(message.chat.id, "/status_ai faqat guruhda ishlaydi.")
        return

    active = group_active(message.chat.id)
    status = "yoqilgan ✅" if active else "o'chirilgan ❌"
    bot.send_message(message.chat.id, f"Aizo holati: {status}")


# =========================================================
# /ADMIN
# =========================================================

@bot.message_handler(commands=["admin"])
def admin_command(message):
    if not is_admin(message):
        bot.reply_to(message, "Bu buyruq faqat admin uchun.")
        return
    bot.send_message(
        message.chat.id,
        "Admin panel:",
        reply_markup=admin_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Ruxsat yo'q.")
        return

    data = call.data

    if data == "admin_stats":
        with data_lock:
            users = len(user_chats)
            groups = len(group_states)
            mems = len(memories)
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.from_user.id,
            f"Statistika:\n\n"
            f"• Faol chatlar: {users}\n"
            f"• Guruhlar: {groups}\n"
            f"• Xotiralar: {mems}"
        )

    elif data == "admin_broadcast":
        waiting_broadcast.add(call.from_user.id)
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.from_user.id,
            "Broadcast xabarini yuboring (yoki /cancel)."
        )

    elif data == "admin_clear":
        memories.clear()
        save_json(MEMORY_FILE, memories)
        bot.answer_callback_query(call.id, "Xotiralar tozalandi.")
        bot.send_message(call.from_user.id, "Barcha xotiralar o'chirildi.")

    elif data == "admin_id":
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.from_user.id,
            f"Sizning ID: `{ADMIN_ID}`",
            parse_mode="Markdown"
        )

    elif data == "admin_close":
        bot.answer_callback_query(call.id)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass


# =========================================================
# /SUMMARIZE
# =========================================================

@bot.message_handler(commands=["summarize"])
def summarize_command(message):
    user_id = message.chat.id
    chat = get_chat(user_id)

    if len(chat) < 3:
        bot.send_message(user_id, "Suhbat hali juda qisqa, xulosa chiqarib bo'lmaydi.")
        return

    chat.append({
        "role": "user",
        "content": "Shu suhbatni qisqa va aniq xulosa qilib ber."
    })

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=chat,
            max_tokens=800
        )
        summary = response.choices[0].message.content
    except Exception:
        logger.exception("Summarize xatosi")
        summary = "Xulosa chiqarishda xatolik yuz berdi."

    bot.send_message(user_id, summary)


# =========================================================
# FLOOD CONTROL
# =========================================================

def is_flooding(user_id):
    now = time.time()
    last = last_message_time.get(user_id, 0)
    if now - last < FLOOD_SECONDS:
        return True
    last_message_time[user_id] = now
    return False


# =========================================================
# AI JAVOB
# =========================================================

def get_ai_reply(user_id, text):
    lock = get_user_lock(user_id)
    with lock:
        chat = get_chat(user_id)
        chat.append({"role": "user", "content": text})
        chat = limit_history(chat)

        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=chat,
                max_tokens=2000,
                temperature=0.7
            )
            reply = response.choices[0].message.content
        except Exception:
            logger.exception("DeepSeek xatosi")
            reply = "Kechirasiz, AI bilan bog'lanishda xatolik yuz berdi. Keyinroq urinib ko'ring."

        chat.append({"role": "assistant", "content": reply})
        user_chats[user_id] = chat
        return reply


# =========================================================
# ASOSIY XABAR HANDLER
# =========================================================

@bot.message_handler(
    content_types=["text"],
    func=lambda m: m.text and not m.text.startswith("/")
)
def handle_message(message):
    if is_flooding(message.from_user.id):
        return

    if is_group(message):
        if not group_active(messa