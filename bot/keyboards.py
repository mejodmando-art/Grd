from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import AMOUNT_PRESETS


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 صفقاتي", callback_data="my_trades"),
            InlineKeyboardButton("📈 الإشارات", callback_data="recent_signals"),
        ],
        [
            InlineKeyboardButton("💰 رصيدي", callback_data="balance"),
            InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings"),
        ],
        [
            InlineKeyboardButton("🤖 التداول التلقائي", callback_data="toggle_auto"),
        ],
        [
            InlineKeyboardButton("📤 إرسال إشارة (أدمن)", callback_data="send_signal"),
        ],
    ])


def amount_selection_keyboard(signal_id: str) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for amount in AMOUNT_PRESETS:
        row.append(InlineKeyboardButton(f"💵 ${amount}", callback_data=f"exec_{signal_id}_{amount}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("✏️ مبلغ مخصص", callback_data=f"custom_{signal_id}"),
        InlineKeyboardButton("❌ تخطي", callback_data="skip_signal"),
    ])
    return InlineKeyboardMarkup(rows)


def trade_action_keyboard(trade_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 تفاصيل الصفقة", callback_data=f"trade_detail_{trade_id}"),
            InlineKeyboardButton("🔴 إغلاق الصفقة", callback_data=f"close_trade_{trade_id}"),
        ],
        [InlineKeyboardButton("🔙 رجوع", callback_data="my_trades")],
    ])


def confirm_close_keyboard(trade_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تأكيد الإغلاق", callback_data=f"confirm_close_{trade_id}"),
            InlineKeyboardButton("❌ إلغاء", callback_data=f"trade_detail_{trade_id}"),
        ],
    ])


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 تحديث مفاتيح MEXC", callback_data="set_api_keys")],
        [InlineKeyboardButton("💵 تغيير المبلغ الافتراضي", callback_data="set_default_amount")],
        [InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="main_menu")],
    ])


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
    ])


def signal_form_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for admin signal creation direction."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 LONG", callback_data="sig_dir_long"),
            InlineKeyboardButton("🔴 SHORT", callback_data="sig_dir_short"),
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data="main_menu")],
    ])
