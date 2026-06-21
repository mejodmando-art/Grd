import ccxt.async_support as ccxt
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def get_exchange(api_key: str, api_secret: str) -> ccxt.mexc:
    """Create and return an authenticated MEXC exchange instance."""
    exchange = ccxt.mexc({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "options": {
            "defaultType": "spot",
        },
    })
    return exchange


async def get_balance(api_key: str, api_secret: str) -> dict:
    """Fetch USDT balance from MEXC."""
    exchange = get_exchange(api_key, api_secret)
    try:
        balance = await exchange.fetch_balance()
        usdt = balance.get("USDT", {})
        return {
            "free": usdt.get("free", 0),
            "used": usdt.get("used", 0),
            "total": usdt.get("total", 0),
        }
    except Exception as e:
        logger.error(f"Balance fetch error: {e}")
        raise
    finally:
        await exchange.close()


async def get_ticker_price(symbol: str, api_key: str = "", api_secret: str = "") -> float:
    """Get current market price for a symbol."""
    exchange = get_exchange(api_key, api_secret) if api_key else ccxt.mexc({"enableRateLimit": True})
    try:
        # Normalize symbol format: BTC/USDT or BTCUSDT -> BTC/USDT
        if "/" not in symbol:
            if symbol.endswith("USDT"):
                symbol = symbol[:-4] + "/USDT"
        ticker = await exchange.fetch_ticker(symbol)
        return float(ticker["last"])
    except Exception as e:
        logger.error(f"Ticker fetch error for {symbol}: {e}")
        raise
    finally:
        await exchange.close()


async def place_buy_order(
    api_key: str,
    api_secret: str,
    symbol: str,
    usdt_amount: float,
) -> dict:
    """Place a market buy order."""
    exchange = get_exchange(api_key, api_secret)
    try:
        # Normalize symbol
        if "/" not in symbol:
            if symbol.endswith("USDT"):
                symbol = symbol[:-4] + "/USDT"

        # Get current price to calculate quantity
        ticker = await exchange.fetch_ticker(symbol)
        price = float(ticker["last"])
        market = await exchange.load_markets()
        market_info = market.get(symbol, {})
        
        # Calculate quantity
        quantity = usdt_amount / price
        
        # Apply minimum notional and precision
        min_amount = market_info.get("limits", {}).get("amount", {}).get("min", 0)
        if quantity < min_amount:
            raise ValueError(f"Amount too small. Minimum: {min_amount} {symbol.split('/')[0]}")

        order = await exchange.create_market_buy_order(symbol, quantity)
        logger.info(f"Buy order placed: {order['id']} | {symbol} | qty={quantity:.6f}")
        return {
            "order_id": str(order["id"]),
            "symbol": symbol,
            "side": "buy",
            "quantity": float(order.get("filled", quantity)),
            "entry_price": float(order.get("average", price)),
            "cost": float(order.get("cost", usdt_amount)),
        }
    except Exception as e:
        logger.error(f"Buy order error: {e}")
        raise
    finally:
        await exchange.close()


async def place_sell_order(
    api_key: str,
    api_secret: str,
    symbol: str,
    quantity: float,
) -> dict:
    """Place a market sell order."""
    exchange = get_exchange(api_key, api_secret)
    try:
        if "/" not in symbol:
            if symbol.endswith("USDT"):
                symbol = symbol[:-4] + "/USDT"

        order = await exchange.create_market_sell_order(symbol, quantity)
        logger.info(f"Sell order placed: {order['id']} | {symbol} | qty={quantity:.6f}")
        return {
            "order_id": str(order["id"]),
            "symbol": symbol,
            "side": "sell",
            "quantity": float(order.get("filled", quantity)),
            "close_price": float(order.get("average", 0)),
            "cost": float(order.get("cost", 0)),
        }
    except Exception as e:
        logger.error(f"Sell order error: {e}")
        raise
    finally:
        await exchange.close()


async def validate_api_keys(api_key: str, api_secret: str) -> bool:
    """Validate MEXC API keys by fetching balance."""
    try:
        await get_balance(api_key, api_secret)
        return True
    except Exception:
        return False
