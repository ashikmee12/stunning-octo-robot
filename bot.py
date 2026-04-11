# bot.py - COMPLETE FIXED VERSION
import asyncio
import threading
import json
import logging
import requests
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config import BOT_TOKEN, OWNER_ID, MINI_APP_URL
from database import *

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

init_db()
flask_app = Flask(__name__)

# Store multiple files for genlink
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
        logger.info(f"Callback received: {data}")
        
        status = data.get('status')
        user_id = data.get('user_id')
        file_code = data.get('file_code')
        batch_code = data.get('batch_code')
        is_batch = data.get('is_batch', False)
        
        if status == 'ad_completed' and user_id:
            if is_batch and batch_code:
                # Send all files in batch
                batch_files = get_batch_files(batch_code)
                if batch_files:
                    for file_id, file_type in batch_files:
                        if file_type == 'video':
                            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo", json={'chat_id': user_id, 'video': file_id})
                        elif file_type == 'photo':
                            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", json={'chat_id': user_id, 'photo': file_id})
                        elif file_type == 'document':
                            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument", json={'chat_id': user_id, 'document': file_id})
                        elif file_type == 'audio':
                            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio", json={'chat_id': user_id, 'audio': file_id})
                        asyncio.sleep(0.5)
                    logger.info(f"Batch {batch_code} sent to {user_id}")
                    
                    # Record ad view for batch
                    record_ad_view(user_id, batch_code)
                else:
                    logger.error(f"Batch not found: {batch_code}")
                    
            elif file_code:
                # Send single file
                file_data = get_file(file_code)
                if file_data:
                    file_id, file_type = file_data
                    if file_type == 'video':
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo", json={'chat_id': user_id, 'video': file_id})
                    elif file_type == 'photo':
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", json={'chat_id': user_id, 'photo': file_id})
                    elif file_type == 'document':
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument", json={'chat_id': user_id, 'document': file_id})
                    elif file_type == 'audio':
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio", json={'chat_id': user_id, 'audio': file_id})
                    logger.info(f"File {file_code} sent to {user_id}")
                    
                    # Record ad view for single file
                    record_ad_view(user_id, file_code)
                else:
                    logger.error(f"File not found: {file_code}")
        
        return jsonify({'status': 'ok'})
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"User {user_id} started with args: {context.args}")
    
    if context.args:
        code = context.args[0]
        
        if code.startswith("file_"):
            short_code = code.replace("file_", "")
            file_data = get_file(short_code)
            
            if file_data:
                file_id, file_type = file_data
                
                if has_viewed_ad(user_id, short_code):
                    await send_file_by_type(update, file_id, file_type)
                else:
                    mini_app_url = f"{MINI_APP_URL}?user_id={user_id}&file_code={short_code}&is_batch=false"
                    keyboard = [[InlineKeyboardButton("🎬 Watch Ad to Get File", web_app=WebAppInfo(url=mini_app_url))]]
                    await update.message.reply_text(
                        "📁 **Your file is ready!**\n\nClick the button below to watch an ad and get your file:",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
            else:
                await update.message.reply_text("❌ Invalid or expired link!")
                
        elif code.startswith("batch_"):
            batch_code = code.replace("batch_", "")
            batch_files = get_batch_files(batch_code)
            
            if batch_files:
                if has_viewed_ad(user_id, batch_code):
                    await update.message.reply_text(f"📦 Sending {len(batch_files)} files...")
                    for file_id, file_type in batch_files:
                        await send_file_by_type(update, file_id, file_type)
                        await asyncio.sleep(0.5)
                else:
                    mini_app_url = f"{MINI_APP_URL}?user_id={user_id}&batch_code={batch_code}&is_batch=true"
                    keyboard = [[InlineKeyboardButton("🎬 Watch Ad to Get All Files", web_app=WebAppInfo(url=mini_app_url))]]
                    await update.message.reply_text(
                        f"📦 **{len(batch_files)} files are ready!**\n\nWatch one ad and get all files instantly:",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
            else:
                await update.message.reply_text("❌ Invalid batch link!")
        else:
            await update.message.reply_text("👋 Welcome to File Store Bot!\n\nUse /help for commands.")
    else:
        await update.message.reply_text("👋 Welcome to File Store Bot!\n\nUse /help for commands.")

async def genlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    user_files[user_id] = []
    await update.message.reply_text(
        "📤 **File Collection Mode**\n\n"
        "Send me files (video, photo, document, or audio).\n"
        "You can send multiple files.\n\n"
        "Type **/done** when finished.\n"
        "Type **/cancel** to stop.\n\n"
        "💡 1 file = single link\n"
        "💡 Multiple files = batch link (watch ad once to get all)",
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
        await update.message.reply_text("❌ Please send video, photo, document, or audio only.")
        return
    
    short_code = generate_short_code()
    save_file(short_code, file_id, file_type, message.chat_id, message.message_id)
    user_files[user_id].append(short_code)
    
    count = len(user_files[user_id])
    await update.message.reply_text(f"✅ File #{count} added. Send more or type /done")

async def genlink_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_files:
        await update.message.reply_text("❌ No active session. Use /genlink first.")
        return
    
    files = user_files[user_id]
    
    if len(files) == 0:
        await update.message.reply_text("❌ No files received.")
        del user_files[user_id]
        return
    
    bot_username = context.bot.username
    
    if len(files) == 1:
        # Single file link
        file_link = f"https://t.me/{bot_username}?start=file_{files[0]}"
        await update.message.reply_text(
            f"✅ **Single File Link Created!**\n\n"
            f"🔗 `{file_link}`\n\n"
            f"💡 User will watch 1 ad to get this file.",
            parse_mode='Markdown'
        )
    else:
        # Multiple files - create batch
        batch_code = generate_short_code()
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
                c.execute("INSERT INTO batch_files (batch_id, file_id, file_index) VALUES (?, ?, ?)", 
                         (batch_id, result[0], idx))
        
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"✅ **Batch Link Created!**\n\n"
            f"📁 Total Files: {len(files)}\n"
            f"🔗 `{batch_link}`\n\n"
            f"💡 User will watch only 1 ad to get all {len(files)} files!",
            parse_mode='Markdown'
        )
    
    del user_files[user_id]

async def genlink_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in user_files:
        del user_files[user_id]
        await update.message.reply_text("❌ File collection cancelled.")
    else:
        await update.message.reply_text("❌ No active session.")

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

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin_user = is_admin(user_id)
    
    text = "**📖 Bot Commands:**\n\n"
    
    if is_admin_user:
        text += "**📁 File Commands:**\n"
        text += "🔹 `/genlink` - Create link (1 or multiple files)\n"
        text += "🔹 `/done` - Finish and get link\n"
        text += "🔹 `/cancel` - Cancel collection\n"
        text += "🔹 `/admins` - List all admins\n\n"
    
    if user_id == OWNER_ID:
        text += "**👑 Owner Commands:**\n"
        text += "🔹 `/addadmin <id>` - Add new admin\n"
        text += "🔹 `/removeadmin <id>` - Remove admin\n\n"
    
    text += "**👤 User Commands:**\n"
    text += "🔹 Click any file link → Watch ad → Get file\n"
    text += "🔹 Batch links: Watch 1 ad → Get all files\n\n"
    
    text += "**💡 How to use /genlink:**\n"
    text += "1. `/genlink` - Start collecting files\n"
    text += "2. Send files one by one\n"
    text += "3. `/done` - Get your link\n\n"
    text += "**📌 Note:**\n"
    text += "• 1 file = single link (1 ad)\n"
    text += "• Multiple files = batch link (1 ad for all)"
    
    await update.message.reply_text(text, parse_mode='Markdown')

def run_flask():
    flask_app.run(host='0.0.0.0', port=10000, debug=False, use_reloader=False)

def main():
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Build the bot application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("genlink", genlink))
    app.add_handler(CommandHandler("done", genlink_done))
    app.add_handler(CommandHandler("cancel", genlink_cancel))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("removeadmin", removeadmin))
    app.add_handler(CommandHandler("admins", listadmins))
    
    # Add message handlers
    app.add_handler(MessageHandler(filters.VIDEO | filters.PHOTO | filters.Document.ALL | filters.AUDIO, handle_genlink_file))
    
    logger.info("🤖 Bot is running with all features fixed!")
    print("🤖 Bot is running with all features fixed!")
    print(f"Mini App URL: {MINI_APP_URL}")
    
    # Start polling
    app.run_polling()

if __name__ == "__main__":
    main()
