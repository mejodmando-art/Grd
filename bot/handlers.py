from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from trading.gate_client import get_balance

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # زر واحد فقط
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("💰 عرض الرصيد", callback_data="balance")]])
    await update.message.reply_text("🚀 بوت سريع جداً", reply_markup=kb)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "balance":
        await q.edit_message_text("⏳ جاري جلب الرصيد...")
        try:
            data = await get_balance()
            msg = "💰 <b>محفظتك</b>\n\n"
            for coin in data['all_coins'][:10]:
                msg += f"• {coin['coin']}: {coin['free']:.4f} | ≈ ${coin['value']:.2f}\n"
            msg += f"\n📊 <b>الإجمالي:</b> ≈ ${data['total_value']:.2f}"
            await q.edit_message_text(msg, parse_mode="HTML", reply_markup=start_kb())
        except Exception as e:
            await q.edit_message_text(f"❌ خطأ: {str(e)[:200]}", reply_markup=start_kb())

def start_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("💰 عرض الرصيد", callback_data="balance")]])

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))