import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from database.client import get_all_open_trades, update_trade, save_trade, get_all_active_users
from trading.gate_client import (
    get_ticker_price, place_buy_order, place_sell_order, get_klines, get_top_symbols, get_balance
)
from config import (
    MONITOR_INTERVAL, TOP_SYMBOLS_COUNT, EMA_FAST, EMA_SLOW,
    TP_PERCENT, SL_PERCENT, MIN_VOLUME_RATIO, KLINE_INTERVAL,
    KLINE_LIMIT, MAX_OPEN_TRADES, DEFAULT_AMOUNT
)

logger = logging.getLogger("GateBot")
_app = None
_top_symbols_cache = []
_last_cache_time = 0
_notified_signals = set()
_failed_symbols = {}

def set_app(app):
    global _app
    _app = app


def tv_link(symbol):
    return f"https://www.tradingview.com/chart/?symbol=GATE:{symbol}"


def calculate_ema(prices, period):
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(prices[:period]) / period]
    for p in prices[period:]:
        ema.append(p * k + ema[-1] * (1 - k))
    return [None] * (period - 1) + ema


async def get_symbols():
    global _top_symbols_cache, _last_cache_time
    if not _top_symbols_cache or time.time() - _last_cache_time > 600:
        try:
            _top_symbols_cache = await get_top_symbols(TOP_SYMBOLS_COUNT)
            _last_cache_time = time.time()
        except:
            pass
    return _top_symbols_cache or ["BTCUSDT", "ETHUSDT"]


async def analyze(symbol):
    try:
        klines = await get_klines(symbol, KLINE_INTERVAL, KLINE_LIMIT)
        if len(klines) < 25:
            return None
        closes = [c["close"] for c in klines]
        volumes = [c["volume"] for c in klines]
        ema_fast = calculate_ema(closes, EMA_FAST)
        ema_slow = calculate_ema(closes, EMA_SLOW)
        if not ema_fast or not ema_slow or ema_fast[-2] is None or ema_slow[-2] is None:
            return None
        if ema_fast[-2] <= ema_slow[-2] and ema_fast[-1] > ema_slow[-1]:
            avg_vol = sum(volumes[-20:-1]) / 19
            if volumes[-1] >= avg_vol * MIN_VOLUME_RATIO:
                price = closes[-1]
                return {"symbol": symbol, "entry_price": price, "take_profit": round(price * (1 + TP_PERCENT/100), 6), "stop_loss": round(price * (1 - SL_PERCENT/100), 6)}
    except:
        pass
    return None


async def notify(user_id, msg):
    if _app:
        try:
            await _app.bot.send_message(user_id, msg, parse_mode="HTML")
        except:
            pass


async def open_trade(signal, user_id, amount):
    global _failed_symbols
    api_key = os.getenv("GATE_API_KEY", "")
    api_secret = os.getenv("GATE_API_SECRET", "")
    if not api_key:
        return
    try:
        bal = await get_balance(api_key, api_secret)
        if bal["free"] < amount:
            await notify(user_id, f"❌ رصيد غير كاف: {signal['symbol']}")
            return
        result = await place_buy_order(api_key, api_secret, signal["symbol"], amount)
        await save_trade({"user_id": user_id, "symbol": signal["symbol"], "side": "buy", "entry_price": result["entry_price"], "amount": amount, "quantity": result["quantity"], "take_profit": signal["take_profit"], "stop_loss": signal["stop_loss"], "status": "open", "order_id": result["order_id"]})
        await notify(user_id, f"✅ صفقة: {signal['symbol']} | ${amount}")
    except Exception as e:
        await notify(user_id, f"❌ فشل: {signal['symbol']}")


async def close_trade(trade, price, reason):
    api_key = os.getenv("GATE_API_KEY", "")
    api_secret = os.getenv("GATE_API_SECRET", "")
    if not api_key:
        return
    try:
        await place_sell_order(api_key, api_secret, trade["symbol"], trade["quantity"])
    except:
        pass
    pnl = (price - float(trade["entry_price"])) * float(trade["quantity"])
    await update_trade(trade["id"], {"status": "closed", "close_price": price, "pnl": round(pnl, 4), "closed_at": datetime.now(timezone.utc).isoformat(), "close_reason": reason})
    await notify(trade["user_id"], f"{'🎯' if reason == 'take_profit' else '🛑'} {trade['symbol']} | P&L: {pnl:+.4f} USDT")


async def monitor_loop():
    logger.info("📡 Gate.io Monitor started")
    while True:
        try:
            trades = await get_all_open_trades()
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

            if len(trades) < MAX_OPEN_TRADES:
                users = await get_all_active_users()
                for u in users:
                    if u.get("ema_trade", True):
                        syms = await get_symbols()
                        for sym in syms:
                            if sym in [t["symbol"] for t in trades]:
                                continue
                            sig = await analyze(sym)
                            if sig:
                                await notify(u["id"], f"🚨 {sig['symbol']}")
                                await open_trade(sig, u["id"], float(u.get("ema_amount", DEFAULT_AMOUNT)))
                                break
        except Exception as e:
            logger.error(f"Error: {e}")
        await asyncio.sleep(MONITOR_INTERVAL)