import hashlib
import hmac
import time
import aiohttp
import logging
import json

logger = logging.getLogger("GateClient")

GATE_BASE = "https://api.gateio.ws/api/v4"


def _sign(secret: str, method: str, path: str, query_string: str, body_string: str, timestamp: str) -> str:
    s = f"{method}\n{path}\n{query_string}\n{body_string}\n{timestamp}"
    return hmac.new(secret.encode('utf-8'), s.encode('utf-8'), hashlib.sha512).hexdigest()


def _headers(api_key: str, signature: str, timestamp: str) -> dict:
    return {
        "KEY": api_key,
        "SIGN": signature,
        "Timestamp": timestamp,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _normalize(symbol: str) -> str:
    sym = symbol.replace("/", "_").upper()
    if "_" not in sym:
        if sym.endswith("USDT"):
            sym = sym[:-4] + "_USDT"
    return sym


def _denormalize(symbol: str) -> str:
    return symbol.replace("_", "")


async def _get(session: aiohttp.ClientSession, path: str, params: dict = None):
    url = f"{GATE_BASE}{path}"
    async with session.get(url, params=params or {}) as r:
        data = await r.json()
        if r.status >= 400:
            raise Exception(f"Gate error {r.status}: {data}")
        return data


async def _signed_request(session: aiohttp.ClientSession, api_key: str, secret: str, method: str, path: str, params: dict = None, body: dict = None):
    query_string = ""
    if params:
        query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    
    body_string = ""
    if body:
        body_string = json.dumps(body)
    
    timestamp = str(int(time.time()))
    signature = _sign(secret, method, path, query_string, body_string, timestamp)
    headers = _headers(api_key, signature, timestamp)
    
    url = f"{GATE_BASE}{path}"
    if query_string and method == "GET":
        url += f"?{query_string}"
    
    async with session.request(method, url, params=params if method == "POST" else None, json=body, headers=headers) as r:
        data = await r.json()
        if r.status >= 400:
            raise Exception(f"Gate error {r.status}: {data}")
        return data


async def get_ticker_price(symbol: str, api_key: str = "", api_secret: str = "") -> float:
    sym = _normalize(symbol)
    async with aiohttp.ClientSession() as s:
        data = await _get(s, "/spot/tickers", {"currency_pair": sym})
    if data and len(data) > 0:
        return float(data[0]["last"])
    raise Exception(f"لم يتم العثور على {symbol}")


async def get_balance(api_key: str, api_secret: str) -> dict:
    async with aiohttp.ClientSession() as s:
        data = await _signed_request(s, api_key, api_secret, "GET", "/spot/accounts")
    
    usdt = next((b for b in data if b.get("currency") == "USDT"), None)
    if not usdt:
        return {"free": 0.0, "used": 0.0, "total": 0.0}
    free = float(usdt.get("available", 0))
    locked = float(usdt.get("locked", 0))
    return {"free": free, "used": locked, "total": free + locked}


async def place_buy_order(api_key: str, api_secret: str, symbol: str, usdt_amount: float) -> dict:
    sym = _normalize(symbol)
    async with aiohttp.ClientSession() as s:
        tickers = await _get(s, "/spot/tickers", {"currency_pair": sym})
        if not tickers:
            raise Exception(f"لم يتم العثور على {symbol}")
        price = float(tickers[0]["last"])
        
        qty = usdt_amount / price
        body = {
            "currency_pair": sym,
            "side": "buy",
            "type": "market",
            "amount": str(round(qty, 6)),
            "time_in_force": "ioc",
        }
        order = await _signed_request(s, api_key, api_secret, "POST", "/spot/orders", body=body)
    
    filled_qty = float(order.get("filled_amount", qty))
    filled_total = float(order.get("filled_total", usdt_amount))
    filled_price = filled_total / filled_qty if filled_qty else price
    
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
        order = await _signed_request(s, api_key, api_secret, "POST", "/spot/orders", body=body)
    
    filled_qty = float(order.get("filled_amount", quantity))
    filled_total = float(order.get("filled_total", 0))
    close_price = filled_total / filled_qty if filled_qty else 0
    
    logger.info(f"Gate Sell: {order.get('id')} | {sym} | qty={filled_qty}")
    return {
        "order_id": str(order.get("id", "")),
        "symbol": symbol,
        "side": "sell",
        "quantity": filled_qty,
        "close_price": round(close_price, 8),
        "cost": filled_total,
    }


async def get_klines(symbol: str, interval: str = "5m", limit: int = 60) -> list:
    sym = _normalize(symbol)
    interval_map = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
    gate_interval = interval_map.get(interval, "5m")
    async with aiohttp.ClientSession() as s:
        data = await _get(s, "/spot/candlesticks", {
            "currency_pair": sym,
            "interval": gate_interval,
            "limit": limit,
        })
    candles = []
    for k in data:
        if len(k) >= 6:
            candles.append({
                "open_time": int(float(k[0])),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            })
    return candles


async def get_top_symbols(count: int = 300) -> list:
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