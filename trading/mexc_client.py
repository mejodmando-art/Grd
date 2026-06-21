import hashlib
import hmac
import time
import aiohttp
import logging
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

MEXC_BASE = "https://api.mexc.com"


def _sign(secret: str, params: dict) -> str:
    query = urlencode(sorted(params.items()))
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def _headers(api_key: str) -> dict:
    return {"X-MEXC-APIKEY": api_key, "Content-Type": "application/json"}


async def _get(session: aiohttp.ClientSession, path: str, params: dict = None):
    async with session.get(f"{MEXC_BASE}{path}", params=params or {}) as r:
        r.raise_for_status()
        return await r.json()


async def _signed_get(session: aiohttp.ClientSession, api_key: str, secret: str, path: str, params: dict = None):
    p = dict(params or {})
    p["timestamp"] = int(time.time() * 1000)
    p["signature"] = _sign(secret, p)
    async with session.get(f"{MEXC_BASE}{path}", params=p, headers=_headers(api_key)) as r:
        r.raise_for_status()
        return await r.json()


async def _signed_post(session: aiohttp.ClientSession, api_key: str, secret: str, path: str, params: dict):
    p = dict(params)
    p["timestamp"] = int(time.time() * 1000)
    p["signature"] = _sign(secret, p)
    async with session.post(f"{MEXC_BASE}{path}", params=p, headers=_headers(api_key)) as r:
        data = await r.json()
        if r.status >= 400:
            raise Exception(f"MEXC error {r.status}: {data}")
        return data


def _normalize(symbol: str) -> str:
    """BTC/USDT or BTCUSDT -> BTCUSDT"""
    return symbol.replace("/", "").upper()


async def get_ticker_price(symbol: str, api_key: str = "", api_secret: str = "") -> float:
    sym = _normalize(symbol)
    async with aiohttp.ClientSession() as s:
        data = await _get(s, "/api/v3/ticker/price", {"symbol": sym})
    return float(data["price"])


async def get_balance(api_key: str, api_secret: str) -> dict:
    async with aiohttp.ClientSession() as s:
        data = await _signed_get(s, api_key, api_secret, "/api/v3/account")
    usdt = next((b for b in data.get("balances", []) if b["asset"] == "USDT"), None)
    if not usdt:
        return {"free": 0.0, "used": 0.0, "total": 0.0}
    free = float(usdt["free"])
    locked = float(usdt["locked"])
    return {"free": free, "used": locked, "total": free + locked}


async def place_buy_order(api_key: str, api_secret: str, symbol: str, usdt_amount: float) -> dict:
    sym = _normalize(symbol)
    async with aiohttp.ClientSession() as s:
        # Get price
        ticker = await _get(s, "/api/v3/ticker/price", {"symbol": sym})
        price = float(ticker["price"])

        # Get symbol info for precision
        info = await _get(s, "/api/v3/exchangeInfo", {"symbol": sym})
        filters = info["symbols"][0].get("filters", []) if info.get("symbols") else []
        step = 0.000001
        min_qty = 0.000001
        for f in filters:
            if f.get("filterType") == "LOT_SIZE":
                step = float(f.get("stepSize", step))
                min_qty = float(f.get("minQty", min_qty))

        # Calculate quantity and round to step
        qty = usdt_amount / price
        precision = len(str(step).rstrip("0").split(".")[-1]) if "." in str(step) else 0
        qty = round(qty - (qty % step), precision)

        if qty < min_qty:
            raise ValueError(f"المبلغ صغير جداً. الحد الأدنى: {min_qty * price:.2f} USDT")

        # Place order
        order = await _signed_post(s, api_key, api_secret, "/api/v3/order", {
            "symbol": sym,
            "side": "BUY",
            "type": "MARKET",
            "quantity": str(qty),
        })

    filled_qty = float(order.get("executedQty", qty))
    filled_price = float(order.get("cummulativeQuoteQty", usdt_amount)) / filled_qty if filled_qty else price

    logger.info(f"Buy order placed: {order.get('orderId')} | {sym} | qty={filled_qty}")
    return {
        "order_id": str(order.get("orderId", "")),
        "symbol": symbol,
        "side": "buy",
        "quantity": filled_qty,
        "entry_price": round(filled_price, 8),
        "cost": usdt_amount,
    }


async def place_sell_order(api_key: str, api_secret: str, symbol: str, quantity: float) -> dict:
    sym = _normalize(symbol)
    async with aiohttp.ClientSession() as s:
        order = await _signed_post(s, api_key, api_secret, "/api/v3/order", {
            "symbol": sym,
            "side": "SELL",
            "type": "MARKET",
            "quantity": str(quantity),
        })

    filled_qty = float(order.get("executedQty", quantity))
    quote_qty = float(order.get("cummulativeQuoteQty", 0))
    close_price = quote_qty / filled_qty if filled_qty else 0

    logger.info(f"Sell order placed: {order.get('orderId')} | {sym} | qty={filled_qty}")
    return {
        "order_id": str(order.get("orderId", "")),
        "symbol": symbol,
        "side": "sell",
        "quantity": filled_qty,
        "close_price": round(close_price, 8),
        "cost": quote_qty,
    }


async def validate_api_keys(api_key: str, api_secret: str) -> bool:
    try:
        await get_balance(api_key, api_secret)
        return True
    except Exception as e:
        logger.error(f"API validation failed: {e}")
        return False
