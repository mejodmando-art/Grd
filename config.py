import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
MEXC_API_SECRET = os.getenv("MEXC_API_SECRET", "")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Monitor interval in seconds
MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "30"))

# Default leverage for futures trading
DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "1"))

# Quick amount presets (USDT)
AMOUNT_PRESETS = [10, 25, 50, 100, 200, 500]
