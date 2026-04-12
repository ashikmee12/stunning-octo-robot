# database.py - MongoDB version (ALL FEATURES)
import os
import random
import string
from datetime import datetime, timedelta
from pymongo import MongoClient
from config import OWNER_ID

# MongoDB connection
MONGO_URL = os.environ.get("MONGO_URL")
if not MONGO_URL:
    raise Exception("MONGO_URL environment variable not set!")

client = MongoClient(MONGO_URL)
db = client.telegram_file_bot

# Collections
files_col = db.files
admins_col = db.admins
ad_views_col = db.ad_views
settings_col = db.settings
ads_settings_col = db.ads_settings
user_ad_counts_col = db.user_ad_counts
ads_bypass_col = db.ads_bypass
force_channels_col = db.force_channels
user_verification_col = db.user_verification
batches_col = db.batches
batch_files_col = db.batch_files
message_queue_col = db.message_queue

def init_db():
    # Create indexes
    files_col.create_index("short_code", unique=True)
    admins_col.create_index("user_id", unique=True)
    user_ad_counts_col.create_index("user_id", unique=True)
    ads_bypass_col.create_index("user_id", unique=True)
    batches_col.create_index("batch_code", unique=True)
    message_queue_col.create_index("delete_at")
    
    # Default messages
    default_message1 = "✅ Your video has been sent.\n\n⏰ This message will be deleted in {timer} seconds.\n\n📌 To save permanently: Forward this message to Saved Messages or your channel/group."
    default_message2 = "📝 Video Player Info:\n\n📱 Android: MX Player, VLC Player\n🍎 iPhone: VLC for Mobile, PlayerXtreme\n💻 Windows/Mac: VLC Media Player\n\nDownload and play with any player above.\n\n━━━━━━━━━━━━━━━━━━\n📢 Admin: {admin_username}"
    
    # Insert default settings
    if not settings_col.find_one({"_id": "timer_seconds"}):
        settings_col.insert_one({"_id": "timer_seconds", "value": "43200"})
    
    if not settings_col.find_one({"_id": "message1_text"}):
        settings_col.insert_one({"_id": "message1_text", "value": default_message1})
    
    if not settings_col.find_one({"_id": "message2_text"}):
        settings_col.insert_one({"_id": "message2_text", "value": default_message2})
    
    if not settings_col.find_one({"_id": "admin_username"}):
        settings_col.insert_one({"_id": "admin_username", "value": "@animethic_admin_bot"})
    
    # Ads settings
    if not ads_settings_col.find_one({"_id": "main"}):
        ads_settings_col.insert_one({"_id": "main", "is_enabled": True, "daily_limit": 3})
    
    # Insert owner as admin
    if not admins_col.find_one({"user_id": OWNER_ID}):
        admins_col.insert_one({"user_id": OWNER_ID, "is_owner": True, "added_by": OWNER_ID, "added_at": datetime.now()})

def generate_short_code():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

# ============ FILE FUNCTIONS ============
def save_file(short_code, file_id, file_type, chat_id, message_id):
    files_col.insert_one({
        "short_code": short_code,
        "file_id": file_id,
        "file_type": file_type,
        "chat_id": chat_id,
        "message_id": message_id,
        "created_at": datetime.now()
    })

def get_file(short_code):
    result = files_col.find_one({"short_code": short_code})
    if result:
        return result["file_id"], result["file_type"]
    return None

# ============ ADMIN FUNCTIONS ============
def is_admin(user_id):
    return admins_col.find_one({"user_id": user_id}) is not None

def add_admin(user_id, added_by):
    if not admins_col.find_one({"user_id": user_id}):
        admins_col.insert_one({
            "user_id": user_id,
            "is_owner": False,
            "added_by": added_by,
            "added_at": datetime.now()
        })

def remove_admin(user_id):
    admins_col.delete_one({"user_id": user_id, "is_owner": False})

def get_all_admins():
    return [(a["user_id"], a.get("is_owner", False)) for a in admins_col.find()]

# ============ AD VIEW FUNCTIONS ============
def record_ad_view(user_id, short_code):
    ad_views_col.insert_one({
        "user_id": user_id,
        "short_code": short_code,
        "viewed_at": datetime.now()
    })

def has_viewed_ad(user_id, short_code):
    return ad_views_col.find_one({"user_id": user_id, "short_code": short_code}) is not None

# ============ SETTINGS FUNCTIONS ============
def get_setting(key, default=None):
    result = settings_col.find_one({"_id": key})
    return result["value"] if result else default

def set_setting(key, value, updated_by=None):
    settings_col.update_one({"_id": key}, {"$set": {"value": value, "updated_at": datetime.now()}}, upsert=True)

def get_timer():
    return int(get_setting("timer_seconds", "43200"))

def set_timer(seconds, updated_by=None):
    set_setting("timer_seconds", str(seconds))

def get_admin_username():
    return get_setting("admin_username", "@admin_username")

def set_admin_username(username, updated_by=None):
    set_setting("admin_username", username)

def get_message1():
    return get_setting("message1_text", "✅ Your file has been sent.")

def get_message2():
    return get_setting("message2_text", "📝 Video Player Info")

# ============ ADS FUNCTIONS ============
def is_ads_enabled():
    result = ads_settings_col.find_one({"_id": "main"})
    return result["is_enabled"] if result else True

def set_ads_enabled(enabled):
    ads_settings_col.update_one({"_id": "main"}, {"$set": {"is_enabled": enabled}}, upsert=True)

def get_ad_limit():
    result = ads_settings_col.find_one({"_id": "main"})
    return result["daily_limit"] if result else 3

def set_ad_limit(limit):
    ads_settings_col.update_one({"_id": "main"}, {"$set": {"daily_limit": limit}}, upsert=True)

def get_user_ad_count(user_id):
    today = datetime.now().date()
    result = user_ad_counts_col.find_one({"user_id": user_id})
    
    if result:
        last_date = result.get("last_reset_date")
        if last_date:
            last_date = last_date.date() if isinstance(last_date, datetime) else last_date
            if last_date != today:
                return 0
        return result.get("count", 0)
    return 0

def increment_user_ad_count(user_id):
    today = datetime.now().date()
    current = get_user_ad_count(user_id)
    user_ad_counts_col.update_one(
        {"user_id": user_id},
        {"$set": {"count": current + 1, "last_reset_date": today}},
        upsert=True
    )

def is_ads_bypass(user_id):
    return ads_bypass_col.find_one({"user_id": user_id}) is not None

def add_ads_bypass(user_id, added_by):
    if not ads_bypass_col.find_one({"user_id": user_id}):
        ads_bypass_col.insert_one({
            "user_id": user_id,
            "added_by": added_by,
            "added_at": datetime.now()
        })

def remove_ads_bypass(user_id):
    ads_bypass_col.delete_one({"user_id": user_id})

def get_bypass_list():
    return [b["user_id"] for b in ads_bypass_col.find()]

# ============ FORCE CHANNEL FUNCTIONS ============
def add_force_channel(channel_username, channel_id, invite_link, added_by):
    force_channels_col.insert_one({
        "channel_username": channel_username,
        "channel_id": channel_id,
        "invite_link": invite_link,
        "is_active": True,
        "added_by": added_by,
        "added_at": datetime.now()
    })

def remove_force_channel(channel_id):
    force_channels_col.delete_one({"_id": channel_id})

def get_force_channels():
    return [(c["_id"], c.get("channel_username"), c.get("channel_id"), c.get("invite_link")) for c in force_channels_col.find({"is_active": True})]

# ============ BATCH FUNCTIONS ============
def save_batch(batch_code, chat_id, total_files):
    result = batches_col.insert_one({
        "batch_code": batch_code,
        "chat_id": chat_id,
        "total_files": total_files,
        "created_at": datetime.now()
    })
    return result.inserted_id

def save_batch_file(batch_id, file_id, file_index):
    batch_files_col.insert_one({
        "batch_id": batch_id,
        "file_id": file_id,
        "file_index": file_index
    })

def get_batch_files(batch_code):
    batch = batches_col.find_one({"batch_code": batch_code})
    if not batch:
        return []
    
    batch_files = list(batch_files_col.find({"batch_id": batch["_id"]}).sort("file_index", 1))
    result = []
    for bf in batch_files:
        file_data = files_col.find_one({"_id": bf["file_id"]})
        if file_data:
            result.append((file_data["file_id"], file_data["file_type"]))
    return result

# ============ MESSAGE QUEUE FUNCTIONS ============
def add_to_delete_queue(chat_id, message_id, seconds, message_type='general'):
    delete_at = datetime.now() + timedelta(seconds=seconds)
    message_queue_col.insert_one({
        "chat_id": chat_id,
        "message_id": message_id,
        "delete_at": delete_at,
        "message_type": message_type
    })

def get_expired_messages():
    return [(q["_id"], q["chat_id"], q["message_id"]) for q in message_queue_col.find({"delete_at": {"$lte": datetime.now()}})]

def delete_from_queue(queue_id):
    message_queue_col.delete_one({"_id": queue_id})
