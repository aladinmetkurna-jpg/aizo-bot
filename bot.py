import telebot
import google.generativeai as genai
import os

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GEMINI_KEY = os.environ.get("GEMINI_KEY", "")

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-3.6-flash")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_chats = {}

@bot.message_handler(commands=['start'])
def start(message):
    user_chats[message.chat.id] = model.start_chat(history=[])
    bot.send_message(message.chat.id,
        "Salom! 👋 Men Aizo\n"
        "Shohruxning AI yordamchisiman.\n"
        "Nima yordam kerak?"
    )

@bot.message_handler(commands=['clear'])
def clear(message):
    user_chats[message.chat.id] = model.start_chat(history=[])
    bot.send_message(message.chat.id, "🗑 Tozalandi!")

@bot.message_handler(func=lambda m: True)
def reply(message):
    user_id = message.chat.id
    bot.send_chat_action(user_id, 'typing')
    if user_id not in user_chats:
        user_chats[user_id] = model.start_chat(history=[])
    try:
        response = user_chats[user_id].send_message(message.text)
        bot.send_message(user_id, response.text)
    except Exception as e:
        bot.send_message(user_id, f"❌ Xatolik: {str(e)}")

print("✅ Aizo ishga tushdi!")
bot.polling(none_stop=True)