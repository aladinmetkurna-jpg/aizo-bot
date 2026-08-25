# =========================================================
# /STATUS_AI
# =========================================================

@bot.message_handler(
    commands=["status_ai"]
)
def status_command(message):

    if not is_group(message):
        bot.send_message(
            message.chat.id,
            "/status_ai faqat guruhda ishlaydi."
        )
        return

    active = group_active(message.chat.id)
    status = "yoqilgan ✅" if active else "o'chirilgan ❌"

    bot.send_message(
        message.chat.id,
        f"Aizo holati: {status}"
    )


# =========================================================
# /ADMIN
# =========================================================

@bot.message_handler(
    commands=["admin"]
)
def admin_command(message):

    if not is_admin(message):
        bot.reply_to(message, "Bu buyruq faqat admin uchun.")
        return

    bot.send_message(
        message.chat.id,
        "Admin panel:",
        reply_markup=admin_keyboard()
    )


# =========================================================
# ADMIN CALLBACKS
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("admin_")
)
def admin_callback(call):

    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Ruxsat yo'q.")
        return

    data = call.data

    if data == "admin_stats":
        with data_lock:
            users = len(user_chats)
            groups = len(group_states)
            mems = len(memories)

        bot.answer_callback_query(call.id)
        bot.send_message(
            call.from_user.id,
            f"Statistika:\n\n"
            f"• Faol chatlar: {users}\n"
            f"• Guruhlar: {groups}\n"
            f"• Xotiralar: {mems}"
        )

    elif data == "admin_broadcast":
        waiting_broadcast.add(call.from_user.id)
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.from_user.id,
            "Broadcast xabarini yuboring (yoki /cancel)."
        )

    elif data == "admin_clear":
        memories.clear()
        save_json(MEMORY_FILE, memories)
        bot.answer_callback_query(call.id, "Xotiralar tozalandi.")
        bot.send_message(call.from_user.id, "Barcha xotiralar o'chirildi.")

    elif data == "admin_id":
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.from_user.id,
            f"Sizning ID: `{ADMIN_ID}`",
            parse_mode="Markdown"
        )

    elif data == "admin_close":
        bot.answer_callback_query(call.id)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass


# =========================================================
# /SUMMARIZE
# =========================================================

@bot.message_handler(
    commands=["summarize"]
)
def summarize_command(message):

    user_id = message.chat.id
    chat = get_chat(user_id)

    if len(chat) < 3:
        bot.send_message(
            user_id,
            "Suhbat hali juda qisqa, xulosa chiqarib bo'lmaydi."
        )
        return

    chat.append({
        "role": "user",
        "content": "Shu suhbatni qisqa va aniq xulosa qilib ber."
    })

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=chat,
            max_tokens=800
        )
        summary = response.choices[0].message.content
    except Exception:
        logger.exception("Summarize xatosi")
        summary = "Xulosa chiqarishda xatolik yuz berdi."

    bot.send_message(user_id, summary)


# =========================================================
# FLOOD CONTROL
# =========================================================

def is_flooding(user_id):
    now = time.time()
    last = last_message_time.get(user_id, 0)

    if now - last < FLOOD_SECONDS:
        return True

    last_message_time[user_id] = now
    return False


# =========================================================
# AI JAVOB OLISH
# =========================================================

def get_ai_reply(user_id, text):

    lock = get_user_lock(user_id)

    with lock:
        chat = get_chat(user_id)
        chat.append({"role": "user", "content": text})
        chat = limit_history(chat)

        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=chat,
                max_tokens=2000,
                temperature=0.7
            )
            reply = response.choices[0].message.content
        except Exception:
            logger.exception("DeepSeek xatosi")
            reply = "Kechirasiz, AI bilan bog'lanishda xatolik yuz berdi. Keyinroq urinib ko'ring."

        chat.append({"role": "assistant", "content": reply})
        user_chats[user_id] = chat

        return reply


# =========================================================
# ASOSIY XABAR HANDLER
# =========================================================

@bot.message_handler(
    content_types=["text"],
    func=lambda m: m.text and not m.text.startswith("/")
)
def handle_message(message):

    if is_flooding(message.from_user.id):
        return

    # Guruhda ishlashni tekshirish
    if is_group(message):
        if not group_active(message.chat.id):
            return

        bot_username = bot.get_me().username
        text = message.text or ""

        is_reply_to_bot = (
            message.reply_to_message
            and message.reply_to_message.from_user
            and message.reply_to_message.from_user.id == bot.get_me().id
        )
        is_mentioned = f"@{bot_username}" in text

        if not (is_reply_to_bot or is_mentioned):
            return

        text = text.replace(f"@{bot_username}", "").strip()
    else:
        text = message.text.strip()

    if not text:
        return

    # Admin broadcast
    if message.from_user.id in waiting_broadcast:
        waiting_broadcast.discard(message.from_user.id)

        if text.lower() == "/cancel":
            bot.reply_to(message, "Broadcast bekor qilindi.")
            return

        sent = 0
        with data_lock:
            targets = list(user_chats.keys())

        for uid in targets:
            try:
                bot.send_message(uid, f"📢 Admin xabari:\n\n{text}")
                sent += 1
            except Exception:
                pass

        bot.reply_to(message, f"Broadcast yuborildi: {sent} ta foydalanuvchi.")
        return

    # AI javob
    def process():
        try:
            bot.send_chat_action(message.chat.id, "typing")
            reply = get_ai_reply(message.chat.id, text)

            markup = None if is_group(message) else private_keyboard()
            send_long_message(message.chat.id, reply, reply_markup=markup)

        except Exception:
            logger.exception("handle_message xatosi")
            bot.reply_to(message, "Xatolik yuz berdi.")

    executor.submit(process)


# =========================================================
# BOT ISHGA TUSHIRISH
# =========================================================

if __name__ == "__main__":
    logger.info("Aizo ishga tushmoqda...")
    bot.infinity_polling(
        timeout=60,
        long_polling_timeout=60,
        skip_pending=True
    )