import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from database.client import (
    get_all_open_trades, update_trade, save_trade, get_all_active_users
)
from trading.mexc_client import (
    get_ticker_price, place_buy_order, place_sell_order, get_klines, get_top_symbols, get_balance
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
_top_symbols_cache = []
_last_cache_time = 0
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
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = prices[-i] - prices[-i-1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(-diff)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def find_support(prices: list) -> float | None:
    """يبحث عن أدنى سعر في آخر 10 شمعات"""
    if len(prices) < 10:
        return None
    return min(prices[-10:-1])


def is_bullish_engulfing(klines: list) -> bool:
    """يتحقق من وجود شمعة ابتلاعية صاعدة"""
    if len(klines) < 2:
        return False
    prev = klines[-2]
    curr = klines[-1]
    prev_body = prev["close"] - prev["open"]
    curr_body = curr["close"] - curr["open"]
    return prev_body < 0 and curr_body > 0 and abs(curr_body) > abs(prev_body) and curr["close"] > prev["open"]


def is_hammer(kline: dict) -> bool:
    """يتحقق من وجود شمعة مطرقة"""
    body = abs(kline["close"] - kline["open"])
    lower_shadow = min(kline["open"], kline["close"]) - kline["low"]
    upper_shadow = kline["high"] - max(kline["open"], kline["close"])
    if body == 0:
        return False
    return lower_shadow >= body * 2 and upper_shadow <= body * 0.5


async def get_symbols_to_scan() -> list:
    global _top_symbols_cache, _last_cache_time
    now = time.time()
    if not _top_symbols_cache or (now - _last_cache_time) > 600:
        try:
            _top_symbols_cache = await get_top_symbols(HARPOON_TOP_SYMBOLS_COUNT)
            _last_cache_time = now
            logger.info(f"هاربون: تم تحديث {len(_top_symbols_cache)} عملة")
        except:
            pass
    return _top_symbols_cache or ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


async def analyze_harpoon(symbol: str) -> dict | None:
    """تحليل استراتيجية الهاربون (تأكيدات متعددة)"""
    try:
        klines = await get_klines(symbol, HARPOON_KLINE_INTERVAL, HARPOON_KLINE_LIMIT)
        if len(klines) < 30:
            return None

        closes = [c["close"] for c in klines]
        volumes = [c["volume"] for c in klines]

        # الأساس: تقاطع EMA
        ema_fast = calculate_ema(closes, HARPOON_EMA_FAST)
        ema_slow = calculate_ema(closes, HARPOON_EMA_SLOW)
        if not ema_fast or not ema_slow:
            return None

        prev_fast = ema_fast[-2]
        prev_slow = ema_slow[-2]
        curr_fast = ema_fast[-1]
        curr_slow = ema_slow[-1]

        if prev_fast is None or prev_slow is None:
            return None

        # التأكيد الأساسي: تقاطع + حجم
        avg_vol = sum(volumes[-20:-1]) / 19 if len(volumes) >= 20 else sum(volumes[:-1]) / max(len(volumes)-1, 1)
        if not (prev_fast <= prev_slow and curr_fast > curr_slow and volumes[-1] >= avg_vol * HARPOON_MIN_VOLUME_RATIO):
            return None

        # حساب التأكيدات
        confirmations = 0
        conf_names = []

        # 🐋 تأكيد 1: الحوت (حجم ضخم + كسر قمة)
        recent_high = max(closes[-10:-1])
        if volumes[-1] >= avg_vol * HARPOON_WHALE_VOLUME_RATIO and closes[-1] > recent_high:
            confirmations += 1
            conf_names.append("🐋 حوت")

        # 📊 تأكيد 2: ارتداد من دعم + شمعة ابتلاعية
        support = find_support(closes)
        if support and closes[-2] <= support * 1.01 and is_bullish_engulfing(klines):
            confirmations += 1
            conf_names.append("📊 دعم")

        # 🔥 تأكيد 3: تشبع بيعي + شمعة مطرقة
        rsi = calculate_rsi(closes)
        if rsi < HARPOON_RSI_OVERSOLD and is_hammer(klines[-1]):
            confirmations += 1
            conf_names.append("🔥 انعكاس")

        if confirmations == 0:
            return None

        price = closes[-1]
        return {
            "symbol": symbol,
            "entry_price": price,
            "take_profit": round(price * (1 + HARPOON_TP_PERCENT/100), 6),
            "stop_loss": round(price * (1 - HARPOON_SL_PERCENT/100), 6),
            "strategy": "HARPOON",
            "confirmations": confirmations,
            "conf_names": conf_names,
            "rsi": round(rsi, 1),
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


async def open_trade(signal: dict, user_id: int, amount: float):
    global _failed_symbols
    api_key = os.getenv("MEXC_API_KEY", "")
    api_secret = os.getenv("MEXC_API_SECRET", "")
    link = tv_link(signal["symbol"])
    symbol = signal["symbol"]
    confs = signal["confirmations"]
    stars = "⭐" * confs

    if not api_key or not api_secret:
        return

    balance = await get_balance(api_key, api_secret)
    if balance["free"] < amount:
        now = time.time()
        if (now - _failed_symbols.get(symbol, 0)) > 900:
            _failed_symbols[symbol] = now
            await send_notification(user_id,
                f"[هاربون] ❌ <b>رصيد غير كافٍ!</b>\n🪙 {symbol}\n💰 مطلوب: ${amount}\n🏦 متاح: ${balance['free']:.2f}"
            )
        return

    try:
        result = await place_buy_order(api_key, api_secret, symbol, amount)
        trade = {
            "user_id": user_id, "symbol": symbol,
            "side": "buy", "entry_price": result["entry_price"],
            "amount": amount, "quantity": result["quantity"],
            "take_profit": signal["take_profit"], "stop_loss": signal["stop_loss"],
            "status": "open", "order_id": result["order_id"],
            "signal_id": "harpoon_auto", "strategy": "HARPOON",
            "confirmations": confs,
        }
        await save_trade(trade)
        logger.info(f"🎯 هاربون: {symbol} ({confs} تأكيد)")
        _failed_symbols.pop(symbol, None)
        await send_notification(user_id,
            f"[هاربون] {stars} <b>صفقة!</b>\n🪙 {symbol}\n📥 دخول: <code>{signal['entry_price']}</code>\n💵 مبلغ: ${amount}\n📊 تأكيدات: {', '.join(signal['conf_names'])}\nRSI: {signal['rsi']}\n🔗 <a href='{link}'>TradingView</a>"
        )
    except Exception as e:
        now = time.time()
        if (now - _failed_symbols.get(symbol, 0)) > 900:
            _failed_symbols[symbol] = now
            await send_notification(user_id,
                f"[هاربون] ❌ <b>فشل!</b>\n🪙 {symbol}\n⚠️ {str(e)[:150]}\n🔗 <a href='{link}'>TradingView</a>"
            )
        logger.error(f"هاربون فشل: {symbol}: {e}")


async def close_trade(trade: dict, price: float, reason: str):
    api_key = os.getenv("MEXC_API_KEY", "")
    api_secret = os.getenv("MEXC_API_SECRET", "")
    if not api_key or not api_secret:
        return
    link = tv_link(trade["symbol"])
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
    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
    reason_text = "هدف ✅" if reason == "take_profit" else "وقف ❌"
    if _app:
        await _app.bot.send_message(trade["user_id"],
            f"[هاربون] {emoji} <b>إغلاق</b>\n🪙 {trade['symbol']}\n{pnl_emoji} P&L: <code>{pnl:+.4f} USDT</code>\n📋 {reason_text}\n🔗 <a href='{link}'>TradingView</a>",
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
            open_count = len(harpoon_trades)

            for t in harpoon_trades:
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

            if open_count < HARPOON_MAX_OPEN_TRADES:
                users = await get_all_active_users()
                auto_users = [u for u in users if u.get("harpoon_trade", True)]
                if auto_users:
                    symbols = await get_symbols_to_scan()
                    open_symbols = [t["symbol"] for t in harpoon_trades]
                    for sym in symbols:
                        if sym in open_symbols:
                            continue
                        signal = await analyze_harpoon(sym)
                        if signal:
                            link = tv_link(signal["symbol"])
                            signal_key = f"harpoon_{signal['symbol']}_{signal['entry_price']:.2f}"
                            if signal_key not in _notified_signals:
                                _notified_signals.add(signal_key)
                                for user in auto_users:
                                    await send_notification(user["id"],
                                        f"[هاربون] 🚨 <b>إشارة!</b>\n🪙 {signal['symbol']}\n📥 <code>{signal['entry_price']}</code>\n📊 تأكيدات: {', '.join(signal['conf_names'])}\nRSI: {signal['rsi']}\n🔗 <a href='{link}'>TradingView</a>"
                                    )
                            for user in auto_users:
                                confs = signal["confirmations"]
                                base = float(user.get("harpoon_amount", HARPOON_BASE_AMOUNT))
                                if confs >= 3:
                                    amount = base * 3
                                elif confs >= 2:
                                    amount = base * 2
                                else:
                                    amount = base
                                await open_trade(signal, user["id"], amount)
                            break
        except Exception as e:
            logger.error(f"خطأ: {e}")
        await asyncio.sleep(MONITOR_INTERVAL)