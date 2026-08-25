import os
import logging
import threading

import telebot
from openai import OpenAI


# =========================================================
# SOZLAMALAR
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Telegram'dagi o'zingning User ID'ing
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

MODEL_NAME = "deepseek-v4-flash"

MAX_TELEGRAM_LENGTH = 4096

# Har bir user uchun saqlanadigan xabarlar soni
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
        "ADMIN_ID topilmadi! Railway Variables'ga ADMIN_ID qo'shing."
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
# ADMIN TEKSHIRISH
# =========================================================

def is_admin(message):

    return (
        message.from_user
        and message.from_user.id == ADMIN_ID
    )


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
# TELEGRAM XABARINI BO'LISH
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
# UZUN XABAR YUBORISH
# =========================================================

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
# /START
# =========================================================

@bot.message_handler(
    commands=["start"]
)
def start(message):

    user_id = message.chat.id

    try:

        user_chats[user_id] = create_chat()

        bot.send_message(
            user_id,

            "Salom!\n\n"
            "Men Aizo — Shohruxning AI yordamchisiman.\n\n"
            "Savolingizni yozing, yordam beraman."
        )

        logger.info(
            "START | user=%s",
            user_id
        )

    except Exception:

        logger.exception(
            "START ERROR | user=%s",
            user_id
        )

        bot.send_message(
            user_id,
            "Botni ishga tushirishda xatolik yuz berdi."
        )


# =========================================================
# /CLEAR
# =========================================================

@bot.message_handler(
    commands=["clear"]
)
def clear(message):

    user_id = message.chat.id

    try:

        user_chats[user_id] = create_chat()

        bot.send_message(
            user_id,
            "Suhbat xotirasi tozalandi."
        )

        logger.info(
            "CLEAR | user=%s",
            user_id
        )

    except Exception:

        logger.exception(
            "CLEAR ERROR | user=%s",
            user_id
        )

        bot.send_message(
            user_id,
            "Suhbatni tozalashda xatolik yuz berdi."
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
        "/start — yangi suhbatni boshlash\n"
        "/clear — suhbat xotirasini tozalash\n"
        "/help — yordam\n\n"
        "Oddiy savolingizni yozishingiz mumkin."
    )


# =========================================================
# ADMIN /ADMIN
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

        "/stats — bot statistikasi\n"
        "/broadcast MATN — barcha userlarga xabar\n"
        "/say MATN — bot nomidan xabar\n"
        "/clearall — barcha suhbat xotirasini tozalash\n"
        "/adminid — admin ID ni ko'rsatish\n"
    )


# =========================================================
# /ADMINID
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
# /STATS
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

    total_users = len(user_chats)

    bot.send_message(
        message.chat.id,

        "Aizo statistikasi\n\n"
        f"Foydalanuvchilar: {total_users}\n"
        f"Model: {MODEL_NAME}\n"
        f"History limit: {MAX_HISTORY_MESSAGES}"
    )


# =========================================================
# /CLEARALL
# =========================================================

@bot.message_handler(
    commands=["clearall"]
)
def clear_all_command(message):

    if not is_admin(message):

        bot.send_message(
            message.chat.id,
            "Bu buyruq faqat admin uchun."
        )

        return

    with global_lock:

        count = len(user_chats)

        user_chats.clear()

        chat_locks.clear()

    bot.send_message(
        message.chat.id,

        "Barcha suhbat xotirasi tozalandi.\n\n"
        f"Tozalangan userlar: {count}"
    )

    logger.info(
        "CLEARALL | admin=%s | users=%s",
        ADMIN_ID,
        count
    )


# =========================================================
# /SAY
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
# /BROADCAST
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

            "Foydalanish:\n\n"
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

            logger.exception(
                "BROADCAST ERROR | user=%s",
                user_id
            )

    bot.send_message(
        message.chat.id,

        "Broadcast tugadi.\n\n"
        f"Yuborildi: {success}\n"
        f"Xato: {failed}"
    )

    logger.info(
        "BROADCAST | success=%s | failed=%s",
        success,
        failed
    )


# =========================================================
# ODDIY TEXT XABARLAR
# =========================================================

@bot.message_handler(
    content_types=["text"],
    func=lambda message: (
        message.text
        and not message.text.startswith("/")
    )
)
def reply(message):

    user_id = message.chat.id

    user_text = message.text.strip()

    if not user_text:
        return

    # =====================================================
    # CHAT MAVJUDLIGINI TEKSHIRISH
    # =====================================================

    if user_id not in user_chats:

        user_chats[user_id] = create_chat()

    # =====================================================
    # USER LOCK
    # =====================================================

    lock = get_user_lock(user_id)

    with lock:

        try:

            # typing...
            bot.send_chat_action(
                user_id,
                "typing"
            )

            # =================================================
            # USER XABARINI HISTORY'GA QO'SHISH
            # =================================================

            user_chats[user_id].append(
                {
                    "role": "user",
                    "content": user_text
                }
            )

            # =================================================
            # HISTORY LIMIT
            # =================================================

            user_chats[user_id] = limit_history(
                user_chats[user_id]
            )

            # =================================================
            # DEEPSEEK REQUEST
            # =================================================

            response = client.chat.completions.create(

                model=MODEL_NAME,

                messages=user_chats[user_id],

                stream=False,

                max_tokens=4096
            )

            # =================================================
            # RESPONSE TEKSHIRISH
            # =================================================

            if not response.choices:

                raise RuntimeError(
                    "DeepSeek bo'sh choices qaytardi."
                )

            answer = response.choices[0].message.content

            if not answer:

                raise RuntimeError(
                    "DeepSeek bo'sh javob qaytardi."
                )

            # =================================================
            # ASSISTANT HISTORY
            # =================================================

            user_chats[user_id].append(
                {
                    "role": "assistant",
                    "content": answer
                }
            )

            # =================================================
            # TELEGRAMGA YUBORISH
            # =================================================

            send_long_message(
                user_id,
                answer
            )

            logger.info(
                "MESSAGE OK | user=%s",
                user_id
            )

        except Exception as e:

            logger.exception(
                "DEEPSEEK ERROR | user=%s",
                user_id
            )

            # =================================================
            # XATO BO'LSA USER XABARINI OLIB TASHLASH
            # =================================================

            if (
                user_chats.get(user_id)
                and user_chats[user_id][-1].get("role") == "user"
            ):

                user_chats[user_id].pop()

            error_text = str(e).lower()

            # =================================================
            # RATE LIMIT
            # =================================================

            if (
                "429" in error_text
                or "rate limit" in error_text
                or "too many requests" in error_text
                or "quota" in error_text
            ):

                user_message = (
                    "Hozircha DeepSeek API limitiga yetildi.\n"
                    "Birozdan keyin qayta urinib ko'ring."
                )

            # =================================================
            # API KEY
            # =================================================

            elif (
                "401" in error_text
                or "api key" in error_text
                or "authentication" in error_text
                or "unauthorized" in error_text
                or "invalid_api_key" in error_text
            ):

                user_message = (
                    "DeepSeek API key bilan muammo bor.\n\n"
                    "Railway Variables'dagi "
                    "DEEPSEEK_API_KEY ni tekshiring."
                )

            # =================================================
            # MODEL
            # =================================================

            elif (
                "model" in error_text
                and (
                    "not found" in error_text
                    or "does not exist" in error_text
                    or "invalid" in error_text
                )
            ):

                user_message = (
                    "DeepSeek modelida muammo yuz berdi.\n"
                    "MODEL_NAME sozlamasini tekshiring."
                )

            # =================================================
            # SERVER
            # =================================================

            elif (
                "500" in error_text
                or "502" in error_text
                or "503" in error_text
                or "server error" in error_text
            ):

                user_message = (
                    "DeepSeek serverida vaqtinchalik "
                    "muammo yuz berdi.\n"
                    "Birozdan keyin qayta urinib ko'ring."
                )

            # =================================================
            # NETWORK
            # =================================================

            elif (
                "connection" in error_text
                or "timeout" in error_text
                or "network" in error_text
            ):

                user_message = (
                    "DeepSeek serveriga ulanishda muammo yuz berdi.\n"
                    "Birozdan keyin qayta urinib ko'ring."
                )

            # =================================================
            # BOSHQA XATO
            # =================================================

            else:

                user_message = (
                    "Kutilmagan xatolik yuz berdi.\n"
                    "Birozdan keyin qayta urinib ko'ring."
                )

            bot.send_message(
                user_id,
                user_message
            )


# =========================================================
# MEDIA XABARLAR
# =========================================================

@bot.message_handler(
    content_types=[
        "photo",
        "video",
        "audio",
        "document",
        "sticker",
        "voice",
        "animation",
        "contact",
        "location"
    ]
)
def unsupported_message(message):

    bot.send_message(
        message.chat.id,

        "Hozircha men faqat matnli "
        "xabarlar bilan ishlayman."
    )


# =========================================================
# BOTNI ISHGA TUSHIRISH
# =========================================================

if __name__ == "__main__":

    logger.info(
        "Aizo — Shohruxning AI yordamchisi ishga tushmoqda..."
    )

    logger.info(
        "ADMIN_ID: %s",
        ADMIN_ID
    )

    try:

        bot.infinity_polling(
            timeout=30,
            long_polling_timeout=20
        )

    except KeyboardInterrupt:

        logger.info(
            "Aizo to'xtatildi."
        )

    except Exception:

        logger.exception(
            "BOT CRITICAL ERROR"
        )