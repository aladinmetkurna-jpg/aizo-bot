import os
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

MODEL_NAME = "deepseek-v4-flash"

MAX_TELEGRAM_LENGTH = 4096
MAX_HISTORY_MESSAGES = 40

# Admin Telegram ID
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0


# =========================================================
# TEKSHIRISH
# =========================================================

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN topilmadi!")

if not DEEPSEEK_API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY topilmadi!")

if ADMIN_ID == 0:
    raise RuntimeError("ADMIN_ID topilmadi!")


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("Aizo")


# =========================================================
# OPENAI CLIENT
# =========================================================

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.b.ai/v1"
)


# =========================================================
# TELEGRAM BOT
# =========================================================

bot = telebot.TeleBot(
    TELEGRAM_TOKEN
)


# =========================================================
# PARALLEL WORKERS
# =========================================================

executor = ThreadPoolExecutor(
    max_workers=20
)


# =========================================================
# AIZO
# =========================================================

BOT_USERNAME = ""


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

Agar foydalanuvchi kod yuborsa va unda xato bo'lsa,
xatoni top, sababini tushuntir va tuzatilgan kodni ber.

Foydalanuvchining oldingi xabarlarini suhbat kontekstida hisobga ol.

Keraksiz uzun javoblar bermagin.

Foydalanuvchiga hurmat bilan murojaat qil.

O'zingni Shohrux deb ko'rsatma.

Sen Aizo — Shohruxning AI yordamchisisan.
"""


# =========================================================
# HISTORY
# =========================================================

# session_key:
# private -> ("private", user_id)
# group   -> ("group", chat_id, user_id)
#
# Shu sababli guruhdagi ikki odamning suhbatlari
# bir-biriga aralashmaydi.

user_chats = {}

chat_locks = {}

global_lock = threading.Lock()


# Aizoning guruhdagi yuborgan xabarlari:
# bot_message_id -> session_key
reply_sessions = {}


# Guruhlarning ON/OFF holati
group_states = {}


# =========================================================
# LOCK
# =========================================================

def get_lock(session_key):

    with global_lock:

        if session_key not in chat_locks:
            chat_locks[session_key] = threading.Lock()

        return chat_locks[session_key]


# =========================================================
# SESSION KEY
# =========================================================

def get_session_key(message):

    user_id = message.from_user.id

    if message.chat.type in (
        "group",
        "supergroup"
    ):
        return (
            "group",
            message.chat.id,
            user_id
        )

    return (
        "private",
        user_id
    )


# =========================================================
# CREATE CHAT
# =========================================================

def create_chat():

    return [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]


def get_chat(session_key):

    with global_lock:

        if session_key not in user_chats:

            user_chats[session_key] = create_chat()

        return user_chats[session_key]


# =========================================================
# HISTORY LIMIT
# =========================================================

def limit_history(messages):

    if len(messages) <= MAX_HISTORY_MESSAGES + 1:
        return messages

    return [
        messages[0],
        *messages[-MAX_HISTORY_MESSAGES:]
    ]


# =========================================================
# SPLIT MESSAGE
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

        chunk = text[:cut].strip()

        if chunk:
            chunks.append(chunk)

        text = text[cut:].strip()

    if text:
        chunks.append(text)

    return chunks


# =========================================================
# SEND MESSAGE
# =========================================================

def send_long_message(
    chat_id,
    text,
    reply_to=None
):

    chunks = split_message(text)

    sent_messages = []

    for index, chunk in enumerate(chunks):

        try:

            msg = bot.send_message(
                chat_id,
                chunk,
                reply_to_message_id=(
                    reply_to
                    if index == 0
                    else None
                )
            )

            sent_messages.append(msg)

        except Exception:

            logger.exception(
                "SEND ERROR | chat=%s",
                chat_id
            )

    return sent_messages


# =========================================================
# GROUP STATE
# =========================================================

def is_group_active(chat_id):

    return group_states.get(
        chat_id,
        True
    )


# =========================================================
# ADMIN
# =========================================================

def is_admin(message):

    return (
        message.from_user
        and message.from_user.id == ADMIN_ID
    )


# =========================================================
# GROUP MESSAGE CHECK
# =========================================================

def starts_with_aizo(text):

    if not text:
        return False

    text = text.strip().lower()

    prefixes = (
        "aizo",
        "aizo ",
        "aizo,",
        "aizo:",
        "aizo!",
        "aizo?",
        "aizo -",
        "aizo —"
    )

    return text.startswith(prefixes)


def has_bot_mention(text):

    if not text:
        return False

    if not BOT_USERNAME:
        return False

    return (
        f"@{BOT_USERNAME.lower()}"
        in text.lower()
    )


def is_reply_to_aizo(message):

    reply = message.reply_to_message

    if not reply:
        return False

    if not reply.from_user:
        return False

    try:

        me = bot.get_me()

        return (
            reply.from_user.id == me.id
        )

    except Exception:

        return False


def should_answer_group(message):

    if not is_group_active(
        message.chat.id
    ):
        return False

    text = message.text or ""

    # Aizo deb chaqirilgan
    if starts_with_aizo(text):
        return True

    # @BotUsername
    if has_bot_mention(text):
        return True

    # Aizoning javobiga reply
    if is_reply_to_aizo(message):
        return True

    return False


# =========================================================
# GROUP TEXT CLEAN
# =========================================================

def clean_group_text(text):

    text = text.strip()

    # Bot mentionini olib tashlash
    if BOT_USERNAME:

        text = text.replace(
            f"@{BOT_USERNAME}",
            ""
        )

        text = text.replace(
            f"@{BOT_USERNAME.lower()}",
            ""
        )

    lower = text.lower()

    prefixes = [
        "aizo,",
        "aizo:",
        "aizo!",
        "aizo?",
        "aizo -",
        "aizo —",
        "aizo"
    ]

    for prefix in prefixes:

        if lower.startswith(prefix):

            text = text[
                len(prefix):
            ].strip()

            break

    return text.strip()


# =========================================================
# ERROR TEXT
# =========================================================

def get_error_text(error):

    text = str(error).lower()

    if (
        "429" in text
        or "quota" in text
        or "rate limit" in text
        or "too many requests" in text
    ):

        return (
            "AI API limitiga yetildi.\n"
            "Birozdan keyin qayta urinib ko'ring."
        )

    if (
        "401" in text
        or "api key" in text
        or "authentication" in text
        or "unauthorized" in text
        or "invalid_api_key" in text
    ):

        return (
            "DEEPSEEK_API_KEY bilan muammo bor.\n"
            "Railway Variables'ni tekshiring."
        )

    if (
        "model" in text
        and (
            "not found" in text
            or "does not exist" in text
            or "invalid" in text
        )
    ):

        return (
            "AI modeli topilmadi.\n"
            f"Model: {MODEL_NAME}"
        )

    if (
        "timeout" in text
        or "connection" in text
        or "network" in text
    ):

        return (
            "AI serveriga ulanishda muammo yuz berdi.\n"
            "Birozdan keyin qayta urinib ko'ring."
        )

    if (
        "500" in text
        or "502" in text
        or "503" in text
    ):

        return (
            "AI serverida vaqtinchalik muammo.\n"
            "Birozdan keyin qayta urinib ko'ring."
        )

    return (
        "Kutilmagan xatolik yuz berdi.\n"
        "Birozdan keyin qayta urinib ko'ring."
    )


# =========================================================
# AI PROCESS
# =========================================================

def process_ai(
    message,
    user_text,
    session_key,
    reply_to=None
):

    lock = get_lock(
        session_key
    )

    with lock:

        try:

            # Typing
            try:

                bot.send_chat_action(
                    message.chat.id,
                    "typing"
                )

            except Exception:
                pass

            # -------------------------------------------------
            # USER MESSAGE
            # -------------------------------------------------

            with global_lock:

                chat = get_chat(
                    session_key
                )

                chat.append(
                    {
                        "role": "user",
                        "content": user_text
                    }
                )

                chat[:] = limit_history(
                    chat
                )

                request_messages = list(
                    chat
                )

            # -------------------------------------------------
            # DEEPSEEK
            # -------------------------------------------------

            response = client.chat.completions.create(

                model=MODEL_NAME,

                messages=request_messages,

                stream=False,

                max_tokens=4096
            )

            if not response.choices:

                raise RuntimeError(
                    "AI bo'sh javob qaytardi."
                )

            answer = (
                response
                .choices[0]
                .message
                .content
            )

            if not answer:

                raise RuntimeError(
                    "AI bo'sh javob qaytardi."
                )

            # -------------------------------------------------
            # ASSISTANT HISTORY
            # -------------------------------------------------

            with global_lock:

                chat = get_chat(
                    session_key
                )

                chat.append(
                    {
                        "role": "assistant",
                        "content": answer
                    }
                )

                chat[:] = limit_history(
                    chat
                )

            # -------------------------------------------------
            # GROUP
            # -------------------------------------------------

            if message.chat.type in (
                "group",
                "supergroup"
            ):

                sent = send_long_message(
                    message.chat.id,
                    answer,
                    reply_to=message.message_id
                )

                # Aizoning birinchi xabarini
                # session bilan bog'lab qo'yamiz.
                #
                # Keyingi odam shu xabarga Reply qilsa,
                # aynan shu suhbat davom etadi.

                for sent_message in sent:

                    reply_sessions[
                        sent_message.message_id
                    ] = session_key

            # -------------------------------------------------
            # PRIVATE
            # -------------------------------------------------

            else:

                send_long_message(
                    message.chat.id,
                    answer
                )

            logger.info(
                "AI OK | chat=%s | user=%s",
                message.chat.id,
                message.from_user.id
            )

        except Exception as error:

            logger.exception(
                "AI ERROR"
            )

            # Xato bo'lsa user xabarini olib tashlash
            with global_lock:

                chat = user_chats.get(
                    session_key
                )

                if (
                    chat
                    and len(chat) > 1
                    and chat[-1].get("role") == "user"
                    and chat[-1].get("content") == user_text
                ):

                    chat.pop()

            bot.send_message(
                message.chat.id,
                get_error_text(error)
            )


# =========================================================
# /START
# =========================================================

@bot.message_handler(
    commands=["start"]
)
def start_command(message):

    session_key = get_session_key(
        message
    )

    with global_lock:

        user_chats[
            session_key
        ] = create_chat()

    bot.send_message(
        message.chat.id,
        "Salom!\n\n"
        "Men Aizo — Shohruxning AI yordamchisiman.\n\n"
        "Savolingizni yozing."
    )


# =========================================================
# /CLEAR
# =========================================================

@bot.message_handler(
    commands=["clear"]
)
def clear_command(message):

    session_key = get_session_key(
        message
    )

    with global_lock:

        user_chats[
            session_key
        ] = create_chat()

    bot.send_message(
        message.chat.id,
        "Suhbat xotirasi tozalandi."
    )


# =========================================================
# /HELP
# =========================================================

@bot.message_handler(
    commands=["help"]
)
def help_command(message):

    if message.chat.type in (
        "group",
        "supergroup"
    ):

        text = (
            "Aizo guruh yordam\n\n"
            "Aizo, savolingiz\n"
            "@bot_username savolingiz\n"
            "yoki Aizoning xabariga Reply qiling.\n\n"
            "/stop — Aizoni to'xtatish\n"
            "/start_ai — Aizoni yoqish\n"
            "/clear — suhbatni tozalash"
        )

    else:

        text = (
            "Aizo yordam\n\n"
            "/start — yangi suhbat\n"
            "/clear — suhbatni tozalash\n"
            "/help — yordam"
        )

    bot.send_message(
        message.chat.id,
        text
    )


# =========================================================
# /STOP
# =========================================================

@bot.message_handler(
    commands=["stop"]
)
def stop_command(message):

    if message.chat.type not in (
        "group",
        "supergroup"
    ):

        bot.send_message(
            message.chat.id,
            "/stop faqat guruhda ishlaydi."
        )

        return

    if not is_admin(message):

        bot.reply_to(
            message,
            "Bu buyruq faqat admin uchun."
        )

        return

    group_states[
        message.chat.id
    ] = False

    bot.send_message(
        message.chat.id,
        "Aizo ushbu guruhda to'xtatildi."
    )


# =========================================================
# /START_AI
# =========================================================

@bot.message_handler(
    commands=["start_ai"]
)
def start_ai_command(message):

    if message.chat.type not in (
        "group",
        "supergroup"
    ):

        bot.send_message(
            message.chat.id,
            "/start_ai faqat guruhda ishlaydi."
        )

        return

    if not is_admin(message):

        bot.reply_to(
            message,
            "Bu buyruq faqat admin uchun."
        )

        return

    group_states[
        message.chat.id
    ] = True

    bot.send_message(
        message.chat.id,
        "Aizo yana ishga tushdi."
    )


# =========================================================
# ADMIN KEYBOARD
# =========================================================

def admin_keyboard():

    keyboard = types.InlineKeyboardMarkup(
        row_width=2
    )

    keyboard.add(

        types.InlineKeyboardButton(
            "Statistika",
            callback_data="stats"
        ),

        types.InlineKeyboardButton(
            "History tozalash",
            callback_data="clear_history"
        )
    )

    keyboard.add(

        types.InlineKeyboardButton(
            "Barcha guruhlarni ON",
            callback_data="groups_on"
        ),

        types.InlineKeyboardButton(
            "Barcha guruhlarni OFF",
            callback_data="groups_off"
        )
    )

    keyboard.add(

        types.InlineKeyboardButton(
            "Admin ID",
            callback_data="admin_id"
        ),

        types.InlineKeyboardButton(
            "Yopish",
            callback_data="close"
        )
    )

    return keyboard


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
            "Bu panel faqat admin uchun."
        )

        return

    bot.send_message(

        message.chat.id,

        "AIZO ADMIN PANEL\n\n"
        "Kerakli funksiyani tanlang:",

        reply_markup=admin_keyboard()
    )


# =========================================================
# ADMIN CALLBACK
# ====================================