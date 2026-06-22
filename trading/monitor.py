import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from database.client import (
    get_all_open_trades, update_trade, save_trade, get_all_active_users
)
from trading.mexc_client import (
    get_ticker_price, place_buy_order, place_sell_order, get_klines, get_top_symbols
)
from config import (
    MONITOR_INTERVAL, TOP_SYMBOLS_COUNT, EMA_FAST, EMA_SLOW,
    TP_PERCENT, SL_PERCENT, MIN_VOLUME_RATIO, KLINE_INTERVAL,
    KLINE_LIMIT, MAX_OPEN_TRADES
)

logger = logging.getLogger(__name__)
_app = None
_top_symbols_cache = []
_last_cache_time = 0

def set_app(app):
    global _app
    _app = app


def calculate_ema(prices: list, period: int) -> list:
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    ema_values = [sum(prices[:period]) / period]
    for price in prices[period:]:
        ema = price * k + ema_values[-1] * (1 - k)
        ema_values.append(ema)
    return [None] * (period - 1) + ema_values


async def get_symbols_to_scan() -> list:
    global _top_symbols_cache, _last_cache_time
    now = time.time()
    if not _top_symbols_cache or (now - _last_cache_time) > 600:
        try:
            _top_symbols_cache = await get_top_symbols(TOP_SYMBOLS_COUNT)
            _last_cache_time = now
            logger.info(f"تم تحديث قائمة {len(_top_symbols_cache)} عملة")
        except Exception as e:
            logger.error(f"خطأ في جلب العملات: {e}")
    return _top_symbols_cache or ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


async def analyze_symbol(symbol: str) -> dict | None:
    try:
        klines = await get_klines(symbol, KLINE_INTERVAL, KLINE_LIMIT)
        if len(klines) < 25:
            return None

        closes = [c["close"] for c in klines]
        volumes = [c["volume"] for c in klines]

        ema_fast = calculate_ema(closes, EMA_FAST)
        ema_slow = calculate_ema(closes, EMA_SLOW)

        if not ema_fast or not ema_slow:
            return None

        prev_fast = ema_fast[-2]
        prev_slow = ema_slow[-2]
        curr_fast = ema_fast[-1]
        curr_slow = ema_slow[-1]

        if prev_fast is None or prev_slow is None:
            return None

        if prev_fast <= prev_slow and curr_fast > curr_slow:
            avg_vol = sum(volumes[-20:-1]) / 19 if len(volumes) >= 20 else sum(volumes[:-1]) / max(len(volumes)-1, 1)
            if volumes[-1] >= avg_vol * MIN_VOLUME_RATIO:
                price = closes[-1]
                return {
                    "symbol": symbol,
                    "entry_price": price,
                    "take_profit": round(price * (1 + TP_PERCENT/100), 6),
                    "stop_loss": round(price * (1 - SL_PERCENT/100), 6),
                }
    except:
        pass
    return None


async def open_trade(signal: dict, user_id: int, amount: float):
    api_key = os.getenv("MEXC_API_KEY", "")
    api_secret = os.getenv("MEXC_API_SECRET", "")
    if not api_key or not api_secret:
        return
    try:
        result = await place_buy_order(api_key, api_secret, signal["symbol"], amount)
        trade = {
            "user_id": user_id, "symbol": signal["symbol"],
            "side": "buy", "entry_price": result["entry_price"],
            "amount": amount, "quantity": result["quantity"],
            "take_profit": signal["take_profit"], "stop_loss": signal["stop_loss"],
            "status": "open", "order_id": result["order_id"], "signal_id": "auto",
        }
        await save_trade(trade)
        logger.info(f"✅ صفقة جديدة: {signal['symbol']}")
        if _app:
            await _app.bot.send_message(user_id, f"🤖 {signal['symbol']}\nدخول: {signal['entry_price']}\nمبلغ: {amount}$", parse_mode="HTML")
    except Exception as e:
        logger.error(f"فشل فتح صفقة {signal['symbol']}: {e}")


async def close_trade(trade: dict, price: float, reason: str):
    api_key = os.getenv("MEXC_API_KEY", "")
    api_secret = os.getenv("MEXC_API_SECRET", "")
    if not api_key or not api_secret:
        return
    try:
        result = await place_sell_order(api_key, api_secret, trade["symbol"], trade["quantity"])
        price = result.get("close_price", price)
    except:
        pass
    pnl = (price - float(trade["entry_price"])) * float(trade["quantity"])
    await update_trade(trade["id"], {
        "status": "closed", "close_price": price, "pnl": round(pnl, 4),
        "closed_at": datetime.now(timezone.utc).isoformat(), "close_reason": reason,
    })
    emoji = "🎯" if reason == "take_profit" else "🛑"
    if _app:
        await _app.bot.send_message(trade["user_id"], f"{emoji} {trade['symbol']} | P&L: {pnl:+.4f} USDT", parse_mode="HTML")


async def monitor_loop():
    logger.info("📡 نظام التداول الآلي السريع...")
    while True:
        try:
            trades = await get_all_open_trades()
            open_count = len(trades)

            for t in trades:
                try:
                    price = await get_ticker_price(t["symbol"])
                    tp = float(t.get("take_profit") or 0)
                    sl = float(t.get("stop_loss") or 0)
                    if tp and price >= tp:
                        await close_trade(t, price, "take_profit")
                    elif sl and price <= sl:
                        await close_trade(t, price, "stop_loss")
                except:
                    pass

            if open_count < MAX_OPEN_TRADES:
                users = await get_all_active_users()
                auto_users = [u for u in users if u.get("auto_trade")]
                if auto_users:
                    symbols = await get_symbols_to_scan()
                    open_symbols = [t["symbol"] for t in trades]
                    for sym in symbols:
                        if sym in open_symbols:
                            continue
                        signal = await analyze_symbol(sym)
                        if signal:
                            for user in auto_users:
                                amount = float(user.get("default_amount", 10))
                                await open_trade(signal, user["id"], amount)
                            break
        except Exception as e:
            logger.error(f"خطأ: {e}")
        await asyncio.sleep(MONITOR_INTERVAL)