import telebot
import requests
import os

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GROQ_KEY1 = os.environ.get("GROQ_KEY1", "")
GROQ_KEY2 = os.environ.get("GROQ_KEY2", "")
GROQ_KEY3 = os.environ.get("GROQ_KEY3", "")

KEYS = [GROQ_KEY1, GROQ_KEY2, GROQ_KEY3]
current = 0
bot = telebot.TeleBot(TELEGRAM_TOKEN)
chats = {}

def ask(messages):
    global current
    for i in range(len(KEYS)):
        key = KEYS[(current + i) % len(KEYS)]
        if not key:
            continue
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "groq/compound-mini", "messages": messages, "max_tokens": 1000}
        ).json()
        if 'error' in res:
            current = (current + 1) % len(KEYS)
            continue
        return res['choices'][0]['message']['content']
    return "⏳ Limit tugadi! Kuting."

@bot.message_handler(commands=['start'])
def start(m):
    chats[m.chat.id] = []
    bot.send_message(m.chat.id, "Salom! 👋\nMen Aizo.\nNima yordam kerak?")

@bot.message_handler(commands=['clear'])
def clear(m):
    chats[m.chat.id] = []
    bot.send_message(m.chat.id, "🗑 Tozalandi!")

@bot.message_handler(func=lambda m: True)
def reply(m):
    bot.send_chat_action(m.chat.id, 'typing')
    if m.chat.id not in chats:
        chats[m.chat.id] = []
    chats[m.chat.id].append({"role": "user", "content": m.text})
    messages = [{"role": "system", "content": "Sen Aizo degan aqlli yordamchisan. O'zbek tilida javob ber."}] + chats[m.chat.id]
    answer = ask(messages)
    chats[m.chat.id].append({"role": "assistant", "content": answer})
    bot.send_message(m.chat.id, answer)

print("✅ Aizo ishga tushdi!")
bot.polling(none_stop=True)
