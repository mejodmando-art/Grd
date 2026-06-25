import asyncio, logging, os, time
from datetime import datetime, timezone
from database.client import get_all_open_trades, update_trade, save_trade, get_all_active_users, get_open_trades, get_user
from trading.gate_client import (
    get_ticker_price, place_buy_order, place_sell_order,
    get_klines, get_top_symbols, get_usdt_free, get_coin_balance
)
from config import *

logger = logging.getLogger("GateBot")
_app = None
_cache = []
_last = 0
notified_signals = set()
_recently_opened = {}

def set_app(a): global _app; _app = a

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

# ─── Strategy 1: EMA ─────────────────────────────────────────────────────────
async def analyze_ema(sym):
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

# ─── Strategy 2: Harpoon ─────────────────────────────────────────────────────
async def analyze_harpoon(sym):
    try:
        kl = await get_klines(sym, "5m", 20)
        if len(kl) < 15: return None
        cl = [c["close"] for c in kl]; vl = [c["volume"] for c in kl]
        avg_vol = sum(vl[-10:-1]) / 9
        if vl[-1] < avg_vol * 2.0: return None
        last = kl[-1]
        change = (last["close"] - last["open"]) / last["open"] * 100
        if change < 1.5: return None
        ef = ema(cl, 5); es = ema(cl, 13)
        if not ef or not es or ef[-1] is None or es[-1] is None: return None
        if ef[-1] <= es[-1]: return None
        p = cl[-1]
        return {
            "symbol": sym, "entry_price": p,
            "take_profit": round(p*(1+3.0/100),6),
            "stop_loss": round(p*(1-1.5/100),6),
            "strategy": "HARPOON"
        }
    except: return None

# ─── Strategy 3: UT Bot (15m) ────────────────────────────────────────────────
async def analyze_ut_bot(sym):
    """
    UT Bot v2 on 15m timeframe
    ATR Trailing Stop with buy/sell signals
    SPOT only: Buy = open, Sell = close
    """
    try:
        kl = await get_klines(sym, "15m", 50)
        if len(kl) < 20: return None

        cl = [c["close"] for c in kl]
        hi = [c["high"] for c in kl]
        lo = [c["low"] for c in kl]

        # ATR calculation
        atr_period = 10
        mult = 2.0

        atr_vals = []
        for i in range(1, len(cl)):
            tr = max(hi[i] - lo[i], abs(hi[i] - cl[i-1]), abs(lo[i] - cl[i-1]))
            atr_vals.append(tr)

        if len(atr_vals) < atr_period: return None
        atr = sum(atr_vals[-atr_period:]) / atr_period
        sl_value = mult * atr

        # Trailing Stop calculation
        tsl = cl[0]
        for i in range(1, len(cl)):
            if cl[i] > tsl and cl[i-1] > tsl:
                tsl = max(tsl, cl[i] - sl_value)
            elif cl[i] < tsl and cl[i-1] < tsl:
                tsl = min(tsl, cl[i] + sl_value)
            elif cl[i] > tsl:
                tsl = cl[i] - sl_value
            else:
                tsl = cl[i] + sl_value

        # Signals
        p = cl[-1]
        prev_p = cl[-2]

        # Buy: price crosses above TSL
        buy = prev_p <= tsl and p > tsl
        # Sell: price crosses below TSL
        sell = prev_p >= tsl and p < tsl

        if buy:
            return {
                "symbol": sym,
                "entry_price": p,
                "take_profit": round(p * (1 + 3.0/100), 6),  # 3% TP
                "stop_loss": round(tsl, 6),  # TSL as SL
                "strategy": "UT_BOT",
                "action": "buy",  # Open position
                "tsl": round(tsl, 6)
            }

        if sell:
            return {
                "symbol": sym,
                "entry_price": p,
                "take_profit": 0,
                "stop_loss": 0,
                "strategy": "UT_BOT",
                "action": "sell",  # Close position
                "tsl": round(tsl, 6)
            }

        return None
    except Exception as e:
        logger.error(f"UT Bot error for {sym}: {e}")
        return None

async def notify(uid, msg):
    if _app:
        try: await _app.bot.send_message(uid, msg, parse_mode="HTML", disable_web_page_preview=True)
        except: pass

async def _user_has_open_symbol(user_id, symbol):
    user_trades = await get_open_trades(user_id)
    for t in user_trades:
        if t.get("symbol") == symbol:
            return True
    return False

async def open_trade(signal, uid, amt):
    ak = os.getenv("GATE_API_KEY",""); sk = os.getenv("GATE_API_SECRET","")
    if not ak:
        await notify(uid, "❌ API Keys غير مضبوطة")
        return

    symbol = signal["symbol"]
    action = signal.get("action", "buy")

    # For UT Bot Sell: check if we have the coin
    if action == "sell":
        coin_balance = await get_coin_balance(symbol)
        if coin_balance <= 0:
            logger.info(f"No {symbol} to sell for user {uid}")
            return  # Nothing to sell

        try:
            r = await place_sell_order(ak, sk, symbol, coin_balance)
            await notify(uid,
                f"🔴 <b>UT Bot SELL (Close)</b>\n\n"
                f"💱 <code>{symbol}</code>\n"
                f"📊 كمية: {r['quantity']:.6f}\n"
                f"💵 سعر: ${r['close_price']:.6f}\n"
                f"💰 قيمة: ${r['cost']:.2f}"
            )
            return
        except Exception as e:
            await notify(uid, f"❌ فشل البيع: {e}")
            return

    # For Buy: normal flow
    if await _user_has_open_symbol(uid, symbol):
        return

    cache_key = f"{uid}_{symbol}"
    if cache_key in _recently_opened and time.time() - _recently_opened[cache_key] < 300:
        return

    try:
        free_usdt = await get_usdt_free()
        if free_usdt < amt:
            await notify(uid, f"⚠️ رصيد غير كافٍ: ${free_usdt:.2f}")
            return

        r = await place_buy_order(ak, sk, symbol, amt)

        await save_trade({
            "user_id": uid, "symbol": symbol, "side": "buy",
            "entry_price": r["entry_price"], "amount": amt,
            "quantity": r["quantity"], "take_profit": signal["take_profit"],
            "stop_loss": signal["stop_loss"], "status": "open",
            "order_id": r["order_id"], "strategy": signal.get("strategy", "EMA")
        })

        _recently_opened[cache_key] = time.time()

        emojis = {"EMA": "📈", "HARPOON": "🐋", "UT_BOT": "🎯"}
        em = emojis.get(signal.get("strategy"), "🚀")

        await notify(uid,
            f"{em} <b>صفقة {signal.get('strategy', 'NEW')} منفذة!</b>\n\n"
            f"💱 <code>{symbol}</code>\n"
            f"🎯 <b>UT Bot 15m</b>\n"
            f"💰 ${r['cost']:.2f} | 📊 {r['quantity']:.6f}\n"
            f"💵 دخول: ${r['entry_price']:.6f}\n"
            f"🎯 TP: ${signal['take_profit']:.6f}\n"
            f"🛑 SL (TSL): ${signal['stop_loss']:.6f}"
        )
    except ValueError as ve:
        await notify(uid, f"❌ <b>رفض:</b> {ve}")
    except Exception as e:
        await notify(uid, f"❌ فشل: {str(e)[:150]}")

async def close_trade(t, price, reason):
    ak = os.getenv("GATE_API_KEY",""); sk = os.getenv("GATE_API_SECRET","")
    if not ak: return

    symbol = t["symbol"]
    try:
        r = await place_sell_order(ak, sk, symbol, t["quantity"])
        close_price = r["close_price"]
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
        f"{em} <b>صفقة مغلقة!</b>\n💱 {symbol}\n{pnl_emoji} P&L: {pnl:+.4f} USDT"
    )

async def monitor_loop():
    global notified_signals
    logger.info("📡 بدء التداول التلقائي — EMA + Harpoon + UT Bot 15m")
    while True:
        try:
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

            if len(trades) < MAX_OPEN_TRADES:
                users = await get_all_active_users()
                ema_users = [u for u in users if u.get("ema_trade", True)]
                harp_users = [u for u in users if u.get("harpoon_trade", False)]
                ut_users = [u for u in users if u.get("ut_bot_trade", False)]

                symbols = await syms()
                open_symbols = [t["symbol"] for t in trades]

                for sym in symbols:
                    if sym in open_symbols:
                        continue

                    # EMA
                    if ema_users:
                        sig = await analyze_ema(sym)
                        if sig:
                            sk = f"EMA_{sig['symbol']}_{sig['entry_price']:.2f}"
                            if sk not in notified_signals:
                                notified_signals.add(sk)
                                for u in ema_users:
                                    await notify(u["id"], f"📈 إشارة EMA: {sym}")
                            for u in ema_users:
                                await open_trade(sig, u["id"], float(u.get("ema_amount", DEFAULT_AMOUNT)))
                            break

                    # Harpoon
                    if harp_users:
                        sig = await analyze_harpoon(sym)
                        if sig:
                            sk = f"HARPOON_{sig['symbol']}_{sig['entry_price']:.2f}"
                            if sk not in notified_signals:
                                notified_signals.add(sk)
                                for u in harp_users:
                                    await notify(u["id"], f"🐋 Harpoon: {sym}")
                            for u in harp_users:
                                await open_trade(sig, u["id"], float(u.get("harpoon_amount", DEFAULT_AMOUNT)))
                            break

                    # UT Bot
                    if ut_users:
                        sig = await analyze_ut_bot(sym)
                        if sig:
                            action = sig.get("action", "buy")
                            sk = f"UT_{sig['symbol']}_{sig['entry_price']:.2f}_{action}"

                            if sk not in notified_signals:
                                notified_signals.add(sk)
                                for u in ut_users:
                                    if action == "buy":
                                        await notify(u["id"],
                                            f"🎯 <b>UT Bot BUY!</b>\n\n"
                                            f"💱 <code>{sym}</code>\n"
                                            f"⏱️ فريم: 15 دقيقة\n"
                                            f"💵 دخول: {sig['entry_price']:.6f}\n"
                                            f"🎯 TP: {sig['take_profit']:.6f}\n"
                                            f"🛑 TSL: {sig['stop_loss']:.6f}"
                                        )
                                    else:
                                        await notify(u["id"],
                                            f"🔴 <b>UT Bot SELL!</b>\n\n"
                                            f"💱 <code>{sym}</code>\n"
                                            f"⏱️ فريم: 15 دقيقة\n"
                                            f"💵 سعر: {sig['entry_price']:.6f}\n"
                                            f"📊 إغلاق المركز"
                                        )

                            for u in ut_users:
                                await open_trade(sig, u["id"], float(u.get("ut_bot_amount", DEFAULT_AMOUNT)))
                            break

            if len(notified_signals) > 500: notified_signals.clear()
            if len(_recently_opened) > 1000: _recently_opened.clear()

        except Exception as e:
            logger.error(f"Monitor error: {e}")

        await asyncio.sleep(MONITOR_INTERVAL)
