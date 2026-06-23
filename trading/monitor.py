import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from database.client import get_all_open_trades, update_trade, save_trade, get_all_active_users
from trading.gate_client import (
    get_ticker_price, place_buy_order, place_sell_order,
    get_klines, get_top_symbols, get_balance
)
from config import (
    MONITOR_INTERVAL, TOP_SYMBOLS_COUNT, EMA_FAST, EMA_SLOW,
    TP_PERCENT, SL_PERCENT, MIN_VOLUME_RATIO, KLINE_INTERVAL,
    KLINE_LIMIT, MAX_OPEN_TRADES, DEFAULT_AMOUNT
)

logger = logging.getLogger("EMA")
_app = None
_cache = []
_last = 0

def set_app(a):
    global _app
    _app = a

def ema(prices: list, n: int) -> list:
    if len(prices) < n:
        return []
    k = 2 / (n + 1)
    result = [sum(prices[:n]) / n]
    for x in prices[n:]:
        result.append(x * k + result[-1] * (1 - k))
    return [None] * (n - 1) + result

async def get_symbols() -> list:
    global _cache, _last
    if not _cache or time.time() - _last > 600:
        try:
            _cache = await get_top_symbols(TOP_SYMBOLS_COUNT)
            _last = time.time()
            logger.info(f"EMA: جلب {len(_cache)} عملة")
        except Exception as e:
            logger.error(f"EMA symbols error: {e}")
    return _cache or ["BTCUSDT", "ETHUSDT"]

async def analyze(sym: str) -> dict | None:
    try:
        kl = await get_klines(sym, KLINE_INTERVAL, KLINE_LIMIT)
        if len(kl) < 25:
            return None
        cl = [c["close"] for c in kl]
        vl = [c["volume"] for c in kl]
        ef = ema(cl, EMA_FAST)
        es = ema(cl, EMA_SLOW)
        if not ef or not es or ef[-2] is None or es[-2] is None:
            return None
        # تقاطع EMA صعودي
        if ef[-2] <= es[-2] and ef[-1] > es[-1]:
            avg_vol = sum(vl[-20:-1]) / 19 if len(vl) >= 20 else sum(vl[:-1]) / max(len(vl) - 1, 1)
            if vl[-1] >= avg_vol * MIN_VOLUME_RATIO:
                p = cl[-1]
                return {
                    "symbol": sym,
                    "entry_price": p,
                    "take_profit": round(p * (1 + TP_PERCENT / 100), 6),
                    "stop_loss": round(p * (1 - SL_PERCENT / 100), 6),
                    "strategy": "EMA",
                }
    except Exception:
        pass
    return None

async def notify(uid: int, msg: str):
    if _app:
        try:
            await _app.bot.send_message(uid, msg, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            pass

async def open_trade(sig: dict, uid: int, amt: float):
    ak = os.getenv("GATE_API_KEY", "")
    sk = os.getenv("GATE_API_SECRET", "")
    if not ak or not sk:
        logger.warning("EMA: GATE_API_KEY أو GATE_API_SECRET غير موجودين")
        return
    try:
        bal = await get_balance(ak, sk)
        usdt = next((c for c in bal['all_coins'] if c['coin'] == 'USDT'), None)
        free = usdt['free'] if usdt else 0
        if free < amt:
            await notify(uid, f"❌ <b>رصيد غير كافٍ</b>\n🪙 {sig['symbol']} | مطلوب: ${amt:.2f} | متاح: ${free:.2f}")
            return
        r = await place_buy_order(ak, sk, sig["symbol"], amt)
        await save_trade({
            "user_id": uid,
            "symbol": sig["symbol"],
            "side": "buy",
            "entry_price": r["entry_price"],
            "amount": amt,
            "quantity": r["quantity"],
            "take_profit": sig["take_profit"],
            "stop_loss": sig["stop_loss"],
            "status": "open",
            "order_id": r["order_id"],
            "strategy": "EMA",
            "exchange": "GATE",
        })
        await notify(uid,
            f"[EMA] ✅ <b>صفقة مفتوحة!</b>\n🪙 {sig['symbol']}\n📥 <code>{r['entry_price']}</code>\n💵 ${amt}\n🎯 TP: <code>{sig['take_profit']}</code>\n🛑 SL: <code>{sig['stop_loss']}</code>"
        )
        logger.info(f"EMA: فتح {sig['symbol']} بـ ${amt}")
    except Exception as e:
        await notify(uid, f"[EMA] ❌ <b>فشل الفتح:</b> {sig['symbol']}\n⚠️ {str(e)[:150]}")
        logger.error(f"EMA open_trade error {sig['symbol']}: {e}")

async def close_trade(t: dict, price: float, reason: str):
    ak = os.getenv("GATE_API_KEY", "")
    sk = os.getenv("GATE_API_SECRET", "")
    if not ak or not sk:
        return
    try:
        result = await place_sell_order(ak, sk, t["symbol"], t["quantity"])
        price = result.get("close_price", price)
    except Exception as e:
        logger.error(f"EMA close_trade sell error {t['symbol']}: {e}")
    pnl = (price - float(t["entry_price"])) * float(t["quantity"])
    await update_trade(t["id"], {
        "status": "closed",
        "close_price": price,
        "pnl": round(pnl, 4),
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "close_reason": reason,
    })
    emoji = "🎯" if reason == "take_profit" else "🛑"
    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
    reason_text = "هدف ✅" if reason == "take_profit" else "وقف ❌"
    await notify(t["user_id"],
        f"[EMA] {emoji} <b>إغلاق:</b> {t['symbol']}\n{pnl_emoji} P&L: <code>{pnl:+.4f} USDT</code>\n📋 {reason_text}"
    )

async def monitor_loop():
    logger.info("📡 EMA Monitor بدأ...")
    while True:
        try:
            trades = await get_all_open_trades()
            ema_trades = [t for t in trades if t.get("strategy") in ("EMA", None, "")]
            for t in ema_trades:
                try:
                    p = await get_ticker_price(t["symbol"])
                    tp = float(t.get("take_profit") or 0)
                    sl = float(t.get("stop_loss") or 0)
                    if tp and p >= tp:
                        await close_trade(t, p, "take_profit")
                    elif sl and p <= sl:
                        await close_trade(t, p, "stop_loss")
                except Exception:
                    pass
            if len(ema_trades) < MAX_OPEN_TRADES:
                users = await get_all_active_users()
                auto_users = [u for u in users if u.get("ema_trade", False)]
                if auto_users:
                    symbols = await get_symbols()
                    open_syms = [t["symbol"] for t in ema_trades]
                    for s in symbols:
                        if s in open_syms:
                            continue
                        sig = await analyze(s)
                        if sig:
                            tv = f"https://www.tradingview.com/chart/?symbol=GATEIO:{s}"
                            for u in auto_users:
                                await notify(u["id"],
                                    f"[EMA] 🚨 <b>إشارة!</b>\n🪙 {sig['symbol']}\n📥 <code>{sig['entry_price']}</code>\n🔗 <a href='{tv}'>TradingView</a>"
                                )
                                amt = float(u.get("ema_amount", DEFAULT_AMOUNT))
                                await open_trade(sig, u["id"], amt)
                            break
        except Exception as e:
            logger.error(f"EMA monitor_loop error: {e}")
        await asyncio.sleep(MONITOR_INTERVAL)
