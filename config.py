# config.py
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8792991594:AAHarRh3aJuV3mULjzNONlOrRxj_WtVNF9Y")
OWNER_ID = int(os.environ.get("OWNER_ID", 7406197326))
MINI_APP_URL = os.environ.get("MINI_APP_URL", "https://miniapp-idc4.onrender.com")

DB_NAME = "file_store.db"

# Default Settings
DEFAULT_TIMER_SECONDS = 60
DEFAULT_ADS_ENABLED = True
DEFAULT_DAILY_AD_LIMIT = 3

# Default Messages (English)
DEFAULT_MESSAGE1 = """✅ Your video has been sent.

⏰ This message will be deleted in {timer} seconds.

📌 **To save permanently:**
Forward this message to Saved Messages or your channel/group."""

DEFAULT_MESSAGE2 = """📝 **Video Player Info:**

📱 Android: MX Player, VLC Player
🍎 iPhone: VLC for Mobile, PlayerXtreme  
💻 Windows/Mac: VLC Media Player

Download and play with any player above.

━━━━━━━━━━━━━━━━━━
📢 **Admin:** @{admin_username}"""

DEFAULT_FORWARD_TEXT = """Forward this message to Saved Messages or your channel/group."""
