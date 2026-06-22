import hashlib
import hmac
import time
import aiohttp
import json

GATE_BASE = "https://api.gateio.ws/api/v4"

def _sign(secret, method, path, query, body, timestamp):
    s = f"{method}\n{path}\n{query}\n{body}\n{timestamp}"
    return hmac.new(secret.encode('utf-8'), s.encode('utf-8'), hashlib.sha512).hexdigest()

def _normalize(symbol):
    sym = symbol.replace("/", "_").upper()
    if "_" not in sym:
        sym = sym[:-4] + "_USDT" if sym.endswith("USDT") else sym + "_USDT"
    return sym

async def _request(method, path, api_key="", api_secret="", params=None, body=None):
    async with aiohttp.ClientSession() as s:
        url = f"{GATE_BASE}{path}"
        headers = {}
        
        if api_key and api_secret:
            qs = ""
            if params:
                qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            body_str = json.dumps(body) if body else ""
            ts = str(int(time.time()))
            sig = _sign(api_secret, method, path, qs, body_str, ts)
            headers = {
                "KEY": api_key,
                "SIGN": sig,
                "Timestamp": ts,
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
        
        full_url = url
        if method == "GET" and params:
            full_url = url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        
        if method == "GET":
            resp = await s.get(full_url, headers=headers)
        else:
            resp = await s.post(url, json=body, headers=headers)
        
        data = await resp.json()
        
        if resp.status >= 400:
            raise Exception(f"Gate error {resp.status}: {data}")
        return data

async def get_ticker_price(symbol, api_key="", api_secret=""):
    sym = _normalize(symbol)
    data = await _request("GET", "/spot/tickers", params={"currency_pair": sym})
    return float(data[0]["last"])

async def get_balance(api_key, api_secret):
    data = await _request("GET", "/spot/accounts", api_key=api_key, api_secret=api_secret)
    usdt = next((b for b in data if b["currency"] == "USDT"), None)
    if not usdt:
        return {"free": 0.0, "used": 0.0, "total": 0.0}
    free = float(usdt["available"])
    locked = float(usdt.get("locked", 0))
    return {"free": free, "used": locked, "total": free + locked}

async def place_buy_order(api_key, api_secret, symbol, usdt_amount):
    sym = _normalize(symbol)
    tickers = await _request("GET", "/spot/tickers", params={"currency_pair": sym})
    price = float(tickers[0]["last"])
    qty = usdt_amount / price
    body = {"currency_pair": sym, "side": "buy", "type": "market", "amount": str(round(qty, 6)), "time_in_force": "ioc"}
    order = await _request("POST", "/spot/orders", api_key=api_key, api_secret=api_secret, body=body)
    filled_qty = float(order.get("filled_amount", qty))
    filled_total = float(order.get("filled_total", usdt_amount))
    filled_price = filled_total / filled_qty if filled_qty else price
    return {"order_id": str(order.get("id", "")), "symbol": symbol, "side": "buy", "quantity": filled_qty, "entry_price": round(filled_price, 8), "cost": usdt_amount}

async def place_sell_order(api_key, api_secret, symbol, quantity):
    sym = _normalize(symbol)
    body = {"currency_pair": sym, "side": "sell", "type": "market", "amount": str(quantity), "time_in_force": "ioc"}
    order = await _request("POST", "/spot/orders", api_key=api_key, api_secret=api_secret, body=body)
    filled_qty = float(order.get("filled_amount", quantity))
    filled_total = float(order.get("filled_total", 0))
    close_price = filled_total / filled_qty if filled_qty else 0
    return {"order_id": str(order.get("id", "")), "symbol": symbol, "side": "sell", "quantity": filled_qty, "close_price": round(close_price, 8), "cost": filled_total}

async def get_klines(symbol, interval="5m", limit=60):
    sym = _normalize(symbol)
    data = await _request("GET", "/spot/candlesticks", params={"currency_pair": sym, "interval": interval, "limit": limit})
    candles = []
    for k in data:
        if len(k) >= 6:
            candles.append({"open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])})
    return candles

async def get_top_symbols(count=300):
    data = await _request("GET", "/spot/tickers")
    symbols = []
    for item in data:
        symbol = item.get("currency_pair", "")
        if symbol.endswith("_USDT"):
            symbols.append({"symbol": symbol.replace("_", ""), "volume": float(item.get("quote_volume", 0))})
    symbols.sort(key=lambda x: x["volume"], reverse=True)
    return [s["symbol"] for s in symbols[:count]]