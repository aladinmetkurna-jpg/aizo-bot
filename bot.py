import logging
import os
import threading

import telebot
from telebot import util
from telebot import types as tg_types

from google import genai
from google.genai import errors
from google.genai import types as genai_types


# Loglarni ko‘rsatish
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# Muhit o‘zgaruvchilari
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")


# Tokenlarni tekshirish
if not TELEGRAM_TOKEN:
    raise RuntimeError(
        "TELEGRAM_TOKEN topilmadi! "
        "Muhit o‘zgaruvchisiga Telegram tokenini kiriting."
    )

if not GEMINI_KEY:
    raise RuntimeError(
        "GEMINI_KEY topilmadi! "
        "Muhit o‘zgaruvchisiga Gemini API kalitini kiriting."
    )


# Gemini modeli
MODEL_NAME = "gemini-2.5-flash"


# Botning asosiy ko‘rsatmasi
SYSTEM_INSTRUCTION = """
Sen Aizo nomli foydali Telegram AI yordamchisan.

Qoidalar:
- Foydalanuvchiga aniq, tushunarli va muloyim javob ber.
- Foydalanuvchi o‘zbek tilida yozsa, o‘zbek tilida javob ber.
- Boshqa tilda yozsa, imkon qadar o‘sha tilda javob ber.
- Bilmagan ma’lumotingni to‘qib chiqarmagin.
- Dasturlash savollarida ishlaydigan va tushunarli kod ber.
- Juda uzun va keraksiz javoblardan qoch.
"""


# Gemini va Telegram obyektlari
client = genai.Client(api_key=GEMINI_KEY)

bot = telebot.TeleBot(
    TELEGRAM_TOKEN,
    threaded=True,
    num_threads=4
)


# Foydalanuvchilarning suhbatlari
user_chats = {}

# Bir foydalanuvchi bir vaqtda ikkita xabar yuborsa,
# suhbat tarixi aralashib ketmasligi uchun lock
sessions_lock = threading.RLock()


def session_key(message):
    """
    Shaxsiy chat va guruhlarda foydalanuvchilar
    tarixini alohida saqlaydi.
    """
    if message.from_user:
        user_id = message.from_user.id
    else:
        user_id = message.chat.id

    return message.chat.id, user_id


def create_new_session():
    """Yangi Gemini chat sessiyasi yaratadi."""

    chat = client.chats.create(
        model=MODEL_NAME,
        history=[],
        config=genai_types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION
        )
    )

    return {
        "chat": chat,
        "lock": threading.Lock()
    }


def get_session(message):
    """Foydalanuvchi sessiyasini oladi yoki yangisini yaratadi."""

    key = session_key(message)

    with sessions_lock:
        if key not in user_chats:
            user_chats[key] = create_new_session()

        return user_chats[key]


def reset_session(message):
    """Foydalanuvchi suhbat tarixini yangilaydi."""

    key = session_key(message)

    with sessions_lock:
        user_chats[key] = create_new_session()


def send_long_message(message, text):
    """
    Uzun javobni Telegram limitiga mos
    qismlarga bo‘lib yuboradi.
    """

    if not text:
        text = "⚠️ Model matnli javob qaytarmadi."

    send_options = {}

    # Telegram forum mavzusiga javob berish
    thread_id = getattr(message, "message_thread_id", None)

    if thread_id is not None:
        send_options["message_thread_id"] = thread_id

    # Xavfsizlik uchun 4096 emas, 4000 belgi
    parts = util.smart_split(
        text,
        chars_per_string=4000
    )

    for part in parts:
        bot.send_message(
            message.chat.id,
            part,
            **send_options
        )


def send_gemini_error(message, exception):
    """Gemini API xatolarini foydalanuvchiga tushunarli ko‘rsatadi."""

    error_code = getattr(exception, "code", None)

    if error_code == 429:
        error_text = (
            "⏳ So‘rovlar limiti vaqtincha tugadi.\n"
            "Biroz kutib, qayta urinib ko‘ring."
        )

    elif error_code == 404:
        error_text = (
            "⚠️ Gemini 3.6 Flash modeli topilmadi yoki "
            "sizning API kalitingizda mavjud emas."
        )

    elif error_code in (401, 403):
        error_text = (
            "🔑 Gemini API kaliti noto‘g‘ri yoki "
            "unga ruxsat berilmagan."
        )

    else:
        error_text = (
            "❌ Gemini bilan bog‘lanishda xatolik yuz berdi.\n"
            "Birozdan so‘ng qayta urinib ko‘ring."
        )

    bot.send_message(
        message.chat.id,
        error_text
    )


@bot.message_handler(commands=["start"])
def start_command(message):
    reset_session(message)

    bot.send_message(
        message.chat.id,
        "Salom!👋🏻 Men Aizo\n\n"
        "Shohruxning AI yordamchisiman.\n\n"
        "Savolingizni yozishingiz mumkin."
    )


@bot.message_handler(commands=["help"])
def help_command(message):
    bot.send_message(
        message.chat.id,
        "📖 Buyruqlar:\n\n"
        "/start — botni qayta boshlash\n"
        "/clear — suhbat tarixini tozalash\n"
        "/model — ishlatilayotgan model\n"
        "/help — yordam\n\n"
        "Oddiy savol yuborsangiz, Aizo javob beradi."
    )


@bot.message_handler(commands=["clear"])
def clear_command(message):
    reset_session(message)

    bot.send_message(
        message.chat.id,
        "🗑 Suhbat tarixi tozalandi!"
    )


@bot.message_handler(commands=["model"])
def model_command(message):
    bot.send_message(
        message.chat.id,
        f"🤖 Ishlatilayotgan model:\n{MODEL_NAME}"
    )


# Noma’lum buyruqlar
@bot.message_handler(
    content_types=["text"],
    func=lambda message: (
        bool(message.text)
        and message.text.startswith("/")
    )
)
def unknown_command(message):
    bot.send_message(
        message.chat.id,
        "❓ Bunday buyruq mavjud emas.\n"
        "Buyruqlar ro‘yxati uchun /help yuboring."
    )


# Oddiy matnli xabarlar
@bot.message_handler(
    content_types=["text"],
    func=lambda message: (
        bool(message.text)
        and not message.text.startswith("/")
    )
)
def reply_to_message(message):
    user_text = message.text.strip()

    if not user_text:
        return

    try:
        bot.send_chat_action(
            message.chat.id,
            "typing"
        )
    except Exception:
        logging.warning("Typing holatini yuborib bo‘lmadi.")

    session = get_session(message)

    try:
        # Bir foydalanuvchining javoblari tartib bilan ishlanadi
        with session["lock"]:
            response = session["chat"].send_message(user_text)

            answer = response.text

            if not answer:
                answer = (
                    "⚠️ Gemini matnli javob qaytarmadi. "
                    "Savolni boshqacha yozib ko‘ring."
                )

            send_long_message(message, answer)

    except errors.APIError as exception:
        logging.exception(
            "Gemini API xatosi. Kod: %s",
            getattr(exception, "code", "noma’lum")
        )

        send_gemini_error(message, exception)

    except Exception:
        logging.exception("Kutilmagan xatolik yuz berdi.")

        bot.send_message(
            message.chat.id,
            "❌ Kutilmagan xatolik yuz berdi.\n"
            "Birozdan keyin qayta urinib ko‘ring."
        )


# Rasm, video, stiker va boshqa xabarlar
@bot.message_handler(func=lambda message: True)
def unsupported_message(message):
    bot.send_message(
        message.chat.id,
        "⚠️ Hozircha faqat matnli xabarlarni qabul qilaman."
    )


def set_bot_commands():
    """Telegram menyusiga buyruqlarni o‘rnatadi."""

    commands = [
        tg_types.BotCommand(
            "start",
            "Botni ishga tushirish"
        ),
        tg_types.BotCommand(
            "clear",
            "Suhbat tarixini tozalash"
        ),
        tg_types.BotCommand(
            "model",
            "Ishlatilayotgan model"
        ),
        tg_types.BotCommand(
            "help",
            "Yordam"
        )
    ]

    bot.set_my_commands(commands)


if __name__ == "__main__":
    try:
        bot_info = bot.get_me()
        set_bot_commands()

        print(
            f"✅ Aizo ishga tushdi!\n"
            f"🤖 Bot: @{bot_info.username}\n"
            f"🧠 Model: {MODEL_NAME}"
        )

        bot.infinity_polling(
            skip_pending=True,
            timeout=20,
            long_polling_timeout=20,
            allowed_updates=["message"]
        )

    except KeyboardInterrupt:
        print("\n🛑 Bot to‘xtatildi.")

    except Exception:
        logging.exception("Botni ishga tushirishda xatolik.")
        raise

    finally:
        client.close()