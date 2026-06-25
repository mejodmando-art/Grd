# 🎯 UT Bot SPOT Edition v4.0

## مميزات الإصدار

### 🎯 UT Bot (جديد)
- **فريم:** 15 دقيقة
- **الإشارات:** Buy (فتح) / Sell (إغلاق)
- **المنطق:** ATR Trailing Stop
- **SPOT فقط:** لا Short

### الاستراتيجيات المتاحة
| الاستراتيجية | الوصف | الفريم |
|-------------|-------|--------|
| 📈 EMA | متابعة الترند | 5m |
| 🐋 Harpoon | صيد الحركات السريعة | 5m |
| 🎯 UT Bot | ATR Trailing Stop | **15m** |
| 🦁 SPHINX | مسح السيولة + تباعد الزخم | 15m |

## إعداد TradingView

1. افتح **BTC/USDT** على **Binance**
2. فريم **15 دقيقة**
3. اضف المؤشر: **UT Bot SPOT**
4. اضبط الـ Alert:
   - **Webhook URL:** URL بتاع البوت
   - **Message:** `{"symbol":"BTCUSDT","side":"buy","strategy":"UT_BOT"}`

## SPOT Rules
- ✅ Buy = اشتري بـ USDT
- ✅ Sell = بيع الكمية اللي معاك
- ❌ Short = ممنوع في SPOT

## التثبيت

1. **Supabase:** شغّل `supabase_schema.sql`
2. **GitHub:** استبدل الملفات
3. **Railway:** Redeploy
