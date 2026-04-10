# bot.py
import asyncio
import threading
import json
import logging
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from config import BOT_TOKEN, OWNER_ID, MINI_APP_URL
from database import *

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

init_db()
flask_app = Flask(__name__)

# Store temporary data
user_batch_data = {}

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
        logger.info(f"Callback received: {data}")
        
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
                    elif file_type == 'audio':
                        requests.post(f"https://api.telegram.org/bot{bot_token}/sendAudio", json={'chat_id': user_id, 'audio': file_id})
                    
                    logger.info(f"File {file_code} sent to {user_id}")
        
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    except Exception as e:
        logger.error(f"Callback error: {e}")
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
    else:
        await update.message.reply_text("File type not supported")

async def send_with_timer(update, text, timer_seconds=None, reply_markup=None):
    if timer_seconds is None:
        timer_seconds = get_timer()
    
    msg = await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    add_to_delete_queue(update.effective_chat.id, msg.message_id, timer_seconds)
    return msg

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"User {user_id} started with args: {context.args}")
    
    if context.args:
        file_code = context.args[0]
        
        if file_code.startswith("file_"):
            short_code = file_code.replace("file_", "")
            file_data = get_file(short_code)
            
            if file_data:
                file_id, file_type = file_data
                
                # Check force channels
                channels = get_force_channels()
                all_joined = True
                for ch in channels:
                    # Check if user joined (simplified)
                    pass
                
                if has_viewed_ad(user_id, short_code):
                    await send_file_by_type(update, file_id, file_type)
                    
                    # Send confirmation with forward button
                    timer = get_timer()
                    msg_text = get_message1().format(timer=timer)
                    
                    keyboard = [[InlineKeyboardButton("📝 Player Info", callback_data=f"player_{short_code}")]]
                    await send_with_timer(update, msg_text, timer, InlineKeyboardMarkup(keyboard))
                else:
                    context.user_data['pending_file'] = short_code
                    
                    keyboard = [[InlineKeyboardButton(
                        text="🎬 Watch Ad to Get File",
                        web_app=WebAppInfo(url=MINI_APP_URL)
                    )]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        "📁 **Your file is ready!**\n\n⚠️ Watch an ad to get your file.\n\nClick the button below:",
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
            else:
                await update.message.reply_text("❌ Invalid or expired link!")
        elif file_code.startswith("batch_"):
            batch_code = file_code.replace("batch_", "")
            batch_files = get_batch_files(batch_code)
            
            if batch_files:
                for file_id, file_type in batch_files:
                    await send_file_by_type(update, file_id, file_type)
                    await asyncio.sleep(1)
                
                timer = get_timer()
                msg_text = f"✅ Batch sent! {len(batch_files)} files delivered.\n\n⏰ This message will be deleted in {timer} seconds."
                await send_with_timer(update, msg_text, timer)
            else:
                await update.message.reply_text("❌ Invalid batch link!")
        else:
            await update.message.reply_text("👋 Welcome to File Store Bot!\n\nUse /help for commands.")
    else:
        await update.message.reply_text("👋 Welcome to File Store Bot!\n\nUse /help for commands.")

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
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    context.user_data['waiting_for_file'] = True
    await update.message.reply_text("📤 Forward me a file (video, photo, document, or audio) to generate a shareable link.")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_for_file'):
        message = update.effective_message
        user_id = update.effective_user.id
        
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
            await update.message.reply_text("❌ Please forward a valid file.")
            return
        
        short_code = generate_short_code()
        save_file(short_code, file_id, file_type, message.chat_id, message.message_id)
        
        bot_username = context.bot.username
        file_link = f"https://t.me/{bot_username}?start=file_{short_code}"
        
        msg_text = f"✅ **File stored successfully!**\n\n🔗 **Shareable Link:**\n`{file_link}`\n\n📁 **Short Code:** `{short_code}`\n📂 **Type:** {file_type}"
        
        await update.message.reply_text(msg_text, parse_mode='Markdown')
        context.user_data['waiting_for_file'] = False

async def batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    user_batch_data[user_id] = {'files': [], 'step': 'first'}
    await update.message.reply_text(
        "📦 **Batch Mode Activated**\n\n"
        "Send me the **FIRST** file (video/photo/document).\n\n"
        "Type /done when finished or /cancel to stop."
    )

async def handle_batch_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_batch_data:
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
        await update.message.reply_text("❌ Please send a valid file.")
        return
    
    short_code = generate_short_code()
    save_file(short_code, file_id, file_type, message.chat_id, message.message_id)
    user_batch_data[user_id]['files'].append(short_code)
    
    count = len(user_batch_data[user_id]['files'])
    await update.message.reply_text(f"✅ File #{count} added.\n\nSend next file or type /done to finish.")

async def batch_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_batch_data:
        await update.message.reply_text("❌ No active batch session.")
        return
    
    files = user_batch_data[user_id]['files']
    
    if len(files) < 2:
        await update.message.reply_text("❌ Batch needs at least 2 files. Use /genlink for single file.")
        del user_batch_data[user_id]
        return
    
    batch_code = generate_short_code()
    bot_username = context.bot.username
    batch_link = f"https://t.me/{bot_username}?start=batch_{batch_code}"
    
    # Save to database
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO batches (batch_code, chat_id, total_files) VALUES (?, ?, ?)", 
              (batch_code, update.effective_chat.id, len(files)))
    batch_id = c.lastrowid
    
    for idx, file_code in enumerate(files):
        c.execute("SELECT id FROM files WHERE short_code = ?", (file_code,))
        result = c.fetchone()
        if result:
            file_id = result[0]
            c.execute("INSERT INTO batch_files (batch_id, file_id, file_index) VALUES (?, ?, ?)", 
                      (batch_id, file_id, idx))
    
    conn.commit()
    conn.close()
    
    await update.message.reply_text(
        f"✅ **Batch Created Successfully!**\n\n"
        f"📦 **Total Files:** {len(files)}\n\n"
        f"🔗 **Batch Link:**\n`{batch_link}`\n\n"
        f"💡 Users will get all files one by one.",
        parse_mode='Markdown'
    )
    
    del user_batch_data[user_id]

async def batch_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in user_batch_data:
        del user_batch_data[user_id]
        await update.message.reply_text("❌ Batch mode cancelled.")
    else:
        await update.message.reply_text("❌ No active batch session.")

async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only owner can add admins.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /addadmin <user_id>")
        return
    
    try:
        new_admin_id = int(context.args[0])
        add_admin(new_admin_id, user_id)
        await update.message.reply_text(f"✅ User `{new_admin_id}` is now an admin.", parse_mode='Markdown')
        logger.info(f"Owner {user_id} added admin {new_admin_id}")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only owner can remove admins.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /removeadmin <user_id>")
        return
    
    try:
        admin_id = int(context.args[0])
        remove_admin(admin_id)
        await update.message.reply_text(f"✅ User `{admin_id}` removed from admins.", parse_mode='Markdown')
        logger.info(f"Owner {user_id} removed admin {admin_id}")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    admins = get_all_admins()
    if not admins:
        await update.message.reply_text("No admins found.")
        return
    
    text = "**👥 Admin List:**\n\n"
    for admin_id, is_owner in admins:
        role = "👑 Owner" if is_owner else "👤 Admin"
        text += f"• `{admin_id}` - {role}\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def set_timer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    if not context.args:
        await update.message.reply_text(f"Current timer: {get_timer()} seconds\n\nUsage: /set_timer <seconds>")
        return
    
    try:
        seconds = int(context.args[0])
        if seconds < 10:
            await update.message.reply_text("❌ Timer must be at least 10 seconds.")
            return
        
        set_timer(seconds, user_id)
        await update.message.reply_text(f"✅ Timer set to {seconds} seconds.\n\nMessages will auto-delete after {seconds} seconds.")
        logger.info(f"Admin {user_id} set timer to {seconds}")
    except ValueError:
        await update.message.reply_text("❌ Invalid number.")

async def set_admin_username_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    if not context.args:
        await update.message.reply_text(f"Current admin username: {get_admin_username()}\n\nUsage: /set_admin_username <@username>")
        return
    
    username = context.args[0]
    if not username.startswith('@'):
        username = '@' + username
    
    set_admin_username(username, user_id)
    await update.message.reply_text(f"✅ Admin username set to {username}")

async def set_message1_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /set_message1 <your message text>\n\nUse {timer} as placeholder for timer value.")
        return
    
    new_message = ' '.join(context.args)
    set_setting('message1_text', new_message, user_id)
    await update.message.reply_text("✅ Message 1 updated successfully!")

async def set_message2_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /set_message2 <your message text>\n\nUse {admin_username} as placeholder for admin username.")
        return
    
    new_message = ' '.join(context.args)
    set_setting('message2_text', new_message, user_id)
    await update.message.reply_text("✅ Message 2 updated successfully!")

async def show_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    msg1 = get_message1()
    msg2 = get_message2()
    timer = get_timer()
    admin_username = get_admin_username()
    
    await update.message.reply_text(
        f"**📊 Current Settings:**\n\n"
        f"**Timer:** {timer} seconds\n"
        f"**Admin Username:** {admin_username}\n\n"
        f"**Message 1:**\n{msg1}\n\n"
        f"**Message 2:**\n{msg2}",
        parse_mode='Markdown'
    )

async def ads_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    set_ads_enabled(True)
    await update.message.reply_text("✅ **Ads Enabled**\n\nUsers will see ads before downloading files.")

async def ads_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    set_ads_enabled(False)
    await update.message.reply_text("✅ **Ads Disabled**\n\nUsers will get files directly without ads.")

async def ads_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    enabled = is_ads_enabled()
    limit = get_ad_limit()
    bypass_count = len(get_bypass_list())
    
    status = "ON ✅" if enabled else "OFF ❌"
    
    await update.message.reply_text(
        f"**📊 Ads Status**\n\n"
        f"**Status:** {status}\n"
        f"**Daily Limit:** {limit} ads per user\n"
        f"**Bypass Users:** {bypass_count}\n\n"
        f"**Commands:**\n"
        f"• `/set_ad_limit <number>` - Set daily limit\n"
        f"• `/add_bypass <user_id>` - Add bypass user\n"
        f"• `/remove_bypass <user_id>` - Remove bypass user",
        parse_mode='Markdown'
    )

async def set_ad_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    if not context.args:
        await update.message.reply_text(f"Current daily limit: {get_ad_limit()}\n\nUsage: /set_ad_limit <number>")
        return
    
    try:
        limit = int(context.args[0])
        if limit < 1:
            await update.message.reply_text("❌ Limit must be at least 1.")
            return
        
        set_ad_limit(limit)
        await update.message.reply_text(f"✅ Daily ad limit set to {limit} ads per user.")
    except ValueError:
        await update.message.reply_text("❌ Invalid number.")

async def add_bypass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /add_bypass <user_id>")
        return
    
    try:
        target_id = int(context.args[0])
        add_ads_bypass(target_id, user_id)
        await update.message.reply_text(f"✅ User `{target_id}` can now download without ads.", parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def remove_bypass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /remove_bypass <user_id>")
        return
    
    try:
        target_id = int(context.args[0])
        remove_ads_bypass(target_id)
        await update.message.reply_text(f"✅ User `{target_id}` removed from bypass list.", parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /add_channel <@username> or <invite_link>")
        return
    
    channel_input = context.args[0]
    add_force_channel(channel_input, None, channel_input, user_id)
    await update.message.reply_text(f"✅ Channel {channel_input} added to force join list.")

async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /remove_channel <channel_id>")
        return
    
    try:
        channel_id = int(context.args[0])
        remove_force_channel(channel_id)
        await update.message.reply_text(f"✅ Channel removed from force join list.")
    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID.")

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    
    channels = get_force_channels()
    if not channels:
        await update.message.reply_text("No force channels configured.")
        return
    
    text = "**📢 Force Channels:**\n\n"
    for ch_id, username, chat_id, invite_link in channels:
        text += f"• {username or invite_link}\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin_user = is_admin(user_id)
    
    text = "**📖 Bot Commands:**\n\n"
    
    if is_admin_user:
        text += "**📁 File Commands:**\n"
        text += "🔹 `/genlink` - Generate shareable link for a file\n"
        text += "🔹 `/batch` - Create batch link for multiple files\n"
        text += "🔹 `/done` - Finish batch creation\n"
        text += "🔹 `/cancel` - Cancel batch mode\n\n"
        
        text += "**⚙️ Settings:**\n"
        text += "🔹 `/set_timer <seconds>` - Set auto-delete timer\n"
        text += "🔹 `/set_admin_username <@username>` - Set admin contact\n"
        text += "🔹 `/set_message1 <text>` - Edit confirmation message\n"
        text += "🔹 `/set_message2 <text>` - Edit player info message\n"
        text += "🔹 `/show_messages` - Show current messages\n\n"
        
        text += "**📢 Ads Control:**\n"
        text += "🔹 `/ads_on` - Enable ads\n"
        text += "🔹 `/ads_off` - Disable ads\n"
        text += "🔹 `/ads_status` - Show ads settings\n"
        text += "🔹 `/set_ad_limit <number>` - Set daily ad limit\n"
        text += "🔹 `/add_bypass <user_id>` - Add ad bypass user\n"
        text += "🔹 `/remove_bypass <user_id>` - Remove ad bypass user\n\n"
        
        text += "**🔗 Force Channels:**\n"
        text += "🔹 `/add_channel <@username>` - Add force join channel\n"
        text += "🔹 `/remove_channel <id>` - Remove force channel\n"
        text += "🔹 `/channels` - List force channels\n\n"
        
        text += "**👥 Admin Management:**\n"
        text += "🔹 `/admins` - List all admins\n"
    
    if user_id == OWNER_ID:
        text += "**👑 Owner Commands:**\n"
        text += "🔹 `/addadmin <id>` - Add new admin\n"
        text += "🔹 `/removeadmin <id>` - Remove admin\n\n"
    
    text += "**👤 User Commands:**\n"
    text += "🔹 `/start` - Start the bot\n"
    text += "🔹 `/help` - Show this help\n\n"
    
    text += "**💡 How to use:**\n"
    text += "1. Click any file link\n"
    text += "2. Watch ad\n"
    text += "3. Get file automatically"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def delete_expired_messages():
    while True:
        try:
            messages = get_expired_messages()
            # Note: Need bot instance to delete messages
            for msg_id, chat_id, message_id in messages:
                delete_from_queue(msg_id)
        except:
            pass
        await asyncio.sleep(30)

def run_flask():
    flask_app.run(host='0.0.0.0', port=10000, debug=False, use_reloader=False)

def main():
    # Start Flask
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start background task
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(delete_expired_messages())
    
    # Build bot
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("genlink", genlink))
    app.add_handler(CommandHandler("batch", batch))
    app.add_handler(CommandHandler("done", batch_done))
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
    app.add_handler(CommandHandler("add_channel", add_channel))
    app.add_handler(CommandHandler("remove_channel", remove_channel))
    app.add_handler(CommandHandler("channels", list_channels))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(player_info_callback, pattern="player_"))
    app.add_handler(CallbackQueryHandler(close_callback, pattern="close"))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.VIDEO | filters.PHOTO | filters.DOCUMENT | filters.AUDIO, handle_file))
    app.add_handler(MessageHandler(filters.VIDEO | filters.PHOTO | filters.DOCUMENT | filters.AUDIO, handle_batch_file))
    
    logger.info("🤖 Bot is running with all features!")
    print("🤖 Bot is running with all features!")
    
    app.run_polling()

if __name__ == "__main__":
    main()
