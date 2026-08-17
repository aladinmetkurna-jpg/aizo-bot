import telebot
import google.generativeai as genai
import os

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

GEMINI_KEYS = [
    os.environ.get("GEMINI_KEY1", ""),
    os.environ.get("GEMINI_KEY2", ""),
]

current_key = 0
bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_chats = {}

def get_model():
    global current_key
    for i in range(len(GEMINI_KEYS)):
        key = GEMINI_KEYS[(current_key + i) % len(GEMINI_KEYS)]
        if key:
            genai.configure(api_key=key)
            return genai.GenerativeModel("gemini-1.5-flash")
    return None

@bot.message_handler(commands=['start'])
def start(message):
    user_chats[message.chat.id] = get_model().start_chat(history=[])
    bot.send_message(message.chat.id,
        "Salom! 👋\n"
        "Men Aizo.\n"
        "Nima yordam kerak?"
    )

@bot.message_handler(commands=['clear'])
def clear(message):
    user_chats[message.chat.id] = get_model().start_chat(history=[])
    bot.send_message(message.chat.id, "🗑 Tozalandi!")

@bot.message_handler(func=lambda m: True)
def reply(message):
    global current_key
    user_id = message.chat.id
    bot.send_chat_action(user_id, 'typing')
    if user_id not in user_chats:
        user_chats[user_id] = get_model().start_chat(history=[])
    try:
        response = user_chats[user_id].send_message(message.text)
        bot.send_message(user_id, response.text)
    except Exception as e:
        error = str(e)
        if "quota" in error.lower() or "limit" in error.lower():
            current_key = (current_key + 1) % len(GEMINI_KEYS)
            user_chats[user_id] = get_model().start_chat(history=[])
            try:
                response = user_chats[user_id].send_message(message.text)
                bot.send_message(user_id, response.text)
            except:
                bot.send_message(user_id, "⏳ Limit tugadi! Biroz kuting.")
        else:
            bot.send_message(user_id, f"❌ Xatolik: {error}")

print("✅ Aizo ishga tushdi!")
bot.polling(none_stop=True)
