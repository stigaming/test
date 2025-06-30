import os
import logging
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from datetime import datetime, timedelta

# Per-group configurations
PIN_INTERVAL = timedelta(hours=12)
group_required_keywords = {}  # chat_id: keyword
last_pin_time = {}  # (chat_id, user_id): datetime
bot_admin_ids = set()  # Bot-level admins (can broadcast, manage admins)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🙏 Welcome!\n\n📌 If your bio contains the required word set by group admins, your message will be pinned."
    )

# Set keyword command (group admin only)
async def set_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in ["administrator", "creator"]:
        await update.message.reply_text("❌ Only group admins can set the keyword.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /setkeyword <word>")
        return

    keyword = context.args[0].strip()
    group_required_keywords[chat.id] = keyword
    await update.message.reply_text(f"✅ Required keyword for this group is now: '{keyword}'")

# Admin panel with inline buttons
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    member = await context.bot.get_chat_member(chat.id, user.id)

    if member.status in ["administrator", "creator"]:
        keyword = group_required_keywords.get(chat.id, "<not set>")
        buttons = [
            [InlineKeyboardButton("Set Keyword", callback_data="setkeyword_prompt")],
            [InlineKeyboardButton("View Keyword", callback_data="viewkeyword")]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(
            f"🛠️ Admin Panel\n\n- Required keyword: '{keyword}'\n- Pinned users: {len(last_pin_time)}",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text("❌ You are not an admin!")

# Handle keyword view via inline button
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == "viewkeyword":
        keyword = group_required_keywords.get(chat_id, "<not set>")
        await query.edit_message_text(f"🔑 Current keyword: {keyword}")
    elif query.data == "setkeyword_prompt":
        await query.edit_message_text("Use /setkeyword <word> to update the required keyword.")

# Broadcast message (bot-level admin only)
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in bot_admin_ids:
        await update.message.reply_text("❌ You are not a bot admin!")
        return

    if not context.args:
        await update.message.reply_text("Usage: /broadcast <your message>")
        return

    message = " ".join(context.args)
    sent_to = set()
    for (chat_id, _) in last_pin_time.keys():
        if chat_id not in sent_to:
            try:
                await context.bot.send_message(chat_id=chat_id, text=message)
                sent_to.add(chat_id)
            except:
                continue

    await update.message.reply_text(f"✅ Broadcast sent to {len(sent_to)} groups.")

# Add bot admin (bot-level admin only)
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in bot_admin_ids:
        await update.message.reply_text("❌ Only existing bot admins can add new ones!")
        return

    if not context.args:
        await update.message.reply_text("Usage: /addadmin <user_id>")
        return

    try:
        new_admin_id = int(context.args[0])
        bot_admin_ids.add(new_admin_id)
        await update.message.reply_text(f"✅ User {new_admin_id} added as bot admin.")
    except:
        await update.message.reply_text("❌ Invalid user ID.")

# Remove bot admin (bot-level admin only)
async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in bot_admin_ids:
        await update.message.reply_text("❌ Only existing bot admins can remove admins!")
        return

    if not context.args:
        await update.message.reply_text("Usage: /removeadmin <user_id>")
        return

    try:
        remove_id = int(context.args[0])
        if remove_id in bot_admin_ids:
            bot_admin_ids.remove(remove_id)
            await update.message.reply_text(f"✅ User {remove_id} removed from bot admins.")
        else:
            await update.message.reply_text("User is not a bot admin.")
    except:
        await update.message.reply_text("❌ Invalid user ID.")

# List all bot admins
async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in bot_admin_ids:
        await update.message.reply_text("❌ You are not a bot admin!")
        return
    await update.message.reply_text("🤖 Bot Admins:\n" + "\n".join(map(str, bot_admin_ids)))

# Handle normal messages and pin if keyword matches
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if not update.message or not chat or chat.type != "supergroup":
        return

    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status in ["administrator", "creator"]:
        return  # Skip group admins

    required_keyword = group_required_keywords.get(chat.id)
    if not required_keyword:
        return  # Keyword not set for this group

    bio = (await context.bot.get_chat(user.id)).bio or ""

    if required_keyword.lower() in bio.lower():
        now = datetime.now()
        last_time = last_pin_time.get((chat.id, user.id))

        if not last_time or now - last_time >= PIN_INTERVAL:
            try:
                await context.bot.pin_chat_message(chat.id, update.message.message_id)
                last_pin_time[(chat.id, user.id)] = now
                logger.info(f"Pinned message from {user.first_name} in {chat.title}")
            except Exception as e:
                logger.warning(f"Pin failed: {e}")
        else:
            logger.info(f"Skipping pin for {user.first_name} (12h cooldown)")
    else:
        logger.info(f"User {user.first_name} bio doesn't contain the required keyword")

# Run bot
def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    bot_admin_ids.update({5888830421})  # replace with your own ID

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("setkeyword", set_keyword))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("addadmin", add_admin))
    app.add_handler(CommandHandler("removeadmin", remove_admin))
    app.add_handler(CommandHandler("listadmins", list_admins))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("✅ Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
