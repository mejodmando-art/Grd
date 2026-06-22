import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters,
)
from database.client import get_user, create_user, update_user, get_open_trades, get_trade_history
from trading.gate_client import get_balance as gate_balance

logger = logging.getLogger(__name__)

AWAIT_EMA_AMOUNT = 0

async def ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict:
    user_tg = update.effective_user
    user = await get_user(user_tg.id)
    if not user:
        user = await create_user(user_tg.id, user_tg.username or user_tg.first_name or "")
    return user

async def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 رصيدي", callback_data="balance"),
         InlineKeyboardButton("📊 صفقاتي", callback_data="my_trades")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
    ])

async def settings_keyboard(user: dict):
    ema_status = "✅" if user.get("ema_trade", True) else "❌"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🤖 التداول التلقائي: {ema_status}", callback_data="toggle_ema")],
        [InlineKeyboardButton("💵 تغيير المبلغ", callback_data="set_amount")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
    ])

WELCOME_MSG = "🤖 <b>بوت التداول الآلي (Gate.io)</b>\n\nاختر من القائمة:"

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
        await query.edit_message_text("⏳ جاري جلب الرصيد...")
        try:
            bal = await gate_balance()
            msg = f"💰 <b>الرصيد (Gate.io)</b>\n\n🟢 متاح: <code>{bal['free']:.2f} USDT</code>\n📊 إجمالي: <code>{bal['total']:.2f} USDT</code>"
            await query.edit_message_text(msg, reply_markup=await main_menu_keyboard(), parse_mode="HTML")
        except Exception as e:
            await query.edit_message_text(f"❌ فشل جلب الرصيد:\n<code>{e}</code>", reply_markup=await main_menu_keyboard(), parse_mode="HTML")

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
        ema_status = "مفعّل ✅" if user.get("ema_trade", True) else "معطّل ❌"
        msg = f"⚙️ <b>الإعدادات</b>\n\n🤖 التلقائي: {ema_status}\n💵 المبلغ: <code>${user.get('ema_amount', 10)}</code>"
        await query.edit_message_text(msg, reply_markup=await settings_keyboard(user), parse_mode="HTML")

    elif data == "toggle_ema":
        new_val = not bool(user.get("ema_trade", True))
        await update_user(user_id, {"ema_trade": new_val})
        user = await get_user(user_id)
        status = "✅ مفعّل" if new_val else "❌ معطّل"
        await query.edit_message_text(f"🤖 التداول التلقائي: <b>{status}</b>", reply_markup=await main_menu_keyboard(), parse_mode="HTML")

    elif data == "set_amount":
        context.user_data["state"] = AWAIT_EMA_AMOUNT
        await query.edit_message_text(
            f"💵 المبلغ الحالي: <code>${user.get('ema_amount', 10)}</code>\n\nأرسل المبلغ الجديد (USDT):",
            reply_markup=await main_menu_keyboard(),
            parse_mode="HTML",
        )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if state == AWAIT_EMA_AMOUNT:
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError
            await update_user(user_id, {"ema_amount": amount})
            context.user_data.pop("state", None)
            await update.message.reply_text(f"✅ تم التحديث إلى <code>${amount}</code>", reply_markup=await main_menu_keyboard(), parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ أرسل رقماً صحيحاً.")
    else:
        await update.message.reply_text("استخدم القائمة:", reply_markup=await main_menu_keyboard())

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))