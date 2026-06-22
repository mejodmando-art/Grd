import hashlib
import hmac
import time
import aiohttp
import logging
import json

logger = logging.getLogger("GateClient")

GATE_BASE = "https://api.gateio.ws/api/v4"


def _sign(secret: str, method: str, path: str, query: str, body: str, timestamp: str) -> str:
    """توقيع طلبات Gate.io"""
    s = f"{method}\n{path}\n{query}\n{body}\n{timestamp}"
    return hmac.new(secret.encode(), s.encode(), hashlib.sha512).hexdigest()


def _headers(api_key: str, signature: str, timestamp: str) -> dict:
    return {
        "KEY": api_key,
        "SIGN": signature,
        "Timestamp": timestamp,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _normalize(symbol: str) -> str:
    """BTC/USDT or BTCUSDT -> BTC_USDT"""
    sym = symbol.replace("/", "_").upper()
    if "_" not in sym:
        sym = sym[:-4] + "_" + sym[-4:]
    return sym


def _denormalize(symbol: str) -> str:
    """BTC_USDT -> BTCUSDT"""
    return symbol.replace("_", "")


async def _get(session: aiohttp.ClientSession, path: str, params: dict = None):
    async with session.get(f"{GATE_BASE}{path}", params=params or {}) as r:
        r.raise_for_status()
        return await r.json()


async def _signed_get(session: aiohttp.ClientSession, api_key: str, secret: str, path: str, params: dict = None):
    query = "&".join([f"{k}={v}" for k, v in sorted((params or {}).items())])
    timestamp = str(int(time.time()))
    signature = _sign(secret, "GET", path, query, "", timestamp)
    headers = _headers(api_key, signature, timestamp)
    async with session.get(f"{GATE_BASE}{path}?{query}" if query else f"{GATE_BASE}{path}", headers=headers) as r:
        r.raise_for_status()
        return await r.json()


async def _signed_post(session: aiohttp.ClientSession, api_key: str, secret: str, path: str, body: dict):
    body_str = json.dumps(body) if body else ""
    timestamp = str(int(time.time()))
    signature = _sign(secret, "POST", path, "", body_str, timestamp)
    headers = _headers(api_key, signature, timestamp)
    async with session.post(f"{GATE_BASE}{path}", data=body_str, headers=headers) as r:
        data = await r.json()
        if r.status >= 400:
            raise Exception(f"Gate error {r.status}: {data}")
        return data


async def get_ticker_price(symbol: str, api_key: str = "", api_secret: str = "") -> float:
    sym = _normalize(symbol)
    async with aiohttp.ClientSession() as s:
        data = await _get(s, "/spot/tickers", {"currency_pair": sym})
    return float(data[0]["last"])


async def get_balance(api_key: str, api_secret: str) -> dict:
    async with aiohttp.ClientSession() as s:
        data = await _signed_get(s, api_key, api_secret, "/spot/accounts")
    usdt = next((b for b in data if b["currency"] == "USDT"), None)
    if not usdt:
        return {"free": 0.0, "used": 0.0, "total": 0.0}
    free = float(usdt["available"])
    locked = float(usdt["locked"])
    return {"free": free, "used": locked, "total": free + locked}


async def place_buy_order(api_key: str, api_secret: str, symbol: str, usdt_amount: float) -> dict:
    sym = _normalize(symbol)
    async with aiohttp.ClientSession() as s:
        tickers = await _get(s, "/spot/tickers", {"currency_pair": sym})
        price = float(tickers[0]["last"])

        qty = usdt_amount / price
        body = {
            "currency_pair": sym,
            "side": "buy",
            "type": "market",
            "amount": str(round(qty, 6)),
            "time_in_force": "ioc",
        }
        order = await _signed_post(s, api_key, api_secret, "/spot/orders", body)

    filled_qty = float(order.get("filled_amount", qty))
    filled_price = float(order.get("filled_total", usdt_amount)) / filled_qty if filled_qty else price

    logger.info(f"Gate Buy: {order.get('id')} | {sym} | qty={filled_qty}")
    return {
        "order_id": str(order.get("id", "")),
        "symbol": symbol,
        "side": "buy",
        "quantity": filled_qty,
        "entry_price": round(filled_price, 8),
        "cost": usdt_amount,
    }


async def place_sell_order(api_key: str, api_secret: str, symbol: str, quantity: float) -> dict:
    sym = _normalize(symbol)
    async with aiohttp.ClientSession() as s:
        body = {
            "currency_pair": sym,
            "side": "sell",
            "type": "market",
            "amount": str(quantity),
            "time_in_force": "ioc",
        }
        order = await _signed_post(s, api_key, api_secret, "/spot/orders", body)

    filled_qty = float(order.get("filled_amount", quantity))
    quote_qty = float(order.get("filled_total", 0))
    close_price = quote_qty / filled_qty if filled_qty else 0

    logger.info(f"Gate Sell: {order.get('id')} | {sym} | qty={filled_qty}")
    return {
        "order_id": str(order.get("id", "")),
        "symbol": symbol,
        "side": "sell",
        "quantity": filled_qty,
        "close_price": round(close_price, 8),
        "cost": quote_qty,
    }


async def get_klines(symbol: str, interval: str = "5m", limit: int = 60) -> list:
    sym = _normalize(symbol)
    # Gate.io يستخدم صيغة مختلفة للفاصل الزمني
    interval_map = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
    gate_interval = interval_map.get(interval, "5m")
    async with aiohttp.ClientSession() as s:
        data = await _get(s, "/spot/candlesticks", {
            "currency_pair": sym,
            "interval": gate_interval,
            "limit": limit,
        })
    candles = []
    for k in reversed(data):
        candles.append({
            "open_time": int(k[0]),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        })
    return candles


async def get_top_symbols(count: int = 300) -> list:
    """جلب أعلى العملات من حيث حجم التداول"""
    async with aiohttp.ClientSession() as s:
        data = await _get(s, "/spot/tickers")
    symbols = []
    for item in data:
        symbol = item.get("currency_pair", "")
        if symbol.endswith("_USDT"):
            try:
                volume = float(item.get("quote_volume", 0))
                symbols.append({"symbol": _denormalize(symbol), "volume": volume})
            except:
                continue
    symbols.sort(key=lambda x: x["volume"], reverse=True)
    return [s["symbol"] for s in symbols[:count]]


async def validate_api_keys(api_key: str, api_secret: str) -> bool:
    try:
        await get_balance(api_key, api_secret)
        return True
    except:
        return False