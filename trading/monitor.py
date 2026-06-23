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
    if not _cache or time.time() - _last > 60:
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
        logger.debug(f"EMA: Analyzing {sym}")
        kl = await gate_klines(sym, KLINE_INTERVAL, KLINE_LIMIT)

        if len(kl) < 25:
            logger.debug(f"EMA: {sym} - Not enough candles ({len(kl)})")
            return None

        cl = [c["close"] for c in kl]
        vl = [c["volume"] for c in kl]

        ef = ema(cl, EMA_FAST)
        es = ema(cl, EMA_SLOW)

        if not ef or not es or ef[-2] is None or es[-2] is None:
            logger.debug(f"EMA: {sym} - EMA not ready")
            return None

        # Log EMA values for debugging
        logger.debug(f"EMA: {sym} - Fast={ef[-1]:.6f} Slow={es[-1]:.6f} PrevFast={ef[-2]:.6f} PrevSlow={es[-2]:.6f}")

        # EMA bullish crossover
        if ef[-2] <= es[-2] and ef[-1] > es[-1]:
            avg_vol = sum(vl[-20:-1]) / 19 if len(vl) >= 20 else sum(vl[:-1]) / max(len(vl) - 1, 1)
            current_vol = vl[-1]
            vol_ratio = current_vol / avg_vol if avg_vol > 0 else 0

            logger.info(f"EMA: {sym} - CROSSOVER! Vol ratio: {vol_ratio:.2f} (need {MIN_VOLUME_RATIO})")

            if current_vol >= avg_vol * MIN_VOLUME_RATIO:
                p = cl[-1]
                logger.info(f"EMA: {sym} - SIGNAL CONFIRMED! Price: {p}")
                return {
                    "symbol": sym,
                    "entry_price": p,
                    "take_profit": round(p * (1 + TP_PERCENT / 100), 6),
                    "stop_loss": round(p * (1 - SL_PERCENT / 100), 6),
                    "strategy": "EMA",
                }
            else:
                logger.debug(f"EMA: {sym} - Volume too low: {vol_ratio:.2f} < {MIN_VOLUME_RATIO}")
        else:
            logger.debug(f"EMA: {sym} - No crossover (prev: {ef[-2]:.6f} vs {es[-2]:.6f}, curr: {ef[-1]:.6f} vs {es[-1]:.6f})")

    except Exception as e:
        logger.debug(f"EMA: {sym} - Analysis error: {e}")
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
        except Exception as e:
            logger.warning(f"EMA: Failed to notify user {uid}: {e}")


async def open_trade(sig: dict, uid: int, amt: float, exchange: str = "gate"):
    """Open a trade for a user."""
    logger.info(f"EMA: Attempting to open trade {sig['symbol']} for user {uid} on {exchange}")

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
        logger.error(f"EMA: API keys not found for {exchange}")
        await notify(uid, f"❌ <b>API keys missing!</b>\nPlease set {exchange.upper()} API keys.")
        return

    try:
        logger.info(f"EMA: Checking balance for user {uid}")
        bal = await balance_func(ak, sk)
        free = bal.get("free", 0)

        logger.info(f"EMA: User {uid} balance: {free} USDT, need: {amt}")

        if free < amt:
            logger.warning(f"EMA: User {uid} insufficient balance: {free} < {amt}")
            await notify(uid,
                f"❌ <b>Insufficient balance!</b>\n"
                f"🪙 {sig['symbol']} | Required: ${amt:.2f} | Available: ${free:.2f}"
            )
            return

        logger.info(f"EMA: Placing buy order for {sig['symbol']} ${amt}")
        r = await buy_func(ak, sk, sig["symbol"], amt)
        logger.info(f"EMA: Buy order result: {r}")

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
            f"[EMA] ✅ <b>Trade opened!</b>\n"
            f"🪙 {sig['symbol']}\n"
            f"📥 `{r['entry_price']}`\n"
            f"💵 ${amt}\n"
            f"🎯 TP: `{sig['take_profit']}`\n"
            f"🛑 SL: `{sig['stop_loss']}`"
        )
        logger.info(f"EMA: Opened {sig['symbol']} for ${amt}")

    except Exception as e:
        logger.error(f"EMA: Failed to open trade {sig['symbol']}: {e}")
        await notify(uid,
            f"[EMA] ❌ <b>Failed to open:</b> {sig['symbol']}\n"
            f"⚠️ {str(e)[:150]}"
        )


async def close_trade(t: dict, price: float, reason: str):
    """Close a trade. CRITICAL: Only update DB if sell succeeds."""
    exchange = t.get("exchange", "GATE").lower()

    if exchange == "gate":
        ak = os.getenv("GATE_API_KEY", "")
        sk = os.getenv("GATE_API_SECRET", "")
        sell_func = gate_sell
    else:
        ak = os.getenv("MEXC_API_KEY", "")
        sk = os.getenv("MEXC_API_SECRET", "")
        sell_func = mexc_sell

    if not ak or not sk:
        logger.warning(f"EMA: API keys not found for {exchange}")
        return

    # Try to sell first
    try:
        logger.info(f"EMA: Selling {t['symbol']} at {price}")
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
    reason_text = "Target ✅" if reason == "take_profit" else "Stop ❌"

    await notify(t["user_id"],
        f"[EMA] {emoji} <b>Closed:</b> {t['symbol']}\n"
        f"{pnl_emoji} P&L: `{pnl:+.4f} USDT` ({pnl_percent:+.2f}%)\n"
        f"📋 {reason_text}"
    )


async def monitor_loop():
    """Main monitoring loop."""
    logger.info("📡 EMA Monitor started...")
    cycle_count = 0

    while True:
        try:
            cycle_count += 1
            logger.info(f"EMA: Cycle #{cycle_count}")

            # Check existing trades for TP/SL
            trades = await get_all_open_trades()
            ema_trades = [t for t in trades if t.get("strategy") in ("EMA", None, "")]
            logger.info(f"EMA: {len(ema_trades)} open trades")

            for t in ema_trades:
                try:
                    exchange = t.get("exchange", "GATE").lower()
                    if exchange == "gate":
                        p = await gate_price(t["symbol"])
                    else:
                        p = await mexc_price(t["symbol"])

                    tp = float(t.get("take_profit") or 0)
                    sl = float(t.get("stop_loss") or 0)

                    logger.debug(f"EMA: {t['symbol']} price={p} TP={tp} SL={sl}")

                    if tp and p >= tp:
                        logger.info(f"EMA: {t['symbol']} hit TP!")
                        await close_trade(t, p, "take_profit")
                    elif sl and p <= sl:
                        logger.info(f"EMA: {t['symbol']} hit SL!")
                        await close_trade(t, p, "stop_loss")
                except Exception as e:
                    logger.debug(f"EMA: Error checking trade {t['symbol']}: {e}")

            # Open new trades if under limit (per user)
            users = await get_all_active_users()
            auto_users = [u for u in users if u.get("ema_trade", False)]
            logger.info(f"EMA: {len(auto_users)} active users with EMA enabled")

            if auto_users:
                symbols = await get_symbols()
                logger.info(f"EMA: Checking {len(symbols)} symbols for signals")

                signals_found = 0
                for u in auto_users:
                    user_id = u["id"]
                    exchange = u.get("exchange", "gate")

                    # Check user's open trades count
                    user_trades = [t for t in ema_trades if t["user_id"] == user_id]
                    if len(user_trades) >= MAX_OPEN_TRADES:
                        logger.info(f"EMA: User {user_id} at max trades ({len(user_trades)})")
                        continue

                    user_open_syms = [t["symbol"] for t in user_trades]

                    for s in symbols:
                        if s in user_open_syms:
                            continue

                        sig = await analyze(s)
                        if sig:
                            signals_found += 1
                            amt = float(u.get("ema_amount", DEFAULT_AMOUNT))
                            logger.info(f"EMA: Signal found for {s}, opening trade for user {user_id}")
                            await open_trade(sig, user_id, amt, exchange)
                            break  # One trade per cycle per user

                if signals_found == 0:
                    logger.info(f"EMA: No signals found in this cycle")

        except Exception as e:
            logger.error(f"EMA monitor_loop error: {e}")

        logger.info(f"EMA: Sleeping for {MONITOR_INTERVAL}s")
        await asyncio.sleep(MONITOR_INTERVAL)