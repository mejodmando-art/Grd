import asyncio
import logging
import os
from datetime import datetime, timezone

from database.client import (
    get_all_open_trades, update_trade, save_trade, get_user, get_all_active_users
)
from trading.mexc_client import (
    get_ticker_price, place_buy_order, place_sell_order, get_klines
)
from config import (
    MONITOR_INTERVAL, SYMBOLS, EMA_FAST, EMA_SLOW,
    TP_PERCENT, SL_PERCENT, MIN_VOLUME_RATIO
)

logger = logging.getLogger(__name__)

_app = None

def set_app(app):
    global _app
    _app = app


def calculate_ema(prices: list, period: int) -> list:
    """حساب المتوسط المتحرك الأسي"""
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    ema_values = []
    sma = sum(prices[:period]) / period
    ema_values.append(sma)
    for price in prices[period:]:
        ema = price * k + ema_values[-1] * (1 - k)
        ema_values.append(ema)
    return [None] * (period - 1) + ema_values


async def analyze_symbol(symbol: str) -> dict | None:
    """تحليل عملة واحدة وإرجاع إشارة إن وجدت"""
    try:
        klines = await get_klines(symbol, "15m", 60)
        if len(klines) < 30:
            return None

        closes = [c["close"] for c in klines]
        volumes = [c["volume"] for c in klines]

        ema_fast = calculate_ema(closes, EMA_FAST)
        ema_slow = calculate_ema(closes, EMA_SLOW)

        if not ema_fast or not ema_slow:
            return None

        # آخر شمعتين للكشف عن التقاطع
        prev_fast = ema_fast[-2]
        prev_slow = ema_slow[-2]
        curr_fast = ema_fast[-1]
        curr_slow = ema_slow[-1]

        # تقاطع إيجابي (Golden Cross)
        if prev_fast is None or prev_slow is None:
            return None

        if prev_fast <= prev_slow and curr_fast > curr_slow:
            # تأكيد بالحجم
            avg_vol = sum(volumes[:-1]) / max(len(volumes) - 1, 1)
            if volumes[-1] >= avg_vol * MIN_VOLUME_RATIO:
                current_price = closes[-1]
                tp = round(current_price * (1 + TP_PERCENT / 100), 6)
                sl = round(current_price * (1 - SL_PERCENT / 100), 6)
                return {
                    "symbol": symbol,
                    "entry_price": current_price,
                    "take_profit": tp,
                    "stop_loss": sl,
                    "signal_type": "ema_crossover",
                }

    except Exception as e:
        logger.error(f"Error analyzing {symbol}: {e}")

    return None


async def open_auto_trade(signal: dict, user_id: int, amount: float):
    """فتح صفقة تلقائية"""
    api_key = os.getenv("MEXC_API_KEY", "")
    api_secret = os.getenv("MEXC_API_SECRET", "")

    if not api_key or not api_secret:
        logger.error("MEXC API keys not configured")
        return

    try:
        result = await place_buy_order(
            api_key=api_key,
            api_secret=api_secret,
            symbol=signal["symbol"],
            usdt_amount=amount,
        )
        trade = {
            "user_id": user_id,
            "symbol": signal["symbol"],
            "side": "buy",
            "entry_price": result["entry_price"],
            "amount": amount,
            "quantity": result["quantity"],
            "take_profit": signal["take_profit"],
            "stop_loss": signal["stop_loss"],
            "status": "open",
            "order_id": result["order_id"],
            "signal_id": "auto",
        }
        saved = await save_trade(trade)
        logger.info(f"Auto trade opened: {signal['symbol']} @ {signal['entry_price']}")

        if _app:
            msg = (
                f"🤖 <b>صفقة تلقائية جديدة!</b>\n\n"
                f"🪙 <b>العملة:</b> {signal['symbol']}\n"
                f"📥 <b>الدخول:</b> <code>{signal['entry_price']}</code>\n"
                f"💵 <b>المبلغ:</b> <code>${amount}</code>\n"
                f"🎯 <b>TP:</b> <code>{signal['take_profit']}</code>\n"
                f"🛑 <b>SL:</b> <code>{signal['stop_loss']}</code>"
            )
            try:
                await _app.bot.send_message(chat_id=user_id, text=msg, parse_mode="HTML")
            except:
                pass

    except Exception as e:
        logger.error(f"Failed to open auto trade for {signal['symbol']}: {e}")


async def close_trade_on_exchange(trade: dict, close_price: float, reason: str) -> dict:
    """إغلاق صفقة على المنصة وتحديث قاعدة البيانات"""
    api_key = os.getenv("MEXC_API_KEY", "")
    api_secret = os.getenv("MEXC_API_SECRET", "")

    if not api_key or not api_secret:
        return {}

    try:
        result = await place_sell_order(
            api_key=api_key,
            api_secret=api_secret,
            symbol=trade["symbol"],
            quantity=trade["quantity"],
        )
        close_price = result.get("close_price", close_price)
    except Exception as e:
        logger.error(f"Failed to close trade on exchange: {e}")

    entry = float(trade["entry_price"])
    qty = float(trade["quantity"])
    pnl = (close_price - entry) * qty

    updates = {
        "status": "closed",
        "close_price": close_price,
        "pnl": round(pnl, 4),
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "close_reason": reason,
    }
    await update_trade(trade["id"], updates)
    return {**trade, **updates}


async def notify_user(user_id: int, message: str):
    """إرسال إشعار للمستخدم"""
    if _app is None:
        return
    try:
        await _app.bot.send_message(chat_id=user_id, text=message, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Failed to notify user {user_id}: {e}")


async def monitor_loop():
    """الحلقة الرئيسية – تحليل السوق ومراقبة الصفقات"""
    logger.info("📡 بدء نظام التداول الآلي...")

    # معرفة المستخدمين النشطين (يفضل الأدمن)
    admin_id = None
    users = await get_all_active_users()
    if users:
        admin_id = users[0]["id"]

    if not admin_id:
        logger.warning("لا يوجد مستخدمين نشطين، التداول الآلي متوقف مؤقتاً")

    while True:
        try:
            # === الجزء الأول: مراقبة الصفقات المفتوحة ===
            trades = await get_all_open_trades()
            for trade in trades:
                try:
                    current_price = await get_ticker_price(trade["symbol"])
                    tp = float(trade.get("take_profit") or 0)
                    sl = float(trade.get("stop_loss") or 0)

                    if tp > 0 and current_price >= tp:
                        closed = await close_trade_on_exchange(trade, current_price, "take_profit")
                        pnl = closed.get("pnl", 0)
                        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
                        msg = (
                            f"🎯 <b>تحقق الهدف!</b>\n\n"
                            f"🪙 {trade['symbol']}\n"
                            f"📥 دخول: <code>{trade['entry_price']}</code>\n"
                            f"📤 خروج: <code>{current_price:.6f}</code>\n"
                            f"{pnl_emoji} P&L: <code>{pnl:+.4f} USDT</code>"
                        )
                        await notify_user(trade["user_id"], msg)

                    elif sl > 0 and current_price <= sl:
                        closed = await close_trade_on_exchange(trade, current_price, "stop_loss")
                        pnl = closed.get("pnl", 0)
                        pnl_emoji = "🔴"
                        msg = (
                            f"🛑 <b>وقف خسارة!</b>\n\n"
                            f"🪙 {trade['symbol']}\n"
                            f"📥 دخول: <code>{trade['entry_price']}</code>\n"
                            f"📤 خروج: <code>{current_price:.6f}</code>\n"
                            f"{pnl_emoji} P&L: <code>{pnl:+.4f} USDT</code>"
                        )
                        await notify_user(trade["user_id"], msg)

                except Exception as e:
                    logger.error(f"Error monitoring trade {trade.get('id')}: {e}")

            # === الجزء الثاني: تحليل السوق وفتح صفقات جديدة ===
            if admin_id:
                # التحقق من وجود مستخدمين بالتداول التلقائي مفعّل
                active_auto_users = []
                for u in await get_all_active_users():
                    if u.get("auto_trade"):
                        active_auto_users.append(u)

                if active_auto_users:
                    # فحص جميع العملات
                    open_symbols = [t["symbol"] for t in trades]
                    for symbol in SYMBOLS:
                        if symbol in open_symbols:
                            continue  # تخطي العملات المفتوح عليها صفقات

                        signal = await analyze_symbol(symbol)
                        if signal:
                            for user in active_auto_users:
                                amount = float(user.get("default_amount", 10))
                                await open_auto_trade(signal, user["id"], amount)
                            break  # فتح صفقة واحدة فقط في كل دورة

        except Exception as e:
            logger.error(f"Monitor loop error: {e}")

        await asyncio.sleep(MONITOR_INTERVAL)
