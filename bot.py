# bot.py - COMPLETE WITH ALL FEATURES
import asyncio
import threading
import json
import logging
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from config import BOT_TOKEN, OWNER_ID, MINI_APP_URL
from database import *

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

init_db()
flask_app = Flask(__name__)

# Storage
user_batch_range = {}

@flask_app.route('/')
def health_check():
    return "Bot is running!"

@flask_app.route('/ad-callback', methods=['POST', 'OPTIONS'])
def ad_callback():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    try:
        data = request.get_json()
        logger.info(f"Callback: {data}")
        
        if data.get('status') == 'ad_completed':
            file_code = data.get('file_code')
            user_id = data.get('user_id')
            
            if file_code and user_id:
                record_ad_view(user_id, file_code)
                file_data = get_file(file_code)
                
                if file_data:
                    file_id, file_type = file_data
                    bot_token = BOT_TOKEN
                    
                    if file_type == 'video':
                        requests.post(f"https://api.telegram.org/bot{bot_token}/sendVideo", json={'chat_id': user_id, 'video': file_id})
                    elif file_type == 'photo':
                        requests.post(f"https://api.telegram.org/bot{bot_token}/sendPhoto", json={'chat_id': user_id, 'photo': file_id})
                    elif file_type == 'document':
                        requests.post(f"https://api.telegram.org/bot{bot_token}/sendDocument", json={'chat_id': user_id, 'document': file_id})
                    
                    logger.info(f"File {file_code} sent to {user_id}")
        
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'status': 'error'}), 500

async def send_file_by_type(update, file_id, file_type):
    if file_type == 'video':
        await update.message.reply_video(file_id)
    elif file_type == 'photo':
        await update.message.reply_photo(file_id)
    elif file_type == 'document':
        await update.message.reply_document(file_id)
    elif file_type == 'audio':
        await update.message.reply_audio(file_id)

async def send_with_timer(update, text, timer_seconds=None, reply_markup=None):
    if timer_seconds is None:
        timer_seconds = get_timer()
    
    msg = await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    add_to_delete_queue(update.effective_chat.id, msg.message_id, timer_seconds)
    return msg

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"User {user_id} started")
    
    if context.args:
        file_code = context.args[0]
        
        if file_code.startswith("file_"):
            short_code = file_code.replace("file_", "")
            file_data = get_file(short_code)
            
            if file_data:
                file_id, file_type = file_data
                
                # Check ads
                ads_enabled = is_ads_enabled()
                is_bypass = is_ads_bypass(user_id)
                
                if not ads_enabled or is_bypass or has_viewed_ad(user_id, short_code):
                    await send_file_by_type(update, file_id, file_type)
                    
                    timer = get_timer()
                    msg_text = get_message1().format(timer=timer)
                    keyboard = [[InlineKeyboardButton("📝 Player Info", callback_data=f"player_{short_code}")]]
                    await send_with_timer(update, msg_text, timer, InlineKeyboardMarkup(keyboard))
                else:
                    context.user_data['pending_file'] = short_code
                    mini_app_url = f"{MINI_APP_URL}?user_id={user_id}&file_code={short_code}"
                    keyboard = [[InlineKeyboardButton("🎬 Watch Ad", web_app=WebAppInfo(url=mini_app_url))]]
                    await update.message.reply_text("Click below to get your file:", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await update.message.reply_text("❌ Invalid link!")
        
        elif file_code.startswith("batch_"):
            batch_code = file_code.replace("batch_", "")
            batch_files = get_batch_files(batch_code)
            
            if batch_files:
                await update.message.reply_text(f"📦 Sending {len(batch_files)} files...")
                for file_id, file_type in batch_files:
                    await send_file_by_type(update, file_id, file_type)
                    await asyncio.sleep(0.5)
                
                timer = get_timer()
                await send_with_timer(update, f"✅ Batch sent! {len(batch_files)} files.\n\n⏰ Deletes in {timer}s.", timer)
            else:
                await update.message.reply_text("❌ Invalid batch link!")
        else:
            await update.message.reply_text("👋 Welcome! Use /help")
    else:
        await update.message.reply_text("👋 Welcome! Use /help")

async def player_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    admin_username = get_admin_username()
    msg_text = get_message2().format(admin_username=admin_username)
    keyboard = [[InlineKeyboardButton("❌ Close", callback_data="close")]]
    await query.edit_message_text(msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.delete_message()

async def genlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    context.user_data['waiting_for_file'] = True
    await update.message.reply_text("📤 Forward me a file to get a link.")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_for_file'):
        message = update.effective_message
        
        if message.video:
            file_id = message.video.file_id
            file_type = 'video'
        elif message.photo:
            file_id = message.photo[-1].file_id
            file_type = 'photo'
        elif message.document:
            file_id = message.document.file_id
            file_type = 'document'
        elif message.audio:
            file_id = message.audio.file_id
            file_type = 'audio'
        else:
            await update.message.reply_text("❌ Send valid file.")
            return
        
        short_code = generate_short_code()
        save_file(short_code, file_id, file_type, message.chat_id, message.message_id)
        bot_username = context.bot.username
        file_link = f"https://t.me/{bot_username}?start=file_{short_code}"
        
        await update.message.reply_text(f"✅ **Link:**\n`{file_link}`", parse_mode='Markdown')
        context.user_data['waiting_for_file'] = False

# ============ BATCH RANGE ============

async def batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    user_batch_range[user_id] = {'step': 'waiting_first'}
    await update.message.reply_text("📦 Forward the **FIRST** message. Type /cancel to stop.")

async def handle_batch_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_batch_range:
        return
    
    message = update.effective_message
    
    if user_batch_range[user_id]['step'] == 'waiting_first':
        user_batch_range[user_id]['first_chat_id'] = message.chat_id
        user_batch_range[user_id]['first_msg_id'] = message.message_id
        user_batch_range[user_id]['step'] = 'waiting_last'
        await update.message.reply_text("✅ Now forward the **LAST** message.")
    
    elif user_batch_range[user_id]['step'] == 'waiting_last':
        first_chat_id = user_batch_range[user_id]['first_chat_id']
        first_msg_id = user_batch_range[user_id]['first_msg_id']
        last_msg_id = message.message_id
        chat_id = message.chat_id
        
        if first_chat_id != chat_id:
            await update.message.reply_text("❌ Messages must be from same chat!")
            del user_batch_range[user_id]
            return
        
        if last_msg_id <= first_msg_id:
            await update.message.reply_text("❌ Last must be after first!")
            del user_batch_range[user_id]
            return
        
        msg_range = last_msg_id - first_msg_id + 1
        if msg_range > 100:
            await update.message.reply_text(f"❌ Range too large ({msg_range}). Max 100.")
            del user_batch_range[user_id]
            return
        
        await update.message.reply_text(f"🔍 Scanning {msg_range} messages...")
        
        collected_files = []
        for msg_id in range(first_msg_id, last_msg_id + 1):
            try:
                msg = await context.bot.forward_message(chat_id=chat_id, from_chat_id=chat_id, message_id=msg_id)
                
                if msg.video:
                    sc = generate_short_code()
                    save_file(sc, msg.video.file_id, 'video', chat_id, msg_id)
                    collected_files.append(sc)
                elif msg.photo:
                    sc = generate_short_code()
                    save_file(sc, msg.photo[-1].file_id, 'photo', chat_id, msg_id)
                    collected_files.append(sc)
                elif msg.document:
                    sc = generate_short_code()
                    save_file(sc, msg.document.file_id, 'document', chat_id, msg_id)
                    collected_files.append(sc)
                
                await msg.delete()
            except:
                pass
        
        if len(collected_files) == 0:
            await update.message.reply_text("❌ No files found!")
            del user_batch_range[user_id]
            return
        
        batch_code = generate_short_code()
        bot_username = context.bot.username
        batch_link = f"https://t.me/{bot_username}?start=batch_{batch_code}"
        
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO batches (batch_code, chat_id, first_msg_id, last_msg_id, total_files) VALUES (?, ?, ?, ?, ?)",
                  (batch_code, chat_id, first_msg_id, last_msg_id, len(collected_files)))
        batch_id = c.lastrowid
        
        for idx, fc in enumerate(collected_files):
            c.execute("SELECT id FROM files WHERE short_code = ?", (fc,))
            r = c.fetchone()
            if r:
                c.execute("INSERT INTO batch_files (batch_id, file_id, file_index) VALUES (?, ?, ?)", (batch_id, r[0], idx))
        
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ **Batch Created!**\n\n📁 {len(collected_files)} files\n🔗 `{batch_link}`", parse_mode='Markdown')
        del user_batch_range[user_id]

async def batch_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_batch_range:
        del user_batch_range[user_id]
        await update.message.reply_text("❌ Cancelled.")

# ============ ADMIN COMMANDS ============

async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /addadmin <id>")
        return
    try:
        add_admin(int(context.args[0]), OWNER_ID)
        await update.message.reply_text(f"✅ Admin added.")
    except:
        await update.message.reply_text("❌ Invalid ID.")

async def removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /removeadmin <id>")
        return
    try:
        remove_admin(int(context.args[0]))
        await update.message.reply_text(f"✅ Admin removed.")
    except:
        await update.message.reply_text("❌ Invalid ID.")

async def listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    admins = get_all_admins()
    text = "**Admins:**\n"
    for uid, owner in admins:
        text += f"• `{uid}` - {'Owner' if owner else 'Admin'}\n"
    await update.message.reply_text(text, parse_mode='Markdown')

# Settings Commands
async def set_timer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not context.args:
        await update.message.reply_text(f"Current timer: {get_timer()}s\nUsage: /set_timer <seconds>")
        return
    try:
        seconds = int(context.args[0])
        if seconds < 10:
            await update.message.reply_text("❌ Minimum 10 seconds.")
            return
        set_timer(seconds, update.effective_user.id)
        await update.message.reply_text(f"✅ Timer set to {seconds}s")
    except:
        await update.message.reply_text("❌ Invalid number.")

async def set_admin_username_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not context.args:
        await update.message.reply_text(f"Current: {get_admin_username()}\nUsage: /set_admin_username <@username>")
        return
    username = context.args[0]
    if not username.startswith('@'):
        username = '@' + username
    set_admin_username(username, update.effective_user.id)
    await update.message.reply_text(f"✅ Set to {username}")

async def set_message1_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /set_message1 <text> (use {timer} for timer)")
        return
    text = ' '.join(context.args)
    set_setting('message1_text', text, update.effective_user.id)
    await update.message.reply_text("✅ Message 1 updated.")

async def set_message2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /set_message2 <text> (use {admin_username})")
        return
    text = ' '.join(context.args)
    set_setting('message2_text', text, update.effective_user.id)
    await update.message.reply_text("✅ Message 2 updated.")

async def show_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    await update.message.reply_text(
        f"**Timer:** {get_timer()}s\n"
        f"**Admin:** {get_admin_username()}\n\n"
        f"**Msg1:** {get_message1()}\n\n"
        f"**Msg2:** {get_message2()}",
        parse_mode='Markdown')

# Ads Control
async def ads_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    set_ads_enabled(True)
    await update.message.reply_text("✅ Ads enabled.")

async def ads_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    set_ads_enabled(False)
    await update.message.reply_text("✅ Ads disabled.")

async def ads_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    await update.message.reply_text(
        f"**Ads:** {'ON' if is_ads_enabled() else 'OFF'}\n"
        f"**Daily Limit:** {get_ad_limit()}\n"
        f"**Bypass Users:** {len(get_bypass_list())}",
        parse_mode='Markdown')

async def set_ad_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not context.args:
        await update.message.reply_text(f"Current: {get_ad_limit()}\nUsage: /set_ad_limit <number>")
        return
    try:
        limit = int(context.args[0])
        if limit < 1:
            await update.message.reply_text("❌ Minimum 1.")
            return
        set_ad_limit(limit)
        await update.message.reply_text(f"✅ Daily limit set to {limit}")
    except:
        await update.message.reply_text("❌ Invalid number.")

async def add_bypass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /add_bypass <user_id>")
        return
    try:
        add_ads_bypass(int(context.args[0]), update.effective_user.id)
        await update.message.reply_text(f"✅ Bypass added.")
    except:
        await update.message.reply_text("❌ Invalid ID.")

async def remove_bypass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /remove_bypass <user_id>")
        return
    try:
        remove_ads_bypass(int(context.args[0]))
        await update.message.reply_text(f"✅ Bypass removed.")
    except:
        await update.message.reply_text("❌ Invalid ID.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = "**📖 Commands:**\n\n"
    
    if is_admin(user_id):
        text += "/genlink - Create file link\n/batch - Batch range\n/done - Finish batch\n/cancel - Cancel\n"
        text += "/set_timer <s> - Set timer\n/set_admin_username <@user>\n/set_message1 <text>\n/set_message2 <text>\n"
        text += "/ads_on - Enable ads\n/ads_off - Disable ads\n/set_ad_limit <n>\n/add_bypass <id>\n/remove_bypass <id>\n"
    
    if user_id == OWNER_ID:
        text += "/addadmin <id>\n/removeadmin <id>\n"
    
    text += "\n**Users:** Click link → Watch ad → Get file"
    await update.message.reply_text(text, parse_mode='Markdown')

def run_flask():
    flask_app.run(host='0.0.0.0', port=10000, debug=False, use_reloader=False)

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("genlink", genlink))
    app.add_handler(CommandHandler("batch", batch))
    app.add_handler(CommandHandler("cancel", batch_cancel))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("removeadmin", removeadmin))
    app.add_handler(CommandHandler("admins", listadmins))
    app.add_handler(CommandHandler("set_timer", set_timer_cmd))
    app.add_handler(CommandHandler("set_admin_username", set_admin_username_cmd))
    app.add_handler(CommandHandler("set_message1", set_message1_cmd))
    app.add_handler(CommandHandler("set_message2", set_message2_cmd))
    app.add_handler(CommandHandler("show_messages", show_messages))
    app.add_handler(CommandHandler("ads_on", ads_on))
    app.add_handler(CommandHandler("ads_off", ads_off))
    app.add_handler(CommandHandler("ads_status", ads_status))
    app.add_handler(CommandHandler("set_ad_limit", set_ad_limit))
    app.add_handler(CommandHandler("add_bypass", add_bypass))
    app.add_handler(CommandHandler("remove_bypass", remove_bypass))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(player_info_callback, pattern="player_"))
    app.add_handler(CallbackQueryHandler(close_callback, pattern="close"))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.VIDEO | filters.PHOTO | filters.Document.ALL | filters.AUDIO, handle_file))
    app.add_handler(MessageHandler(filters.VIDEO | filters.PHOTO | filters.Document.ALL | filters.AUDIO, handle_batch_range))
    
    logger.info("Bot started with all features!")
    app.run_polling()

if __name__ == "__main__":
    main()
