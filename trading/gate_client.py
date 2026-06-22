import hashlib
import hmac
import time
import aiohttp
import logging
import json

logger = logging.getLogger("GateClient")

GATE_BASE = "https://api.gateio.ws/api/v4"


def _sign(secret, method, path, query, body, timestamp):
    s = f"{method}\n{path}\n{query}\n{body}\n{timestamp}"
    return hmac.new(secret.encode(), s.encode(), hashlib.sha512).hexdigest()


def _headers(api_key, signature, timestamp):
    return {"KEY": api_key, "SIGN": signature, "Timestamp": timestamp, "Content-Type": "application/json"}


def _normalize(symbol):
    sym = symbol.replace("/", "_").upper()
    if "_" not in sym:
        sym = sym[:-4] + "_USDT"
    return sym


async def _get(session, path, params=None):
    async with session.get(f"{GATE_BASE}{path}", params=params or {}) as r:
        return await r.json()


async def _signed(session, api_key, secret, method, path, params=None, body=None):
    qs = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    body_str = json.dumps(body) if body else ""
    ts = str(int(time.time()))
    sig = _sign(secret, method, path, qs, body_str, ts)
    h = _headers(api_key, sig, ts)
    url = f"{GATE_BASE}{path}" + (f"?{qs}" if qs and method == "GET" else "")
    async with session.request(method, url, json=body, headers=h) as r:
        data = await r.json()
        if r.status >= 400:
            raise Exception(f"Gate error {r.status}: {data}")
        return data


async def get_ticker_price(symbol, api_key="", api_secret=""):
    sym = _normalize(symbol)
    async with aiohttp.ClientSession() as s:
        data = await _get(s, "/spot/tickers", {"currency_pair": sym})
    return float(data[0]["last"])


async def get_balance(api_key, api_secret):
    async with aiohttp.ClientSession() as s:
        data = await _signed(s, api_key, api_secret, "GET", "/spot/accounts")
    usdt = next((b for b in data if b["currency"] == "USDT"), None)
    if not usdt:
        return {"free": 0.0, "used": 0.0, "total": 0.0}
    return {"free": float(usdt["available"]), "used": float(usdt.get("locked", 0)), "total": float(usdt["available"]) + float(usdt.get("locked", 0))}


async def place_buy_order(api_key, api_secret, symbol, usdt_amount):
    sym = _normalize(symbol)
    async with aiohttp.ClientSession() as s:
        tickers = await _get(s, "/spot/tickers", {"currency_pair": sym})
        price = float(tickers[0]["last"])
        qty = usdt_amount / price
        order = await _signed(s, api_key, api_secret, "POST", "/spot/orders", body={
            "currency_pair": sym, "side": "buy", "type": "market",
            "amount": str(round(qty, 6)), "time_in_force": "ioc"
        })
    filled_qty = float(order.get("filled_amount", qty))
    filled_price = float(order.get("filled_total", usdt_amount)) / filled_qty if filled_qty else price
    return {"order_id": str(order.get("id", "")), "symbol": symbol, "side": "buy", "quantity": filled_qty, "entry_price": round(filled_price, 8), "cost": usdt_amount}


async def place_sell_order(api_key, api_secret, symbol, quantity):
    sym = _normalize(symbol)
    async with aiohttp.ClientSession() as s:
        order = await _signed(s, api_key, api_secret, "POST", "/spot/orders", body={
            "currency_pair": sym, "side": "sell", "type": "market",
            "amount": str(quantity), "time_in_force": "ioc"
        })
    filled_qty = float(order.get("filled_amount", quantity))
    quote_qty = float(order.get("filled_total", 0))
    close_price = quote_qty / filled_qty if filled_qty else 0
    return {"order_id": str(order.get("id", "")), "symbol": symbol, "side": "sell", "quantity": filled_qty, "close_price": round(close_price, 8), "cost": quote_qty}


async def get_klines(symbol, interval="5m", limit=60):
    sym = _normalize(symbol)
    async with aiohttp.ClientSession() as s:
        data = await _get(s, "/spot/candlesticks", {"currency_pair": sym, "interval": interval, "limit": limit})
    candles = []
    for k in data:
        candles.append({"open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])})
    return candles


async def get_top_symbols(count=300):
    async with aiohttp.ClientSession() as s:
        data = await _get(s, "/spot/tickers")
    symbols = []
    for item in data:
        symbol = item.get("currency_pair", "")
        if symbol.endswith("_USDT"):
            symbols.append({"symbol": symbol.replace("_", ""), "volume": float(item.get("quote_volume", 0))})
    symbols.sort(key=lambda x: x["volume"], reverse=True)
    return [s["symbol"] for s in symbols[:count]]