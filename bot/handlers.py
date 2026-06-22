import logging, os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, ConversationHandler, filters
from database.client import get_user, create_user, update_user, get_open_trades, get_trade_history
from trading.gate_client import get_balance as gate_balance

logger = logging.getLogger(__name__)
AWAIT_AMOUNT = 0

async def ensure(update, context):
    u = update.effective_user
    user = await get_user(u.id)
    return user or await create_user(u.id, u.username or u.first_name or "")

async def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 رصيدي", callback_data="bal"), InlineKeyboardButton("📊 صفقاتي", callback_data="trd")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="set")],
    ])

async def start(update, context):
    await ensure(update, context)
    await update.message.reply_text("🤖 بوت Gate.io", reply_markup=await menu())

async def buttons(update, context):
    q = update.callback_query; await q.answer(); d = q.data; u = await ensure(update, context)
    if d == "bal":
        try:
            b = await gate_balance(os.getenv("GATE_API_KEY",""), os.getenv("GATE_API_SECRET",""))
            await q.edit_message_text(f"💰 Gate.io: {b['free']:.2f} USDT", reply_markup=await menu())
        except Exception as e: await q.edit_message_text(f"❌ {e}", reply_markup=await menu())
    elif d == "trd":
        t = await get_open_trades(u["id"])
        await q.edit_message_text(f"📊 مفتوحة: {len(t)}", reply_markup=await menu())
    elif d == "set":
        await q.edit_message_text("⚙️ الإعدادات", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💵 المبلغ", callback_data="amt")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")],
        ]))
    elif d == "back": await q.edit_message_text("القائمة:", reply_markup=await menu())
    elif d == "amt":
        context.user_data["state"] = AWAIT_AMOUNT
        await q.edit_message_text("أرسل المبلغ:")

async def msgs(update, context):
    if context.user_data.get("state") == AWAIT_AMOUNT:
        try:
            a = float(update.message.text)
            await update_user(update.effective_user.id, {"ema_amount": a})
            context.user_data.pop("state")
            await update.message.reply_text(f"✅ ${a}", reply_markup=await menu())
        except: await update.message.reply_text("❌ خطأ")
    else: await update.message.reply_text("استخدم القائمة", reply_markup=await menu())

def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msgs))