import asyncio, logging, os, time
from datetime import datetime, timezone
from database.client import get_all_open_trades, update_trade, save_trade, get_all_active_users
from trading.gate_client import get_ticker_price, place_buy_order, place_sell_order, get_klines, get_top_symbols, get_balance
from config import *

logger = logging.getLogger("GateBot")
_app = None
_cache = []; _last = 0
_sigs = set()

def set_app(a): global _app; _app = a

def ema(p, n):
    if len(p) < n: return []
    k = 2/(n+1)
    e = [sum(p[:n])/n]
    for x in p[n:]: e.append(x*k + e[-1]*(1-k))
    return [None]*(n-1) + e

async def syms():
    global _cache, _last
    if not _cache or time.time()-_last > 600:
        try:
            _cache = await get_top_symbols(TOP_SYMBOLS_COUNT)
            _last = time.time()
        except: pass
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
                return {"symbol": sym, "entry_price": p, "take_profit": round(p*(1+TP_PERCENT/100),6), "stop_loss": round(p*(1-SL_PERCENT/100),6)}
    except: pass
    return None

async def notify(uid, msg):
    if _app:
        try: await _app.bot.send_message(uid, msg, parse_mode="HTML")
        except: pass

async def open_trade(sig, uid, amt):
    ak = os.getenv("GATE_API_KEY",""); sk = os.getenv("GATE_API_SECRET","")
    if not ak: return
    try:
        bal = await get_balance(ak, sk)
        if bal["free"] < amt:
            await notify(uid, f"❌ رصيد غير كاف: {sig['symbol']}")
            return
        r = await place_buy_order(ak, sk, sig["symbol"], amt)
        await save_trade({"user_id": uid, "symbol": sig["symbol"], "side": "buy", "entry_price": r["entry_price"], "amount": amt, "quantity": r["quantity"], "take_profit": sig["take_profit"], "stop_loss": sig["stop_loss"], "status": "open", "order_id": r["order_id"]})
        await notify(uid, f"✅ {sig['symbol']} | ${amt}")
    except Exception as e:
        await notify(uid, f"❌ {sig['symbol']}: {str(e)[:100]}")

async def close_trade(t, price, reason):
    ak = os.getenv("GATE_API_KEY",""); sk = os.getenv("GATE_API_SECRET","")
    if not ak: return
    try: await place_sell_order(ak, sk, t["symbol"], t["quantity"])
    except: pass
    pnl = (price - float(t["entry_price"])) * float(t["quantity"])
    await update_trade(t["id"], {"status": "closed", "close_price": price, "pnl": round(pnl,4), "closed_at": datetime.now(timezone.utc).isoformat(), "close_reason": reason})
    em = "🎯" if reason == "take_profit" else "🛑"
    await notify(t["user_id"], f"{em} {t['symbol']} | P&L: {pnl:+.4f} USDT")

async def monitor_loop():
    logger.info("📡 Gate.io Monitor")
    while True:
        try:
            trades = await get_all_open_trades()
            for t in trades:
                try:
                    p = await get_ticker_price(t["symbol"])
                    if float(t.get("take_profit",0)) and p >= float(t["take_profit"]): await close_trade(t, p, "take_profit")
                    elif float(t.get("stop_loss",0)) and p <= float(t["stop_loss"]): await close_trade(t, p, "stop_loss")
                except: pass
            if len(trades) < MAX_OPEN_TRADES:
                users = await get_all_active_users()
                for u in users:
                    if u.get("ema_trade", True):
                        ss = await syms()
                        for s in ss:
                            if s in [t["symbol"] for t in trades]: continue
                            sig = await analyze(s)
                            if sig:
                                await notify(u["id"], f"🚨 {sig['symbol']}")
                                await open_trade(sig, u["id"], float(u.get("ema_amount", DEFAULT_AMOUNT)))
                                break
        except Exception as e:
            logger.error(f"Error: {e}")
        await asyncio.sleep(MONITOR_INTERVAL)