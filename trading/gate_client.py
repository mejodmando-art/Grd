import ccxt
import os

def _client():
    return ccxt.gate({
        'apiKey': os.getenv('GATE_API_KEY', ''),
        'secret': os.getenv('GATE_API_SECRET', ''),
        'options': {'defaultType': 'spot'},
    })

async def get_balance(*a):
    """جلب جميع العملات مع قيمتها مقابل USDT"""
    exchange = _client()
    balance = exchange.fetch_balance()
    total_value = 0.0
    all_coins = []

    # استخراج العملات من مفتاح 'total'
    currencies = balance.get('total', {})
    for coin, amount in currencies.items():
        if amount > 0:
            free = balance.get('free', {}).get(coin, 0)
            used = balance.get('used', {}).get(coin, 0)
            try:
                if coin == 'USDT':
                    price = 1.0
                else:
                    ticker = exchange.fetch_ticker(f"{coin}/USDT")
                    price = ticker['last']
            except Exception:
                # إذا فشل جلب السعر، نعتبره 0
                price = 0.0
            value = amount * price
            total_value += value
            all_coins.append({
                'coin': coin,
                'free': free,
                'used': used,
                'total': amount,
                'price': price,
                'value': value
            })

    # ترتيب تنازلي حسب القيمة الإجمالية
    all_coins.sort(key=lambda x: x['value'], reverse=True)
    return {'all_coins': all_coins, 'total_value': total_value}


# دوال احتياطية (غير مستخدمة حالياً)
async def get_ticker_price(*a): pass
async def place_buy_order(*a): pass
async def place_sell_order(*a): pass
async def get_klines(*a): pass
async def get_top_symbols(*a): pass