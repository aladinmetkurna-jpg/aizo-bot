import os
import json
import logging
import threading

import telebot
from telebot import types
from openai import OpenAI


# =========================================================
# SOZLAMALAR
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Railway Variables:
# ADMIN_ID=123456789

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

MODEL_NAME = "deepseek-v4-flash"

MAX_TELEGRAM_LENGTH = 4096

# System message'dan tashqari saqlanadigan xabarlar
MAX_HISTORY_MESSAGES = 40

# Guruh holatlarini saqlash
GROUPS_FILE = "groups.json"


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
    raise RuntimeError(
        "TELEGRAM_TOKEN topilmadi!"
    )

if not DEEPSEEK_API_KEY:
    raise RuntimeError(
        "DEEPSEEK_API_KEY topilmadi!"
    )

if ADMIN_ID == 0:
    raise RuntimeError(
        "ADMIN_ID topilmadi yoki noto'g'ri!\n"
        "Railway Variables ichiga ADMIN_ID qo'shing."
    )


# =========================================================
# B.AI / DEEPSEEK CLIENT
# =========================================================

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.b.ai/v1"
)


# =========================================================
# TELEGRAM BOT
# =========================================================

bot = telebot.TeleBot(
    TELEGRAM_TOKEN,
    parse_mode=None
)


# =========================================================
# AIZO SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
Sening isming Aizo.

Sen Shohruxning shaxsiy AI yordamchisisan.

Agar foydalanuvchi:
"Sen kimsan?"
"Kimsan?"
"Isming nima?"
"Kimning yordamchisisan?"
yoki shunga o'xshash savol bersa,

o'zingni:

"Men Aizo — Shohruxning AI yordamchisiman."

deb tanishtir.

Sen Telegram ichida ishlaydigan aqlli AI yordamchisan.

Asosan o'zbek tilida javob ber.

Agar foydalanuvchi boshqa tilda yozsa,
shu tilda javob berishing mumkin.

Javoblaring tabiiy, tushunarli va foydali bo'lsin.

Texnik savollarga aniq va amaliy javob ber.

Kod so'ralsa, imkon qadar to'liq va ishlaydigan kod ber.

Agar foydalanuvchi kod yuborsa va unda xato bo'lsa,
xatoni top, sababini tushuntir va tuzatilgan kodni ber.

Foydalanuvchining oldingi xabarlarini suhbat kontekstida hisobga ol.

Keraksiz uzun javoblar bermagin.

Foydalanuvchiga hurmat bilan murojaat qil.

O'zingni Shohrux deb ko'rsatma.

Sen Aizo — Shohruxning AI yordamchisisan.
"""


# =========================================================
# XOTIRA
# =========================================================

user_chats = {}

chat_locks = {}

global_lock = threading.Lock()


# =========================================================
# GURUH HOLATLARI
# =========================================================

groups_lock = threading.Lock()


def load_groups():
    if not os.path.exists(GROUPS_FILE):
        return {}

    try:
        with open(
            GROUPS_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, dict):
            return data

    except Exception:
        logger.exception(
            "groups.json o'qishda xato"
        )

    return {}


group_states = load_groups()


def save_groups():

    try:

        with groups_lock:

            temp_file = GROUPS_FILE + ".tmp"

            with open(
                temp_file,
                "w",
                encoding="utf-8"
            ) as file:

                json.dump(
                    group_states,
                    file,
                    ensure_ascii=False,
                    indent=2
                )

            os.replace(
                temp_file,
                GROUPS_FILE
            )

    except Exception:

        logger.exception(
            "groups.json saqlashda xato"
        )


def is_group_active(chat_id):

    # Yangi guruh default:
    # Aizo yoqilgan
    return group_states.get(
        str(chat_id),
        True
    )


def set_group_state(
    chat_id,
    active
):

    group_states[
        str(chat_id)
    ] = active

    save_groups()


# =========================================================
# YORDAMCHI FUNKSIYALAR
# =========================================================

def is_admin(message):

    if not message.from_user:
        return False

    return (
        message.from_user.id
        == ADMIN_ID
    )


def is_group(message):

    return message.chat.type in (
        "group",
        "supergroup"
    )


def get_user_lock(user_id):

    with global_lock:

        if user_id not in chat_locks:

            chat_locks[user_id] = (
                threading.Lock()
            )

        return chat_locks[user_id]


def create_chat():

    return [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]


def limit_history(messages):

    if (
        len(messages)
        <= MAX_HISTORY_MESSAGES + 1
    ):
        return messages

    system_message = messages[0]

    recent_messages = messages[
        -MAX_HISTORY_MESSAGES:
    ]

    return [
        system_message,
        *recent_messages
    ]


# =========================================================
# TELEGRAM UZUNLIK LIMITI
# =========================================================

def split_message(
    text,
    max_length=MAX_TELEGRAM_LENGTH
):

    if not text:
        return [
            "AI javob qaytarmadi."
        ]

    if len(text) <= max_length:
        return [text]

    chunks = []

    while len(text) > max_length:

        cut = text.rfind(
            "\n",
            0,
            max_length
        )

        if cut < 1000:

            cut = text.rfind(
                " ",
                0,
                max_length
            )

        if cut < 1000:
            cut = max_length

        chunk = text[
            :cut
        ].strip()

        if chunk:
            chunks.append(chunk)

        text = text[
            cut:
        ].strip()

    if text:
        chunks.append(text)

    return chunks


def send_long_message(
    chat_id,
    text
):

    chunks = split_message(text)

    for chunk in chunks:

        bot.send_message(
            chat_id,
            chunk
        )


# =========================================================
# PRIVATE CHAT TUGMASI
# =========================================================

def private_keyboard():

    keyboard = types.InlineKeyboardMarkup()

    keyboard.add(
        types.InlineKeyboardButton(
            "Suhbatni tozalash",
            callback_data="user_clear"
        )
    )

    return keyboard


# =========================================================
# ADMIN PANEL
# =========================================================

def admin_keyboard():

    keyboard = types.InlineKeyboardMarkup(
        row_width=2
    )

    keyboard.add(

        types.InlineKeyboardButton(
            "Statistika",
            callback_data="admin_stats"
        ),

        types.InlineKeyboardButton(
            "Broadcast",
            callback_data="admin_broadcast"
        )
    )

    keyboard.add(

        types.InlineKeyboardButton(
            "Barcha xotirani tozalash",
            callback_data="admin_clearall"
        )
    )

    keyboard.add(

        types.InlineKeyboardButton(
            "Admin ID",
            callback_data="admin_id"
        )
    )

    keyboard.add(

        types.InlineKeyboardButton(
            "Yopish",
            callback_data="admin_close"
        )
    )

    return keyboard


def send_admin_panel(chat_id):

    bot.send_message(

        chat_id,

        "Aizo Admin Panel\n\n"
        "Kerakli amalni tanlang:",

        reply_markup=admin_keyboard()
    )


# =========================================================
# BROADCAST HOLATI
# =========================================================

broadcast_waiting = set()

broadcast_lock = threading.Lock()


# =========================================================
# /START
# =========================================================

@bot.message_handler(
    commands=["start"]
)
def start_command(message):

    user_id = message.chat.id

    user_chats[
        user_id
    ] = create_chat()

    if is_group(message):

        bot.send_message(

            user_id,

            "Aizo ishga tushdi.\n\n"
            "Guruhda yozilgan har bir oddiy "
            "xabar uchun javob beraman.\n\n"
            "/stop — Aizoni to'xtatish\n"
            "/start_ai — Aizoni yoqish\n"
            "/status_ai — holatini ko'rish"
        )

    else:

        bot.send_message(

            user_id,

            "Salom!\n\n"
            "Men Aizo — Shohruxning "
            "AI yordamchisiman.\n\n"
            "Savolingizni yozing, yordam beraman.",

            reply_markup=private_keyboard()
        )


# =========================================================
# /HELP
# =========================================================

@bot.message_handler(
    commands=["help"]
)
def help_command(message):

    if is_group(message):

        bot.send_message(

            message.chat.id,

            "Aizo yordam\n\n"
            "Men guruhdagi oddiy matnli "
            "xabarlarning barchasiga javob beraman.\n\n"
            "/stop — Aizoni to'xtatish\n"
            "/start_ai — Aizoni qayta yoqish\n"
            "/status_ai — holatini ko'rish"
        )

    else:

        bot.send_message(

            message.chat.id,

            "Aizo yordam\n\n"
            "Oddiy savolingizni yozing.\n"
            "Suhbatni pastdagi tugma orqali "
            "tozalashingiz mumkin."
        )


# =========================================================
# /CLEAR
# =========================================================

@bot.message_handler(
    commands=["clear"]
)
def clear_command(message):

    user_id = message.chat.id

    user_chats[
        user_id
    ] = create_chat()

    bot.send_message(

        user_id,

        "Suhbat xotirasi tozalandi."
    )


# =========================================================
# PRIVATE CHAT — CLEAR TUGMASI
# =========================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "user_clear"
)
def user_clear_callback(call):

    user_id = call.from_user.id

    if (
        not call.message
        or call.message.chat.type
        != "private"
    ):

        bot.answer_callback_query(

            call.id,

            "Bu tugma faqat private chatda ishlaydi."
        )

        return

    if (
        call.from_user.id
        != call.message.chat.id
    ):

        bot.answer_callback_query(

            call.id,

            "Bu tugma siz uchun emas."
        )

        return

    user_chats[
        user_id
    ] = create_chat()

    bot.answer_callback_query(

        call.id,

        "Suhbat tozalandi."
    )

    bot.send_message(

        user_id,

        "Suhbat xotirasi tozalandi.",

        reply_markup=private_keyboard()
    )


# =========================================================
# /ADMIN
# =========================================================

@bot.message_handler(
    commands=["admin"]
)
def admin_command(message):

    if not is_admin(message):

        bot.send_message(

            message.chat.id,

            "Bu buyruq faqat admin uchun."
        )

        return

    send_admin_panel(
        message.chat.id
    )


# =========================================================
# /ADMINID
# =========================================================

@bot.message_handler(
    commands=["adminid"]
)
def adminid_command(message):

    if not is_admin(message):

        bot.send_message(

            message.chat.id,

            "Bu buyruq faqat admin uchun."
        )

        return

    bot.send_message(

        message.chat.id,

        f"Admin ID: {ADMIN_ID}"
    )


# =========================================================
# /STOP
# =========================================================

@bot.message_handler(
    commands=["stop"]
)
def stop_command(message):

    if not is_group(message):

        bot.send_message(

            message.chat.id,

            "Bu buyruq faqat guruhda ishlaydi."
        )

        return

    if not is_admin(message):

        bot.reply_to(

            message,

            "Bu buyruq faqat admin uchun."
        )

        return

    set_group_state(

        message.chat.id,

        False
    )

    bot.send_message(

        message.chat.id,

        "Aizo ushbu guruhda to'xtatildi.\n\n"
        "Qayta yoqish: /start_ai"
    )


# =========================================================
# /START_AI
# =========================================================

@bot.message_handler(
    commands=["start_ai"]
)
def start_ai_command(message):

    if not is_group(message):

        bot.send_message(

            message.chat.id,

            "Bu buyruq faqat guruhda ishlaydi."
        )

        return

    if not is_admin(message):

        bot.reply_to(

            message,

            "Bu buyruq faqat admin uchun."
        )

        return

    set_group_state(

        message.chat.id,

        True
    )

    bot.send_message(

        message.chat.id,

        "Aizo ushbu guruhda yana ishga tushdi."
    )


# =========================================================
# /STATUS_AI
# =========================================================

@bot.message_handler(
    commands=["status_ai"]
)
def status_ai_command(message):

    if not is_group(message):

        bot.send_message(

            message.chat.id,

            "Bu buyruq faqat guruhda ishlaydi."
        )

        return

    status = (

        "ISHAYAPTI"

        if is_group_active(
            message.chat.id
        )

        else "TO'XTATILGAN"
    )

    bot.send_message(

        message.chat.id,

        f"Aizo holati: {status}"
    )


# =========================================================
# ADMIN STATISTIKA
# =========================================================

def admin_stats_text():

    active_groups = sum(

        1

        for state
        in group_states.values()

        if state
    )

    stopped_groups = sum(

        1

        for state
        in group_states.values()

        if not state
    )

    return (

        "Aizo statistikasi\n\n"

        f"Saqlangan chatlar: "
        f"{len(user_chats)}\n"

        f"Saqlangan guruhlar: "
        f"{len(group_states)}\n"

        f"Faol guruhlar: "
        f"{active_groups}\n"

        f"To'xtatilgan guruhlar: "
        f"{stopped_groups}\n\n"

        f"Model: {MODEL_NAME}"
    )


# =========================================================
# ADMIN CALLBACKLAR
# =========================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("admin_")
)
def admin_callback(call):

    if (
        call.from_user.id
        != ADMIN_ID
    ):

        bot.answer_callback_query(

            call.id,

            "Bu panel faqat admin uchun.",

            show_alert=True
        )

        return

    action = call.data


    # -----------------------------------------------------
    # STATISTIKA
    # -----------------------------------------------------

    if action == "admin_stats":

        bot.answer_callback_query(
            call.id
        )

        try:

            bot.edit_message_text(

                admin_stats_text(),

                call.message.chat.id,

                call.message.message_id,

                reply_markup=admin_keyboard()
            )

        except Exception:

            bot.send_message(

                call.message.chat.id,

                admin_stats_text(),

                reply_markup=admin_keyboard()
            )


    # -----------------------------------------------------
    # ADMIN ID
    # -----------------------------------------------------

    elif action == "admin_id":

        bot.answer_callback_query(
            call.id
        )

        text = (
            "Aizo Admin ID\n\n"
            f"{ADMIN_ID}"
        )

        try:

            bot.edit_message_text(

                text,

                call.message.chat.id,

                call.message.message_id,

                reply_markup=admin_keyboard()
            )

        except Exception:

            bot.send_message(

                call.message.chat.id,

                text,

                reply_markup=admin_keyboard()
            )


    # -----------------------------------------------------
    # BARCHA XOTIRANI TOZALASH
    # -----------------------------------------------------

    elif action == "admin_clearall":

        with global_lock:

            count = len(
                user_chats
            )

            user_chats.clear()

            chat_locks.clear()

        bot.answer_callback_query(

            call.id,

            "Xotira tozalandi."
        )

        text = (

            "Barcha suhbat xotirasi "
            "tozalandi.\n\n"

            f"Tozalangan chatlar: {count}"
        )

        try:

            bot.edit_message_text(

                text,

                call.message.chat.id,

                call.message.message_id,

                reply_markup=admin_keyboard()
            )

        except Exception:

            bot.send_message(

                call.message.chat.id,

                text,

                reply_markup=admin_keyboard()
            )


    # -----------------------------------------------------
    # BROADCAST
    # -----------------------------------------------------

    elif action == "admin_broadcast":

        with broadcast_lock:

            broadcast_waiting.add(
                call.from_user.id
            )

        bot.answer_callback_query(
            call.id
        )

        text = (

            "Broadcast rejimi yoqildi.\n\n"

            "Endi yubormoqchi bo'lgan "
            "xabaringizni oddiy matn sifatida "
            "yuboring.\n\n"

            "Bekor qilish:\n"
            "/cancel_broadcast"
        )

        try:

            bot.edit_message_text(

                text,

                call.message.chat.id,

                call.message.message_id,

                reply_markup=admin_keyboard()
            )

        except Exception:

            bot.send_message(

                call.message.chat.id,

                text,

                reply_markup=admin_keyboard()
            )


    # -----------------------------------------------------
    # YOPISH
    # -----------------------------------------------------

    elif action == "admin_close":

        bot.answer_callback_query(
            call.id
        )

        try:

            bot.delete_message(

                call.message.chat.id,

                call.message.message_id
            )

        except Exception:

            pass


# =========================================================
# BROADCAST CANCEL
# =========================================================

@bot.message_handler(
    commands=["cancel_broadcast"]
)
def cancel_broadcast(message):

    if not is_admin(message):
        return

    with broadcast_lock:

        broadcast_waiting.discard(
            message.from_user.id
        )

    bot.send_message(

        message.chat.id,

        "Broadcast bekor qilindi."
    )


# ==========================================