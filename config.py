import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))

OLCRTC_BIN = os.getenv("OLCRTC_BIN", "/root/olcrtc/olcrtc")
OLCRTC_DATA = os.getenv("OLCRTC_DATA", "/root/olcrtc/data")
OLCRTC_DNS = os.getenv("OLCRTC_DNS", "1.1.1.1:53")

DB_PATH = "profiles.db"
