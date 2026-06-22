import os
from dotenv import load_dotenv

load_dotenv()

# ─── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# ─── MEXC API ──────────────────────────────────────────────────────────────────
MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
MEXC_API_SECRET = os.getenv("MEXC_API_SECRET", "")

# ─── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ─── إعدادات المراقبة ──────────────────────────────────────────────────────────
MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "30"))

# ─── إعدادات الرافعة المالية (غير مستخدمة حالياً) ──────────────────────────────
DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "1"))

# ─── مبالغ سريعة (غير مستخدمة حالياً) ───────────────────────────────────────────
AMOUNT_PRESETS = [10, 25, 50, 100, 200, 500]

# ═══════════════════════════════════════════════════════════════════════════════
# إعدادات استراتيجية EMA Crossover (الحالية)
# ═══════════════════════════════════════════════════════════════════════════════
EMA_TOP_SYMBOLS_COUNT = 300
EMA_FAST = 5
EMA_SLOW = 13
EMA_TP_PERCENT = 2.0
EMA_SL_PERCENT = 1.0
EMA_MIN_VOLUME_RATIO = 1.2
EMA_KLINE_INTERVAL = "5m"
EMA_KLINE_LIMIT = 40
EMA_MAX_OPEN_TRADES = 3
EMA_DEFAULT_AMOUNT = 10.0

# ═══════════════════════════════════════════════════════════════════════════════
# إعدادات استراتيجية الهاربون (الجديدة - متعددة التأكيدات)
# ═══════════════════════════════════════════════════════════════════════════════
HARPOON_TOP_SYMBOLS_COUNT = 200
HARPOON_EMA_FAST = 5
HARPOON_EMA_SLOW = 13
HARPOON_TP_PERCENT = 2.0
HARPOON_SL_PERCENT = 1.0
HARPOON_KLINE_INTERVAL = "5m"
HARPOON_KLINE_LIMIT = 60
HARPOON_MAX_OPEN_TRADES = 2
HARPOON_BASE_AMOUNT = 10.0       # مبلغ الصفقة إذا تحقق تأكيد واحد
HARPOON_DOUBLE_AMOUNT = 20.0     # مبلغ الصفقة إذا تحقق تأكيدان
HARPOON_TRIPLE_AMOUNT = 30.0     # مبلغ الصفقة إذا تحقق ثلاث تأكيدات
HARPOON_WHALE_VOLUME_RATIO = 3.0 # حجم التداول لتأكيد الحوت
HARPOON_RSI_OVERSOLD = 30        # حد التشبع البيعي
HARPOON_MIN_VOLUME_RATIO = 1.5   # الحد الأدنى لحجم التداول