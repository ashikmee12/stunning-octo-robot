# bot.py
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

# Store user file mapping temporarily
user_file_map = {}

@flask_app.route('/')
def health_check():
    return "Bot is running!"

@flask_app.route('/ad-callback', methods=['POST'])
def ad_callback():
    try:
        data = request.get_json()
        logger.info(f"Callback received: {data}")
        
        status = data.get('status')
        file_code = data.get('file_code')
        user_id = data.get('user_id')
        
        if status == 'ad_completed' and file_code and user_id:
            # Mark ad as viewed
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("INSERT INTO ad_views (user_id, short_code) VALUES (?, ?)", (user_id, file_code))
            conn.commit()
            conn.close()
            
            # Get file and send
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
    else:
        await update.message.reply_text("File sent")

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
                
                # Check if already viewed ad
                conn = sqlite3.connect(DB_NAME)
                c = conn.cursor()
                c.execute("SELECT 1 FROM ad_views WHERE user_id = ? AND short_code = ?", (user_id, short_code))
                viewed = c.fetchone()
                conn.close()
                
                if viewed:
                    await send_file_by_type(update, file_id, file_type)
                else:
                    # Store for callback
                    user_file_map[user_id] = short_code
                    
                    keyboard = [[InlineKeyboardButton(
                        text="🎬 Watch Ad & Get File",
                        web_app=WebAppInfo(url=MINI_APP_URL)
                    )]]
                    
                    await update.message.reply_text(
                        "📁 **Your file is ready!**\n\nClick the button below to watch an ad and get your file:",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
            else:
                await update.message.reply_text("❌ Invalid or expired link!")
        else:
            await update.message.reply_text("👋 Welcome!\nUse /help for commands.")
    else:
        await update.message.reply_text("👋 Welcome!\nUse /help for commands.")

async def genlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    context.user_data['waiting_for_file'] = True
    await update.message.reply_text("📤 Forward me a file (video/photo/document) to get a link.")

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
        else:
            await update.message.reply_text("❌ Send video, photo, or document.")
            return
        
        short_code = generate_short_code()
        save_file(short_code, file_id, file_type, message.chat_id, message.message_id)
        
        bot_username = context.bot.username
        file_link = f"https://t.me/{bot_username}?start=file_{short_code}"
        
        await update.message.reply_text(
            f"✅ **Link created!**\n\n`{file_link}`\n\nCode: `{short_code}`",
            parse_mode='Markdown'
        )
        context.user_data['waiting_for_file'] = False

# Batch command - Simple version
user_batch_data = {}

async def batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    user_batch_data[user_id] = {'files': [], 'step': 'first'}
    await update.message.reply_text("📦 **Batch Mode**\n\nSend me the FIRST file (or /cancel to stop)")

async def handle_batch_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_batch_data:
        return
    
    message = update.effective_message
    
    # Get file
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
        await update.message.reply_text("❌ Send valid file.")
        return
    
    # Save file temporarily
    short_code = generate_short_code()
    save_file(short_code, file_id, file_type, message.chat_id, message.message_id)
    user_batch_data[user_id]['files'].append(short_code)
    
    if user_batch_data[user_id]['step'] == 'first':
        user_batch_data[user_id]['step'] = 'more'
        await update.message.reply_text(f"✅ File {len(user_batch_data[user_id]['files'])} added.\n\nSend NEXT file or type /done to finish.")
    else:
        await update.message.reply_text(f"✅ File {len(user_batch_data[user_id]['files'])} added.\n\nSend NEXT file or /done to finish.")

async def batch_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_batch_data:
        await update.message.reply_text("❌ No active batch.")
        return
    
    files = user_batch_data[user_id]['files']
    if len(files) < 2:
        await update.message.reply_text("❌ Need at least 2 files for batch.")
        del user_batch_data[user_id]
        return
    
    # Create batch code
    batch_code = generate_short_code()
    bot_username = context.bot.username
    batch_link = f"https://t.me/{bot_username}?start=batch_{batch_code}"
    
    # Save batch to database
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO batches (batch_code, total_files) VALUES (?, ?)", (batch_code, len(files)))
    batch_id = c.lastrowid
    
    for idx, file_code in enumerate(files):
        c.execute("SELECT id FROM files WHERE short_code = ?", (file_code,))
        file_id = c.fetchone()[0]
        c.execute("INSERT INTO batch_files (batch_id, file_id, file_index) VALUES (?, ?, ?)", (batch_id, file_id, idx))
    
    conn.commit()
    conn.close()
    
    await update.message.reply_text(
        f"✅ **Batch created!**\n\n{len(files)} files\n\n🔗 **Link:**\n`{batch_link}`",
        parse_mode='Markdown'
    )
    del user_batch_data[user_id]

async def batch_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_batch_data:
        del user_batch_data[user_id]
        await update.message.reply_text("❌ Batch cancelled.")

# Admin commands
async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /addadmin <user_id>")
        return
    try:
        new_admin = int(context.args[0])
        add_admin(new_admin, OWNER_ID)
        await update.message.reply_text(f"✅ Added admin: {new_admin}")
    except:
        await update.message.reply_text("❌ Invalid ID.")

async def removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /removeadmin <user_id>")
        return
    try:
        admin_id = int(context.args[0])
        remove_admin(admin_id)
        await update.message.reply_text(f"✅ Removed admin: {admin_id}")
    except:
        await update.message.reply_text("❌ Invalid ID.")

async def listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    admins = get_all_admins()
    text = "**Admins:**\n"
    for uid, owner in admins:
        text += f"• `{uid}` - {'👑 Owner' if owner else '👤 Admin'}\n"
    await update.message.reply_text(text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = "**📖 Commands:**\n\n"
    
    if is_admin(user_id):
        text += "/genlink - Create file link\n"
        text += "/batch - Create batch link\n"
        text += "/admins - List admins\n"
        text += "/done - Finish batch\n"
        text += "/cancel - Cancel batch\n\n"
    
    if user_id == OWNER_ID:
        text += "/addadmin <id> - Add admin\n"
        text += "/removeadmin <id> - Remove admin\n\n"
    
    text += "**Users:**\nClick any link → Watch ad → Get file"
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
    app.add_handler(CommandHandler("done", batch_done))
    app.add_handler(CommandHandler("cancel", batch_cancel))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("removeadmin", removeadmin))
    app.add_handler(CommandHandler("admins", listadmins))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.VIDEO | filters.PHOTO | filters.DOCUMENT, handle_file))
    app.add_handler(MessageHandler(filters.VIDEO | filters.PHOTO | filters.DOCUMENT, handle_batch_file))
    
    logger.info("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
