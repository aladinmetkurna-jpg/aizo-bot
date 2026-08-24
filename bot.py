import os
import requests
import telebot

# =========================
# SOZLAMALAR
# =========================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Local AI server manzili
# Keyin Oracle serverining IP manzilini shu yerga qo'yamiz.
AI_URL = os.environ.get(
    "AI_URL",
    "http://127.0.0.1:8080/v1/chat/completions"
)

MODEL_NAME = os.environ.get("MODEL_NAME", "aizo")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Har bir foydalanuvchining vaqtinchalik suhbat xotirasi
user_histories = {}

# Nechta eski xabarni saqlash
MAX_HISTORY = 12


# =========================
# AIZO SHAXSIYATI
# =========================

SYSTEM_PROMPT = """
Sen Aizo nomli shaxsiy sun'iy intellekt yordamchisisan.

Asosiy tiling — o'zbek tili.
Foydalanuvchi qaysi tilda gapirsa, imkon qadar shu tilda javob ber.

Javoblaring tabiiy, tushunarli va foydali bo'lsin.
Keraksiz uzun javob bermagin.
Agar foydalanuvchi oddiy suhbat qilsa, tabiiy suhbatlash.

O'zingni Aizo deb bil.
Sen tashqi API xizmatiga bog'liq emassan.
"""


# =========================
# LOCAL AI
# =========================

def ask_ai(messages):

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 500,
        "stream": False
    }

    try:

        response = requests.post(
            AI_URL,
            json=payload,
            timeout=180
        )

        response.raise_for_status()

        data = response.json()

        answer = data["choices"][0]["message"]["content"]

        return answer.strip()

    except requests.exceptions.Timeout:

        return "⏳ Aizo biroz sekin ishlayapti. Yana bir marta yuborib ko'r."

    except requests.exceptions.ConnectionError:

        return "❌ Aizo AI serveriga ulanib bo'lmadi."

    except Exception as e:

        print("AI ERROR:", e)

        return "❌ Aizo'da xatolik yuz berdi."


# =========================
# /START
# =========================

@bot.message_handler(commands=["start"])
def start(message):

    user_id = message.from_user.id

    user_histories[user_id] = []

    bot.reply_to(
        message,
        "Salom 👋\n\n"
        "Men Aizoman — sening shaxsiy AI yordamching.\n\n"
        "Menga xohlagan narsangni yozaver."
    )


# =========================
# /CLEAR
# =========================

@bot.message_handler(commands=["clear"])
def clear_memory(message):

    user_id = message.from_user.id

    user_histories[user_id] = []

    bot.reply_to(
        message,
        "🧠 Suhbat xotirasi tozalandi."
    )


# =========================
# /HELP
# =========================

@bot.message_handler(commands=["help"])
def help_command(message):

    bot.reply_to(
        message,
        "🤖 Aizo buyruqlari:\n\n"
        "/start — Aizoni boshlash\n"
        "/clear — suhbat xotirasini tozalash\n"
        "/help — yordam"
    )


# =========================
# MATN XABARLARI
# =========================

@bot.message_handler(
    content_types=["text"]
)
def handle_message(message):

    user_id = message.from_user.id

    user_text = message.text.strip()

    if not user_text:
        return

    # Foydalanuvchi xotirasi mavjud bo'lmasa
    if user_id not in user_histories:
        user_histories[user_id] = []

    history = user_histories[user_id]

    # Foydalanuvchi xabarini qo'shish
    history.append({
        "role": "user",
        "content": user_text
    })

    # Juda ko'p tarix yig'ilib ketmasin
    history = history[-MAX_HISTORY:]

    user_histories[user_id] = history

    # AI uchun messages
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    messages.extend(history)

    # AI javobini olish
    answer = ask_ai(messages)

    # Javobni xotiraga saqlash
    history.append({
        "role": "assistant",
        "content": answer
    })

    user_histories[user_id] = history[-MAX_HISTORY:]

    # Telegramga yuborish
    try:

        bot.reply_to(
            message,
            answer
        )

    except Exception as e:

        print("TELEGRAM ERROR:", e)


# =========================
# BOTNI ISHGA TUSHIRISH
# =========================

print("Aizo ishga tushdi...")

bot.infinity_polling(
    skip_pending=True
)