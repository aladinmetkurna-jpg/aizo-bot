import os
import logging
import threading

import telebot
from google import genai
from google.genai import types


# =========================================================
# SOZLAMALAR
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Gemini modeling
MODEL_NAME = "gemini-2.0"

# Telegram maksimal xabar hajmi
MAX_TELEGRAM_LENGTH = 4096


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("Aizo")


# =========================================================
# API KEY TEKSHIRISH
# =========================================================

if not TELEGRAM_TOKEN:
    raise RuntimeError(
        "TELEGRAM_TOKEN topilmadi!"
    )

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY topilmadi!"
    )


# =========================================================
# GEMINI CLIENT
# =========================================================

client = genai.Client(
    api_key=GEMINI_API_KEY
)


# =========================================================
# TELEGRAM BOT
# =========================================================

bot = telebot.TeleBot(
    TELEGRAM_TOKEN,
    parse_mode="HTML"
)


# =========================================================
# USER CHAT XOTIRASI
# =========================================================

user_chats = {}

# Har bir user uchun alohida lock
chat_locks = {}

# Global lock
global_lock = threading.Lock()


# =========================================================
# USER LOCK
# =========================================================

def get_user_lock(user_id):
    """
    Har bir foydalanuvchi uchun alohida lock yaratadi.
    """

    with global_lock:

        if user_id not in chat_locks:
            chat_locks[user_id] = threading.Lock()

        return chat_locks[user_id]


# =========================================================
# AIZO SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
Sening isming Aizo.

Sen Shohruxning shaxsiy AI yordamchisisan.

Agar foydalanuvchi:
- "Sen kimsan?"
- "Kimsan?"
- "Isming nima?"
- "Kimning yordamchisisan?"
- yoki shunga o'xshash savol bersa,

o'zingni quyidagicha tanishtir:

"Men Aizo — Shohruxning AI yordamchisiman."

Sen Telegram ichida ishlaydigan aqlli AI yordamchisan.

Asosan o'zbek tilida javob ber.

Agar foydalanuvchi boshqa tilda yozsa,
shu tilda javob berishing mumkin.

Javoblaring tabiiy, tushunarli va foydali bo'lsin.

Texnik savollarga aniq va amaliy javob ber.

Kod so'ralsa, imkon qadar to'liq va ishlaydigan kod ber.

Agar foydalanuvchi xato kod yuborsa,
xatoni topib, tuzatib ber.

Keraksiz uzun javob bermagin.

Foydalanuvchiga hurmat bilan murojaat qil.

Emoji ishlatish majburiy emas.

O'zingni Shohrux deb ko'rsatma.
Sen Aizo — Shohruxning AI yordamchisisan.
"""


# =========================================================
# YANGI CHAT YARATISH
# =========================================================

def create_chat():

    return client.chats.create(
        model=MODEL_NAME,

        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,

            temperature=0.7,

            max_output_tokens=2048
        )
    )


# =========================================================
# UZUN XABARNI BO'LISH
# =========================================================

def split_message(
    text,
    max_length=MAX_TELEGRAM_LENGTH
):
    """
    Telegram 4096 belgilik limitidan oshib ketmaslik
    uchun javobni bir nechta xabarga bo'ladi.
    """

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
# UZUN JAVOBNI YUBORISH
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
            "Men <b>Aizo</b> — "
            "<b>Shohruxning AI yordamchisiman.</b>\n\n"
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

        "<b>Aizo yordam</b>\n\n"

        "/start — yangi suhbatni boshlash\n"
        "/clear — suhbat xotirasini tozalash\n"
        "/help — yordam\n\n"

        "Oddiy savolingizni yozishingiz mumkin."
    )


# =========================================================
# TEXT XABARLAR
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

    # Chat mavjud bo'lmasa yaratamiz
    if user_id not in user_chats:

        try:

            user_chats[user_id] = create_chat()

        except Exception:

            logger.exception(
                "CHAT CREATE ERROR | user=%s",
                user_id
            )

            bot.send_message(
                user_id,
                "AI bilan ulanishda xatolik yuz berdi."
            )

            return

    # User requestlarini navbat bilan bajarish
    lock = get_user_lock(user_id)

    with lock:

        try:

            bot.send_chat_action(
                user_id,
                "typing"
            )

            chat = user_chats[user_id]

            response = chat.send_message(
                user_text
            )

            answer = getattr(
                response,
                "text",
                None
            )

            if not answer:

                logger.warning(
                    "EMPTY RESPONSE | user=%s",
                    user_id
                )

                bot.send_message(
                    user_id,
                    "AI javob bera olmadi. "
                    "Iltimos, qayta urinib ko'ring."
                )

                return

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
                "GEMINI ERROR | user=%s",
                user_id
            )

            error_text = str(e).lower()

            # 429 / quota
            if (
                "429" in error_text
                or "quota" in error_text
                or "resource exhausted" in error_text
            ):

                user_message = (
                    "Hozircha Gemini API limiti tugagan.\n"
                    "Birozdan keyin qayta urinib ko'ring."
                )

            # API key
            elif (
                "api key" in error_text
                or "authentication" in error_text
                or "unauthorized" in error_text
            ):

                user_message = (
                    "Gemini API key bilan muammo bor.\n"
                    "GEMINI_API_KEY sozlamasini tekshiring."
                )

            # Safety
            elif (
                "blocked" in error_text
                or "safety" in error_text
            ):

                user_message = (
                    "Bu so'rov xavfsizlik sababli "
                    "qaytarilmadi."
                )

            # Boshqa xatolar
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
# QO'LLAB-QUVVATLANMAYDIGAN XABARLAR
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

    try:

        bot.infinity_polling(
            timeout=60,
            long_polling_timeout=30
        )

    except KeyboardInterrupt:

        logger.info(
            "Aizo to'xtatildi."
        )

    except Exception:

        logger.exception(
            "BOT CRITICAL ERROR"
        )