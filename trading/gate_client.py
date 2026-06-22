import ccxt
import os

def _client():
    return ccxt.gateio({
        'apiKey': os.getenv('GATE_API_KEY', ''),
        'secret': os.getenv('GATE_API_SECRET', ''),
        'options': {'defaultType': 'spot'},
    })

def _normalize(symbol):
    if '/' in symbol:
        return symbol
    return symbol[:-4] + '/' + symbol[-4:]

async def get_ticker_price(symbol, api_key='', api_secret=''):
    return _client().fetch_ticker(_normalize(symbol))['last']

async def get_balance(api_key, api_secret):
    b = _client().fetch_balance().get('USDT', {})
    f = float(b.get('free', 0))
    u = float(b.get('used', 0))
    return {'free': f, 'used': u, 'total': f + u}

async def place_buy_order(api_key, api_secret, symbol, usdt_amount):
    e = _client()
    p = e.fetch_ticker(_normalize(symbol))['last']
    q = usdt_amount / p
    o = e.create_market_buy_order(_normalize(symbol), q)
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

async def get_klines(symbol, interval='5m', limit=60):
    ohlcv = _client().fetch_ohlcv(_normalize(symbol), timeframe=interval, limit=limit)
    return [{'open': o[1], 'high': o[2], 'low': o[3], 'close': o[4], 'volume': o[5]} for o in ohlcv]

async def get_top_symbols(count=300):
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