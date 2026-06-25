import ccxt, os, logging, math, urllib.request, json

logger = logging.getLogger("GateClient")

# ─── Singleton Gate.io Client ───────────────────────────────────────────────
_gate_client = None

def _client():
    global _gate_client
    if _gate_client is None:
        _gate_client = ccxt.gate({
            'apiKey': os.getenv('GATE_API_KEY', ''),
            'secret': os.getenv('GATE_API_SECRET', ''),
            'options': {
                'defaultType': 'spot',
                'createMarketBuyOrderRequiresPrice': False,  # ✅ الحل
            },
            'enableRateLimit': True,
            'rateLimit': 100,
        })
    return _gate_client

def _normalize(symbol: str) -> str:
    if '/' in symbol:
        return symbol
    return symbol[:-4] + '/' + symbol[-4:]

# ─── Filters ──────────────────────────────────────────────────────────────────
STABLECOINS = {'USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'FDUSD', 'USDE', 'PYUSD'}
MAX_MARKET_CAP = 5_000_000_000

def _is_stable_pair(symbol: str) -> bool:
    base = symbol.replace('/USDT', '').replace('USDT', '').upper()
    return base in STABLECOINS

_MCAP_CACHE = {}

def _get_market_cap(symbol: str) -> float:
    base = symbol.replace('/USDT', '').replace('USDT', '').upper()
    if base in _MCAP_CACHE:
        return _MCAP_CACHE[base]
    try:
        url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&symbols={base.lower()}&per_page=1"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read())
            if data and len(data) > 0:
                mcap = float(data[0].get('market_cap', 0))
                _MCAP_CACHE[base] = mcap
                return mcap
    except Exception as e:
        logger.warning(f"Market cap fetch failed for {base}: {e}")
    _MCAP_CACHE[base] = 0.0
    return 0.0

# ─── Market Info Cache ──────────────────────────────────────────────────────
_MARKET_CACHE = {}

def _get_market_info(symbol: str):
    global _MARKET_CACHE
    norm = _normalize(symbol)
    if norm not in _MARKET_CACHE:
        try:
            e = _client()
            markets = e.load_markets()
            if norm in markets:
                _MARKET_CACHE[norm] = markets[norm]
            else:
                return None
        except Exception as ex:
            logger.error(f"Failed to load market info for {norm}: {ex}")
            return None
    return _MARKET_CACHE.get(norm)

def _format_qty(symbol: str, qty: float) -> float:
    info = _get_market_info(symbol)
    if info:
        try:
            e = _client()
            formatted = e.amount_to_precision(_normalize(symbol), qty)
            return float(formatted)
        except Exception as ex:
            logger.warning(f"amount_to_precision failed for {symbol}: {ex}")
            return round(qty, 6)
    return round(qty, 6)

# ─── Balance (مُحسّن) ────────────────────────────────────────────────────────
async def get_balance(*a):
    try:
        exchange = _client()
        balance = exchange.fetch_balance()
        total_value = 0.0
        all_coins = []
        currencies = balance.get('total', {})
        for coin, amount in currencies.items():
            if amount > 0:
                free = balance.get('free', {}).get(coin, 0)
                used = balance.get('used', {}).get(coin, 0)
                price = 1.0 if coin == 'USDT' else 0.0
                value = amount * price
                total_value += value
                all_coins.append({'coin': coin, 'free': free, 'used': used, 'total': amount, 'price': price, 'value': value})
        all_coins.sort(key=lambda x: x['value'], reverse=True)
        return {'all_coins': all_coins, 'total_value': total_value}
    except Exception as e:
        logger.error(f"Balance fetch error: {e}")
        return {'all_coins': [], 'total_value': 0.0}

async def get_usdt_free():
    try:
        exchange = _client()
        balance = exchange.fetch_balance()
        free = float(balance.get('free', {}).get('USDT', 0))
        logger.info(f"USDT Free: {free:.2f}")
        return free
    except Exception as e:
        raise Exception(f"خطأ في جلب الرصيد: {e}") from e

# ─── Prices ───────────────────────────────────────────────────────────────────
async def get_ticker_price(symbol, *a):
    return _client().fetch_ticker(_normalize(symbol))['last']

# ─── Orders (الإصلاح النهائي) ───────────────────────────────────────────────
async def place_buy_order(api_key, api_secret, symbol, usdt_amount):
    norm = _normalize(symbol)

    # ❌ Filters
    if _is_stable_pair(symbol):
        raise ValueError(f"⛔ {symbol} عملة مستقرة — تم الرفض")

    mcap = _get_market_cap(symbol)
    if mcap > MAX_MARKET_CAP:
        raise ValueError(f"⛔ {symbol} ماركت كاب ${mcap/1e9:.1f}B > 5B — تم الرفض")

    if usdt_amount < 1:
        raise ValueError(f"المبلغ {usdt_amount} أقل من الحد الأدنى ($1)")

    e = _client()
    p = e.fetch_ticker(norm)['last']
    if not p or p <= 0:
        raise ValueError(f"سعر غير صالح لـ {symbol}: {p}")

    # ✅ الحل: amount = مبلغ USDT (مش كمية العملة)
    # لأن createMarketBuyOrderRequiresPrice = False
    logger.info(f"BUY: {symbol} | amount={usdt_amount} USDT | price≈{p}")

    try:
        o = e.create_market_buy_order(norm, usdt_amount)
        
        logger.info(f"✅ ORDER SUCCESS: {o}")
        
        filled = float(o.get('filled', 0))
        cost = float(o.get('cost', 0))
        
        return {
            'order_id': o.get('id', ''),
            'symbol': symbol,
            'side': 'buy',
            'quantity': filled,
            'entry_price': round(cost / filled if filled else p, 8),
            'cost': cost
        }
    except Exception as ex:
        logger.error(f"❌ ORDER FAILED: {ex}")
        raise ValueError(f"فشل الشراء: {ex}")

async def place_sell_order(api_key, api_secret, symbol, quantity):
    if quantity <= 0:
        raise ValueError(f"كمية البيع صفر أو سالبة: {quantity}")

    e = _client()
    norm = _normalize(symbol)
    qty = _format_qty(symbol, quantity)
    if qty <= 0:
        raise ValueError(f"الكمية المنقحة صفر لـ {symbol}")

    logger.info(f"SELL: {symbol} | qty={qty}")
    o = e.create_market_sell_order(norm, qty)

    filled = float(o.get('filled', 0))
    cost = float(o.get('cost', 0))
    logger.info(f"SELL filled: {filled} {symbol}")

    return {
        'order_id': o.get('id', ''),
        'symbol': symbol,
        'side': 'sell',
        'quantity': filled,
        'close_price': round(cost / filled if filled else 0, 8),
        'cost': cost
    }

# ─── Klines & Top Symbols ───────────────────────────────────────────────────
async def get_klines(symbol, interval='5m', limit=60):
    ohlcv = _client().fetch_ohlcv(_normalize(symbol), timeframe=interval, limit=limit)
    return [{'open': o[1], 'high': o[2], 'low': o[3], 'close': o[4], 'volume': o[5]} for o in ohlcv]

async def get_top_symbols(count=200):
    syms = []
    for s, t in _client().fetch_tickers().items():
        if s.endswith('/USDT'):
            try:
                vol = float(t.get('quoteVolume', 0))
                syms.append({'symbol': s.replace('/', ''), 'volume': vol})
            except: continue
    syms.sort(key=lambda x: x['volume'], reverse=True)
    return [s['symbol'] for s in syms[:count]]