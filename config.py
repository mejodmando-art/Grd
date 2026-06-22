import os
from dotenv import load_dotenv
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
GATE_API_KEY = os.getenv("GATE_API_KEY", "")
GATE_API_SECRET = os.getenv("GATE_API_SECRET", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "30"))
TOP_SYMBOLS_COUNT = 200
EMA_FAST = 5
EMA_SLOW = 13
TP_PERCENT = 2.0
SL_PERCENT = 1.0
MIN_VOLUME_RATIO = 1.2
KLINE_INTERVAL = "5m"
KLINE_LIMIT = 40
MAX_OPEN_TRADES = 3
DEFAULT_AMOUNT = 10.0
MIN_MARKET_CAP = 2_000_000_000  # 2 مليار دولار