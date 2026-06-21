import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    symbol: str
    direction: str          # "long" or "short"
    entry_price: Optional[float] = None
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.normalize_symbol(),
            "direction": self.direction,
            "entry_price": self.entry_price,
            "take_profit": self.take_profit,
            "stop_loss": self.stop_loss,
            "message": self.message,
        }

    def normalize_symbol(self) -> str:
        """Ensure symbol is in CCXT format: BTC/USDT"""
        s = self.symbol.upper().replace("-", "/")
        if "/" not in s:
            if s.endswith("USDT"):
                s = s[:-4] + "/USDT"
            else:
                s = s + "/USDT"
        return s

    def side(self) -> str:
        return "buy" if self.direction.lower() == "long" else "sell"

    def format_message(self) -> str:
        direction_emoji = "🟢 LONG" if self.direction.lower() == "long" else "🔴 SHORT"
        lines = [
            f"📊 <b>إشارة تداول جديدة!</b>",
            f"",
            f"🪙 <b>العملة:</b> <code>{self.normalize_symbol()}</code>",
            f"📈 <b>الاتجاه:</b> {direction_emoji}",
        ]
        if self.entry_price:
            lines.append(f"💰 <b>سعر الدخول:</b> <code>{self.entry_price}</code>")
        if self.take_profit:
            lines.append(f"🎯 <b>Take Profit:</b> <code>{self.take_profit}</code>")
        if self.stop_loss:
            lines.append(f"🛑 <b>Stop Loss:</b> <code>{self.stop_loss}</code>")
        if self.message:
            lines.append(f"\n📝 {self.message}")
        return "\n".join(lines)


def parse_signal_from_text(text: str) -> Optional[Signal]:
    """
    Try to parse a signal from free-form text.
    Expected format (flexible):
        SYMBOL: BTCUSDT
        Direction: LONG / SHORT
        Entry: 45000
        TP: 47000
        SL: 44000
    """
    lines = text.strip().splitlines()
    data = {}
    for line in lines:
        if ":" in line:
            key, _, val = line.partition(":")
            data[key.strip().lower()] = val.strip()

    symbol = data.get("symbol") or data.get("pair") or data.get("coin")
    direction = data.get("direction") or data.get("side") or data.get("type")
    entry = data.get("entry") or data.get("entry price") or data.get("price")
    tp = data.get("tp") or data.get("take profit") or data.get("target")
    sl = data.get("sl") or data.get("stop loss") or data.get("stop")

    if not symbol or not direction:
        return None

    direction = direction.lower()
    if direction not in ("long", "short", "buy", "sell"):
        return None
    if direction == "buy":
        direction = "long"
    if direction == "sell":
        direction = "short"

    return Signal(
        symbol=symbol,
        direction=direction,
        entry_price=float(entry) if entry else None,
        take_profit=float(tp) if tp else None,
        stop_loss=float(sl) if sl else None,
    )
