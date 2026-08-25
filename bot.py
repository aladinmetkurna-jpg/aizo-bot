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

# Bir vaqtda nechta turli user ishlashi mumkin
MAX_WORKERS = 20

# Juda tez-tez yuborilgan bir xil user xabarlarini cheklash
FLOOD_SECONDS = 0.5

GROUPS_FILE = "groups.json"
MEMORIES_FILE = "memories.json"


# =========================================================
# TEKSHIRISH
# =========================================================

if not TELEGRAM_TOKEN:
    raise RuntimeError(
        "TELEGRAM_TOKEN topilmadi!"
    )

if not DEEPSEEK_API_KEY:
    raise RuntimeError(
        "DEEPSEEK_API_KEY topilmadi!"
    )

if ADMIN_ID <= 0:
    raise RuntimeError(
        "ADMIN_ID topilmadi yoki noto'g'ri!"
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
# DEEPSEEK / B.AI
# =========================================================

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.b.ai/v1"
)


# =========================================================
# TELEGRAM
# =========================================================

bot = telebot.TeleBot(
    TELEGRAM_TOKEN,
    parse_mode=None
)


# =========================================================
# THREAD POOL
# =========================================================

executor = ThreadPoolExecutor(
    max_workers=MAX_WORKERS
)


# =========================================================
# GLOBAL DATA
# =========================================================

user_chats = {}
user_locks = {}

group_states = {}
memories = {}

last_message_time = {}

bot_username = ""


# =========================================================
# LOCKLAR
# =========================================================

global_lock = threading.RLock()
user_locks_lock = threading.Lock()
file_lock = threading.Lock()


def get_user_lock(user_id):
    """
    Har bir Telegram user uchun alohida lock.
    """

    with user_locks_lock:

        if user_id not in user_locks:

            user_locks[user_id] = threading.Lock()

        return user_locks[user_id]


# =========================================================
# JSON
# =========================================================

def load_json(filename, default):

    if not os.path.exists(filename):
        return default

    try:

        with open(
            filename,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, type(default)):
            return data

        return default

    except Exception:

        logger.exception(
            "JSON LOAD ERROR: %s",
            filename
        )

        return default


def save_json(filename, data):

    try:

        with file_lock:

            temp_file = filename + ".tmp"

            with open(
                temp_file,
                "w",
                encoding="utf-8"
            ) as file:

                json.dump(
                    data,
                    file,
                    ensure_ascii=False,
                    indent=2
                )

            os.replace(
                temp_file,
                filename
            )

    except Exception:

        logger.exception(
            "JSON SAVE ERROR: %s",
            filename
        )


# =========================================================
# DATA
# =========================================================

group_states = load_json(
    GROUPS_FILE,
    {}
)

memories = load_json(
    MEMORIES_FILE,
    {}
)


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
shu tilda javob ber.

Javoblaring tabiiy, tushunarli va foydali bo'lsin.

Texnik savollarga aniq va amaliy javob ber.

Kod so'ralsa, imkon qadar to'liq va ishlaydigan kod ber.

Agar foydalanuvchi kod yuborsa:
- xatoni top;
- sababini tushuntir;
- tuzatilgan kodni ber.

Keraksiz uzun javob bermagin.

Foydalanuvchiga hurmat bilan murojaat qil.

O'zingni Shohrux deb ko'rsatma.

Sen Aizo — Shohruxning AI yordamchisisan.
"""


# =========================================================
# CHAT
# =========================================================

def create_chat(user_id):

    system_prompt = SYSTEM_PROMPT

    memory = memories.get(
        str(user_id),
        ""
    )

    if memory:

        system_prompt += (
            "\n\nFoydalanuvchi haqida saqlangan "
            "xotira:\n"
            + memory
        )

    return [
        {
            "role": "system",
            "content": system_prompt
        }
    ]


def get_chat(user_id):

    with global_lock:

        if user_id not in user_chats:

            user_chats[user_id] = create_chat(
                user_id
            )

        return user_chats[user_id]


def clear_chat(user_id):

    lock = get_user_lock(
        user_id
    )

    with lock:

        with global_lock:

            user_chats[user_id] = create_chat(
                user_id
            )


def limit_history(messages):

    if len(messages) <= MAX_HISTORY_MESSAGES + 1:

        return messages

    return [
        messages[0],
        *messages[-MAX_HISTORY_MESSAGES:]
    ]


# =========================================================
# GROUP STATE
# =========================================================

def is_group(message):

    return message.chat.type in (
        "group",
        "supergroup"
    )


def is_group_active(chat_id):

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

    save_json(
        GROUPS_FILE,
        group_states
    )


# =========================================================
# ADMIN
# =========================================================

def is_admin(message):

    return (
        message.from_user is not None
        and message.from_user.id == ADMIN_ID
    )


# =========================================================
# USER NAME
# =========================================================

def get_user_name(message):

    user = message.from_user

    if user is None:
        return "Foydalanuvchi"

    if user.username:
        return "@" + user.username

    name = (
        f"{user.first_name or ''} "
        f"{user.last_name or ''}"
    ).strip()

    return name or "Foydalanuvchi"


# =========================================================
# TELEGRAM LENGTH
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


def send_long_message(
    chat_id,
    text,
    reply_to_message_id=None
):

    chunks = split_message(text)

    for index, chunk in enumerate(chunks):

        try:

            bot.send_message(
                chat_id,
                chunk,
                reply_to_message_id=(
                    reply_to_message_id
                    if index == 0
                    else None
                )
            )

        except Exception:

            logger.exception(
                "SEND MESSAGE ERROR | chat=%s",
                chat_id
            )


# =========================================================
# GROUP AIZO CHAQRIG'INI TEKSHIRISH
# =========================================================

def remove_bot_mention(text):

    if not text:
        return text

    result = text

    # @AizoBot ni olib tashlash
    if bot_username:

        mention = "@" + bot_username

        result = result.replace(
            mention,
            ""
        )

    return result.strip()


def starts_with_aizo(text):

    if not text:
        return False

    clean = text.strip()

    lower = clean.lower()

    names = [
        "aizo",
        "aizo,",
        "aizo:",
        "aizo!",
        "aizo?",
        "aizo -",
        "aizo —"
    ]

    for name in names:

        if lower.startswith(name):

            return True

    return False


def is_reply_to_aizo(message):

    reply = message.reply_to_message

    if not reply:
        return False

    # Aizoning xabari ekanini aniqlash
    if (
        reply.from_user
        and reply.from_user.id == bot.get_me().id
    ):

        return True

    return False


def should_aizo_answer(message):

    # Private chat
    if not is_group(message):

        return True

    # Guruh o'chirilgan bo'lsa
    if not is_group_active(
        message.chat.id
    ):

        return False

    text = message.text or ""

    # Aizo deb chaqirish
    if starts_with_aizo(text):

        return True

    # @BotUsername
    if (
        bot_username
        and f"@{bot_username.lower()}" in text.lower()
    ):

        return True

    # Aizoning xabariga reply
    if is_reply_to_aizo(message):

        return True

    return False


# =========================================================
# TOZALANGAN GROUP TEXT
# =========================================================

def clean_group_text(text):

    if not text:
        return ""

    result = text.strip()

    # @BotUsername ni olib tashlash
    if bot_username:

        result = result.replace(
            "@" + bot_username,
            ""
        )

        result = result.replace(
            "@" + bot_username.lower(),
            ""
        )

    # Boshidagi Aizo ni olib tashlash
    prefixes = [
        "aizo,",
        "aizo:",
        "aizo!",
        "aizo?",
        "aizo -",
        "aizo —",
        "aizo"
    ]

    lower = result.lower()

    for prefix in prefixes:

        if lower.startswith(prefix):

            result = result[
                len(prefix):
            ].strip()

            break

    return result.strip()


# =========================================================
# ERROR MESSAGE
# =========================================================

def get_error_message(error):

    text = str(error).lower()

    if (
        "429" in text
        or "quota" in text
        or "rate limit" in text
        or "too many requests" in text
    ):

        return (
            "AI API limitiga yetildi. "
            "Birozdan keyin qayta urinib ko'ring."
        )

    if (
        "401" in text
        or "api key" in text
        or "unauthorized" in text
        or "authentication" in text
        or "invalid_api_key" in text
    ):

        return (
            "DEEPSEEK_API_KEY bilan muammo bor. "
            "Railway Variables'dagi API keyni tekshiring."
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
            "AI modelida muammo yuz berdi.\n"
            f"Model: {MODEL_NAME}"
        )

    if (
        "timeout" in text
        or "connection" in text
        or "network" in text
    ):

        return (
            "AI serveriga ulanishda muammo yuz berdi. "
            "Birozdan keyin qayta urinib ko'ring."
        )

    if (
        "500" in text
        or "502" in text
        or "503" in text
        or "server error" in text
    ):

        return (
            "AI serverida vaqtinchalik muammo yuz berdi. "
            "Birozdan keyin qayta urinib ko'ring."
        )

    return (
        "Kutilmagan xatolik yuz berdi. "
        "Birozdan keyin qayta urinib ko'ring."
    )


# =========================================================
# AI WORKER
# =========================================================

def process_ai_message(
    message,
    user_text
):

    user_id = message.from_user.id
    chat_id = message.chat.id

    lock = get_user_lock(
        user_id
    )

    # -----------------------------------------------------
    # MUHIM:
    #
    # Har bir user o'z lock'iga ega.
    #
    # Ali -> Ali lock
    # Vali -> Vali lock
    #
    # Shuning uchun Ali Vali'ni kutmaydi.
    #
    # Lekin Ali 2 ta xabar yuborsa,
    # ular history ichida aralashmaydi.
    # -----------------------------------------------------

    with lock:

        try:

            # Typing
            try:

                bot.send_chat_action(
                    chat_id,
                    "typing"
                )

            except Exception:
                pass

            # -------------------------------------------------
            # HISTORY'DAN REQUEST SNAPSHOT
            # -------------------------------------------------

            with global_lock:

                chat = get_chat(
                    user_id
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

            response = (
                client
                .chat
                .completions
                .create(
                    model=MODEL_NAME,
                    messages=request_messages,
                    stream=False,
                    max_tokens=4096
                )
            )

            if not response.choices:

                raise RuntimeError(
                    "AI bo'sh choices qaytardi."
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
                    user_id
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
            # TELEGRAM
            # -------------------------------------------------

            if is_group(message):

                username = get_user_name(
                    message
                )

                final_answer = (
                    f"{username}\n\n"
                    f"Aizo:\n{answer}"
                )

                # Javobni user xabariga reply qilib yuborish
                send_long_message(
                    chat_id,
                    final_answer,
                    message.message_id
                )

            else:

                send_long_message(
                    chat_id,
                    answer
                )

            logger.info(
                "AI OK | user=%s | chat=%s",
                user_id,
                chat_id
            )

        except Exception as error:

            logger.exception(
                "AI ERROR | user=%s",
                user_id
            )

            # -------------------------------------------------
            # XATO BO'LSA USER XABARINI HISTORY'DAN O'CHIRAMIZ
            # -------------------------------------------------

            with global_lock:

                chat = user_chats.get(
                    user_id
                )

                if (
                    chat
                    and len(chat) > 1
                    and chat[-1].get("role") == "user"
                    and chat[-1].get("content") == user_text
                ):

                    chat.pop()

            bot.send_message(
                chat_id,
                get_error_message(error)
            )


# =========================================================
# /START
# =========================================================

@bot.message_handler(
    commands=["start"]
)
def start_command(message):

    clear_chat(
        message.from_user.id
    )

    if is_group(message):

        bot.send_message(

            message.chat.id,

            "Aizo ishga tushdi.\n\n"
            "Guruhda menga `Aizo` deb murojaat "
            "qiling yoki Aizoning xabariga Reply qiling.\n\n"
            "/stop — to'xtatish\n"
            "/start_ai — qayta yoqish"
        )

    else:

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

    clear_chat(
        message.from_user.id
    )

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

    bot.send_message(

        message.chat.id,

        "Aizo yordam\n\n"

        "Private chatda oddiy yozishingiz mumkin.\n\n"

        "Guruhda:\n"
        "Aizo, savolim bor\n"
        "@bot_username savolim bor\n"
        "yoki Aizoning xabariga Reply qiling.\n\n"

        "/clear — suhbatni tozalash\n"
        "/stop — guruhda Aizoni to'xtatish\n"
        "/start_ai — guruhda Aizoni yoqish\n"
        "/status_ai — holatini ko'rish\n"
        "/admin — admin panel"
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
            "/stop faqat guruhda ishlaydi."
        )

   