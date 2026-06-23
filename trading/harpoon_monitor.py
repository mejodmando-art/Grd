import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List

from database.client import (
    get_all_open_trades, update_trade, save_trade, get_all_active_users
)
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
    MONITOR_INTERVAL, HARPOON_TOP_SYMBOLS_COUNT, HARPOON_EMA_FAST, HARPOON_EMA_SLOW,
    HARPOON_TP_PERCENT, HARPOON_SL_PERCENT, HARPOON_KLINE_INTERVAL,
    HARPOON_KLINE_LIMIT, HARPOON_MAX_OPEN_TRADES, HARPOON_BASE_AMOUNT,
    HARPOON_DOUBLE_AMOUNT, HARPOON_TRIPLE_AMOUNT, HARPOON_WHALE_VOLUME_RATIO,
    HARPOON_RSI_OVERSOLD, HARPOON_MIN_VOLUME_RATIO
)

logger = logging.getLogger("HARPOON")
_app = None
_top_symbols_cache: Dict[str, List[str]] = {}
_last_cache_time: Dict[str, float] = {}
_notified_signals: set = set()
_failed_symbols: Dict[str, float] = {}


def set_app(app):
    global _app
    _app = app


def tv_link(symbol: str, exchange: str = "mexc") -> str:
    """Generate TradingView link."""
    sym = symbol.replace("/", "").upper()
    tv_exchange = "GATEIO" if exchange == "gate" else "MEXC"
    return f"https://www.tradingview.com/chart/?symbol={tv_exchange}:{sym}"


def calculate_ema(prices: list, period: int) -> List[Optional[float]]:
    """Calculate Exponential Moving Average."""
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    ema_values = [sum(prices[:period]) / period]
    for price in prices[period:]:
        ema = price * k + ema_values[-1] * (1 - k)
        ema_values.append(ema)
    return [None] * (period - 1) + ema_values


def calculate_rsi(prices: list, period: int = 14) -> float:
    """Calculate RSI with Wilder's smoothing."""
    if len(prices) < period + 1:
        return 50.0

    gains, losses = [], []
    for i in range(1, period + 1):
        diff = prices[-i] - prices[-i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # Wilder's smoothing
    for i in range(period + 1, len(prices)):
        diff = prices[-i] - prices[-i - 1]
        gain = max(diff, 0)
        loss = max(-diff, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def find_support(prices: list) -> Optional[float]:
    """Find recent support level."""
    if len(prices) < 10:
        return None
    return min(prices[-10:-1])


def is_bullish_engulfing(klines: list) -> bool:
    """Check for bullish engulfing pattern."""
    if len(klines) < 2:
        return False
    prev, curr = klines[-2], klines[-1]
    prev_body = prev["close"] - prev["open"]
    curr_body = curr["close"] - curr["open"]
    return (
        prev_body < 0 and curr_body > 0 and
        curr["close"] > prev["close"] and
        curr["open"] < prev["close"]
    )


def is_hammer(kline: dict) -> bool:
    """Check for hammer pattern."""
    body = abs(kline["close"] - kline["open"])
    lower_shadow = min(kline["open"], kline["close"]) - kline["low"]
    upper_shadow = kline["high"] - max(kline["open"], kline["close"])
    if body == 0:
        return False
    return lower_shadow >= body * 2 and upper_shadow <= body * 0.5


async def get_symbols_to_scan(exchange: str = "mexc") -> List[str]:
    """Get top symbols with caching."""
    global _top_symbols_cache, _last_cache_time
    now = time.time()
    if (exchange not in _top_symbols_cache or
            (now - _last_cache_time.get(exchange, 0)) > 60):  # 1 minute cache
        try:
            if exchange == "gate":
                _top_symbols_cache[exchange] = await gate_top(HARPOON_TOP_SYMBOLS_COUNT)
            else:
                _top_symbols_cache[exchange] = await mexc_top(HARPOON_TOP_SYMBOLS_COUNT)
            _last_cache_time[exchange] = now
            logger.info(f"HARPOON: Loaded {len(_top_symbols_cache[exchange])} symbols from {exchange}")
        except Exception as e:
            logger.error(f"HARPOON symbols error: {e}")
    return _top_symbols_cache.get(exchange, ["BTCUSDT", "ETHUSDT", "BNBUSDT"])


async def analyze_harpoon(symbol: str, exchange: str = "mexc") -> Optional[Dict]:
    """Analyze symbol for HARPOON signal."""
    try:
        if exchange == "gate":
            klines = await gate_klines(symbol, HARPOON_KLINE_INTERVAL, HARPOON_KLINE_LIMIT)
        else:
            klines = await mexc_klines(symbol, HARPOON_KLINE_INTERVAL, HARPOON_KLINE_LIMIT)

        if len(klines) < 30:
            return None

        closes = [c["close"] for c in klines]
        volumes = [c["volume"] for c in klines]

        ema_fast = calculate_ema(closes, HARPOON_EMA_FAST)
        ema_slow = calculate_ema(closes, HARPOON_EMA_SLOW)
        if not ema_fast or not ema_slow:
            return None

        prev_fast, prev_slow = ema_fast[-2], ema_slow[-2]
        curr_fast, curr_slow = ema_fast[-1], ema_slow[-1]
        if prev_fast is None or prev_slow is None:
            return None

        avg_vol = sum(volumes[-20:-1]) / 19 if len(volumes) >= 20 else sum(volumes[:-1]) / max(len(volumes) - 1, 1)
        if not (prev_fast <= prev_slow and curr_fast > curr_slow and volumes[-1] >= avg_vol * HARPOON_MIN_VOLUME_RATIO):
            return None

        confirmations = 0
        conf_names = []

        # Whale volume confirmation
        recent_high = max(closes[-10:-1])
        if volumes[-1] >= avg_vol * HARPOON_WHALE_VOLUME_RATIO and closes[-1] > recent_high:
            confirmations += 1
            conf_names.append("🐋 Whale")

        # Support + bullish engulfing confirmation
        support = find_support(closes)
        if support and closes[-2] <= support * 1.01 and is_bullish_engulfing(klines):
            confirmations += 1
            conf_names.append("📊 Support")

        # RSI + hammer confirmation
        rsi = calculate_rsi(closes)
        if rsi < HARPOON_RSI_OVERSOLD and is_hammer(klines[-1]):
            confirmations += 1
            conf_names.append("🔥 Reversal")

        if confirmations == 0:
            return None

        price = closes[-1]
        return {
            "symbol": symbol,
            "entry_price": price,
            "take_profit": round(price * (1 + HARPOON_TP_PERCENT / 100), 6),
            "stop_loss": round(price * (1 - HARPOON_SL_PERCENT / 100), 6),
            "strategy": "HARPOON",
            "confirmations": confirmations,
            "conf_names": conf_names,
            "rsi": round(rsi, 1),
        }
    except Exception:
        pass
    return None


async def send_notification(user_id: int, message: str):
    """Send notification to user."""
    if _app:
        try:
            await _app.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception:
            pass


async def open_trade(signal: dict, user_id: int, amount: float, exchange: str = "mexc"):
    """Open a trade for a user."""
    global _failed_symbols

    link = tv_link(signal["symbol"], exchange)
    symbol = signal["symbol"]
    stars = "⭐" * signal["confirmations"]

    if exchange == "gate":
        api_key = os.getenv("GATE_API_KEY", "")
        api_secret = os.getenv("GATE_API_SECRET", "")
        balance_func = gate_balance
        buy_func = gate_buy
    else:
        api_key = os.getenv("MEXC_API_KEY", "")
        api_secret = os.getenv("MEXC_API_SECRET", "")
        balance_func = mexc_balance
        buy_func = mexc_buy

    if not api_key or not api_secret:
        logger.warning(f"HARPOON: API keys not found for {exchange}")
        return

    try:
        balance = await balance_func(api_key, api_secret)
    except Exception as e:
        logger.error(f"HARPOON: Balance check failed for {symbol}: {e}")
        return

    if balance["free"] < amount:
        now = time.time()
        if (now - _failed_symbols.get(symbol, 0)) > 900:
            _failed_symbols[symbol] = now
            await send_notification(user_id,
                f"[HARPOON-{exchange.upper()}] ❌ <b>Insufficient balance!</b>\n"
                f"🪙 {symbol}\n"
                f"💰 Required: ${amount}\n"
                f"🏦 Available: ${balance['free']:.2f}"
            )
        return

    try:
        result = await buy_func(api_key, api_secret, symbol, amount)
        trade = {
            "user_id": user_id,
            "symbol": symbol,
            "side": "buy",
            "entry_price": result["entry_price"],
            "amount": amount,
            "quantity": result["quantity"],
            "take_profit": signal["take_profit"],
            "stop_loss": signal["stop_loss"],
            "status": "open",
            "order_id": result["order_id"],
            "signal_id": "harpoon_auto",
            "strategy": "HARPOON",
            "confirmations": signal["confirmations"],
            "exchange": exchange.upper(),
        }
        await save_trade(trade)
        logger.info(f"HARPOON: Opened {symbol} ({signal['confirmations']} confirmations) on {exchange}")
        _failed_symbols.pop(symbol, None)

        await send_notification(user_id,
            f"[HARPOON-{exchange.upper()}] {stars} <b>Trade opened!</b>\n"
            f"🪙 {symbol}\n"
            f"📥 <code>{signal['entry_price']}</code>\n"
            f"💵 ${amount}\n"
            f"📊 {', '.join(signal['conf_names'])}\n"
            f"RSI: {signal['rsi']}\n"
            f"🔗 <a href='{link}'>TV</a>"
        )
    except Exception as e:
        now = time.time()
        if (now - _failed_symbols.get(symbol, 0)) > 900:
            _failed_symbols[symbol] = now
            await send_notification(user_id,
                f"[HARPOON-{exchange.upper()}] ❌ <b>Failed!</b>\n"
                f"🪙 {symbol}\n"
                f"⚠️ {str(e)[:150]}"
            )
        logger.error(f"HARPOON failed {symbol}: {e}")


async def close_trade(trade: dict, price: float, reason: str):
    """Close a trade. CRITICAL: Only update DB if sell succeeds."""
    exchange = trade.get("exchange", "MEXC").lower()

    if exchange == "gate":
        api_key = os.getenv("GATE_API_KEY", "")
        api_secret = os.getenv("GATE_API_SECRET", "")
        sell_func = gate_sell
    else:
        api_key = os.getenv("MEXC_API_KEY", "")
        api_secret = os.getenv("MEXC_API_SECRET", "")
        sell_func = mexc_sell

    if not api_key or not api_secret:
        logger.warning(f"HARPOON: API keys not found for {exchange}")
        return

    link = tv_link(trade["symbol"], exchange)

    # Try to sell first
    try:
        result = await sell_func(api_key, api_secret, trade["symbol"], trade["quantity"])
        price = result.get("close_price", price)
        logger.info(f"HARPOON: Sold {trade['symbol']} at {price}")
    except Exception as e:
        logger.error(f"HARPOON: Sell failed for {trade['symbol']}, keeping trade open: {e}")
        return  # CRITICAL: Don't update DB if sell failed!

    # Calculate P&L correctly
    entry_total = float(trade["entry_price"]) * float(trade["quantity"])
    current_total = price * float(trade["quantity"])
    pnl = current_total - entry_total
    pnl_percent = (pnl / entry_total) * 100 if entry_total else 0

    await update_trade(trade["id"], {
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

    if _app:
        await _app.bot.send_message(
            trade["user_id"],
            f"[HARPOON-{exchange.upper()}] {emoji} <b>Closed</b>\n"
            f"🪙 {trade['symbol']}\n"
            f"{pnl_emoji} P&L: <code>{pnl:+.4f} USDT</code> ({pnl_percent:+.2f}%)\n"
            f"📋 {reason_text}\n"
            f"🔗 <a href='{link}'>TV</a>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )


async def harpoon_loop():
    """Main HARPOON monitoring loop."""
    global _notified_signals, _failed_symbols
    logger.info("🎯 HARPOON Monitor started")

    while True:
        try:
            now = time.time()
            # Clean old failed symbols
            _failed_symbols = {k: v for k, v in _failed_symbols.items() if (now - v) < 3600}

            # Clean old notified signals
            if len(_notified_signals) > 500:
                _notified_signals.clear()

            # Check existing trades for TP/SL
            trades = await get_all_open_trades()
            harpoon_trades = [t for t in trades if t.get("strategy") == "HARPOON"]

            for t in harpoon_trades:
                try:
                    exchange = t.get("exchange", "MEXC").lower()
                    if exchange == "gate":
                        price = await gate_price(t["symbol"])
                    else:
                        price = await mexc_price(t["symbol"])

                    tp = float(t.get("take_profit") or 0)
                    sl = float(t.get("stop_loss") or 0)

                    if tp and price >= tp:
                        await close_trade(t, price, "take_profit")
                    elif sl and price <= sl:
                        await close_trade(t, price, "stop_loss")
                except Exception:
                    pass

            # Open new trades (per user, per exchange)
            users = await get_all_active_users()
            for user in users:
                if not user.get("harpoon_trade", False):  # FIXED: default False
                    continue

                exchange = user.get("exchange", "mexc")
                exchanges_to_trade = ["mexc", "gate"] if exchange == "both" else [exchange]

                for ex in exchanges_to_trade:
                    # Count user's open trades for this exchange
                    user_ex_trades = [
                        t for t in harpoon_trades
                        if t.get("user_id") == user["id"] and t.get("exchange", "MEXC").lower() == ex
                    ]
                    if len(user_ex_trades) >= HARPOON_MAX_OPEN_TRADES:
                        continue

                    symbols = await get_symbols_to_scan(ex)
                    user_open_symbols = [t["symbol"] for t in user_ex_trades]

                    for sym in symbols:
                        if sym in user_open_symbols:
                            continue

                        signal = await analyze_harpoon(sym, ex)
                        if signal:
                            link = tv_link(signal["symbol"], ex)
                            signal_key = f"harpoon_{ex}_{signal['symbol']}_{signal['entry_price']:.2f}"

                            if signal_key not in _notified_signals:
                                _notified_signals.add(signal_key)
                                await send_notification(user["id"],
                                    f"[HARPOON-{ex.upper()}] 🚨 <b>Signal!</b>\n"
                                    f"🪙 {signal['symbol']}\n"
                                    f"📥 <code>{signal['entry_price']}</code>\n"
                                    f"📊 {', '.join(signal['conf_names'])}\n"
                                    f"RSI: {signal['rsi']}\n"
                                    f"🔗 <a href='{link}'>TV</a>"
                                )

                            # Calculate amount based on confirmations
                            base = float(user.get("harpoon_amount", HARPOON_BASE_AMOUNT))
                            confs = signal["confirmations"]
                            if confs >= 3:
                                amount = base * 3
                            elif confs >= 2:
                                amount = base * 2
                            else:
                                amount = base

                            await open_trade(signal, user["id"], amount, ex)
                            break  # One trade per cycle per user per exchange

        except Exception as e:
            logger.error(f"HARPOON error: {e}")

        await asyncio.sleep(MONITOR_INTERVAL)