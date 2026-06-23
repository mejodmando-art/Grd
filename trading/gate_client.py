import asyncio
import ccxt
import os

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

# ─── المحفظة ───────────────────────────────────────────────────
# FIX: ccxt is synchronous — wrap in asyncio.to_thread to avoid blocking the event loop

def _fetch_balance_sync():
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
                    price = ticker['last'] or 0.0
            except Exception:
                price = 0.0
            value = amount * price
            total_value += value
            all_coins.append({
                'coin': coin, 'free': free, 'used': used,
                'total': amount, 'price': price, 'value': value
            })
    all_coins.sort(key=lambda x: x['value'], reverse=True)
    return {'all_coins': all_coins, 'total_value': total_value}

async def get_balance(api_key: str = "", api_secret: str = "") -> dict:
    return await asyncio.to_thread(_fetch_balance_sync)

# ─── الأسعار ──────────────────────────────────────────────────
def _fetch_price_sync(symbol: str) -> float:
    return _client().fetch_ticker(_normalize(symbol))['last']

async def get_ticker_price(symbol: str, *a) -> float:
    return await asyncio.to_thread(_fetch_price_sync, symbol)

# ─── الأوامر ──────────────────────────────────────────────────
def _place_buy_sync(symbol: str, usdt_amount: float) -> dict:
    e = _client()
    sym = _normalize(symbol)
    p = e.fetch_ticker(sym)['last']
    qty = usdt_amount / p
    o = e.create_market_buy_order(sym, qty)
    filled = float(o.get('filled') or qty)
    cost = float(o.get('cost') or usdt_amount)
    return {
        'order_id': str(o.get('id', '')),
        'symbol': symbol,
        'side': 'buy',
        'quantity': filled,
        'entry_price': round(cost / filled if filled else p, 8),
        'cost': usdt_amount,
    }

async def place_buy_order(api_key: str, api_secret: str, symbol: str, usdt_amount: float) -> dict:
    return await asyncio.to_thread(_place_buy_sync, symbol, usdt_amount)

def _place_sell_sync(symbol: str, quantity: float) -> dict:
    e = _client()
    sym = _normalize(symbol)
    o = e.create_market_sell_order(sym, quantity)
    filled = float(o.get('filled') or quantity)
    cost = float(o.get('cost') or 0)
    return {
        'order_id': str(o.get('id', '')),
        'symbol': symbol,
        'side': 'sell',
        'quantity': filled,
        'close_price': round(cost / filled if filled else 0, 8),
        'cost': cost,
    }

async def place_sell_order(api_key: str, api_secret: str, symbol: str, quantity: float) -> dict:
    return await asyncio.to_thread(_place_sell_sync, symbol, quantity)

# ─── الشموع ────────────────────────────────────────────────────
def _fetch_klines_sync(symbol: str, interval: str, limit: int) -> list:
    ohlcv = _client().fetch_ohlcv(_normalize(symbol), timeframe=interval, limit=limit)
    return [{'open': o[1], 'high': o[2], 'low': o[3], 'close': o[4], 'volume': o[5]} for o in ohlcv]

async def get_klines(symbol: str, interval: str = '5m', limit: int = 60) -> list:
    return await asyncio.to_thread(_fetch_klines_sync, symbol, interval, limit)

# ─── أعلى العملات ─────────────────────────────────────────────
def _fetch_top_symbols_sync(count: int) -> list:
    syms = []
    for s, t in _client().fetch_tickers().items():
        if s.endswith('/USDT'):
            try:
                vol = float(t.get('quoteVolume') or 0)
                syms.append({'symbol': s.replace('/', ''), 'volume': vol})
            except Exception:
                continue
    syms.sort(key=lambda x: x['volume'], reverse=True)
    return [s['symbol'] for s in syms[:count]]

async def get_top_symbols(count: int = 200) -> list:
    return await asyncio.to_thread(_fetch_top_symbols_sync, count)
