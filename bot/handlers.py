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
    ema = "✅" if user.get("ema_trade", True) else "❌"
    harpoon = "✅" if user.get("harpoon_trade", False) else "❌"
    ema_amt = user.get('ema_amount', 10)
    harp_amt = user.get('harpoon_amount', 10)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📈 EMA: {ema} (${ema_amt})", callback_data="toggle_ema")],
        [InlineKeyboardButton(f"🐋 Harpoon: {harpoon} (${harp_amt})", callback_data="toggle_harpoon")],
        [InlineKeyboardButton("💵 تغيير مبلغ EMA", callback_data="set_ema_amount")],
        [InlineKeyboardButton("💵 تغيير مبلغ Harpoon", callback_data="set_harp_amount")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = await get_user(user.id)
    if not u:
        await create_user(user.id, user.username or user.first_name or "")
    await update.message.reply_text(
        "🤖 <b>GRD Trading Bot</b>\n"
        "بوت التداول الآلي على Gate.io\n\n"
        "📈 استراتيجية EMA: متابعة الترند\n"
        "🐋 استراتيجية Harpoon: صيد الحركات السريعة\n\n"
        "اختر من القائمة:",
        reply_markup=await main_menu(),
        parse_mode="HTML"
    )

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
            msg += f"\n📊 <b>الإجمالي:</b> ≈ ${data['total_value']:.2f}"
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
            strat = t.get('strategy', 'EMA')
            msg += f"• {t['symbol']} | {strat} | دخول: {t['entry_price']} | ${t['amount']}\n"
        await q.edit_message_text(msg, reply_markup=await main_menu(), parse_mode="HTML")

    elif d == "settings":
        await q.edit_message_text("⚙️ <b>الإعدادات</b>\n\n"
            "📈 EMA: متابعة الترند البطيء\n"
            "🐋 Harpoon: صيد الحركات السريعة\n"
            "💵 يمكنك تغيير المبلغ لكل استراتيجية",
            reply_markup=await settings_menu(u), parse_mode="HTML")

    elif d == "toggle_ema":
        new_val = not u.get("ema_trade", True)
        await update_user(u["id"], {"ema_trade": new_val})
        u = await get_user(q.from_user.id)
        status = "✅ تم التفعيل" if new_val else "❌ تم التعطيل"
        await q.edit_message_text(f"📈 EMA\n{status}", reply_markup=await settings_menu(u))

    elif d == "toggle_harpoon":
        new_val = not u.get("harpoon_trade", False)
        await update_user(u["id"], {"harpoon_trade": new_val})
        u = await get_user(q.from_user.id)
        status = "✅ تم التفعيل" if new_val else "❌ تم التعطيل"
        await q.edit_message_text(f"🐋 Harpoon\n{status}", reply_markup=await settings_menu(u))

    elif d == "set_ema_amount":
        context.user_data["awaiting"] = "ema_amount"
        await q.edit_message_text("💵 أرسل مبلغ EMA الجديد (USDT):", reply_markup=await main_menu())

    elif d == "set_harp_amount":
        context.user_data["awaiting"] = "harpoon_amount"
        await q.edit_message_text("💵 أرسل مبلغ Harpoon الجديد (USDT):", reply_markup=await main_menu())

    elif d == "main_menu":
        await q.edit_message_text("🤖 <b>القائمة الرئيسية</b>", reply_markup=await main_menu(), parse_mode="HTML")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting") == "ema_amount":
        try:
            amt = float(update.message.text.strip())
            if amt <= 0: raise ValueError
            await update_user(update.effective_user.id, {"ema_amount": amt})
            context.user_data["awaiting"] = None
            await update.message.reply_text(f"✅ مبلغ EMA: ${amt}", reply_markup=await main_menu())
        except:
            await update.message.reply_text("❌ رقم غير صحيح.")

    elif context.user_data.get("awaiting") == "harpoon_amount":
        try:
            amt = float(update.message.text.strip())
            if amt <= 0: raise ValueError
            await update_user(update.effective_user.id, {"harpoon_amount": amt})
            context.user_data["awaiting"] = None
            await update.message.reply_text(f"✅ مبلغ Harpoon: ${amt}", reply_markup=await main_menu())
        except:
            await update.message.reply_text("❌ رقم غير صحيح.")

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))