import asyncio
import logging
from datetime import datetime, timezone

from database.client import get_all_open_trades, update_trade, get_user
from trading.mexc_client import get_ticker_price, place_sell_order
from config import MONITOR_INTERVAL

logger = logging.getLogger(__name__)

# Global application reference (set from main.py)
_app = None


def set_app(app):
    global _app
    _app = app


async def close_trade_on_exchange(trade: dict, close_price: float, reason: str) -> dict:
    """Close a trade on the exchange and update DB."""
    user = await get_user(trade["user_id"])
    if not user or not user.get("mexc_api_key"):
        return {}

    try:
        result = await place_sell_order(
            api_key=user["mexc_api_key"],
            api_secret=user["mexc_api_secret"],
            symbol=trade["symbol"],
            quantity=trade["quantity"],
        )
        close_price = result.get("close_price", close_price)
    except Exception as e:
        logger.error(f"Failed to close trade {trade['id']} on exchange: {e}")

    entry = float(trade["entry_price"])
    qty = float(trade["quantity"])
    pnl = (close_price - entry) * qty if trade["side"] == "buy" else (entry - close_price) * qty

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
    """Send notification to a Telegram user."""
    if _app is None:
        return
    try:
        await _app.bot.send_message(chat_id=user_id, text=message, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Failed to notify user {user_id}: {e}")


async def monitor_loop():
    """Main monitoring loop – checks all open trades every MONITOR_INTERVAL seconds."""
    logger.info("📡 Monitor loop started")
    while True:
        try:
            trades = await get_all_open_trades()
            if trades:
                logger.debug(f"Monitoring {len(trades)} open trade(s)")

            for trade in trades:
                try:
                    current_price = await get_ticker_price(trade["symbol"])
                    tp = float(trade.get("take_profit") or 0)
                    sl = float(trade.get("stop_loss") or 0)
                    side = trade.get("side", "buy")

                    hit_tp = tp > 0 and (
                        (side == "buy" and current_price >= tp) or
                        (side == "sell" and current_price <= tp)
                    )
                    hit_sl = sl > 0 and (
                        (side == "buy" and current_price <= sl) or
                        (side == "sell" and current_price >= sl)
                    )

                    if hit_tp or hit_sl:
                        reason = "take_profit" if hit_tp else "stop_loss"
                        emoji = "🎯" if hit_tp else "🛑"
                        label = "Take Profit ✅" if hit_tp else "Stop Loss ❌"

                        closed = await close_trade_on_exchange(trade, current_price, reason)
                        pnl = closed.get("pnl", 0)
                        pnl_emoji = "🟢" if pnl >= 0 else "🔴"

                        msg = (
                            f"{emoji} <b>{label} تم!</b>\n\n"
                            f"🪙 <b>العملة:</b> {trade['symbol']}\n"
                            f"📥 <b>سعر الدخول:</b> <code>{trade['entry_price']}</code>\n"
                            f"📤 <b>سعر الخروج:</b> <code>{current_price:.6f}</code>\n"
                            f"{pnl_emoji} <b>الربح/الخسارة:</b> <code>{pnl:+.4f} USDT</code>\n"
                            f"⏰ <b>الوقت:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                        await notify_user(trade["user_id"], msg)

                except Exception as e:
                    logger.error(f"Error monitoring trade {trade.get('id')}: {e}")

        except Exception as e:
            logger.error(f"Monitor loop error: {e}")

        await asyncio.sleep(MONITOR_INTERVAL)
