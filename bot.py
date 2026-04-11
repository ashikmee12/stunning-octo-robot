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
                
                if has_viewed_ad(user_id, short_code):
                    await send_file_by_type(update, file_id, file_type)
                else:
                    # FIXED: Send user_id and file_code in URL
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
            else:
                await update.message.reply_text("❌ Invalid batch link!")
        else:
            await update.message.reply_text("Welcome! Use /help")
    else:
        await update.message.reply_text("Welcome! Use /help")

# ============ UNIVERSAL GENLINK ============

async def genlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    user_files[user_id] = []
    await update.message.reply_text(
        "📤 **Send me files** (video/photo/document)\n\n"
        "You can send multiple files one by one.\n"
        "Type **/done** when finished.\n"
        "Type **/cancel** to stop."
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
    else:
        await update.message.reply_text("❌ Send video, photo or document only.")
        return
    
    short_code = generate_short_code()
    save_file(short_code, file_id, file_type, message.chat_id, message.message_id)
    user_files[user_id].append(short_code)
    
    count = len(user_files[user_id])
    await update.message.reply_text(f"✅ File #{count} added. Send more or type /done")

async def genlink_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_files:
        await update.message.reply_text("❌ No active session.")
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
        await update.message.reply_text(f"✅ **Link:**\n`{file_link}`", parse_mode='Markdown')
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
                c.execute("INSERT INTO batch_files (batch_id, file_id, file_index) VALUES (?, ?, ?)", (batch_id, result[0], idx))
        
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"✅ **Batch Link Created!**\n\n"
            f"📁 Total files: {len(files)}\n"
            f"🔗 `{batch_link}`",
            parse_mode='Markdown'
        )
    
    del user_files[user_id]

async def genlink_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_files:
        del user_files[user_id]
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

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = "**📖 Commands:**\n\n"
    
    if is_admin(user_id):
        text += "/genlink - Create link (1 or multiple files)\n"
        text += "/done - Finish and get link\n"
        text += "/cancel - Cancel\n"
        text += "/admins - List admins\n"
    
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
    app.add_handler(CommandHandler("done", genlink_done))
    app.add_handler(CommandHandler("cancel", genlink_cancel))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("removeadmin", removeadmin))
    app.add_handler(CommandHandler("admins", listadmins))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.VIDEO | filters.PHOTO | filters.Document.ALL, handle_genlink_file))
    
    logger.info("Bot started with Universal Genlink!")
    app.run_polling()

if __name__ == "__main__":
    main()
