import hashlib
import hmac
import time
import aiohttp
import logging
from urllib.parse import urlencode
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

MEXC_BASE = "https://api.mexc.com"

# Shared session to avoid creating new connections every request
_session: Optional[aiohttp.ClientSession] = None


async def get_session() -> aiohttp.ClientSession:
    """Get or create shared aiohttp session."""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=100, limit_per_host=20)
        )
    return _session


async def close_session():
    """Close shared session on shutdown."""
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


def _sign(secret: str, params: dict) -> str:
    """Sign request with HMAC SHA256."""
    # Add recvWindow for security
    if "recvWindow" not in params:
        params["recvWindow"] = 5000

    query = urlencode(sorted(params.items()))
    return hmac.new(
        secret.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()


def _headers(api_key: str) -> dict:
    """Build request headers."""
    return {
        "X-MEXC-APIKEY": api_key,
        "Content-Type": "application/json"
    }


async def _get(path: str, params: dict = None) -> dict:
    """Make GET request."""
    session = await get_session()
    async with session.get(f"{MEXC_BASE}{path}", params=params or {}) as r:
        r.raise_for_status()
        return await r.json()


async def _signed_get(api_key: str, secret: str, path: str, params: dict = None) -> dict:
    """Make signed GET request."""
    session = await get_session()
    p = dict(params or {})
    p["timestamp"] = int(time.time() * 1000)
    p["signature"] = _sign(secret, p)

    async with session.get(
        f"{MEXC_BASE}{path}",
        params=p,
        headers=_headers(api_key)
    ) as r:
        r.raise_for_status()
        return await r.json()


async def _signed_post(api_key: str, secret: str, path: str, params: dict) -> dict:
    """Make signed POST request."""
    session = await get_session()
    p = dict(params)
    p["timestamp"] = int(time.time() * 1000)
    p["signature"] = _sign(secret, p)

    async with session.post(
        f"{MEXC_BASE}{path}",
        params=p,
        headers=_headers(api_key)
    ) as r:
        data = await r.json()
        if r.status >= 400:
            raise Exception(f"MEXC error {r.status}: {data}")
        return data


def _normalize(symbol: str) -> str:
    """Normalize symbol to MEXC format: BTCUSDT."""
    return symbol.replace("/", "").upper()


# ═══════════════════════════════════════════════════════════════
# الدوال العامة
# ═══════════════════════════════════════════════════════════════

async def get_ticker_price(symbol: str, api_key: str = "", api_secret: str = "") -> float:
    """Get current price for a symbol."""
    sym = _normalize(symbol)
    data = await _get("/api/v3/ticker/price", {"symbol": sym})
    return float(data["price"])


async def get_balance(api_key: str, api_secret: str) -> dict:
    """Get account balance."""
    data = await _signed_get(api_key, api_secret, "/api/v3/account")
    usdt = next(
        (b for b in data.get("balances", []) if b["asset"] == "USDT"),
        None
    )
    if not usdt:
        return {"free": 0.0, "used": 0.0, "total": 0.0}

    free = float(usdt["free"])
    locked = float(usdt["locked"])
    return {
        "free": free,
        "used": locked,
        "total": free + locked
    }


async def place_buy_order(api_key: str, api_secret: str, symbol: str, usdt_amount: float) -> dict:
    """Place market buy order."""
    sym = _normalize(symbol)

    # Get current price
    ticker = await _get("/api/v3/ticker/price", {"symbol": sym})
    price = float(ticker["price"])

    # Get exchange info for lot size
    info = await _get("/api/v3/exchangeInfo", {"symbol": sym})
    filters = info["symbols"][0].get("filters", []) if info.get("symbols") else []

    step = 0.000001
    min_qty = 0.000001
    for f in filters:
        if f.get("filterType") == "LOT_SIZE":
            step = float(f.get("stepSize", step))
            min_qty = float(f.get("minQty", min_qty))

    # Calculate quantity with precision
    qty = usdt_amount / price
    precision = len(str(step).rstrip("0").split(".")[-1]) if "." in str(step) else 0
    qty = round(qty - (qty % step), precision)

    if qty < min_qty:
        raise ValueError(
            f"المبلغ صغير جداً. الحد الأدنى: {min_qty * price:.2f} USDT"
        )

    # Place order
    order = await _signed_post(api_key, api_secret, "/api/v3/order", {
        "symbol": sym,
        "side": "BUY",
        "type": "MARKET",
        "quantity": str(qty),
    })

    filled_qty = float(order.get("executedQty", qty))
    filled_price = (
        float(order.get("cummulativeQuoteQty", usdt_amount)) / filled_qty
        if filled_qty else price
    )

    logger.info(f"MEXC buy order: {order.get('orderId')} | {sym} | qty={filled_qty}")

    return {
        "order_id": str(order.get("orderId", "")),
        "symbol": symbol,
        "side": "buy",
        "quantity": filled_qty,
        "entry_price": round(filled_price, 8),
        "cost": usdt_amount,
    }


async def place_sell_order(api_key: str, api_secret: str, symbol: str, quantity: float) -> dict:
    """Place market sell order."""
    sym = _normalize(symbol)

    order = await _signed_post(api_key, api_secret, "/api/v3/order", {
        "symbol": sym,
        "side": "SELL",
        "type": "MARKET",
        "quantity": str(quantity),
    })

    filled_qty = float(order.get("executedQty", quantity))
    quote_qty = float(order.get("cummulativeQuoteQty", 0))
    close_price = quote_qty / filled_qty if filled_qty else 0

    logger.info(f"MEXC sell order: {order.get('orderId')} | {sym} | qty={filled_qty}")

    return {
        "order_id": str(order.get("orderId", "")),
        "symbol": symbol,
        "side": "sell",
        "quantity": filled_qty,
        "close_price": round(close_price, 8),
        "cost": quote_qty,
    }


async def validate_api_keys(api_key: str, api_secret: str) -> bool:
    """Validate API keys by fetching balance."""
    try:
        await get_balance(api_key, api_secret)
        return True
    except Exception as e:
        logger.error(f"API validation failed: {e}")
        return False


async def get_klines(symbol: str, interval: str = "15m", limit: int = 60) -> List[Dict]:
    """Get OHLCV candles."""
    sym = _normalize(symbol)
    data = await _get("/api/v3/klines", {
        "symbol": sym,
        "interval": interval,
        "limit": limit
    })

    candles = []
    for k in data:
        candles.append({
            "open_time": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        })
    return candles


# ═══════════════════════════════════════════════════════════════
# دالة جلب أعلى العملات (خاصة بالاستراتيجية السريعة)
# ═══════════════════════════════════════════════════════════════

async def get_top_symbols(count: int = 300) -> List[str]:
    """Get top symbols by 24h volume."""
    stats = await _get("/api/v3/ticker/24hr", {})

    symbols = []
    for stat in stats:
        symbol = stat.get("symbol", "")
        if symbol.endswith("USDT"):
            try:
                volume = float(stat.get("quoteVolume", 0))
                symbols.append({
                    "symbol": symbol,
                    "volume": volume
                })
            except:
                continue

    symbols.sort(key=lambda x: x["volume"], reverse=True)
    return [s["symbol"] for s in symbols[:count]]