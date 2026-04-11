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

user_files = {}

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
            user_id = data.get('user_id')
            file_code = data.get('file_code')
            batch_code = data.get('batch_code')
            is_batch = data.get('is_batch', False)
            
            if user_id:
                if is_batch and batch_code:
                    record_ad_view(user_id, batch_code)
                    batch_files = get_batch_files(batch_code)
                    if batch_files:
                        for file_id, file_type in batch_files:
                            send_file_via_api(user_id, file_id, file_type)
                            import time; time.sleep(0.5)
                elif file_code:
                    record_ad_view(user_id, file_code)
                    file_data = get_file(file_code)
                    if file_data:
                        file_id, file_type = file_data
                        send_file_via_api(user_id, file_id, file_type)
        
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'status': 'error'}), 500

def send_file_via_api(user_id, file_id, file_type):
    bot_token = BOT_TOKEN
    if file_type == 'video':
        requests.post(f"https://api.telegram.org/bot{bot_token}/sendVideo", json={'chat_id': user_id, 'video': file_id})
    elif file_type == 'photo':
        requests.post(f"https://api.telegram.org/bot{bot_token}/sendPhoto", json={'chat_id': user_id, 'photo': file_id})
    elif file_type == 'document':
        requests.post(f"https://api.telegram.org/bot{bot_token}/sendDocument", json={'chat_id': user_id, 'document': file_id})
    elif file_type == 'audio':
        requests.post(f"https://api.telegram.org/bot{bot_token}/sendAudio", json={'chat_id': user_id, 'audio': file_id})

async def send_file_by_type(update, file_id, file_type):
    if file_type == 'video':
        await update.message.reply_video(file_id)
    elif file_type == 'photo':
        await update.message.reply_photo(file_id)
    elif file_type == 'document':
        await update.message.reply_document(file_id)
    elif file_type == 'audio':
        await update.message.reply_audio(file_id)

async def send_with_timer(update, text, timer_seconds, reply_markup=None):
    """Send message and schedule deletion"""
    msg = await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    # Schedule deletion
    async def delete_msg():
        await asyncio.sleep(timer_seconds)
        try:
            await msg.delete()
            logger.info(f"Deleted message {msg.message_id} after {timer_seconds}s")
        except Exception as e:
            logger.error(f"Failed to delete: {e}")
    
    asyncio.create_task(delete_msg())
    return msg

async def check_force_channels(user_id):
    channels = get_force_channels()
    return True, []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    joined, not_joined = await check_force_channels(user_id)
    if not joined:
        await update.message.reply_text("🔒 Please join channels first.")
        return
    
    if context.args:
        code = context.args[0]
        
        if code.startswith("file_"):
            short_code = code.replace("file_", "")
            file_data = get_file(short_code)
            
            if file_data:
                file_id, file_type = file_data
                ads_enabled = is_ads_enabled()
                is_bypass = is_ads_bypass(user_id)
                
                if not ads_enabled or is_bypass or has_viewed_ad(user_id, short_code):
                    # Send file
                    await send_file_by_type(update, file_id, file_type)
                    
                    # Send Message 1 with timer
                    timer = get_timer()
                    msg_text = get_message1().format(timer=timer)
                    keyboard = [[InlineKeyboardButton("📝 Player Info", callback_data="player")]]
                    await send_with_timer(update, msg_text, timer, InlineKeyboardMarkup(keyboard))
                else:
                    mini_app_url = f"{MINI_APP_URL}?user_id={user_id}&file_code={short_code}&is_batch=false"
                    keyboard = [[InlineKeyboardButton("🎬 Watch Ad", web_app=WebAppInfo(url=mini_app_url))]]
                    await update.message.reply_text("Click below to get your file:", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await update.message.reply_text("Invalid link!")
                
        elif code.startswith("batch_"):
            batch_code = code.replace("batch_", "")
            batch_files = get_batch_files(batch_code)
            
            if batch_files:
                ads_enabled = is_ads_enabled()
                is_bypass = is_ads_bypass(user_id)
                
                if not ads_enabled or is_bypass or has_viewed_ad(user_id, batch_code):
                    await update.message.reply_text(f"Sending {len(batch_files)} files...")
                    for file_id, file_type in batch_files:
                        await send_file_by_type(update, file_id, file_type)
                        await asyncio.sleep(0.5)
                    
                    timer = get_timer()
                    msg_text = f"✅ Batch sent! {len(batch_files)} files delivered.\n\n⏰ This message will be deleted in {timer} seconds."
                    await send_with_timer(update, msg_text, timer)
                else:
                    mini_app_url = f"{MINI_APP_URL}?user_id={user_id}&batch_code={batch_code}&is_batch=true"
                    keyboard = [[InlineKeyboardButton("🎬 Watch Ad (1 ad for all)", web_app=WebAppInfo(url=mini_app_url))]]
                    await update.message.reply_text(f"📦 {len(batch_files)} files ready! Watch 1 ad to get all:", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await update.message.reply_text("Invalid batch link!")
        else:
            await update.message.reply_text("Welcome! Use /help")
    else:
        await update.message.reply_text("Welcome! Use /help")

async def player_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin_username = get_admin_username()
    msg_text = get_message2().format(admin_username=admin_username)
    keyboard = [[InlineKeyboardButton("❌ Close", callback_data="close")]]
    
    # Send Message 2 (no timer, permanent)
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
    user_files[user_id] = []
    await update.message.reply_text(
        "📤 **File Collection Mode**\n\n"
        "Send me files. Type /done when finished, /cancel to stop.\n\n"
        "💡 1 file = single link\n"
        "💡 Multiple files = batch link (1 ad for all)",
        parse_mode='Markdown'
    )

async def handle_genlink_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_files:
        return
    
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
        await update.message.reply_text("Send video, photo, document, or audio only.")
        return
    
    short_code = generate_short_code()
    save_file(short_code, file_id, file_type, message.chat_id, message.message_id)
    user_files[user_id].append(short_code)
    
    count = len(user_files[user_id])
    await update.message.reply_text(f"✅ File #{count} added. Send more or /done")

async def genlink_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_files:
        await update.message.reply_text("No active session. Use /genlink first.")
        return
    
    files = user_files[user_id]
    if len(files) == 0:
        await update.message.reply_text("No files received.")
        del user_files[user_id]
        return
    
    bot_username = context.bot.username
    
    if len(files) == 1:
        link = f"https://t.me/{bot_username}?start=file_{files[0]}"
        await update.message.reply_text(
            f"✅ **Single File Link Created!**\n\n🔗 `{link}`\n\nUser will watch 1 ad.",
            parse_mode='Markdown'
        )
    else:
        batch_code = generate_short_code()
        link = f"https://t.me/{bot_username}?start=batch_{batch_code}"
        
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO batches (batch_code, chat_id, total_files) VALUES (?, ?, ?)", 
                  (batch_code, update.effective_chat.id, len(files)))
        batch_id = c.lastrowid
        
        for idx, fc in enumerate(files):
            c.execute("SELECT id FROM files WHERE short_code = ?", (fc,))
            r = c.fetchone()
            if r:
                c.execute("INSERT INTO batch_files (batch_id, file_id, file_index) VALUES (?, ?, ?)", 
                         (batch_id, r[0], idx))
        
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"✅ **Batch Link Created!**\n\n📁 {len(files)} files\n🔗 `{link}`\n\nUser will watch only 1 ad to get all!",
            parse_mode='Markdown'
        )
    
    del user_files[user_id]

async def genlink_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_files:
        del user_files[user_id]
        await update.message.reply_text("Cancelled.")
    else:
        await update.message.reply_text("No active session.")

# ============ ADMIN COMMANDS ============

async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /addadmin <user_id>")
        return
    try:
        new_admin_id = int(context.args[0])
        add_admin(new_admin_id, update.effective_user.id)
        await update.message.reply_text(f"✅ User `{new_admin_id}` is now an admin.", parse_mode='Markdown')
    except:
        await update.message.reply_text("Invalid user ID.")

async def removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /removeadmin <user_id>")
        return
    try:
        admin_id = int(context.args[0])
        remove_admin(admin_id)
        await update.message.reply_text(f"✅ User `{admin_id}` removed.", parse_mode='Markdown')
    except:
        await update.message.reply_text("Invalid user ID.")

async def listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    admins = get_all_admins()
    if not admins:
        await update.message.reply_text("No admins.")
        return
    text = "**👥 Admin List:**\n\n"
    for admin_id, is_owner in admins:
        role = "👑 Owner" if is_owner else "👤 Admin"
        text += f"• `{admin_id}` - {role}\n"
    await update.message.reply_text(text, parse_mode='Markdown')

async def set_timer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    if not context.args:
        current = get_timer()
        await update.message.reply_text(f"Current timer: {current} seconds\nUsage: /set_timer <seconds>")
        return
    try:
        seconds = int(context.args[0])
        if seconds < 10:
            await update.message.reply_text("Minimum 10 seconds.")
            return
        set_timer(seconds, update.effective_user.id)
        await update.message.reply_text(f"✅ Timer set to {seconds} seconds.")
    except:
        await update.message.reply_text("Invalid number.")

async def set_admin_username_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    if not context.args:
        await update.message.reply_text(f"Current: {get_admin_username()}\nUsage: /set_admin_username <@username>")
        return
    username = context.args[0]
    if not username.startswith('@'):
        username = '@' + username
    set_admin_username(username, update.effective_user.id)
    await update.message.reply_text(f"✅ Admin username set to {username}")

async def set_message1_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /set_message1 <text> (use {timer})")
        return
    new_message = ' '.join(context.args)
    set_setting('message1_text', new_message, update.effective_user.id)
    await update.message.reply_text("✅ Message 1 updated.")

async def set_message2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /set_message2 <text> (use {admin_username})")
        return
    new_message = ' '.join(context.args)
    set_setting('message2_text', new_message, update.effective_user.id)
    await update.message.reply_text("✅ Message 2 updated.")

async def show_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    timer = get_timer()
    admin_username = get_admin_username()
    msg1 = get_message1()
    msg2 = get_message2()
    
    await update.message.reply_text(
        f"**📊 Settings:**\n\n"
        f"**Timer:** {timer} seconds\n"
        f"**Admin:** {admin_username}\n\n"
        f"**Msg1:** {msg1}\n\n"
        f"**Msg2:** {msg2}",
        parse_mode='Markdown'
    )

async def ads_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    set_ads_enabled(True)
    await update.message.reply_text("✅ Ads enabled.")

async def ads_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    set_ads_enabled(False)
    await update.message.reply_text("✅ Ads disabled.")

async def ads_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    enabled = is_ads_enabled()
    limit = get_ad_limit()
    bypass_count = len(get_bypass_list())
    status = "ON ✅" if enabled else "OFF ❌"
    await update.message.reply_text(
        f"**Ads:** {status}\n**Daily Limit:** {limit}\n**Bypass Users:** {bypass_count}",
        parse_mode='Markdown'
    )

async def set_ad_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    if not context.args:
        await update.message.reply_text(f"Current: {get_ad_limit()}\nUsage: /set_ad_limit <number>")
        return
    try:
        limit = int(context.args[0])
        if limit < 1:
            await update.message.reply_text("Minimum 1.")
            return
        set_ad_limit(limit)
        await update.message.reply_text(f"✅ Daily limit set to {limit}.")
    except:
        await update.message.reply_text("Invalid number.")

async def add_bypass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /add_bypass <user_id>")
        return
    try:
        target_id = int(context.args[0])
        add_ads_bypass(target_id, update.effective_user.id)
        await update.message.reply_text(f"✅ Bypass added for `{target_id}`.", parse_mode='Markdown')
    except:
        await update.message.reply_text("Invalid ID.")

async def remove_bypass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /remove_bypass <user_id>")
        return
    try:
        target_id = int(context.args[0])
        remove_ads_bypass(target_id)
        await update.message.reply_text(f"✅ Bypass removed for `{target_id}`.", parse_mode='Markdown')
    except:
        await update.message.reply_text("Invalid ID.")

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /add_channel <@username>")
        return
    channel_input = context.args[0]
    add_force_channel(channel_input, None, channel_input, update.effective_user.id)
    await update.message.reply_text(f"✅ Channel {channel_input} added.")

async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /remove_channel <id>")
        return
    try:
        channel_id = int(context.args[0])
        remove_force_channel(channel_id)
        await update.message.reply_text(f"✅ Channel removed.")
    except:
        await update.message.reply_text("Invalid ID.")

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    channels = get_force_channels()
    if not channels:
        await update.message.reply_text("No force channels.")
        return
    text = "**📢 Force Channels:**\n"
    for ch_id, username, chat_id, invite_link in channels:
        text += f"• {username or invite_link}\n"
    await update.message.reply_text(text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin_user = is_admin(user_id)
    
    text = "**📖 Bot Commands:**\n\n"
    
    if is_admin_user:
        text += "**📁 File:**\n/genlink, /done, /cancel\n\n"
        text += "**⚙️ Settings:**\n/set_timer, /set_admin_username, /set_message1, /set_message2, /show_messages\n\n"
        text += "**📢 Ads:**\n/ads_on, /ads_off, /ads_status, /set_ad_limit, /add_bypass, /remove_bypass\n\n"
        text += "**🔗 Force Channel:**\n/add_channel, /remove_channel, /channels\n\n"
        text += "**👥 Admin:**\n/admins\n"
    
    if user_id == OWNER_ID:
        text += "**👑 Owner:**\n/addadmin, /removeadmin\n\n"
    
    text += "**💡 Users:** Click link → Watch ad → Get file"
    
    await update.message.reply_text(text, parse_mode='Markdown')

def run_flask():
    flask_app.run(host='0.0.0.0', port=10000, debug=False, use_reloader=False)

def main():
    # Start Flask
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Build bot
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("genlink", genlink))
    app.add_handler(CommandHandler("done", genlink_done))
    app.add_handler(CommandHandler("cancel", genlink_cancel))
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
    app.add_handler(CommandHandler("add_channel", add_channel))
    app.add_handler(CommandHandler("remove_channel", remove_channel))
    app.add_handler(CommandHandler("channels", list_channels))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(player_info_callback, pattern="player"))
    app.add_handler(CallbackQueryHandler(close_callback, pattern="close"))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.VIDEO | filters.PHOTO | filters.Document.ALL | filters.AUDIO, handle_genlink_file))
    
    logger.info("✅ Bot started with Timer working!")
    print("✅ Bot started with Timer working!")
    
    app.run_polling()

if __name__ == "__main__":
    main()
