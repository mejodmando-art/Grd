import asyncio, logging, os, time
from datetime import datetime, timezone
from database.client import get_all_open_trades, update_trade, save_trade, get_all_active_users, get_open_trades, get_user
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
_recently_opened = {}

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

# ─── Strategy 1: EMA Crossover ────────────────────────────────────────────────
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
                return {
                    "symbol": sym, "entry_price": p,
                    "take_profit": round(p*(1+TP_PERCENT/100),6),
                    "stop_loss": round(p*(1-SL_PERCENT/100),6),
                    "strategy": "EMA"
                }
    except: pass
    return None

# ─── Strategy 2: Harpoon (Volume Spike + Strong Candle) ──────────────────────
async def analyze_harpoon(sym):
    try:
        kl = await get_klines(sym, "5m", 20)
        if len(kl) < 15: return None
        cl = [c["close"] for c in kl]; vl = [c["volume"] for c in kl]

        # Volume Spike > 2x average
        avg_vol = sum(vl[-10:-1]) / 9
        if vl[-1] < avg_vol * 2.0:
            return None

        # Strong bullish candle > 1.5%
        last = kl[-1]
        change = (last["close"] - last["open"]) / last["open"] * 100
        if change < 1.5:
            return None

        # EMA confirmation
        ef = ema(cl, 5); es = ema(cl, 13)
        if not ef or not es or ef[-1] is None or es[-1] is None:
            return None
        if ef[-1] <= es[-1]:
            return None

        p = cl[-1]
        return {
            "symbol": sym, "entry_price": p,
            "take_profit": round(p*(1+3.0/100),6),
            "stop_loss": round(p*(1-1.5/100),6),
            "strategy": "HARPOON"
        }
    except: return None

async def notify(uid, msg):
    if _app:
        try: await _app.bot.send_message(uid, msg, parse_mode="HTML", disable_web_page_preview=True)
        except: pass

async def _user_has_open_symbol(user_id: int, symbol: str) -> bool:
    user_trades = await get_open_trades(user_id)
    for t in user_trades:
        if t.get("symbol") == symbol:
            return True
    return False

async def open_trade(sig, uid, amt):
    ak = os.getenv("GATE_API_KEY",""); sk = os.getenv("GATE_API_SECRET","")
    if not ak:
        await notify(uid, "❌ API Keys غير مضبوطة — تواصل مع المشرف")
        return

    symbol = sig["symbol"]
    has_open = await _user_has_open_symbol(uid, symbol)
    if has_open:
        logger.info(f"User {uid} already has open trade on {symbol}, skipping")
        return

    cache_key = f"{uid}_{symbol}"
    if cache_key in _recently_opened:
        if time.time() - _recently_opened[cache_key] < 300:
            logger.info(f"Trade {symbol} recently opened for user {uid}, cooling down")
            return

    try:
        try:
            free_usdt = await get_usdt_free()
        except Exception as balance_err:
            await notify(uid, f"❌ **فشل في قراءة الرصيد**\n\n{balance_err}\n\n🔧 تأكد من API Keys ووجود USDT في Spot")
            return

        if free_usdt < amt:
            await notify(uid, f"⚠️ **رصيد غير كافٍ**\n\n💱 {symbol}\n💰 المطلوب: ${amt:.2f}\n💵 المتاح: ${free_usdt:.2f}")
            return

        r = await place_buy_order(ak, sk, symbol, amt)

        await save_trade({
            "user_id": uid, "symbol": symbol, "side": "buy",
            "entry_price": r["entry_price"], "amount": amt,
            "quantity": r["quantity"], "take_profit": sig["take_profit"],
            "stop_loss": sig["stop_loss"], "status": "open",
            "order_id": r["order_id"], "strategy": sig.get("strategy", "EMA")
        })

        _recently_opened[cache_key] = time.time()

        strat_emoji = "📈" if sig.get("strategy") == "EMA" else "🐋"
        await notify(uid,
            f"{strat_emoji} <b>صفقة جديدة منفذة!</b>\n\n"
            f"💱 العملة: <code>{symbol}</code>\n"
            f"🧠 الاستراتيجية: {sig.get('strategy', 'EMA')}\n"
            f"💰 المبلغ: ${r['cost']:.2f}\n"
            f"📊 الكمية: {r['quantity']:.6f}\n"
            f"💵 سعر الدخول: ${r['entry_price']:.6f}\n"
            f"🎯 TP: ${sig['take_profit']:.6f}\n"
            f"🛑 SL: ${sig['stop_loss']:.6f}"
        )
        logger.info(f"Trade opened: {symbol} for user {uid} @ ${r['entry_price']}")

    except ValueError as ve:
        logger.error(f"Validation error: {ve}")
        await notify(uid, f"❌ <b>تم الرفض</b>\n\n{symbol}\n{ve}")
    except Exception as e:
        error_str = str(e)
        logger.error(f"Failed to open trade {symbol} for user {uid}: {error_str}")
        if "balance" in error_str.lower() or "insufficient" in error_str.lower():
            await notify(uid, f"❌ <b>رصيد غير كافٍ</b>\n\n💱 {symbol}\n📥 تأكد من USDT في Spot")
        else:
            await notify(uid, f"❌ <b>فشل في فتح الصفقة</b>\n\n💱 {symbol}\n📝 {error_str[:150]}")

async def close_trade(t, price, reason):
    ak = os.getenv("GATE_API_KEY",""); sk = os.getenv("GATE_API_SECRET","")
    if not ak: return

    symbol = t["symbol"]
    try:
        r = await place_sell_order(ak, sk, symbol, t["quantity"])
        close_price = r["close_price"]
        logger.info(f"SELL filled: {symbol} @ ${close_price}")
    except Exception as e:
        logger.error(f"SELL failed: {e}")
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
        f"📊 السبب: {'Take Profit' if reason == 'take_profit' else 'Stop Loss'}"
    )

# ─── Main Monitor Loop ────────────────────────────────────────────────────────
async def monitor_loop():
    global notified_signals
    logger.info("📡 بدء التداول التلقائي...")
    while True:
        try:
            # 1. Check open trades (TP/SL)
            trades = await get_all_open_trades()
            for t in trades:
                try:
                    p = await get_ticker_price(t["symbol"])
                    tp = float(t.get("take_profit",0) or 0)
                    sl = float(t.get("stop_loss",0) or 0)
                    if tp and p >= tp:
                        await close_trade(t, p, "take_profit")
                        await asyncio.sleep(1)
                    elif sl and p <= sl:
                        await close_trade(t, p, "stop_loss")
                        await asyncio.sleep(1)
                except Exception as e:
                    logger.warning(f"Error checking trade: {e}")

            # 2. Open new trades
            if len(trades) < MAX_OPEN_TRADES:
                users = await get_all_active_users()
                ema_users = [u for u in users if u.get("ema_trade", True)]
                harpoon_users = [u for u in users if u.get("harpoon_trade", False)]

                symbols = await syms()
                open_symbols = [t["symbol"] for t in trades]

                for sym in symbols:
                    if sym in open_symbols:
                        continue

                    # Strategy 1: EMA
                    if ema_users:
                        signal = await analyze(sym)
                        if signal:
                            signal_key = f"EMA_{signal['symbol']}_{signal['entry_price']:.2f}"
                            if signal_key not in notified_signals:
                                notified_signals.add(signal_key)
                                for user in ema_users:
                                    await notify(user["id"],
                                        f"📈 <b>إشارة EMA جديدة!</b>\n\n"
                                        f"💱 <code>{signal['symbol']}</code>\n"
                                        f"💵 {signal['entry_price']:.6f}\n"
                                        f"🎯 TP: {signal['take_profit']:.6f}\n"
                                        f"🛑 SL: {signal['stop_loss']:.6f}"
                                    )
                                    await asyncio.sleep(0.5)
                            for idx, user in enumerate(ema_users):
                                amt = float(user.get("ema_amount", DEFAULT_AMOUNT))
                                await open_trade(signal, user["id"], amt)
                                if idx < len(ema_users) - 1:
                                    await asyncio.sleep(2)
                            break

                    # Strategy 2: Harpoon
                    if harpoon_users:
                        signal = await analyze_harpoon(sym)
                        if signal:
                            signal_key = f"HARPOON_{signal['symbol']}_{signal['entry_price']:.2f}"
                            if signal_key not in notified_signals:
                                notified_signals.add(signal_key)
                                for user in harpoon_users:
                                    await notify(user["id"],
                                        f"🐋 <b>Harpoon Signal!</b>\n\n"
                                        f"💱 <code>{signal['symbol']}</code>\n"
                                        f"💵 {signal['entry_price']:.6f}\n"
                                        f"🎯 TP: {signal['take_profit']:.6f}\n"
                                        f"🛑 SL: {signal['stop_loss']:.6f}\n"
                                        f"📊 Volume Spike: 2x+"
                                    )
                                    await asyncio.sleep(0.5)
                            for idx, user in enumerate(harpoon_users):
                                amt = float(user.get("harpoon_amount", DEFAULT_AMOUNT))
                                await open_trade(signal, user["id"], amt)
                                if idx < len(harpoon_users) - 1:
                                    await asyncio.sleep(2)
                            break

            # Cleanup
            if len(notified_signals) > 500:
                notified_signals.clear()
            if len(_recently_opened) > 1000:
                _recently_opened.clear()

        except Exception as e:
            logger.error(f"Monitor error: {e}")

        await asyncio.sleep(MONITOR_INTERVAL)