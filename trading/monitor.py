import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List

from database.client import get_all_open_trades, update_trade, save_trade, get_all_active_users
from trading.gate_client import (
    get_ticker_price as gate_price, place_buy_order as gate_buy,
    place_sell_order as gate_sell, get_klines as gate_klines,
    get_top_symbols as gate_top, get_balance as gate_balance
)
from trading.mexc_client import (
    get_ticker_price as mexc_price, place_buy_order as mexc_buy,
    place_sell_order as mexc_sell, get_klines as mexc_klines,
    get_top_symbols as mexc_top, get_balance as mexc_balance
)
from config import (
    MONITOR_INTERVAL, TOP_SYMBOLS_COUNT, EMA_FAST, EMA_SLOW,
    TP_PERCENT, SL_PERCENT, MIN_VOLUME_RATIO, KLINE_INTERVAL,
    KLINE_LIMIT, MAX_OPEN_TRADES, DEFAULT_AMOUNT
)

logger = logging.getLogger("EMA")
_app = None
_cache: List[str] = []
_last = 0.0


def set_app(a):
    global _app
    _app = a


def ema(prices: list, n: int) -> list:
    """Calculate Exponential Moving Average."""
    if len(prices) < n:
        return []
    k = 2 / (n + 1)
    result = [sum(prices[:n]) / n]
    for x in prices[n:]:
        result.append(x * k + result[-1] * (1 - k))
    return [None] * (n - 1) + result


async def get_symbols() -> list:
    """Get top symbols with caching."""
    global _cache, _last
    if not _cache or time.time() - _last > 60:  # Cache for 1 minute instead of 10
        try:
            _cache = await gate_top(TOP_SYMBOLS_COUNT)
            _last = time.time()
            logger.info(f"EMA: Loaded {len(_cache)} symbols")
        except Exception as e:
            logger.error(f"EMA symbols error: {e}")
    return _cache or ["BTCUSDT", "ETHUSDT"]


async def analyze(sym: str) -> Optional[Dict]:
    """Analyze symbol for EMA crossover signal."""
    try:
        kl = await gate_klines(sym, KLINE_INTERVAL, KLINE_LIMIT)
        if len(kl) < 25:
            return None

        cl = [c["close"] for c in kl]
        vl = [c["volume"] for c in kl]

        ef = ema(cl, EMA_FAST)
        es = ema(cl, EMA_SLOW)

        if not ef or not es or ef[-2] is None or es[-2] is None:
            return None

        # EMA bullish crossover
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
    """Send notification to user."""
    if _app:
        try:
            await _app.bot.send_message(
                uid, msg,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception:
            pass


async def open_trade(sig: dict, uid: int, amt: float, exchange: str = "gate"):
    """Open a trade for a user."""
    if exchange == "gate":
        ak = os.getenv("GATE_API_KEY", "")
        sk = os.getenv("GATE_API_SECRET", "")
        balance_func = gate_balance
        buy_func = gate_buy
    else:
        ak = os.getenv("MEXC_API_KEY", "")
        sk = os.getenv("MEXC_API_SECRET", "")
        balance_func = mexc_balance
        buy_func = mexc_buy

    if not ak or not sk:
        logger.warning(f"EMA: API keys not found for {exchange}")
        return

    try:
        bal = await balance_func(ak, sk)
        free = bal.get("free", 0)

        if free < amt:
            await notify(uid,
                f"❌ <b>رصيد غير كافٍ</b>\n"
                f"🪙 {sig['symbol']} | مطلوب: ${amt:.2f} | متاح: ${free:.2f}"
            )
            return

        r = await buy_func(ak, sk, sig["symbol"], amt)

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
            "exchange": exchange.upper(),
        })

        await notify(uid,
            f"[EMA] ✅ <b>صفقة مفتوحة!</b>\n"
            f"🪙 {sig['symbol']}\n"
            f"📥 `{r['entry_price']}`\n"
            f"💵 ${amt}\n"
            f"🎯 TP: `{sig['take_profit']}`\n"
            f"🛑 SL: `{sig['stop_loss']}`"
        )
        logger.info(f"EMA: Opened {sig['symbol']} for ${amt}")

    except Exception as e:
        await notify(uid,
            f"[EMA] ❌ <b>فشل الفتح:</b> {sig['symbol']}\n"
            f"⚠️ {str(e)[:150]}"
        )
        logger.error(f"EMA open_trade error {sig['symbol']}: {e}")


async def close_trade(t: dict, price: float, reason: str):
    """Close a trade. CRITICAL: Only update DB if sell succeeds."""
    exchange = t.get("exchange", "GATE").lower()

    if exchange == "gate":
        ak = os.getenv("GATE_API_KEY", "")
        sk = os.getenv("GATE_API_SECRET", "")
        sell_func = gate_sell
        price_func = gate_price
    else:
        ak = os.getenv("MEXC_API_KEY", "")
        sk = os.getenv("MEXC_API_SECRET", "")
        sell_func = mexc_sell
        price_func = mexc_price

    if not ak or not sk:
        logger.warning(f"EMA: API keys not found for {exchange}")
        return

    # Try to sell first
    try:
        result = await sell_func(ak, sk, t["symbol"], t["quantity"])
        price = result.get("close_price", price)
        logger.info(f"EMA: Sold {t['symbol']} at {price}")
    except Exception as e:
        logger.error(f"EMA: Sell failed for {t['symbol']}, keeping trade open: {e}")
        return  # CRITICAL: Don't update DB if sell failed!

    # Calculate P&L correctly
    entry_total = float(t["entry_price"]) * float(t["quantity"])
    current_total = price * float(t["quantity"])
    pnl = current_total - entry_total
    pnl_percent = (pnl / entry_total) * 100 if entry_total else 0

    await update_trade(t["id"], {
        "status": "closed",
        "close_price": price,
        "pnl": round(pnl, 4),
        "pnl_percent": round(pnl_percent, 2),
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "close_reason": reason,
    })

    emoji = "🎯" if reason == "take_profit" else "🛑"
    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
    reason_text = "هدف ✅" if reason == "take_profit" else "وقف ❌"

    await notify(t["user_id"],
        f"[EMA] {emoji} <b>إغلاق:</b> {t['symbol']}\n"
        f"{pnl_emoji} P&L: `{pnl:+.4f} USDT` ({pnl_percent:+.2f}%)\n"
        f"📋 {reason_text}"
    )


async def monitor_loop():
    """Main monitoring loop."""
    logger.info("📡 EMA Monitor started...")
    while True:
        try:
            # Check existing trades for TP/SL
            trades = await get_all_open_trades()
            ema_trades = [t for t in trades if t.get("strategy") in ("EMA", None, "")]

            for t in ema_trades:
                try:
                    exchange = t.get("exchange", "GATE").lower()
                    if exchange == "gate":
                        p = await gate_price(t["symbol"])
                    else:
                        p = await mexc_price(t["symbol"])

                    tp = float(t.get("take_profit") or 0)
                    sl = float(t.get("stop_loss") or 0)

                    if tp and p >= tp:
                        await close_trade(t, p, "take_profit")
                    elif sl and p <= sl:
                        await close_trade(t, p, "stop_loss")
                except Exception:
                    pass

            # Open new trades if under limit (per user)
            users = await get_all_active_users()
            auto_users = [u for u in users if u.get("ema_trade", False)]

            if auto_users:
                symbols = await get_symbols()

                for u in auto_users:
                    user_id = u["id"]
                    exchange = u.get("exchange", "gate")

                    # Check user's open trades count
                    user_trades = [t for t in ema_trades if t["user_id"] == user_id]
                    if len(user_trades) >= MAX_OPEN_TRADES:
                        continue

                    user_open_syms = [t["symbol"] for t in user_trades]

                    for s in symbols:
                        if s in user_open_syms:
                            continue

                        sig = await analyze(s)
                        if sig:
                            amt = float(u.get("ema_amount", DEFAULT_AMOUNT))
                            await open_trade(sig, user_id, amt, exchange)
                            break  # One trade per cycle per user

        except Exception as e:
            logger.error(f"EMA monitor_loop error: {e}")

        await asyncio.sleep(MONITOR_INTERVAL)