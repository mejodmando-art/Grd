import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()

GATE_API_KEY = os.getenv("GATE_API_KEY", "")
GATE_API_SECRET = os.getenv("GATE_API_SECRET", "")

async def test_gate_connection():
    print("=" * 50)
    print("اختبار الاتصال بـ Gate.io")
    print("=" * 50)
    
    if not GATE_API_KEY or not GATE_API_SECRET:
        print("❌ GATE_API_KEY أو GATE_API_SECRET غير موجودين في Railway Variables")
        return
    
    print(f"🔑 API Key: {GATE_API_KEY[:10]}...")
    print(f"🔐 Secret: {GATE_API_SECRET[:10]}...")
    
    try:
        # استيراد الدوال
        from trading.gate_client import get_balance, get_ticker_price
        
        # اختبار جلب السعر (بدون توقيع)
        print("\n1️⃣ اختبار جلب سعر BTC...")
        try:
            price = await get_ticker_price("BTCUSDT")
            print(f"   ✅ سعر BTC: ${price}")
        except Exception as e:
            print(f"   ❌ فشل: {e}")
        
        # اختبار جلب الرصيد (بتوقيع)
        print("\n2️⃣ اختبار جلب الرصيد...")
        try:
            bal = await get_balance(GATE_API_KEY, GATE_API_SECRET)
            print(f"   ✅ متاح: ${bal['free']:.2f}")
            print(f"   ✅ محجوز: ${bal['used']:.2f}")
            print(f"   ✅ إجمالي: ${bal['total']:.2f}")
        except Exception as e:
            print(f"   ❌ فشل: {e}")
            print(f"   رسالة الخطأ كاملة: {str(e)}")
        
        # اختبار جلب أعلى العملات
        print("\n3️⃣ اختبار جلب أعلى 5 عملات...")
        try:
            from trading.gate_client import get_top_symbols
            symbols = await get_top_symbols(5)
            print(f"   ✅ {symbols}")
        except Exception as e:
            print(f"   ❌ فشل: {e}")
        
    except ImportError as e:
        print(f"❌ خطأ في الاستيراد: {e}")
        print("   تأكد من وجود ملف trading/gate_client.py")
    
    print("\n" + "=" * 50)
    print("انتهى الاختبار")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(test_gate_connection())