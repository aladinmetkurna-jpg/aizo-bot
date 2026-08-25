import os
import json
import logging
import threading

import telebot
from openai import OpenAI


# =========================================================
# SOZLAMALAR
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Telegram User ID
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

MODEL_NAME = "deepseek-v4-flash"

MAX_TELEGRAM_LENGTH = 4096
MAX_HISTORY_MESSAGES = 40

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
        "ADMIN_ID topilmadi!"
    )


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

bot = telebot.TeleBot(
    TELEGRAM_TOKEN
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
# USER CHAT HISTORY
# =========================================================

user_chats = {}


# =========================================================
# LOCKLAR
# =========================================================

chat_locks = {}
global_lock = threading.Lock()

groups_lock = threading.Lock()


# =========================================================
# GURUHLARNI YUKLASH
# =========================================================

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
            "GROUPS FILE LOAD ERROR"
        )

    return {}


# =========================================================
# GURUHLARNI SAQLASH
# =========================================================

def save_groups():

    try:

        with groups_lock:

            with open(
                GROUPS_FILE,
                "w",
                encoding="utf-8"
            ) as file:

                json.dump(
                    group_states,
                    file,
                    ensure_ascii=False,
                    indent=2
                )

    except Exception:

        logger.exception(
            "GROUPS FILE SAVE ERROR"
        )


# =========================================================
# GROUP STATES
# =========================================================

group_states = load_groups()


# =========================================================
# USER LOCK
# =========================================================

def get_user_lock(user_id):

    with global_lock:

        if user_id not in chat_locks:

            chat_locks[user_id] = threading.Lock()

        return chat_locks[user_id]


# =========================================================
# ADMIN TEKSHIRISH
# =========================================================

def is_admin(message):

    return (
        message.from_user
        and message.from_user.id == ADMIN_ID
    )


# =========================================================
# GURUHMI?
# =========================================================

def is_group(message):

    return message.chat.type in [
        "group",
        "supergroup"
    ]


# =========================================================
# GURUH AI HOLATI
# =========================================================

def is_group_active(chat_id):

    chat_id = str(chat_id)

    return group_states.get(
        chat_id,
        True
    )


# =========================================================
# GURUH HOLATINI O'ZGARTIRISH
# =========================================================

def set_group_state(
    chat_id,
    active
):

    group_states[str(chat_id)] = active

    save_groups()


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

    recent_messages = messages[
        -MAX_HISTORY_MESSAGES:
    ]

    return [
        system_message,
        *recent_messages
    ]


# =========================================================
# MESSAGE SPLITTER
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
# LONG MESSAGE
# =========================================================

def send_long_message(
    chat_id,
    text
):

    for chunk in split_message(text):

        bot.send_message(
            chat_id,
            chunk
        )


# =========================================================
# START
# =========================================================

@bot.message_handler(
    commands=["start"]
)
def start(message):

    user_id = message.chat.id

    user_chats[user_id] = create_chat()

    bot.send_message(
        user_id,

        "Salom!\n\n"
        "Men Aizo — Shohruxning AI yordamchisiman.\n\n"
        "Savolingizni yozing, yordam beraman."
    )


# =========================================================
# CLEAR
# =========================================================

@bot.message_handler(
    commands=["clear"]
)
def clear(message):

    user_id = message.chat.id

    user_chats[user_id] = create_chat()

    bot.send_message(
        user_id,
        "Suhbat xotirasi tozalandi."
    )


# =========================================================
# HELP
# =========================================================

@bot.message_handler(
    commands=["help"]
)
def help_command(message):

    bot.send_message(
        message.chat.id,

        "Aizo yordam\n\n"

        "/start — yangi suhbat\n"
        "/clear — suhbatni tozalash\n"
        "/help — yordam\n\n"

        "Guruhda:\n"
        "Aizo, savol\n"
        "@AizoBot savol"
    )


# =========================================================
# ADMIN
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

    bot.send_message(
        message.chat.id,

        "Aizo Admin Panel\n\n"

        "/stats — statistika\n"
        "/broadcast MATN — barcha userlarga xabar\n"
        "/say MATN — o'zingizga xabar\n"
        "/clearall — barcha history'ni tozalash\n"
        "/adminid — admin ID\n\n"

        "Guruh boshqaruvi:\n"
        "/stop — Aizoni guruhda to'xtatish\n"
        "/start_ai — Aizoni guruhda yoqish\n"
        "/status_ai — Aizo holati"
    )


# =========================================================
# ADMIN ID
# =========================================================

@bot.message_handler(
    commands=["adminid"]
)
def admin_id_command(message):

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
# STATS
# =========================================================

@bot.message_handler(
    commands=["stats"]
)
def stats_command(message):

    if not is_admin(message):

        bot.send_message(
            message.chat.id,
            "Bu buyruq faqat admin uchun."
        )

        return

    active_groups = sum(
        1
        for state in group_states.values()
        if state
    )

    inactive_groups = sum(
        1
        for state in group_states.values()
        if not state
    )

    bot.send_message(
        message.chat.id,

        "Aizo statistikasi\n\n"

        f"Userlar: {len(user_chats)}\n"
        f"Guruhlar: {len(group_states)}\n"
        f"Faol guruhlar: {active_groups}\n"
        f"O'chirilgan guruhlar: {inactive_groups}\n\n"

        f"Model: {MODEL_NAME}"
    )


# =========================================================
# CLEAR ALL
# =========================================================

@bot.message_handler(
    commands=["clearall"]
)
def clear_all(message):

    if not is_admin(message):

        bot.send_message(
            message.chat.id,
            "Bu buyruq faqat admin uchun."
        )

        return

    count = len(user_chats)

    with global_lock:

        user_chats.clear()
        chat_locks.clear()

    bot.send_message(
        message.chat.id,

        "Barcha suhbat xotirasi tozalandi.\n\n"
        f"Userlar: {count}"
    )


# =========================================================
# SAY
# =========================================================

@bot.message_handler(
    commands=["say"]
)
def say_command(message):

    if not is_admin(message):

        bot.send_message(
            message.chat.id,
            "Bu buyruq faqat admin uchun."
        )

        return

    text = message.text.replace(
        "/say",
        "",
        1
    ).strip()

    if not text:

        bot.send_message(
            message.chat.id,
            "Foydalanish:\n/say Xabar"
        )

        return

    send_long_message(
        message.chat.id,
        text
    )


# =========================================================
# BROADCAST
# =========================================================

@bot.message_handler(
    commands=["broadcast"]
)
def broadcast_command(message):

    if not is_admin(message):

        bot.send_message(
            message.chat.id,
            "Bu buyruq faqat admin uchun."
        )

        return

    text = message.text.replace(
        "/broadcast",
        "",
        1
    ).strip()

    if not text:

        bot.send_message(
            message.chat.id,

            "Foydalanish:\n"
            "/broadcast Salom hammaga!"
        )

        return

    users = list(user_chats.keys())

    success = 0
    failed = 0

    bot.send_message(
        message.chat.id,
        f"Broadcast boshlandi.\n"
        f"Userlar: {len(users)}"
    )

    for user_id in users:

        try:

            send_long_message(
                user_id,
                text
            )

            success += 1

        except Exception:

            failed += 1

    bot.send_message(
        message.chat.id,

        "Broadcast tugadi.\n\n"
        f"Yuborildi: {success}\n"
        f"Xato: {failed}"
    )


# =========================================================
# STOP AI
# =========================================================

@bot.message_handler(
    commands=["stop"]
)
def stop_ai(message):

    if not is_group(message):

        bot.send_message(
            message.chat.id,
            "Bu buyruq faqat guruhlarda ishlaydi."
        )

        return

    if not is_admin(message):

        bot.reply_to(
            message,
            "Bu buyruq faqat bot admini uchun."
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

    logger.info(
        "GROUP STOP | group=%s",
        message.chat.id
    )


# =========================================================
# START AI
# =========================================================

@bot.message_handler(
    commands=["start_ai"]
)
def start_ai(message):

    if not is_group(message):

        bot.send_message(
            message.chat.id,
            "Bu buyruq faqat guruhlarda ishlaydi."
        )

        return

    if not is_admin(message):

        bot.reply_to(
            message,
            "Bu buyruq faqat bot admini uchun."
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

    logger.info(
        "GROUP START | group=%s",
        message.chat.id
    )


# =========================================================
# STATUS AI
# =========================================================

@bot.message_handler(
    commands=["status_ai"]
)
def status_ai(message):

    if not is_group(message):

        bot.send_message(
            message.chat.id,
            "Bu buyruq faqat guruhlarda ishlaydi."
        )

        return

    if is_group_active(message.chat.id):

        status = "ISHLAYAPTI"

    else:

        status = "TO'XTATILGAN"

    bot.send_message(
        message.chat.id,

        f"Aizo holati: {status}"
    )


# =========================================================
# TEXT XABARLAR
# =========================================================

@bot.message_handler(
    content_types=["text"]
)
def text_handler(message):

    user_id = message.chat.id
    text = message.text.strip()

    if not text:
        return

    # =====================================================
    # COMMANDLARNI O'TKAZIB YUBORISH
    # =====================================================

    if text.startswith("/"):
        return

    # =====================================================
    # GURUH
    # =====================================================

    if is_group(message):

        # Aizo o'chirilgan bo'lsa
        if not is_group_active(user_id):
            return

        # Bot username
        bot_username = ""

        try:

            me = bot.get_me()

            if me.username:
                bot_username = (
                    "@" + me.username.lower()
                )

        except Exception:
            pass

        text_lower = text.lower()

        # =================================================
        # GURUHDAGI MUROJAATNI TEKSHIRISH
        # =================================================

        mentioned = False

        if text_lower.startswith("aizo"):

            mentioned = True

        elif text_lower.startswith(
            "aizo,"
        ):

            mentioned = True

        elif bot_username and bot_username in text_lower:

            mentioned = True

        # Reply orqali murojaat
        if (
            message.reply_to_message
            and message.reply_to_message.from_user
            and message.reply_to_message.from_user.id
            == bot.get_me().id
        ):

            mentioned = True

        # Aizo'ga murojaat qilinmagan bo'lsa
        if not mentioned:
            return

        # "Aizo" qismini olib tashlash
        user_text = text

        if user_text.lower().startswith("aizo"):

            user_text = user_text[4:].strip()

            if user_text.startswith(","):
                user_text = user_text[1:].strip()

        # =================================================
        # @BOTUSERNAME NI OLIB TASHLASH
        # =================================================

        if bot_username:

            user_text = user_text.replace(
                bot_username,
                ""
            ).strip()

        if not user_text:

            bot.reply_to(
                message,
                "Ha, eshitaman."
            )

            return

    # =====================================================
    # PRIVATE CHAT
    # =====================================================

    else:

        user_text = text

    # =====================================================
    # CHAT YARATISH
    # =====================================================

    if user_id not in user_chats:

        user_chats[user_id] = create_chat()

    # =====================================================
    # LOCK
    # =====================================================

    lock = get_user_lock(user_id)

    with lock:

        try:

            bot.send_chat_action(
                user_id,
                "typing"
            )

            # =================================================
            # USER MESSAGE
            # =================================================

            user_chats[user_id].append(
                {
                    "role": "user",
                    "content": user_text
                }
            )

            user_chats[user_id] = limit_history(
                user_chats[user_id]
            )

            # =================================================
            # AI REQUEST
            # =================================================

            response = client.chat.completions.create(

                model=MODEL_NAME,

                messages=user_chats[user_id],

                stream=False,

                max_tokens=4096
            )

            # =================================================
            # RESPONSE
            # =================================================

            if not response.choices:

                raise RuntimeError(
                    "DeepSeek bo'sh choices qaytardi."
                )

            answer = response.choices[0].message.content

            if not answer:

                raise Runt