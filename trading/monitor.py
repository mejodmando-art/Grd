import asyncio, logging, os, time
from datetime import datetime, timezone
from database.client import get_all_open_trades, update_trade, save_trade, get_all_active_users, get_open_trades
from trading.gate_client import (
    get_ticker_price, place_buy_order, place_sell_order,
    get_klines, get_top_symbols, get_usdt_free
)
from config import *

logger = logging.getLogger("GateBot")
_app = None
_cache = []
_last = 0
notified_signals = set()
# تتبع الصفقات اللي اتفتحت مؤخراً عشان نتجنب فتحها تاني
_recently_opened = {}  # {user_id_symbol: timestamp}

def set_app(a): global _app; _app = a

def tv_link(symbol: str) -> str:
    return f"https://www.tradingview.com/chart/?symbol=GATEIO:{symbol}"

def ema(p, n):
    if len(p) < n: return []
    k = 2/(n+1); e = [sum(p[:n])/n]
    for x in p[n:]: e.append(x*k + e[-1]*(1-k))
    return [None]*(n-1) + e

async def syms():
    global _cache, _last
    if not _cache or time.time()-_last > 600:
        try:
            _cache = await get_top_symbols(TOP_SYMBOLS_COUNT)
            _last = time.time()
            logger.info(f"قائمة محدثة: {len(_cache)} عملة")
        except Exception as e: logger.error(f"Error: {e}")
    return _cache or ["BTCUSDT","ETHUSDT"]

async def analyze(sym):
    try:
        kl = await get_klines(sym, KLINE_INTERVAL, KLINE_LIMIT)
        if len(kl) < 25: return None
        cl = [c["close"] for c in kl]; vl = [c["volume"] for c in kl]
        ef = ema(cl, EMA_FAST); es = ema(cl, EMA_SLOW)
        if not ef or not es or ef[-2] is None: return None
        if ef[-2] <= es[-2] and ef[-1] > es[-1]:
            av = sum(vl[-20:-1])/19
            if vl[-1] >= av * MIN_VOLUME_RATIO:
                p = cl[-1]
                return {"symbol": sym, "entry_price": p,
                        "take_profit": round(p*(1+TP_PERCENT/100),6),
                        "stop_loss": round(p*(1-SL_PERCENT/100),6)}
    except: pass
    return None

async def notify(uid, msg):
    if _app:
        try: await _app.bot.send_message(uid, msg, parse_mode="HTML", disable_web_page_preview=True)
        except: pass


# ─── فحص إذا المستخدم عنده صفقة مفتوحة على نفس العملة ────────────────────────

async def _user_has_open_symbol(user_id: int, symbol: str) -> bool:
    """التحقق إذا المستخدم عنده صفقة مفتوحة على نفس العملة"""
    user_trades = await get_open_trades(user_id)
    for t in user_trades:
        if t.get("symbol") == symbol:
            return True
    return False


# ─── فتح صفقة جديدة ───────────────────────────────────────────────────────────

async def open_trade(sig, uid, amt):
    ak = os.getenv("GATE_API_KEY",""); sk = os.getenv("GATE_API_SECRET","")
    if not ak:
        await notify(uid, "❌ API Keys غير مضبوطة — تواصل مع المشرف")
        return

    symbol = sig["symbol"]

    # ✅ فحص إذا المستخدم عنده صفقة مفتوحة على نفس العملة
    has_open = await _user_has_open_symbol(uid, symbol)
    if has_open:
        logger.info(f"User {uid} already has open trade on {symbol}, skipping")
        return

    # ✅ فحص إذا فتحنا صفقة حديثة على نفس العملة (rate limiting)
    cache_key = f"{uid}_{symbol}"
    if cache_key in _recently_opened:
        if time.time() - _recently_opened[cache_key] < 300:  # 5 دقائق cooldown
            logger.info(f"Trade {symbol} recently opened for user {uid}, cooling down")
            return

    try:
        # ✅ جلب الرصيد مع error handling واضح
        try:
            free_usdt = await get_usdt_free()
        except Exception as balance_err:
            error_msg = str(balance_err)
            logger.error(f"Balance check failed for user {uid}: {error_msg}")
            await notify(uid, f"❌ <b>فشل في قراءة الرصيد</b>\n\n{error_msg}\n\n🔧 تأكد من:\n• API Keys صحيحة\n• حساب Gate.io فيه رصيد USDT")
            return

        # ✅ فحص الرصيد
        if free_usdt < amt:
            await notify(uid, f"⚠️ <b>رصيد غير كافٍ</b>\n\n💱 العملة: {symbol}\n💰 المطلوب: ${amt:.2f}\n💵 المتاح: ${free_usdt:.2f}\n\n📥 حول USDT لحساب Spot في Gate.io")
            return

        # ✅ تنفيذ الشراء
        r = await place_buy_order(ak, sk, symbol, amt)

        # ✅ حفظ في الداتابيز
        await save_trade({
            "user_id": uid, "symbol": symbol, "side": "buy",
            "entry_price": r["entry_price"], "amount": amt,
            "quantity": r["quantity"], "take_profit": sig["take_profit"],
            "stop_loss": sig["stop_loss"], "status": "open",
            "order_id": r["order_id"]
        })

        # ✅ تسجيل إننا فتحنا صفقة حديثة
        _recently_opened[cache_key] = time.time()

        # ✅ إشعار النجاح
        entry = r['entry_price']
        qty = r['quantity']
        cost = r['cost']
        await notify(uid,
            f"✅ <b>صفقة جديدة منفذة!</b>\n\n"
            f"💱 العملة: <code>{symbol}</code>\n"
            f"💰 المبلغ: ${cost:.2f}\n"
            f"📊 الكمية: {qty:.6f}\n"
            f"💵 سعر الدخول: ${entry:.6f}\n"
            f"🎯 TP: ${sig['take_profit']:.6f}\n"
            f"🛑 SL: ${sig['stop_loss']:.6f}\n"
            f"🔗 <a href='{tv_link(symbol)}'>TradingView</a>"
        )
        logger.info(f"Trade opened: {symbol} for user {uid} @ ${entry}")

    except ValueError as ve:
        logger.error(f"Validation error opening {symbol} for user {uid}: {ve}")
        await notify(uid, f"❌ <b>خطأ في البيانات</b>\n\n{symbol}\n{ve}")
    except Exception as e:
        error_str = str(e)
        logger.error(f"Failed to open trade {symbol} for user {uid}: {error_str}")
        # رسالة خطأ أوضح
        if "balance" in error_str.lower() or "insufficient" in error_str.lower():
            await notify(uid, f"❌ <b>رصيد غير كافٍ في Gate.io</b>\n\n"
                             f"💱 {symbol}\n"
                             f"📥 تأكد إن عندك USDT كافي في حساب Spot\n"
                             f"(مش حساب Futures أو Margin)")
        elif "precision" in error_str.lower():
            await notify(uid, f"❌ <b>خطأ في دقة الكمية</b>\n\n"
                             f"{symbol}\n"
                             f"🔧 جاري الإصلاح التلقائي...")
        else:
            await notify(uid, f"❌ <b>فشل في فتح الصفقة</b>\n\n"
                             f"💱 {symbol}\n"
                             f"📝 {error_str[:150]}")


# ─── إغلاق صفقة ───────────────────────────────────────────────────────────────

async def close_trade(t, price, reason):
    ak = os.getenv("GATE_API_KEY",""); sk = os.getenv("GATE_API_SECRET","")
    if not ak: return

    symbol = t["symbol"]
    try:
        r = await place_sell_order(ak, sk, symbol, t["quantity"])
        close_price = r["close_price"]
        logger.info(f"SELL filled for {symbol}: qty={r['quantity']} @ ${close_price}")
    except Exception as e:
        logger.error(f"SELL order failed for {symbol}: {e}")
        # نستخدم السعر الحالي لو فشل الأمر
        close_price = price

    pnl = (close_price - float(t["entry_price"])) * float(t["quantity"])
    await update_trade(t["id"], {
        "status": "closed", "close_price": close_price, "pnl": round(pnl,4),
        "closed_at": datetime.now(timezone.utc).isoformat(), "close_reason": reason
    })
    em = "🎯" if reason == "take_profit" else "🛑"
    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
    await notify(t["user_id"],
        f"{em} <b>صفقة مغلقة!</b>\n\n"
        f"💱 {symbol}\n"
        f"{pnl_emoji} P&L: {pnl:+.4f} USDT\n"
        f"🎯 السعر: ${close_price:.6f}\n"
        f"📊 السبب: {'Take Profit' if reason == 'take_profit' else 'Stop Loss'}\n"
        f"🔗 <a href='{tv_link(symbol)}'>TradingView</a>"
    )


# ─── حلقة المراقبة الرئيسية ─────────────────────────────────────────────────

async def monitor_loop():
    global notified_signals
    logger.info("📡 بدء التداول التلقائي (خفيف)...")
    while True:
        try:
            # ─── 1. فحص الصفقات المفتوحة (TP/SL) ──────────────────────────
            trades = await get_all_open_trades()
            for t in trades:
                try:
                    p = await get_ticker_price(t["symbol"])
                    tp = float(t.get("take_profit",0) or 0)
                    sl = float(t.get("stop_loss",0) or 0)
                    if tp and p >= tp:
                        await close_trade(t, p, "take_profit")
                        await asyncio.sleep(1)  # تأخير بسيط بعد الإغلاق
                    elif sl and p <= sl:
                        await close_trade(t, p, "stop_profit")
                        await asyncio.sleep(1)
                except Exception as e:
                    logger.warning(f"Error checking trade {t.get('symbol')}: {e}")

            # ─── 2. فتح صفقات جديدة ──────────────────────────────────────
            if len(trades) < MAX_OPEN_TRADES:
                users = await get_all_active_users()
                auto_users = [u for u in users if u.get("ema_trade", True)]
                if auto_users:
                    symbols = await syms()
                    open_symbols = [t["symbol"] for t in trades]
                    for sym in symbols:
                        if sym in open_symbols:
                            continue
                        signal = await analyze(sym)
                        if signal:
                            signal_key = f"{signal['symbol']}_{signal['entry_price']:.2f}"

                            # إشعار بالإشارة الجديدة
                            if signal_key not in notified_signals:
                                notified_signals.add(signal_key)
                                for user in auto_users:
                                    await notify(user["id"],
                                        f"🚨 <b>إشارة جديدة!</b>\n\n"
                                        f"💱 العملة: <code>{signal['symbol']}</code>\n"
                                        f"💵 السعر: {signal['entry_price']:.6f}\n"
                                        f"🎯 TP: {signal['take_profit']:.6f}\n"
                                        f"🛑 SL: {signal['stop_loss']:.6f}\n"
                                        f"🔗 <a href='{tv_link(signal['symbol'])}'>TradingView</a>"
                                    )
                                await asyncio.sleep(0.5)  # تأخير بين الإشعارات

                            # فتح صفقات للمستخدمين (بتأخير بين كل واحد)
                            for idx, user in enumerate(auto_users):
                                amt = float(user.get("ema_amount", DEFAULT_AMOUNT))
                                await open_trade(signal, user["id"], amt)
                                # ✅ تأخير 2 ثواني بين صفقات المستخدمين عشان نتجنب rate limit
                                if idx < len(auto_users) - 1:
                                    await asyncio.sleep(2)
                            break  # فتحنا صفقة على عملة واحدة في هذه الدورة

            # تنظيف الكاش لو كبر
            if len(notified_signals) > 500:
                notified_signals.clear()
            if len(_recently_opened) > 1000:
                _recently_opened.clear()

        except Exception as e:
            logger.error(f"Monitor error: {e}")

        await asyncio.sleep(MONITOR_INTERVAL)
