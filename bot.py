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

MODEL_NAME = "deepseek-v4-flash"

MAX_TELEGRAM_LENGTH = 4096

# Bir user uchun maksimal saqlanadigan suhbat xabarlari
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

bot = telebot.TeleBot(
    TELEGRAM_TOKEN,
    parse_mode="HTML"
)


# =========================================================
# SYSTEM PROMPT
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
xatoni topib, sababini tushuntirib,
tuzatilgan variantni ber.

Foydalanuvchining oldingi xabarlarini suhbat
kontekstida hisobga ol.

Keraksiz uzun javob bermagin.

Foydalanuvchiga hurmat bilan murojaat qil.

O'zingni Shohrux deb ko'rsatma.

Sen Aizo — Shohruxning AI yordamchisisan.
"""


# =========================================================
# USER CHAT HISTORY
# =========================================================

user_chats = {}


# Har bir user uchun alohida lock
chat_locks = {}

global_lock = threading.Lock()


# =========================================================
# USER LOCK
# =========================================================

def get_user_lock(user_id):

    with global_lock:

        if user_id not in chat_locks:
            chat_locks[user_id] = threading.Lock()

        return chat_locks[user_id]


# =========================================================
# YANGI CHAT YARATISH
# =========================================================

def create_chat():

    return [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]


# =========================================================
# TARIXNI CHEKLASH
# =========================================================

def limit_history(messages):

    if len(messages) <= MAX_HISTORY_MESSAGES + 1:
        return messages

    system_message = messages[0]

    recent_messages = messages[
        -(MAX_HISTORY_MESSAGES):
    ]

    return [
        system_message,
        *recent_messages
    ]


# =========================================================
# UZUN XABARNI BO'LISH
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


    # =====================================================
    # CHAT MAVJUD BO'LMASA
    # =====================================================

    if user_id not in user_chats:

        user_chats[user_id] = create_chat()


    # =====================================================
    # LOCK
    # =====================================================

    lock = get_user_lock(user_id)

    with lock:

        try:

            # Typing
            bot.send_chat_action(
                user_id,
                "typing"
            )


            # =============================================
            # USER XABARINI TARIXGA QO'SHISH
            # =============================================

            user_chats[user_id].append(
                {
                    "role": "user",
                    "content": user_text
                }
            )


            # =============================================
            # HISTORY LIMIT
            # =============================================

            user_chats[user_id] = limit_history(
                user_chats[user_id]
            )


            # =============================================
            # DEEPSEEK REQUEST
            # =============================================

            response = client.chat.completions.create(

                model=MODEL_NAME,

                messages=user_chats[user_id],

                stream=False,

                max_tokens=4096,

                thinking={
                    "type": "enabled"
                },

                reasoning_effort="high"
            )


            # =============================================
            # JAVOBNI OLISH
            # =============================================

            answer = response.choices[0].message.content


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


            # =============================================
            # ASSISTANT JAVOBINI TARIXGA QO'SHISH
            # =============================================

            user_chats[user_id].append(
                {
                    "role": "assistant",
                    "content": answer
                }
            )


            # =============================================
            # TELEGRAMGA YUBORISH
            # =============================================

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


            # =============================================
            # USER XABARINI HISTORY'DAN OLIB TASHLASH
            # =============================================

            if (
                user_chats.get(user_id)
                and user_chats[user_id][-1].get("role") == "user"
            ):

                user_chats[user_id].pop()


            error_text = str(e).lower()


            # =============================================
            # RATE LIMIT / BALANCE
            # =============================================

            if (
                "429" in error_text
                or "rate limit" in error_text
                or "quota" in error_text
            ):

                user_message = (
                    "Hozircha DeepSeek API limiti yoki "
                    "so'rov chegarasiga yetildi.\n"
                    "Birozdan keyin qayta urinib ko'ring."
                )


            # =============================================
            # API KEY
            # =============================================

            elif (
                "401" in error_text
                or "api key" in error_text
                or "authentication" in error_text
                or "unauthorized" in error_text
            ):

                user_message = (
                    "DeepSeek API key bilan muammo bor.\n"
                    "Railway Variables'dagi "
                    "DEEPSEEK_API_KEY ni tekshiring."
                )


            # =============================================
            # BAD REQUEST
            # =============================================

            elif "400" in error_text:

                user_message = (
                    "DeepSeek so'rovni qabul qilmadi.\n"
                    "Model yoki API sozlamasida muammo bo'lishi mumkin."
                )


            # =============================================
            # SERVER ERROR
            # =============================================

            elif (
                "500" in error_text
                or "502" in error_text
                or "503" in error_text
            ):

                user_message = (
                    "DeepSeek serverida vaqtinchalik muammo.\n"
                    "Birozdan keyin qayta urinib ko'ring."
                )


            # =============================================
            # BOSHQA XATO
            # =============================================

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