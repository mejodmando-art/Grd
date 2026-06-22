import ccxt
import os
import aiohttp

GATE_BASE = "https://api.gateio.ws/api/v4"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

def _client():
    return ccxt.gate({
        'apiKey': os.getenv('GATE_API_KEY', ''),
        'secret': os.getenv('GATE_API_SECRET', ''),
        'options': {'defaultType': 'spot'},
    })

def _normalize(symbol: str) -> str:
    if '/' in symbol:
        return symbol
    return symbol[:-4] + '/' + symbol[-4:]

# ---------- المحفظة ----------
async def get_balance(*a):
    exchange = _client()
    balance = exchange.fetch_balance()
    total_value = 0.0
    all_coins = []
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
            except:
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
    all_coins.sort(key=lambda x: x['value'], reverse=True)
    return {'all_coins': all_coins, 'total_value': total_value}

# ---------- الأسعار ----------
async def get_ticker_price(symbol, *a):
    return _client().fetch_ticker(_normalize(symbol))['last']

# ---------- الأوامر ----------
async def place_buy_order(api_key, api_secret, symbol, usdt_amount):
    e = _client()
    p = e.fetch_ticker(_normalize(symbol))['last']
    qty = usdt_amount / p
    o = e.create_market_buy_order(_normalize(symbol), qty)
    filled = float(o['filled'])
    cost = float(o['cost'])
    return {
        'order_id': o['id'],
        'symbol': symbol,
        'side': 'buy',
        'quantity': filled,
        'entry_price': round(cost / filled if filled else p, 8),
        'cost': usdt_amount,
    }

async def place_sell_order(api_key, api_secret, symbol, quantity):
    o = _client().create_market_sell_order(_normalize(symbol), quantity)
    filled = float(o['filled'])
    cost = float(o['cost'])
    return {
        'order_id': o['id'],
        'symbol': symbol,
        'side': 'sell',
        'quantity': filled,
        'close_price': round(cost / filled if filled else 0, 8),
        'cost': cost,
    }

# ---------- الشموع ----------
async def get_klines(symbol, interval='5m', limit=60):
    ohlcv = _client().fetch_ohlcv(_normalize(symbol), timeframe=interval, limit=limit)
    return [{'open': o[1], 'high': o[2], 'low': o[3], 'close': o[4], 'volume': o[5]} for o in ohlcv]

# ---------- أعلى العملات ----------
async def get_top_symbols(count=200):
    syms = []
    for s, t in _client().fetch_tickers().items():
        if s.endswith('/USDT'):
            try:
                vol = float(t.get('quoteVolume', 0))
                syms.append({'symbol': s.replace('/', ''), 'volume': vol})
            except:
                continue
    syms.sort(key=lambda x: x['volume'], reverse=True)
    return [s['symbol'] for s in syms[:count]]

# ---------- فلتر القيمة السوقية ----------
_market_caps_cache = {}
_market_caps_time = 0

async def get_top_coins_by_market_cap(min_cap: int = 2_000_000_000) -> list:
    """جلب أعلى 250 عملة من CoinGecko وتصفية حسب القيمة السوقية"""
    global _market_caps_cache, _market_caps_time
    import time
    now = time.time()
    if _market_caps_cache and (now - _market_caps_time) < 3600:
        return [c for c, cap in _market_caps_cache.items() if cap >= min_cap]
    try:
        async with aiohttp.ClientSession() as s:
            url = f"{COINGECKO_BASE}/coins/markets"
            params = {
                'vs_currency': 'usd',
                'order': 'market_cap_desc',
                'per_page': 250,
                'page': 1,
                'sparkline': 'false'
            }
            resp = await s.get(url, params=params)
            data = await resp.json()
            for coin in data:
                symbol = coin.get('symbol', '').upper()
                market_cap = coin.get('market_cap', 0)
                if market_cap:
                    _market_caps_cache[symbol] = market_cap
            _market_caps_time = now
            return [c for c, cap in _market_caps_cache.items() if cap >= min_cap]
    except Exception as e:
        logger = logging.getLogger("GateClient")
        logger.error(f"CoinGecko fetch failed: {e}")
        return list(_market_caps_cache.keys()) if _market_caps_cache else []