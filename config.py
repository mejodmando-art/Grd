import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# MEXC API
MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
MEXC_API_SECRET = os.getenv("MEXC_API_SECRET", "")

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Monitor interval (seconds)
MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "30"))

# Default leverage (unused but kept)
DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "1"))

# Quick amount presets
AMOUNT_PRESETS = [10, 25, 50, 100, 200, 500]

# ========== إعدادات التداول الآلي ==========
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT",
           "DOGEUSDT", "XRPUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT"]

EMA_FAST = 9
EMA_SLOW = 21
TP_PERCENT = 3.0      # %
SL_PERCENT = 1.5      # %
MIN_VOLUME_RATIO = 1.5
