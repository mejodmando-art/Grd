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
# إعدادات التداول الآلي السريع (أعلى 300 عملة)
# ═══════════════════════════════════════════════════════════════════════════════

# عدد العملات المراد تحليلها (أعلى 300 عملة من حيث الحجم)
TOP_SYMBOLS_COUNT = 300

# إعدادات الاستراتيجية السريعة
EMA_FAST = 5               # المتوسط السريع (5 شموع)
EMA_SLOW = 13              # المتوسط البطيء (13 شمعة)
TP_PERCENT = 2.0           # هدف ربح %
SL_PERCENT = 1.0           # وقف خسارة %
MIN_VOLUME_RATIO = 1.2     # تأكيد حجم التداول
KLINE_INTERVAL = "5m"      # إطار زمني للشموع
KLINE_LIMIT = 40           # عدد الشموع للتحليل
MAX_OPEN_TRADES = 3        # أقصى عدد صفقات مفتوحة في نفس الوقت