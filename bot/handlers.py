import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters
from database.client import get_user, create_user, update_user, get_open_trades, get_trade_history
from trading.gate_client import get_balance as gate_balance

logger = logging.getLogger(__name__)
AWAIT_AMOUNT = 0


async def ensure_user(update, context):
    user_tg = update.effective_user
    user = await get_user(user_tg.id)
    if not user:
        user = await create_user(user_tg.id, user_tg.username or user_tg.first_name or "")
    return user


async def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 رصيدي", callback_data="balance"), InlineKeyboardButton("📊 صفقاتي", callback_data="trades")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
    ])


async def start(update, context):
    await ensure_user(update, context)
    await update.message.reply_text("🤖 بوت Gate.io", reply_markup=await menu(), parse_mode="HTML")


async def button_handler(update, context):
    q = update.callback_query
    await q.answer()
    d = q.data
    u = await ensure_user(update, context)

    if d == "balance":
        ak = os.getenv("GATE_API_KEY", "")
        sk = os.getenv("GATE_API_SECRET", "")
        if not ak:
            await q.edit_message_text("❌ مفاتيح مفقودة", reply_markup=await menu())
            return
        try:
            bal = await gate_balance(ak, sk)
            await q.edit_message_text(f"💰 Gate.io: {bal['free']:.2f} USDT", reply_markup=await menu(), parse_mode="HTML")
        except Exception as e:
            await q.edit_message_text(f"❌ فشل: {e}", reply_markup=await menu())

    elif d == "trades":
        ot = await get_open_trades(u["id"])
        await q.edit_message_text(f"📊 صفقات مفتوحة: {len(ot)}", reply_markup=await menu())

    elif d == "settings":
        await q.edit_message_text(f"⚙️ المبلغ: ${u.get('ema_amount', 10)}", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💵 تغيير المبلغ", callback_data="set_amount")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="menu")],
        ]))

    elif d == "menu":
        await q.edit_message_text("القائمة:", reply_markup=await menu())

    elif d == "set_amount":
        context.user_data["state"] = AWAIT_AMOUNT
        await q.edit_message_text("أرسل المبلغ الجديد:")


async def message_handler(update, context):
    if context.user_data.get("state") == AWAIT_AMOUNT:
        try:
            amt = float(update.message.text.strip())
            await update_user(update.effective_user.id, {"ema_amount": amt})
            context.user_data.pop("state")
            await update.message.reply_text(f"✅ تم: ${amt}", reply_markup=await menu())
        except:
            await update.message.reply_text("❌ رقم خطأ")


def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))