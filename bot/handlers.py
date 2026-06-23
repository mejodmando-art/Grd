from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from trading.gate_client import get_balance
from database.client import get_user, create_user, update_user, get_open_trades, get_trade_history

async def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 رصيدي", callback_data="balance"),
         InlineKeyboardButton("📊 صفقاتي", callback_data="trades")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
    ])

async def settings_menu(user):
    status = "✅ مفعّل" if user.get("ema_trade", True) else "❌ معطّل"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🤖 التلقائي: {status}", callback_data="toggle_auto")],
        [InlineKeyboardButton("💵 المبلغ", callback_data="set_amount")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = await get_user(user.id)
    if not u:
        await create_user(user.id, user.username or user.first_name or "")
    await update.message.reply_text("🤖 بوت التداول الآلي\nاختر من القائمة:", reply_markup=await main_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    u = await get_user(q.from_user.id)

    if d == "balance":
        await q.edit_message_text("⏳ جاري جلب المحفظة...")
        try:
            data = await get_balance()
            msg = "💰 <b>محفظتك على Gate.io</b>\n\n"
            for coin in data['all_coins'][:10]:
                msg += f"• {coin['coin']}: {coin['free']:.4f} | ≈ ${coin['value']:.2f}\n"
            msg += f"\n📊 <b>القيمة الإجمالية:</b> ≈ ${data['total_value']:.2f}"
            await q.edit_message_text(msg, reply_markup=await main_menu(), parse_mode="HTML")
        except Exception as e:
            await q.edit_message_text(f"❌ فشل: {str(e)[:200]}", reply_markup=await main_menu())

    elif d == "trades":
        open_trades = await get_open_trades(q.from_user.id)
        if not open_trades:
            await q.edit_message_text("📊 لا توجد صفقات مفتوحة.", reply_markup=await main_menu())
            return
        msg = "📊 <b>صفقات مفتوحة:</b>\n"
        for t in open_trades:
            msg += f"• {t['symbol']} | دخول: {t['entry_price']} | ${t['amount']}\n"
        await q.edit_message_text(msg, reply_markup=await main_menu(), parse_mode="HTML")

    elif d == "settings":
        amt = u.get('ema_amount', 10)
        status = '✅' if u.get('ema_trade', True) else '❌'
        await q.edit_message_text(
            f"⚙️ الإعدادات\n\nالمبلغ: ${amt}\nالتلقائي: {status}",
            reply_markup=await settings_menu(u)
        )

    elif d == "toggle_auto":
        new_val = not u.get("ema_trade", True)
        await update_user(u["id"], {"ema_trade": new_val})
        u = await get_user(q.from_user.id)
        await q.edit_message_text(f"تم {'تفعيل' if new_val else 'إيقاف'} التلقائي.", reply_markup=await settings_menu(u))

    elif d == "set_amount":
        context.user_data["awaiting_amount"] = True
        await q.edit_message_text("أرسل المبلغ الجديد (USDT):", reply_markup=await main_menu())

    elif d == "main_menu":
        await q.edit_message_text("القائمة الرئيسية:", reply_markup=await main_menu())

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_amount"):
        try:
            amt = float(update.message.text.strip())
            if amt <= 0: raise ValueError
            await update_user(update.effective_user.id, {"ema_amount": amt})
            context.user_data["awaiting_amount"] = False
            await update.message.reply_text(f"✅ تم تعيين المبلغ: ${amt}", reply_markup=await main_menu())
        except:
            await update.message.reply_text("❌ رقم غير صحيح.")

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))