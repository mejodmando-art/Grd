import logging
import os
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters,
)
from config import ADMIN_IDS
from database.client import get_user, create_user, update_user, get_open_trades, get_trade_history
from trading.mexc_client import get_balance, get_ticker_price

logger = logging.getLogger(__name__)

AWAIT_DEFAULT_AMOUNT = 0


async def ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict:
    user_tg = update.effective_user
    user = await get_user(user_tg.id)
    if not user:
        user = await create_user(user_tg.id, user_tg.username or user_tg.first_name or "")
    return user


async def main_menu_keyboard():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 رصيدي", callback_data="balance"),
         InlineKeyboardButton("📊 صفقاتي", callback_data="my_trades")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
    ])


async def settings_keyboard():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 تغيير المبلغ", callback_data="set_amount")],
        [InlineKeyboardButton("🤖 تشغيل/إيقاف التلقائي", callback_data="toggle_auto")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
    ])


WELCOME_MSG = "🤖 <b>بوت التداول الآلي Spot</b>\n\nاختر من القائمة:"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update, context)
    await update.message.reply_text(WELCOME_MSG, reply_markup=await main_menu_keyboard(), parse_mode="HTML")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    user = await ensure_user(update, context)

    if data == "main_menu":
        await query.edit_message_text("القائمة الرئيسية:", reply_markup=await main_menu_keyboard(), parse_mode="HTML")

    elif data == "balance":
        api_key = os.getenv("MEXC_API_KEY", "")
        api_secret = os.getenv("MEXC_API_SECRET", "")
        if not api_key or not api_secret:
            await query.edit_message_text("❌ مفاتيح MEXC غير مضبوطة.", reply_markup=await main_menu_keyboard())
            return
        await query.edit_message_text("⏳ جاري جلب الرصيد...")
        try:
            bal = await get_balance(api_key, api_secret)
            msg = f"💰 <b>الرصيد</b>\n\n🟢 متاح: <code>{bal['free']:.4f} USDT</code>\n📊 إجمالي: <code>{bal['total']:.4f} USDT</code>"
            await query.edit_message_text(msg, reply_markup=await main_menu_keyboard(), parse_mode="HTML")
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}", reply_markup=await main_menu_keyboard())

    elif data == "my_trades":
        open_trades = await get_open_trades(user_id)
        history = await get_trade_history(user_id, 5)
        if not open_trades and not history:
            await query.edit_message_text("📊 لا توجد صفقات.", reply_markup=await main_menu_keyboard())
            return
        msg = "📊 <b>صفقاتي</b>\n\n"
        if open_trades:
            msg += f"🟢 <b>مفتوحة:</b>\n"
            for t in open_trades:
                msg += f"• {t['symbol']} | دخول: <code>{t['entry_price']}</code> | ${t['amount']}\n"
        if history:
            msg += f"\n📜 <b>آخر الصفقات:</b>\n"
            for t in history:
                pnl = t.get("pnl", 0) or 0
                emoji = "🟢" if float(pnl) >= 0 else "🔴"
                msg += f"• {t['symbol']} | {emoji} {float(pnl):+.2f} USDT\n"
        await query.edit_message_text(msg, reply_markup=await main_menu_keyboard(), parse_mode="HTML")

    elif data == "settings":
        status = "✅ مفعّل" if user.get("auto_trade") else "❌ معطّل"
        msg = f"⚙️ <b>الإعدادات</b>\n\nالمبلغ: <code>${user.get('default_amount', 10)}</code>\nالتلقائي: {status}"
        await query.edit_message_text(msg, reply_markup=await settings_keyboard(), parse_mode="HTML")

    elif data == "set_amount":
        context.user_data["state"] = AWAIT_DEFAULT_AMOUNT
        await query.edit_message_text(
            f"💵 المبلغ الحالي: <code>${user.get('default_amount', 10)}</code>\n\nأرسل المبلغ الجديد (USDT):",
            reply_markup=await main_menu_keyboard(),
            parse_mode="HTML",
        )

    elif data == "toggle_auto":
        new_val = not bool(user.get("auto_trade", False))
        await update_user(user_id, {"auto_trade": new_val})
        status = "✅ مفعّل" if new_val else "❌ معطّل"
        await query.edit_message_text(
            f"🤖 التداول التلقائي: <b>{status}</b>",
            reply_markup=await main_menu_keyboard(),
            parse_mode="HTML",
        )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if state == AWAIT_DEFAULT_AMOUNT:
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError
            await update_user(user_id, {"default_amount": amount})
            context.user_data.pop("state", None)
            await update.message.reply_text(
                f"✅ تم التحديث إلى <code>${amount}</code>",
                reply_markup=await main_menu_keyboard(),
                parse_mode="HTML",
            )
        except ValueError:
            await update.message.reply_text("❌ أرسل رقماً صحيحاً.")
    else:
        await update.message.reply_text("استخدم القائمة:", reply_markup=await main_menu_keyboard())


def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))