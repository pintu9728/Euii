import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "modbot.db")

DEFAULT_SETTINGS = {
    "welcome_enabled": True,
    "welcome_text": "👋 Welcome {mention} to {group}!",
    "captcha_enabled": True,
    "captcha_type": "image",
    "antispam_enabled": True,
    "max_warnings": 3,
    "flood_limit": 5,
    "flood_window": 5,
    "night_mode": False,
    "night_start": "00:00",
    "night_end": "06:00",
    "lock_sticker": False,
    "lock_gif": False,
    "lock_photo": False,
    "lock_video": False,
    "lock_forward": False,
    "lock_url": False,
    "log_channel": None,
    "toxicity_enabled": False,
    "toxicity_threshold": 0.8,
    "toxicity_action": "warn",
    "antiservice_enabled": False,
    "raid_mode": False,
    "slow_mode": 0,
    "rules": None,
    "auto_evasion_ban": False,
}
