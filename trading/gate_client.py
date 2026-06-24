import ccxt, os, logging, math

logger = logging.getLogger("GateClient")

# ─── إعدادات الاتصال بـ Gate.io ──────────────────────────────────────────────

_gate_client = None

def _client():
    """إنشاء اتصال بـ Gate.io مع تفعيل Rate Limiting (singleton)"""
    global _gate_client
    if _gate_client is None:
        _gate_client = ccxt.gate({
            'apiKey': os.getenv('GATE_API_KEY', ''),
            'secret': os.getenv('GATE_API_SECRET', ''),
            'options': {'defaultType': 'spot'},
            'enableRateLimit': True,
            'rateLimit': 100,
        })
    return _gate_client

def _normalize(symbol: str) -> str:
    """تحويل BTCUSDT → BTC/USDT"""
    if '/' in symbol:
        return symbol
    return symbol[:-4] + '/' + symbol[-4:]

# ─── معلومات السوق (precisions & limits) ────────────────────────────────────

_MARKET_CACHE = {}

def _get_market_info(symbol: str):
    """جلب معلومات السوق: min amount, precisions, إلخ"""
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

# ─── تنسيق الكمية والسعر ────────────────────────────────────────────────────

def _format_qty(symbol: str, qty: float) -> float:
    """تنسيق الكمية حسب دقة السوق"""
    info = _get_market_info(symbol)
    if info:
        try:
            e = _client()
            formatted = e.amount_to_precision(_normalize(symbol), qty)
            return float(formatted)
        except Exception as ex:
            logger.warning(f"amount_to_precision failed for {symbol}: {ex}, using rounded value")
            return round(qty, 6)
    return round(qty, 6)

def _format_price(symbol: str, price: float) -> float:
    """تنسيق السعر حسب دقة السوق"""
    info = _get_market_info(symbol)
    if info:
        try:
            e = _client()
            formatted = e.price_to_precision(_normalize(symbol), price)
            return float(formatted)
        except Exception as ex:
            logger.warning(f"price_to_precision failed for {symbol}: {ex}, using rounded value")
            return round(price, 8)
    return round(price, 8)

def _get_min_amount(symbol: str) -> float:
    """الحد الأدنى للكمية"""
    info = _get_market_info(symbol)
    if info:
        limits = info.get('limits', {})
        amount_min = limits.get('amount', {}).get('min')
        cost_min = limits.get('cost', {}).get('min')
        return max(amount_min or 0, (cost_min or 0) / 1000)
    return 0.0001

def _get_min_cost(symbol: str) -> float:
    """الحد الأدنى للقيمة بالـ USDT"""
    info = _get_market_info(symbol)
    if info:
        limits = info.get('limits', {})
        cost_min = limits.get('cost', {}).get('min')
        return cost_min or 1.0
    return 1.0

# ─── عرض المحفظة الكاملة ────────────────────────────────────────────────────

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
            all_coins.append({'coin': coin, 'free': free, 'used': used, 'total': amount, 'price': price, 'value': value})
    all_coins.sort(key=lambda x: x['value'], reverse=True)
    return {'all_coins': all_coins, 'total_value': total_value}

# ─── رصيد USDT المتاح للتداول ─────────────────────────────────────────────────

async def get_usdt_free():
    """
    يرجع رصيد USDT المتاح.
    في حالة الخطأ: يرمي Exception بدلاً من إرجاع 0.0
    """
    try:
        exchange = _client()
        balance = exchange.fetch_balance()
        free = float(balance.get('free', {}).get('USDT', 0))
        used = float(balance.get('used', {}).get('USDT', 0))
        total = float(balance.get('total', {}).get('USDT', 0))
        logger.info(f"USDT Balance — Free: {free:.2f}, Used: {used:.2f}, Total: {total:.2f}")
        return free
    except ccxt.AuthenticationError as e:
        logger.error(f"Gate.io Authentication Error: {e}")
        raise Exception("فشل المصادقة مع Gate.io — تأكد من API Keys") from e
    except ccxt.NetworkError as e:
        logger.error(f"Gate.io Network Error: {e}")
        raise Exception("مشكلة في الاتصال بـ Gate.io — جرب تاني") from e
    except ccxt.ExchangeError as e:
        logger.error(f"Gate.io Exchange Error: {e}")
        raise Exception(f"خطأ من Gate.io: {e}") from e
    except Exception as e:
        logger.error(f"Unexpected error fetching USDT balance: {e}")
        raise Exception(f"خطأ غير متوقع في جلب الرصيد: {e}") from e

# ─── الأسعار ────────────────────────────────────────────────────────────────

async def get_ticker_price(symbol, *a):
    return _client().fetch_ticker(_normalize(symbol))['last']

# ─── أوامر الشراء والبيع ────────────────────────────────────────────────────

async def place_buy_order(api_key, api_secret, symbol, usdt_amount):
    """
    تنفيذ أمر شراء سوقي مع:
    - التأكد من الحد الأدنى للصفقة
    - تنسيق الكمية حسب دقة السوق
    - تمرير السعر لـ Gate.io (إصلاح الخطأ)
    """
    if usdt_amount < 1:
        raise ValueError(f"المبلغ {usdt_amount} أقل من الحد الأدنى ($1)")

    e = _client()
    norm = _normalize(symbol)

    # جلب السعر الحالي
    p = e.fetch_ticker(norm)['last']
    if not p or p <= 0:
        raise ValueError(f"سعر غير صالح لـ {symbol}: {p}")

    # حساب الكمية وتنسيقها
    raw_qty = usdt_amount / p
    qty = _format_qty(symbol, raw_qty)

    # التأكد من الحد الأدنى للكمية
    min_qty = _get_min_amount(symbol)
    if qty < min_qty:
        qty = math.ceil(min_qty * 1000000) / 1000000
        logger.info(f"Adjusted qty to minimum {qty} for {symbol}")

    # التأكد من الحد الأدنى للقيمة
    min_cost = _get_min_cost(symbol)
    actual_cost = qty * p
    if actual_cost < min_cost:
        qty = _format_qty(symbol, min_cost / p)
        logger.info(f"Adjusted qty to meet min cost ${min_cost}: {qty}")

    # ✅ تنسيق السعر للـ Gate.io
    formatted_price = _format_price(symbol, p)

    logger.info(f"Placing BUY order: {symbol} | qty={qty} | price≈{p} | cost≈{qty*p:.2f} USDT")

    # ✅ الإصلاح الرئيسي: تمرير السعر كـ parameter ثالث
    o = e.create_market_buy_order(norm, qty, formatted_price)

    filled = float(o.get('filled', 0))
    cost = float(o.get('cost', 0))

    logger.info(f"BUY filled: {filled} {symbol} @ ${cost/filled if filled else p:.4f}")

    return {
        'order_id': o.get('id', ''),
        'symbol': symbol,
        'side': 'buy',
        'quantity': filled,
        'entry_price': round(cost / filled if filled else p, 8),
        'cost': cost
    }

async def place_sell_order(api_key, api_secret, symbol, quantity):
    """
    تنفيذ أمر بيع سوقي مع تنسيق الكمية
    """
    if quantity <= 0:
        raise ValueError(f"كمية البيع صفر أو سالبة: {quantity}")

    e = _client()
    norm = _normalize(symbol)

    qty = _format_qty(symbol, quantity)
    if qty <= 0:
        raise ValueError(f"الكمية المنقحة صفر لـ {symbol}")

    logger.info(f"Placing SELL order: {symbol} | qty={qty}")

    o = e.create_market_sell_order(norm, qty)

    filled = float(o.get('filled', 0))
    cost = float(o.get('cost', 0))

    logger.info(f"SELL filled: {filled} {symbol} @ ${cost/filled if filled else 0:.4f}")

    return {
        'order_id': o.get('id', ''),
        'symbol': symbol,
        'side': 'sell',
        'quantity': filled,
        'close_price': round(cost / filled if filled else 0, 8),
        'cost': cost
    }

# ─── الشموع ──────────────────────────────────────────────────────────────────

async def get_klines(symbol, interval='5m', limit=60):
    ohlcv = _client().fetch_ohlcv(_normalize(symbol), timeframe=interval, limit=limit)
    return [{'open': o[1], 'high': o[2], 'low': o[3], 'close': o[4], 'volume': o[5]} for o in ohlcv]

# ─── أعلى العملات ────────────────────────────────────────────────────────────

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