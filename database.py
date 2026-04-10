# database.py
import sqlite3
import random
import string
from datetime import datetime, timedelta
from config import DB_NAME, OWNER_ID, DEFAULT_TIMER_SECONDS, DEFAULT_ADS_ENABLED, DEFAULT_DAILY_AD_LIMIT, DEFAULT_MESSAGE1, DEFAULT_MESSAGE2, DEFAULT_FORWARD_TEXT

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Files table
    c.execute('''CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        short_code TEXT UNIQUE,
        file_id TEXT,
        file_type TEXT,
        chat_id INTEGER,
        message_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Admins table
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        added_by INTEGER,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_owner BOOLEAN DEFAULT 0
    )''')
    
    # Ad views table
    c.execute('''CREATE TABLE IF NOT EXISTS ad_views (
        user_id INTEGER,
        short_code TEXT,
        viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed BOOLEAN DEFAULT 0
    )''')
    
    # Bot settings table
    c.execute('''CREATE TABLE IF NOT EXISTS bot_settings (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT,
        updated_by INTEGER,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Ads settings table
    c.execute('''CREATE TABLE IF NOT EXISTS ads_settings (
        id INTEGER PRIMARY KEY,
        is_enabled BOOLEAN DEFAULT 1,
        daily_limit INTEGER DEFAULT 3
    )''')
    
    # User ad counts table
    c.execute('''CREATE TABLE IF NOT EXISTS user_ad_counts (
        user_id INTEGER PRIMARY KEY,
        count INTEGER DEFAULT 0,
        last_reset_date DATE
    )''')
    
    # Ads bypass users
    c.execute('''CREATE TABLE IF NOT EXISTS ads_bypass (
        user_id INTEGER PRIMARY KEY,
        added_by INTEGER,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Force channels table
    c.execute('''CREATE TABLE IF NOT EXISTS force_channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_username TEXT,
        channel_id INTEGER,
        invite_link TEXT,
        is_active BOOLEAN DEFAULT 1,
        added_by INTEGER,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # User verification for channels
    c.execute('''CREATE TABLE IF NOT EXISTS user_verification (
        user_id INTEGER,
        channel_id INTEGER,
        verified_at TIMESTAMP,
        expires_at TIMESTAMP,
        PRIMARY KEY (user_id, channel_id)
    )''')
    
    # Batch files table
    c.execute('''CREATE TABLE IF NOT EXISTS batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_code TEXT UNIQUE,
        chat_id INTEGER,
        first_msg_id INTEGER,
        last_msg_id INTEGER,
        total_files INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS batch_files (
        batch_id INTEGER,
        file_id INTEGER,
        file_index INTEGER,
        FOREIGN KEY(batch_id) REFERENCES batches(id),
        FOREIGN KEY(file_id) REFERENCES files(id)
    )''')
    
    # Message queue for auto delete
    c.execute('''CREATE TABLE IF NOT EXISTS message_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        message_id INTEGER,
        delete_at TIMESTAMP,
        message_type TEXT
    )''')
    
    # Insert default settings
    c.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES ('timer_seconds', ?)", (str(DEFAULT_TIMER_SECONDS),))
    c.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES ('message1_text', ?)", (DEFAULT_MESSAGE1,))
    c.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES ('message2_text', ?)", (DEFAULT_MESSAGE2,))
    c.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES ('forward_text', ?)", (DEFAULT_FORWARD_TEXT,))
    c.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_value) VALUES ('admin_username', ?)", ('@admin_username',))
    
    # Insert default ads settings
    c.execute("INSERT OR IGNORE INTO ads_settings (id, is_enabled, daily_limit) VALUES (1, ?, ?)", (1, DEFAULT_DAILY_AD_LIMIT))
    
    # Insert owner as admin
    c.execute("INSERT OR IGNORE INTO admins (user_id, is_owner) VALUES (?, 1)", (OWNER_ID,))
    
    conn.commit()
    conn.close()

def generate_short_code():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

# File functions
def save_file(short_code, file_id, file_type, chat_id, message_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO files (short_code, file_id, file_type, chat_id, message_id) VALUES (?, ?, ?, ?, ?)",
              (short_code, file_id, file_type, chat_id, message_id))
    conn.commit()
    conn.close()

def get_file(short_code):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT file_id, file_type FROM files WHERE short_code = ?", (short_code,))
    result = c.fetchone()
    conn.close()
    return result

# Admin functions
def is_admin(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def add_admin(user_id, added_by):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO admins (user_id, added_by, is_owner) VALUES (?, ?, 0)", (user_id, added_by))
    conn.commit()
    conn.close()

def remove_admin(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id = ? AND is_owner = 0", (user_id,))
    conn.commit()
    conn.close()

def get_all_admins():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id, is_owner FROM admins")
    result = c.fetchall()
    conn.close()
    return result

# Ad view functions
def record_ad_view(user_id, short_code):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO ad_views (user_id, short_code, completed) VALUES (?, ?, 1)", (user_id, short_code))
    conn.commit()
    conn.close()

def has_viewed_ad(user_id, short_code):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT 1 FROM ad_views WHERE user_id = ? AND short_code = ?", (user_id, short_code))
    result = c.fetchone()
    conn.close()
    return result is not None

# Settings functions
def get_setting(key, default=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT setting_value FROM bot_settings WHERE setting_key = ?", (key,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else default

def set_setting(key, value, updated_by):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO bot_settings (setting_key, setting_value, updated_by, updated_at) VALUES (?, ?, ?, ?)",
              (key, value, updated_by, datetime.now()))
    conn.commit()
    conn.close()

def get_timer():
    return int(get_setting('timer_seconds', 60))

def set_timer(seconds, updated_by):
    set_setting('timer_seconds', str(seconds), updated_by)

def get_admin_username():
    return get_setting('admin_username', '@admin_username')

def set_admin_username(username, updated_by):
    set_setting('admin_username', username, updated_by)

def get_message1():
    return get_setting('message1_text', DEFAULT_MESSAGE1)

def get_message2():
    return get_setting('message2_text', DEFAULT_MESSAGE2)

# Ads functions
def is_ads_enabled():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT is_enabled FROM ads_settings WHERE id = 1")
    result = c.fetchone()
    conn.close()
    return bool(result[0]) if result else True

def set_ads_enabled(enabled):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE ads_settings SET is_enabled = ? WHERE id = 1", (1 if enabled else 0,))
    conn.commit()
    conn.close()

def get_ad_limit():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT daily_limit FROM ads_settings WHERE id = 1")
    result = c.fetchone()
    conn.close()
    return result[0] if result else 3

def set_ad_limit(limit):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE ads_settings SET daily_limit = ? WHERE id = 1", (limit,))
    conn.commit()
    conn.close()

def get_user_ad_count(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    today = datetime.now().date()
    c.execute("SELECT count, last_reset_date FROM user_ad_counts WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    
    if result:
        count, last_date = result
        if last_date:
            last_date = datetime.strptime(last_date, '%Y-%m-%d').date()
            if last_date != today:
                count = 0
    else:
        count = 0
    
    conn.close()
    return count

def increment_user_ad_count(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    today = datetime.now().date()
    current = get_user_ad_count(user_id)
    c.execute("INSERT OR REPLACE INTO user_ad_counts (user_id, count, last_reset_date) VALUES (?, ?, ?)",
              (user_id, current + 1, today))
    conn.commit()
    conn.close()

def is_ads_bypass(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT 1 FROM ads_bypass WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def add_ads_bypass(user_id, added_by):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO ads_bypass (user_id, added_by) VALUES (?, ?)", (user_id, added_by))
    conn.commit()
    conn.close()

def remove_ads_bypass(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM ads_bypass WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_bypass_list():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM ads_bypass")
    result = c.fetchall()
    conn.close()
    return [r[0] for r in result]

# Force channel functions
def add_force_channel(channel_username, channel_id, invite_link, added_by):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO force_channels (channel_username, channel_id, invite_link, added_by) VALUES (?, ?, ?, ?)",
              (channel_username, channel_id, invite_link, added_by))
    conn.commit()
    conn.close()

def remove_force_channel(channel_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM force_channels WHERE id = ?", (channel_id,))
    conn.commit()
    conn.close()

def get_force_channels():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, channel_username, channel_id, invite_link FROM force_channels WHERE is_active = 1")
    result = c.fetchall()
    conn.close()
    return result

# Batch functions
def save_batch(batch_code, chat_id, first_msg_id, last_msg_id, total_files):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO batches (batch_code, chat_id, first_msg_id, last_msg_id, total_files) VALUES (?, ?, ?, ?, ?)",
              (batch_code, chat_id, first_msg_id, last_msg_id, total_files))
    batch_id = c.lastrowid
    conn.commit()
    conn.close()
    return batch_id

def save_batch_file(batch_id, file_id, file_index):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO batch_files (batch_id, file_id, file_index) VALUES (?, ?, ?)",
              (batch_id, file_id, file_index))
    conn.commit()
    conn.close()

def get_batch_files(batch_code):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT f.file_id, f.file_type FROM batch_files bf
                 JOIN batches b ON bf.batch_id = b.id
                 JOIN files f ON bf.file_id = f.id
                 WHERE b.batch_code = ?
                 ORDER BY bf.file_index''', (batch_code,))
    result = c.fetchall()
    conn.close()
    return result

# Message queue for auto delete
def add_to_delete_queue(chat_id, message_id, seconds, message_type='general'):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    delete_at = datetime.now() + timedelta(seconds=seconds)
    c.execute("INSERT INTO message_queue (chat_id, message_id, delete_at, message_type) VALUES (?, ?, ?, ?)",
              (chat_id, message_id, delete_at, message_type))
    conn.commit()
    conn.close()

def get_expired_messages():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, chat_id, message_id FROM message_queue WHERE delete_at <= ?", (datetime.now(),))
    result = c.fetchall()
    conn.close()
    return result

def delete_from_queue(queue_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM message_queue WHERE id = ?", (queue_id,))
    conn.commit()
    conn.close()
