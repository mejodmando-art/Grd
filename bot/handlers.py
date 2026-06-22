from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from trading.gate_client import get_balance

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = await get_balance()
        msg = "💰 <b>محفظتك على Gate.io</b>\n\n"
        for coin in data['all_coins'][:15]:
            msg += f"• <b>{coin['coin']}</b>: {coin['free']:.4f} (متاح) | {coin['used']:.4f} (محجوز) | ≈ ${coin['value']:.2f}\n"
        msg += f"\n📊 <b>القيمة الإجمالية:</b> ≈ ${data['total_value']:.2f}"
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الاتصال: {str(e)}")

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))