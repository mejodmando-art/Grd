import asyncio, logging, os, time
from datetime import datetime, timezone
from database.client import get_all_open_trades, update_trade, save_trade, get_all_active_users
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

async def open_trade(sig, uid, amt):
    ak = os.getenv("GATE_API_KEY",""); sk = os.getenv("GATE_API_SECRET","")
    if not ak: return
    try:
        free_usdt = await get_usdt_free()
        if free_usdt < amt:
            await notify(uid, f"❌ رصيد غير كافٍ: {sig['symbol']}\n💰 مطلوب: ${amt}\n💵 متاح: ${free_usdt:.2f}")
            return
        r = await place_buy_order(ak, sk, sig["symbol"], amt)
        await save_trade({
            "user_id": uid, "symbol": sig["symbol"], "side": "buy",
            "entry_price": r["entry_price"], "amount": amt,
            "quantity": r["quantity"], "take_profit": sig["take_profit"],
            "stop_loss": sig["stop_loss"], "status": "open",
            "order_id": r["order_id"]
        })
        await notify(uid, f"✅ صفقة جديدة: {sig['symbol']}\n💰 ${amt}\n🔗 {tv_link(sig['symbol'])}")
    except Exception as e:
        await notify(uid, f"❌ فشل فتح: {sig['symbol']}\n{e}")

async def close_trade(t, price, reason):
    ak = os.getenv("GATE_API_KEY",""); sk = os.getenv("GATE_API_SECRET","")
    if not ak: return
    try: await place_sell_order(ak, sk, t["symbol"], t["quantity"])
    except: pass
    pnl = (price - float(t["entry_price"])) * float(t["quantity"])
    await update_trade(t["id"], {
        "status": "closed", "close_price": price, "pnl": round(pnl,4),
        "closed_at": datetime.now(timezone.utc).isoformat(), "close_reason": reason
    })
    em = "🎯" if reason == "take_profit" else "🛑"
    await notify(t["user_id"], f"{em} إغلاق: {t['symbol']}\nP&L: {pnl:+.4f} USDT\n🔗 {tv_link(t['symbol'])}")

async def monitor_loop():
    global notified_signals
    logger.info("📡 بدء التداول التلقائي (خفيف)...")
    while True:
        try:
            trades = await get_all_open_trades()
            for t in trades:
                try:
                    p = await get_ticker_price(t["symbol"])
                    tp = float(t.get("take_profit",0) or 0)
                    sl = float(t.get("stop_loss",0) or 0)
                    if tp and p >= tp: await close_trade(t, p, "take_profit")
                    elif sl and p <= sl: await close_trade(t, p, "stop_loss")
                except: pass
            if len(trades) < MAX_OPEN_TRADES:
                users = await get_all_active_users()
                auto_users = [u for u in users if u.get("ema_trade", True)]
                if auto_users:
                    symbols = await syms()
                    open_symbols = [t["symbol"] for t in trades]
                    for sym in symbols:
                        if sym in open_symbols: continue
                        signal = await analyze(sym)
                        if signal:
                            signal_key = f"{signal['symbol']}_{signal['entry_price']:.2f}"
                            if signal_key not in notified_signals:
                                notified_signals.add(signal_key)
                                for user in auto_users:
                                    await notify(user["id"],
                                        f"🚨 إشارة جديدة: {signal['symbol']}\n"
                                        f"السعر: {signal['entry_price']}\n"
                                        f"🔗 {tv_link(signal['symbol'])}"
                                    )
                            for user in auto_users:
                                amt = float(user.get("ema_amount", DEFAULT_AMOUNT))
                                await open_trade(signal, user["id"], amt)
                            break
            if len(notified_signals) > 500: notified_signals.clear()
        except Exception as e: logger.error(f"Monitor error: {e}")
        await asyncio.sleep(MONITOR_INTERVAL)