import os
from dotenv import load_dotenv
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
GATE_API_KEY = os.getenv("GATE_API_KEY", "")
GATE_API_SECRET = os.getenv("GATE_API_SECRET", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ─── إعدادات عامة ─────────────────────────────────────────────
MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "60"))
AMOUNT_PRESETS = [5, 10, 20, 50, 100]

# ─── استراتيجية EMA (الكلاسيكية) ──────────────────────────────
TOP_SYMBOLS_COUNT = 50
EMA_FAST = 5
EMA_SLOW = 13
TP_PERCENT = 2.0
SL_PERCENT = 1.0
MIN_VOLUME_RATIO = 1.2
KLINE_INTERVAL = "5m"
KLINE_LIMIT = 40
MAX_OPEN_TRADES = 3
DEFAULT_AMOUNT = 10.0

# ─── استراتيجية HARPOON (المتقدمة) ───────────────────────────
HARPOON_TOP_SYMBOLS_COUNT = 80
HARPOON_EMA_FAST = 8
HARPOON_EMA_SLOW = 21
HARPOON_TP_PERCENT = 3.0
HARPOON_SL_PERCENT = 1.5
HARPOON_KLINE_INTERVAL = "15m"
HARPOON_KLINE_LIMIT = 60
HARPOON_MAX_OPEN_TRADES = 5
HARPOON_BASE_AMOUNT = 10.0
HARPOON_DOUBLE_AMOUNT = 20.0
HARPOON_TRIPLE_AMOUNT = 30.0
HARPOON_WHALE_VOLUME_RATIO = 2.5
HARPOON_RSI_OVERSOLD = 40
HARPOON_MIN_VOLUME_RATIO = 1.5
