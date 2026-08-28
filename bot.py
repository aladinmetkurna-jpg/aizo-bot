import os
import logging
import threading
import base64
import io

import telebot
from openai import OpenAI
from telebot.types import Message


# =========================================================
# SOZLAMALAR
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

MODEL_NAME = "deepseek-v4-flash-vision-exp"

MAX_TELEGRAM_LENGTH = 2500

# Javob uzunligi (token). Kichikroq = qisqaroq javob, tezroq javob.
MAX_TOKENS = 700

# Har bir user uchun saqlanadigan suhbat xabarlari soni
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
    raise RuntimeError("TELEGRAM_TOKEN topilmadi!")

if not DEEPSEEK_API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY topilmadi!")


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

bot = telebot.TeleBot(TELEGRAM_TOKEN)


# =========================================================
# AIZO SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
Sening isming Aizo. Sen Shohruxning shaxsiy AI yordamchisisan.

Kim ekaningni so'rashsa: "Men Aizo — Shohruxning AI yordamchisiman."

QOIDALAR:
- Javoblaring QISQA va aniq bo'lsin. Odatda 2-5 gap yetarli.
- Kerak bo'lmasa uzun tushuntirish, ortiqcha kirish so'zlari yozma.
- To'g'ridan-to'g'ri javobdan boshla, "albatta", "juda ajoyib savol" kabi keraksiz kirish qilma.
- Asosan o'zbek tilida javob ber. Foydalanuvchi boshqa tilda yozsa, o'sha tilda javob ber.
- Texnik/kod savollarida: ishlaydigan kodni ber, ortiqcha izohsiz. Zarur bo'lgandagina qisqa tushuntirish qo'sh.
- Kodda xato bo'lsa: xatoni qisqa ayt, tuzatilgan kodni ber.
- Foydalanuvchi aniq "batafsil tushuntir" yoki "to'liq yoz" desagina uzunroq javob ber.
- Suhbat tarixini hisobga ol.
- Rasm yuborilsa, qisqa va aniq tahlil ber — batafsil emas.
- Hurmat bilan murojaat qil. O'zingni Shohrux deb ko'rsatma — sen Aizo.
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
    recent_messages = messages[-MAX_HISTORY_MESSAGES:]
    return [system_message, *recent_messages]


# =========================================================
# TELEGRAM XABARINI BO'LISH
# =========================================================

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


# =========================================================
# UZUN JAVOBNI YUBORISH
# =========================================================

def send_long_message(chat_id, text, reply_to_message_id=None, is_group=False):
    chunks = split_message(text)

    for chunk in chunks:
        if is_group:
            bot.send_message(
                chat_id,
                chunk,
                reply_to_message_id=reply_to_message_id
            )
        else:
            bot.send_message(chat_id, chunk)


# =========================================================
# RASMNI BASE64 GA O'TKAZISH
# =========================================================

def get_photo_base64(message: Message) -> str | None:
    """
    Telegramdagi eng katta o'lchamdagi rasmni yuklab,
    base64 string qaytaradi.
    """
    try:
        photo = message.photo[-1]
        file_info = bot.get_file(photo.file_id)
        downloaded = bot.download_file(file_info.file_path)

        b64 = base64.b64encode(downloaded).decode("utf-8")
        return b64
    except Exception as e:
        logger.exception("Rasm yuklashda xato: %s", e)
        return None


# =========================================================
# /START
# =========================================================

@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.chat.id

    try:
        user_chats[user_id] = create_chat()

        bot.send_message(
            user_id,
            "Salom!\n\n"
            "Men Aizo — Shohruxning AI yordamchisiman.\n\n"
            "Savolingizni yozing yoki rasm yuboring, yordam beraman."
        )

        logger.info("START | user=%s", user_id)

    except Exception:
        logger.exception("START ERROR | user=%s", user_id)
        bot.send_message(user_id, "Botni ishga tushirishda xatolik yuz berdi.")


# =========================================================
# /CLEAR
# =========================================================

@bot.message_handler(commands=["clear"])
def clear(message):
    user_id = message.chat.id

    try:
        user_chats[user_id] = create_chat()
        bot.send_message(user_id, "Suhbat xotirasi tozalandi.")
        logger.info("CLEAR | user=%s", user_id)

    except Exception:
        logger.exception("CLEAR ERROR | user=%s", user_id)
        bot.send_message(user_id, "Suhbatni tozalashda xatolik yuz berdi.")


# =========================================================
# /HELP
# =========================================================

@bot.message_handler(commands=["help"])
def help_command(message):
    bot.send_message(
        message.chat.id,
        "Aizo yordam\n\n"
        "/start — yangi suhbatni boshlash\n"
        "/clear — suhbat xotirasini tozalash\n"
        "/help — yordam\n\n"
        "Matn yozishingiz yoki rasm yuborishingiz mumkin."
    )


# =========================================================
# TEXT XABARLAR
# =========================================================

@bot.message_handler(
    content_types=["text"],
    func=lambda message: message.text and not message.text.startswith("/")
)
def reply(message):
    process_message(message, is_photo=False)


# =========================================================
# PHOTO (RASM) XABARLAR
# =========================================================

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    process_message(message, is_photo=True)


# =========================================================
# ASOSIY XABAR ISHLOV BERISH FUNKSIYASI
# =========================================================

def process_message(message: Message, is_photo: bool = False):
    user_id = message.chat.id
    is_group = message.chat.type in ["group", "supergroup"]

    if user_id not in user_chats:
        user_chats[user_id] = create_chat()

    lock = get_user_lock(user_id)

    with lock:
        try:
            bot.send_chat_action(user_id, "typing")

            # ---------------------------------------------
            # USER XABARINI TAYYORLASH
            # ---------------------------------------------
            if is_photo:
                b64_image = get_photo_base64(message)

                if not b64_image:
                    bot.send_message(
                        user_id,
                        "Rasmni yuklab olishda xatolik yuz berdi.",
                        reply_to_message_id=message.message_id if is_group else None
                    )
                    return

                caption = message.caption.strip() if message.caption else "Bu rasmni tahlil qil."

                user_content = [
                    {
                        "type": "text",
                        "text": caption
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64_image}"
                        }
                    }
                ]

                user_chats[user_id].append({
                    "role": "user",
                    "content": user_content
                })

            else:
                user_text = message.text.strip()
                if not user_text:
                    return

                user_chats[user_id].append({
                    "role": "user",
                    "content": user_text
                })

            # ---------------------------------------------
            # HISTORY LIMIT
            # ---------------------------------------------
            user_chats[user_id] = limit_history(user_chats[user_id])

            # ---------------------------------------------
            # DEEPSEEK REQUEST
            # ---------------------------------------------
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=user_chats[user_id],
                stream=False,
                max_tokens=MAX_TOKENS
            )

            if not response.choices:
                raise RuntimeError("DeepSeek bo'sh choices qaytardi.")

            answer = response.choices[0].message.content

            if not answer:
                raise RuntimeError("DeepSeek bo'sh javob qaytardi.")

            # ---------------------------------------------
            # ASSISTANT JAVOBINI HISTORY'GA QO'SHISH
            # ---------------------------------------------
            user_chats[user_id].append({
                "role": "assistant",
                "content": answer
            })

            # ---------------------------------------------
            # JAVOBNI YUBORISH
            # ---------------------------------------------
            send_long_message(
                chat_id=user_id,
                text=answer,
                reply_to_message_id=message.message_id,
                is_group=is_group
            )

            logger.info(
                "MESSAGE OK | user=%s | chat_type=%s | is_photo=%s",
                user_id,
                message.chat.type,
                is_photo
            )

        except Exception as e:
            logger.exception("DEEPSEEK ERROR | user=%s", user_id)

            # Xato bo'lganida oxirgi user xabarini olib tashlash
            if (
                user_chats.get(user_id)
                and user_chats[user_id][-1].get("role") == "user"
            ):
                user_chats[user_id].pop()

            error_text = str(e).lower()

            if any(x in error_text for x in ["429", "rate limit", "too many requests", "quota"]):
                user_message = (
                    "Hozircha DeepSeek API limitiga yetildi.\n"
                    "Birozdan keyin qayta urinib ko'ring."
                )
            elif any(x in error_text for x in ["401", "api key", "authentication", "unauthorized", "invalid_api_key"]):
                user_message = (
                    "DeepSeek API key bilan muammo bor.\n\n"
                    "Railway Variables'dagi DEEPSEEK_API_KEY ni tekshiring."
                )
            elif "model" in error_text and any(x in error_text for x in ["not found", "does not exist", "invalid"]):
                user_message = (
                    "DeepSeek modelida muammo yuz berdi.\n"
                    "MODEL_NAME sozlamasini tekshiring."
                )
            elif any(x in error_text for x in ["500", "502", "503", "server error"]):
                user_message = (
                    "DeepSeek serverida vaqtinchalik muammo yuz berdi.\n"
                    "Birozdan keyin qayta urinib ko'ring."
                )
            elif any(x in error_text for x in ["connection", "timeout", "network"]):
                user_message = (
                    "DeepSeek serveriga ulanishda muammo yuz berdi.\n"
                    "Birozdan keyin qayta urinib ko'ring."
                )
            else:
                user_message = (
                    "Kutilmagan xatolik yuz berdi.\n"
                    "Birozdan keyin qayta urinib ko'ring."
                )

            if is_group:
                bot.send_message(
                    user_id,
                    user_message,
                    reply_to_message_id=message.message_id
                )
            else:
                bot.send_message(user_id, user_message)


# =========================================================
# BOSHQA MEDIA (video, audio va h.k.)
# =========================================================

@bot.message_handler(
    content_types=[
        "video", "audio", "document", "sticker",
        "voice", "animation", "contact", "location"
    ]
)
def unsupported_message(message):
    is_group = message.chat.type in ["group", "supergroup"]

    text = "Hozircha men faqat matn va rasm bilan ishlayman."

    if is_group:
        bot.send_message(
            message.chat.id,
            text,
            reply_to_message_id=message.message_id
        )
    else:
        bot.send_message(message.chat.id, text)


# =========================================================
# BOTNI ISHGA TUSHIRISH
# =========================================================

if __name__ == "__main__":
    logger.info("Aizo — Shohruxning AI yordamchisi ishga tushmoqda...")

    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=30)
    except KeyboardInterrupt:
        logger.info("Aizo to'xtatildi.")
    except Exception:
        logger.exception("BOT CRITICAL ERROR")