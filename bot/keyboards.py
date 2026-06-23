from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import AMOUNT_PRESETS


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💰 رصيدي", callback_data="balance"),
            InlineKeyboardButton("📊 صفقاتي", callback_data="my_trades"),
        ],
        [
            InlineKeyboardButton("📈 سجل الصفقات", callback_data="trade_history"),
            InlineKeyboardButton("📡 الإشارات", callback_data="recent_signals"),
        ],
        [
            InlineKeyboardButton("🤖 الاستراتيجيات", callback_data="strategies"),
        ],
        [
            InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings"),
        ],
    ])


def strategies_keyboard(user: dict) -> InlineKeyboardMarkup:
    ema_status = "✅ مفعّل" if user.get("ema_trade", False) else "❌ معطّل"
    harpoon_status = "✅ مفعّل" if user.get("harpoon_trade", False) else "❌ معطّل"
    ema_amt = user.get("ema_amount", 10)
    harp_amt = user.get("harpoon_amount", 10)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📈 EMA: {ema_status} | ${ema_amt}", callback_data="ema_menu")],
        [InlineKeyboardButton(f"🎯 HARPOON: {harpoon_status} | ${harp_amt}", callback_data="harpoon_menu")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
    ])


def ema_menu_keyboard(user: dict) -> InlineKeyboardMarkup:
    status = "✅ مفعّل" if user.get("ema_trade", False) else "❌ معطّل"
    toggle_text = "🔴 إيقاف EMA" if user.get("ema_trade", False) else "🟢 تفعيل EMA"
    amt = user.get("ema_amount", 10)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_text, callback_data="toggle_ema")],
        [InlineKeyboardButton(f"💵 المبلغ الحالي: ${amt}", callback_data="set_ema_amount")],
        [
            InlineKeyboardButton(f"${p}", callback_data=f"ema_amt_{p}")
            for p in AMOUNT_PRESETS[:3]
        ],
        [
            InlineKeyboardButton(f"${p}", callback_data=f"ema_amt_{p}")
            for p in AMOUNT_PRESETS[3:]
        ],
        [InlineKeyboardButton("🔙 رجوع", callback_data="strategies")],
    ])


def harpoon_menu_keyboard(user: dict) -> InlineKeyboardMarkup:
    toggle_text = "🔴 إيقاف HARPOON" if user.get("harpoon_trade", False) else "🟢 تفعيل HARPOON"
    amt = user.get("harpoon_amount", 10)
    exchange = user.get("exchange", "gate").upper()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_text, callback_data="toggle_harpoon")],
        [InlineKeyboardButton(f"💵 المبلغ الأساسي: ${amt}", callback_data="set_harpoon_amount")],
        [
            InlineKeyboardButton(f"${p}", callback_data=f"harp_amt_{p}")
            for p in AMOUNT_PRESETS[:3]
        ],
        [
            InlineKeyboardButton(f"${p}", callback_data=f"harp_amt_{p}")
            for p in AMOUNT_PRESETS[3:]
        ],
        [InlineKeyboardButton(f"🏦 البورصة: {exchange}", callback_data="exchange_menu")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="strategies")],
    ])


def exchange_keyboard(current: str) -> InlineKeyboardMarkup:
    opts = [
        ("Gate.io", "gate"),
        ("MEXC", "mexc"),
        ("كلاهما", "both"),
    ]
    rows = []
    for label, val in opts:
        check = "✅ " if current == val else ""
        rows.append([InlineKeyboardButton(f"{check}{label}", callback_data=f"set_exchange_{val}")])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="harpoon_menu")])
    return InlineKeyboardMarkup(rows)


def trades_keyboard(trades: list) -> InlineKeyboardMarkup:
    rows = []
    for t in trades[:8]:
        sym = t["symbol"]
        strategy = t.get("strategy", "EMA")
        amt = t.get("amount", 0)
        rows.append([InlineKeyboardButton(
            f"[{strategy}] {sym} | ${amt}",
            callback_data=f"trade_detail_{t['id']}"
        )])
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def trade_detail_keyboard(trade_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 إغلاق الصفقة يدوياً", callback_data=f"close_confirm_{trade_id}")],
        [InlineKeyboardButton("🔙 رجوع للصفقات", callback_data="my_trades")],
    ])


def confirm_close_keyboard(trade_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد الإغلاق", callback_data=f"close_exec_{trade_id}"),
            InlineKeyboardButton("❌ إلغاء", callback_data=f"trade_detail_{trade_id}"),
        ],
    ])


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
    ])


def back_keyboard(target: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=target)],
    ])
