# العملات التي سيحللها البوت تلقائياً
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT", 
           "DOGEUSDT", "XRPUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT"]

# إعدادات الاستراتيجية (EMA تقاطع)
EMA_FAST = 9          # المتوسط السريع
EMA_SLOW = 21         # المتوسط البطيء
TP_PERCENT = 3.0      # نسبة الربح %
SL_PERCENT = 1.5      # نسبة الخسارة %
MIN_VOLUME_RATIO = 1.5 # الحد الأدنى لنسبة الحجم إلى المتوسط
