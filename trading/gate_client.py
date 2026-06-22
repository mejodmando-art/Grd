import ccxt, os

def _client():
    return ccxt.gate({
        'apiKey': os.getenv('GATE_API_KEY', ''),
        'secret': os.getenv('GATE_API_SECRET', ''),
        'options': {'defaultType': 'spot'},
    })

def _normalize(symbol):
    return symbol.replace('/', '') if '/' in symbol else symbol[:-4] + '/' + symbol[-4:]

async def get_ticker_price(s, *a): return _client().fetch_ticker(_normalize(s))['last']
async def get_balance(ak, sk):
    b = _client().fetch_balance().get('USDT', {})
    return {'free': float(b.get('free',0)), 'used': float(b.get('used',0)), 'total': float(b.get('total',0))}
async def place_buy_order(ak, sk, sym, amt):
    e=_client(); p=e.fetch_ticker(_normalize(sym))['last']; q=amt/p
    o=e.create_market_buy_order(_normalize(sym), q)
    f=float(o['filled']); c=float(o['cost'])
    return {'order_id':o['id'],'symbol':sym,'side':'buy','quantity':f,'entry_price':round(c/f if f else p,8),'cost':amt}
async def place_sell_order(ak, sk, sym, qty):
    o=_client().create_market_sell_order(_normalize(sym), qty)
    f=float(o['filled']); c=float(o['cost'])
    return {'order_id':o['id'],'symbol':sym,'side':'sell','quantity':f,'close_price':round(c/f if f else 0,8),'cost':c}
async def get_klines(sym, interval='5m', limit=60):
    ohlcv=_client().fetch_ohlcv(_normalize(sym), timeframe=interval, limit=limit)
    return [{'open':o[1],'high':o[2],'low':o[3],'close':o[4],'volume':o[5]} for o in ohlcv]
async def get_top_symbols(count=300):
    syms=[]
    for s,t in _client().fetch_tickers().items():
        if s.endswith('/USDT'):
            try: syms.append({'symbol':s.replace('/',''), 'volume':float(t.get('quoteVolume',0))})
            except: pass
    syms.sort(key=lambda x: x['volume'], reverse=True)
    return [s['symbol'] for s in syms[:count]]