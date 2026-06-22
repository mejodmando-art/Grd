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
_notified_signals = set()

def set_app(app):
    global _app
    _app = app


def tv_link(symbol: str) -> str:
    """توليد رابط TradingView للعملة"""
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


async def send_notification(user_id: int, message: str):
    if _app:
        try:
            await _app.bot.send_message(chat_id=user_id, text=message, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            logger.warning(f"فشل إرسال إشعار: {e}")


async def open_trade(signal: dict, user_id: int, amount: float):
    api_key = os.getenv("MEXC_API_KEY", "")
    api_secret = os.getenv("MEXC_API_SECRET", "")
    link = tv_link(signal["symbol"])

    if not api_key or not api_secret:
        await send_notification(user_id,
            f"❌ <b>فشل فتح صفقة: مفاتيح API غير موجودة</b>\n\n"
            f"🪙 <b>{signal['symbol']}</b>\n"
            f"🔗 <a href='{link}'>فتح في TradingView</a>\n\n"
            f"⚠️ السبب: لم يتم إعداد MEXC_API_KEY في الخادم."
        )
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
        await send_notification(user_id,
            f"✅ <b>تم فتح الصفقة بنجاح!</b>\n\n"
            f"🪙 <b>{signal['symbol']}</b>\n"
            f"📥 دخول: <code>{signal['entry_price']}</code>\n"
            f"💵 مبلغ: <code>${amount}</code>\n"
            f"🎯 TP: <code>{signal['take_profit']}</code>\n"
            f"🛑 SL: <code>{signal['stop_loss']}</code>\n\n"
            f"🔗 <a href='{link}'>مشاهدة على TradingView</a>"
        )
    except Exception as e:
        error_str = str(e).lower()
        if any(kw in error_str for kw in ["insufficient", "balance", "margin", "fund"]):
            reason = "رصيد USDT غير كافٍ في حساب MEXC"
        elif "minimum" in error_str or "min_qty" in error_str or "minimal" in error_str:
            reason = "المبلغ أقل من الحد الأدنى للصفقة"
        elif "api" in error_str or "key" in error_str or "signature" in error_str:
            reason = "خطأ في مفاتيح API أو التوقيع"
        elif "network" in error_str or "timeout" in error_str or "connect" in error_str:
            reason = "خطأ في الاتصال بالإنترنت أو MEXC"
        elif "symbol" in error_str or "not found" in error_str:
            reason = "رمز العملة غير موجود أو غير مدعوم"
        elif "rate" in error_str or "limit" in error_str:
            reason = "تم تجاوز حد الطلبات (Rate Limit)"
        else:
            reason = f"خطأ غير معروف: {str(e)[:150]}"

        await send_notification(user_id,
            f"❌ <b>فشل فتح صفقة!</b>\n\n"
            f"🪙 <b>{signal['symbol']}</b>\n"
            f"💰 مبلغ: <code>${amount}</code>\n"
            f"🔗 <a href='{link}'>فتح في TradingView</a>\n\n"
            f"⚠️ <b>السبب:</b> {reason}"
        )
        logger.error(f"فشل فتح صفقة {signal['symbol']}: {e}")


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
    reason_text = "تحقق الهدف ✅" if reason == "take_profit" else "وقف خسارة ❌"
    if _app:
        await _app.bot.send_message(trade["user_id"],
            f"{emoji} <b>إغلاق صفقة</b>\n\n"
            f"🪙 <b>{trade['symbol']}</b>\n"
            f"📥 دخول: <code>{trade['entry_price']}</code>\n"
            f"📤 خروج: <code>{price:.6f}</code>\n"
            f"{pnl_emoji} P&L: <code>{pnl:+.4f} USDT</code>\n"
            f"📋 السبب: {reason_text}\n\n"
            f"🔗 <a href='{link}'>مشاهدة على TradingView</a>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )


async def monitor_loop():
    logger.info("📡 نظام التداول الآلي السريع...")
    while True:
        try:
            trades = await get_all_open_trades()
            open_count = len(trades)

            # مراقبة الصفقات المفتوحة
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

            # فتح صفقات جديدة
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
                            link = tv_link(signal["symbol"])
                            signal_key = f"{signal['symbol']}_{signal['entry_price']:.2f}"
                            if signal_key not in _notified_signals:
                                _notified_signals.add(signal_key)
                                for user in auto_users:
                                    await send_notification(user["id"],
                                        f"🚨 <b>إشارة جديدة!</b>\n\n"
                                        f"🪙 <b>{signal['symbol']}</b>\n"
                                        f"📥 سعر: <code>{signal['entry_price']}</code>\n"
                                        f"🎯 TP: <code>{signal['take_profit']}</code>\n"
                                        f"🛑 SL: <code>{signal['stop_loss']}</code>\n\n"
                                        f"🔗 <a href='{link}'>فتح في TradingView</a>"
                                    )
                            for user in auto_users:
                                amount = float(user.get("default_amount", 10))
                                await open_trade(signal, user["id"], amount)
                            break
        except Exception as e:
            logger.error(f"خطأ: {e}")
        await asyncio.sleep(MONITOR_INTERVAL)