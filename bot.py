import telebot
import requests
import os

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GROQ_KEY = os.environ.get("GROQ_KEY", "")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_histories = {}

def ask_groq(messages):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "groq/compound-mini",
        "messages": messages,
        "max_tokens": 1000
    }
    res = requests.post(url, headers=headers, json=data)
    result = res.json()
    if 'error' in result:
        return f"Xato: {result['error']['message']}"
    return result['choices'][0]['message']['content']

@bot.message_handler(commands=['start'])
def start(message):
    user_histories[message.chat.id] = []
    bot.send_message(message.chat.id,
        "Salom! 👋\n"
        "Men Aizo.\n"
        "Nima yordam kerak?"
    )

@bot.message_handler(commands=['clear'])
def clear(message):
    user_histories[message.chat.id] = []
    bot.send_message(message.chat.id, "🗑 Tozalandi!")

@bot.message_handler(func=lambda m: True)
def reply(message):
    user_id = message.chat.id
    bot.send_chat_action(user_id, 'typing')
    if user_id not in user_histories:
        user_histories[user_id] = []
    user_histories[user_id].append({
        "role": "user",
        "content": message.text
    })
    messages = [
        {
            "role": "system",
            "content": "Sen Aizo degan aqlli yordamchisan. O'zbek tilida qisqa va aniq javob ber."
        }
    ] + user_histories[user_id]
    answer = ask_groq(messages)
    user_histories[user_id].append({
        "role": "assistant",
        "content": answer
    })
    bot.send_message(user_id, answer)

print("✅ Aizo ishga tushdi!")
bot.polling(none_stop=True)
