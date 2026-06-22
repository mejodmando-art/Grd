import ccxt
import os

def _client():
    return ccxt.gate({
        'apiKey': os.getenv('GATE_API_KEY', ''),
        'secret': os.getenv('GATE_API_SECRET', ''),
        'options': {'defaultType': 'spot'},
    })

async def get_balance(*a):
    b = _client().fetch_balance()
    all_coins = []
    total_value = 0.0
    for coin, data in b.items():
        if data['free'] > 0 or data['used'] > 0:
            try:
                if coin == 'USDT':
                    price = 1.0
                else:
                    ticker = _client().fetch_ticker(f"{coin}/USDT")
                    price = ticker['last']
            except:
                price = 0.0
            value = (data['free'] + data['used']) * price
            total_value += value
            all_coins.append({
                'coin': coin,
                'free': data['free'],
                'used': data['used'],
                'total': data['total'],
                'price': price,
                'value': value
            })
    all_coins.sort(key=lambda x: x['value'], reverse=True)
    return {'all_coins': all_coins, 'total_value': total_value}

# الدوال الأخرى فارغة مؤقتاً
async def get_ticker_price(*a): pass
async def place_buy_order(*a): pass
async def place_sell_order(*a): pass
async def get_klines(*a): pass
async def get_top_symbols(*a): pass