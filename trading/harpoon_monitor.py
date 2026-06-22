import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from database.client import (
    get_all_open_trades, update_trade, save_trade, get_all_active_users
)
from trading.mexc_client import (
    get_ticker_price as mexc_price, place_buy_order as mexc_buy,
    place_sell_order as mexc_sell, get_klines as mexc_klines,
    get_top_symbols as mexc_top, get_balance as mexc_balance
)
from trading.gate_client import (
    get_ticker_price as gate_price, place_buy_order as gate_buy,
    place_sell_order as gate_sell, get_klines as gate_klines,
    get_top_symbols as gate_top, get_balance as gate_balance
)
from config import (
    MONITOR_INTERVAL, HARPOON_TOP_SYMBOLS_COUNT, HARPOON_EMA_FAST, HARPOON_EMA_SLOW,
    HARPOON_TP_PERCENT, HARPOON_SL_PERCENT, HARPOON_KLINE_INTERVAL,
    HARPOON_KLINE_LIMIT, HARPOON_MAX_OPEN_TRADES, HARPOON_BASE_AMOUNT,
    HARPOON_DOUBLE_AMOUNT, HARPOON_TRIPLE_AMOUNT, HARPOON_WHALE_VOLUME_RATIO,
    HARPOON_RSI_OVERSOLD, HARPOON_MIN_VOLUME_RATIO
)

logger = logging.getLogger("HARPOON")
_app = None
_top_symbols_cache = {}
_last_cache_time = {}
_notified_signals = set()
_failed_symbols = {}

def set_app(app):
    global _app
    _app = app


def tv_link(symbol: str) -> str:
    sym = symbol.replace("/", "").upper()
    return f"https://www.tradingview.com/chart/?symbol=MEXC:{sym}"


def calculate_ema(prices: list, period: int) -> list:
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    ema_values = [sum(prices[:period]) / period]
    for price in prices[period:]:
        ema = price * k + ema_values[-1] * (1 - k)
        ema_values.append(ema)
    return [None] * (period - 1) + ema_values


def calculate_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = prices[-i] - prices[-i-1]
        gains.append(diff if diff >= 0 else 0)
        losses.append(-diff if diff < 0 else 0)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    return 100 - (100 / (1 + avg_gain / avg_loss))


def find_support(prices: list) -> float | None:
    if len(prices) < 10:
        return None
    return min(prices[-10:-1])


def is_bullish_engulfing(klines: list) -> bool:
    if len(klines) < 2:
        return False
    prev, curr = klines[-2], klines[-1]
    prev_body = prev["close"] - prev["open"]
    curr_body = curr["close"] - curr["open"]
    return prev_body < 0 and curr_body > 0 and abs(curr_body) > abs(prev_body) and curr["close"] > prev["open"]


def is_hammer(kline: dict) -> bool:
    body = abs(kline["close"] - kline["open"])
    lower_shadow = min(kline["open"], kline["close"]) - kline["low"]
    upper_shadow = kline["high"] - max(kline["open"], kline["close"])
    if body == 0:
        return False
    return lower_shadow >= body * 2 and upper_shadow <= body * 0.5


async def get_symbols_to_scan(exchange: str = "mexc") -> list:
    global _top_symbols_cache, _last_cache_time
    now = time.time()
    if exchange not in _top_symbols_cache or (now - _last_cache_time.get(exchange, 0)) > 600:
        try:
            if exchange == "gate":
                _top_symbols_cache[exchange] = await gate_top(HARPOON_TOP_SYMBOLS_COUNT)
            else:
                _top_symbols_cache[exchange] = await mexc_top(HARPOON_TOP_SYMBOLS_COUNT)
            _last_cache_time[exchange] = now
            logger.info(f"هاربون: {len(_top_symbols_cache[exchange])} عملة من {exchange}")
        except:
            pass
    return _top_symbols_cache.get(exchange, ["BTCUSDT", "ETHUSDT", "BNBUSDT"])


async def analyze_harpoon(symbol: str, exchange: str = "mexc") -> dict | None:
    try:
        if exchange == "gate":
            klines = await gate_klines(symbol, HARPOON_KLINE_INTERVAL, HARPOON_KLINE_LIMIT)
        else:
            klines = await mexc_klines(symbol, HARPOON_KLINE_INTERVAL, HARPOON_KLINE_LIMIT)

        if len(klines) < 30:
            return None

        closes = [c["close"] for c in klines]
        volumes = [c["volume"] for c in klines]

        ema_fast = calculate_ema(closes, HARPOON_EMA_FAST)
        ema_slow = calculate_ema(closes, HARPOON_EMA_SLOW)
        if not ema_fast or not ema_slow:
            return None

        prev_fast, prev_slow = ema_fast[-2], ema_slow[-2]
        curr_fast, curr_slow = ema_fast[-1], ema_slow[-1]
        if prev_fast is None or prev_slow is None:
            return None

        avg_vol = sum(volumes[-20:-1]) / 19 if len(volumes) >= 20 else sum(volumes[:-1]) / max(len(volumes)-1, 1)
        if not (prev_fast <= prev_slow and curr_fast > curr_slow and volumes[-1] >= avg_vol * HARPOON_MIN_VOLUME_RATIO):
            return None

        confirmations = 0
        conf_names = []

        recent_high = max(closes[-10:-1])
        if volumes[-1] >= avg_vol * HARPOON_WHALE_VOLUME_RATIO and closes[-1] > recent_high:
            confirmations += 1
            conf_names.append("🐋 حوت")

        support = find_support(closes)
        if support and closes[-2] <= support * 1.01 and is_bullish_engulfing(klines):
            confirmations += 1
            conf_names.append("📊 دعم")

        rsi = calculate_rsi(closes)
        if rsi < HARPOON_RSI_OVERSOLD and is_hammer(klines[-1]):
            confirmations += 1
            conf_names.append("🔥 انعكاس")

        if confirmations == 0:
            return None

        price = closes[-1]
        return {
            "symbol": symbol, "entry_price": price,
            "take_profit": round(price * (1 + HARPOON_TP_PERCENT/100), 6),
            "stop_loss": round(price * (1 - HARPOON_SL_PERCENT/100), 6),
            "strategy": "HARPOON", "confirmations": confirmations,
            "conf_names": conf_names, "rsi": round(rsi, 1),
        }
    except:
        pass
    return None


async def send_notification(user_id: int, message: str):
    if _app:
        try:
            await _app.bot.send_message(chat_id=user_id, text=message, parse_mode="HTML", disable_web_page_preview=True)
        except:
            pass


async def open_trade(signal: dict, user_id: int, amount: float, exchange: str = "mexc"):
    global _failed_symbols
    link = tv_link(signal["symbol"])
    symbol = signal["symbol"]
    stars = "⭐" * signal["confirmations"]

    if exchange == "gate":
        api_key = os.getenv("GATE_API_KEY", "")
        api_secret = os.getenv("GATE_API_SECRET", "")
        balance_func = gate_balance
        buy_func = gate_buy
    else:
        api_key = os.getenv("MEXC_API_KEY", "")
        api_secret = os.getenv("MEXC_API_SECRET", "")
        balance_func = mexc_balance
        buy_func = mexc_buy

    if not api_key or not api_secret:
        return

    try:
        balance = await balance_func(api_key, api_secret)
    except:
        return

    if balance["free"] < amount:
        now = time.time()
        if (now - _failed_symbols.get(symbol, 0)) > 900:
            _failed_symbols[symbol] = now
            await send_notification(user_id,
                f"[هاربون-{exchange.upper()}] ❌ <b>رصيد غير كافٍ!</b>\n🪙 {symbol}\n💰 مطلوب: ${amount}\n🏦 متاح: ${balance['free']:.2f}"
            )
        return

    try:
        result = await buy_func(api_key, api_secret, symbol, amount)
        trade = {
            "user_id": user_id, "symbol": symbol,
            "side": "buy", "entry_price": result["entry_price"],
            "amount": amount, "quantity": result["quantity"],
            "take_profit": signal["take_profit"], "stop_loss": signal["stop_loss"],
            "status": "open", "order_id": result["order_id"],
            "signal_id": "harpoon_auto", "strategy": "HARPOON",
            "confirmations": signal["confirmations"], "exchange": exchange.upper(),
        }
        await save_trade(trade)
        logger.info(f"🎯 هاربون: {symbol} ({signal['confirmations']} تأكيد) على {exchange}")
        _failed_symbols.pop(symbol, None)
        await send_notification(user_id,
            f"[هاربون-{exchange.upper()}] {stars} <b>صفقة!</b>\n🪙 {symbol}\n📥 <code>{signal['entry_price']}</code>\n💵 ${amount}\n📊 {', '.join(signal['conf_names'])}\nRSI: {signal['rsi']}\n🔗 <a href='{link}'>TV</a>"
        )
    except Exception as e:
        now = time.time()
        if (now - _failed_symbols.get(symbol, 0)) > 900:
            _failed_symbols[symbol] = now
            await send_notification(user_id,
                f"[هاربون-{exchange.upper()}] ❌ <b>فشل!</b>\n🪙 {symbol}\n⚠️ {str(e)[:150]}"
            )
        logger.error(f"هاربون فشل {symbol}: {e}")


async def close_trade(trade: dict, price: float, reason: str):
    exchange = trade.get("exchange", "MEXC").lower()
    if exchange == "gate":
        api_key = os.getenv("GATE_API_KEY", "")
        api_secret = os.getenv("GATE_API_SECRET", "")
        sell_func = gate_sell
    else:
        api_key = os.getenv("MEXC_API_KEY", "")
        api_secret = os.getenv("MEXC_API_SECRET", "")
        sell_func = mexc_sell

    if not api_key or not api_secret:
        return

    link = tv_link(trade["symbol"])
    try:
        result = await sell_func(api_key, api_secret, trade["symbol"], trade["quantity"])
        price = result.get("close_price", price)
    except:
        pass
    pnl = (price - float(trade["entry_price"])) * float(trade["quantity"])
    await update_trade(trade["id"], {
        "status": "closed", "close_price": price, "pnl": round(pnl, 4),
        "closed_at": datetime.now(timezone.utc).isoformat(), "close_reason": reason,
    })
    emoji = "🎯" if reason == "take_profit" else "🛑"
    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
    reason_text = "هدف ✅" if reason == "take_profit" else "وقف ❌"
    if _app:
        await _app.bot.send_message(trade["user_id"],
            f"[هاربون-{exchange.upper()}] {emoji} <b>إغلاق</b>\n🪙 {trade['symbol']}\n{pnl_emoji} P&L: <code>{pnl:+.4f} USDT</code>\n📋 {reason_text}\n🔗 <a href='{link}'>TV</a>",
            parse_mode="HTML", disable_web_page_preview=True
        )


async def harpoon_loop():
    global _notified_signals, _failed_symbols
    logger.info("🎯 هاربون Monitor started")
    while True:
        try:
            now = time.time()
            _failed_symbols = {k: v for k, v in _failed_symbols.items() if (now - v) < 3600}
            if len(_notified_signals) > 500:
                _notified_signals.clear()

            trades = await get_all_open_trades()
            harpoon_trades = [t for t in trades if t.get("strategy") == "HARPOON"]

            for t in harpoon_trades:
                try:
                    exchange = t.get("exchange", "MEXC").lower()
                    if exchange == "gate":
                        price = await gate_price(t["symbol"])
                    else:
                        price = await mexc_price(t["symbol"])
                    tp = float(t.get("take_profit") or 0)
                    sl = float(t.get("stop_loss") or 0)
                    if tp and price >= tp:
                        await close_trade(t, price, "take_profit")
                    elif sl and price <= sl:
                        await close_trade(t, price, "stop_loss")
                except:
                    pass

            users = await get_all_active_users()
            for user in users:
                if not user.get("harpoon_trade", True):
                    continue
                exchange = user.get("exchange", "mexc")
                exchanges_to_trade = ["mexc", "gate"] if exchange == "both" else [exchange]

                for ex in exchanges_to_trade:
                    open_count = len([t for t in harpoon_trades if t.get("exchange", "MEXC").lower() == ex])
                    if open_count >= HARPOON_MAX_OPEN_TRADES:
                        continue

                    symbols = await get_symbols_to_scan(ex)
                    open_symbols = [t["symbol"] for t in harpoon_trades if t.get("exchange", "MEXC").lower() == ex]
                    for sym in symbols:
                        if sym in open_symbols:
                            continue
                        signal = await analyze_harpoon(sym, ex)
                        if signal:
                            link = tv_link(signal["symbol"])
                            signal_key = f"harpoon_{ex}_{signal['symbol']}_{signal['entry_price']:.2f}"
                            if signal_key not in _notified_signals:
                                _notified_signals.add(signal_key)
                                await send_notification(user["id"],
                                    f"[هاربون-{ex.upper()}] 🚨 <b>إشارة!</b>\n🪙 {signal['symbol']}\n📥 <code>{signal['entry_price']}</code>\n📊 {', '.join(signal['conf_names'])}\nRSI: {signal['rsi']}\n🔗 <a href='{link}'>TV</a>"
                                )
                            base = float(user.get("harpoon_amount", HARPOON_BASE_AMOUNT))
                            confs = signal["confirmations"]
                            if confs >= 3:
                                amount = base * 3
                            elif confs >= 2:
                                amount = base * 2
                            else:
                                amount = base
                            await open_trade(signal, user["id"], amount, ex)
                            break
        except Exception as e:
            logger.error(f"هاربون خطأ: {e}")
        await asyncio.sleep(MONITOR_INTERVAL)