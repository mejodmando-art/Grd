from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from trading.gate_client import get_balance
from database.client import get_user, create_user, update_user, get_open_trades

async def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 المحفظة", callback_data="balance"),
         InlineKeyboardButton("📊 الصفقات المفتوحة", callback_data="trades")],
        [InlineKeyboardButton("📈 الأداء", callback_data="performance"),
         InlineKeyboardButton("📉 تاريخ الصفقات", callback_data="history")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings"),
         InlineKeyboardButton("🔔 الإشعارات", callback_data="notifications")],
        [InlineKeyboardButton("💡 نصائح", callback_data="tips"),
         InlineKeyboardButton("❓ المساعدة", callback_data="help")],
    ])

async def settings_menu(user):
    ema = "✅" if user.get("ema_trade", True) else "❌"
    harp = "✅" if user.get("harpoon_trade", False) else "❌"
    ut = "✅" if user.get("ut_bot_trade", False) else "❌"
    sphinx = "✅" if user.get("sphinx_trade", False) else "❌"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📈 EMA: {ema}", callback_data="toggle_ema")],
        [InlineKeyboardButton(f"🐋 Harpoon: {harp}", callback_data="toggle_harpoon")],
        [InlineKeyboardButton(f"🎯 UT Bot 15m: {ut}", callback_data="toggle_ut")],
        [InlineKeyboardButton(f"🦁 SPHINX: {sphinx}", callback_data="toggle_sphinx")],
        [InlineKeyboardButton("💵 تغيير المبالغ", callback_data="amounts_menu")],
        [InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="main_menu")],
    ])

async def amounts_menu(user):
    ema_amt = user.get('ema_amount', 10)
    harp_amt = user.get('harpoon_amount', 10)
    ut_amt = user.get('ut_bot_amount', 10)
    sphinx_amt = user.get('sphinx_amount', 25)

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📈 EMA: ${ema_amt}", callback_data="set_ema_amt")],
        [InlineKeyboardButton(f"🐋 Harpoon: ${harp_amt}", callback_data="set_harp_amt")],
        [InlineKeyboardButton(f"🎯 UT Bot: ${ut_amt}", callback_data="set_ut_amt")],
        [InlineKeyboardButton(f"🦁 SPHINX: ${sphinx_amt}", callback_data="set_sphinx_amt")],
        [InlineKeyboardButton("🔙 رجوع للإعدادات", callback_data="settings")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = await get_user(user.id)
    if not u:
        await create_user(user.id, user.username or user.first_name or "")

    welcome_text = (
        "🤖 <b>GRD Trading Bot v4.0 — UT Bot Edition</b>\n\n"
        "مرحباً بك في بوت التداول الآلي المتقدم!\n\n"
        "📈 <b>EMA</b> — متابعة الترند\n"
        "🐋 <b>Harpoon</b> — صيد الحركات السريعة\n"
        "🎯 <b>UT Bot 15m</b> — ATR Trailing Stop\n"
        "🦁 <b>SPHINX</b> — مسح السيولة + تباعد الزخم\n\n"
        "<b>UT Bot:</b>\n"
        "⏱️ فريم 15 دقيقة\n"
        "🎯 Buy = فتح مركز\n"
        "🔴 Sell = إغلاق مركز (SPOT)\n\n"
        "اختر من القائمة:"
    )

    await update.message.reply_text(welcome_text, reply_markup=await main_menu(), parse_mode="HTML")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    u = await get_user(q.from_user.id)

    if d == "main_menu":
        await q.edit_message_text("🤖 <b>القائمة الرئيسية</b>\nاختر ما تريد:", reply_markup=await main_menu(), parse_mode="HTML")

    elif d == "balance":
        await q.edit_message_text("⏳ جاري جلب المحفظة...")
        try:
            data = await get_balance()
            msg = "💰 <b>محفظتك على Gate.io</b>\n\n"
            for i, coin in enumerate(data['all_coins'][:15]):
                msg += f"{i+1}. <b>{coin['coin']}</b>: {coin['free']:.6f} | ≈ ${coin['value']:.2f}\n"
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
            emoji = {"EMA": "📈", "HARPOON": "🐋", "UT_BOT": "🎯", "SPHINX": "🦁"}.get(strat, "🚀")
            msg += f"{emoji} {t['symbol']} | {strat} | دخول: {t['entry_price']}\n"
        await q.edit_message_text(msg, reply_markup=await main_menu(), parse_mode="HTML")

    elif d == "settings":
        await q.edit_message_text(
            "⚙️ <b>الإعدادات</b>\n\n"
            "🎯 <b>UT Bot 15m:</b> ATR Trailing Stop\n"
            "Buy = فتح مركز | Sell = إغلاق\n\n"
            "اختر الاستراتيجية:",
            reply_markup=await settings_menu(u), parse_mode="HTML"
        )

    elif d == "toggle_ema":
        new_val = not u.get("ema_trade", True)
        await update_user(u["id"], {"ema_trade": new_val})
        u = await get_user(q.from_user.id)
        await q.edit_message_text(f"📈 EMA: {'✅ تفعيل' if new_val else '❌ تعطيل'}", reply_markup=await settings_menu(u))

    elif d == "toggle_harpoon":
        new_val = not u.get("harpoon_trade", False)
        await update_user(u["id"], {"harpoon_trade": new_val})
        u = await get_user(q.from_user.id)
        await q.edit_message_text(f"🐋 Harpoon: {'✅ تفعيل' if new_val else '❌ تعطيل'}", reply_markup=await settings_menu(u))

    elif d == "toggle_ut":
        new_val = not u.get("ut_bot_trade", False)
        await update_user(u["id"], {"ut_bot_trade": new_val})
        u = await get_user(q.from_user.id)
        await q.edit_message_text(f"🎯 UT Bot 15m: {'✅ تفعيل' if new_val else '❌ تعطيل'}", reply_markup=await settings_menu(u))

    elif d == "toggle_sphinx":
        new_val = not u.get("sphinx_trade", False)
        await update_user(u["id"], {"sphinx_trade": new_val})
        u = await get_user(q.from_user.id)
        await q.edit_message_text(f"🦁 SPHINX: {'✅ تفعيل' if new_val else '❌ تعطيل'}", reply_markup=await settings_menu(u))

    elif d == "amounts_menu":
        await q.edit_message_text("💵 <b>تغيير المبالغ</b>", reply_markup=await amounts_menu(u), parse_mode="HTML")

    elif d == "set_ema_amt":
        context.user_data["awaiting"] = "ema_amount"
        await q.edit_message_text("📈 أرسل مبلغ EMA:", reply_markup=await main_menu())

    elif d == "set_harp_amt":
        context.user_data["awaiting"] = "harpoon_amount"
        await q.edit_message_text("🐋 أرسل مبلغ Harpoon:", reply_markup=await main_menu())

    elif d == "set_ut_amt":
        context.user_data["awaiting"] = "ut_bot_amount"
        await q.edit_message_text("🎯 أرسل مبلغ UT Bot (موصى: $20-$50):", reply_markup=await main_menu())

    elif d == "set_sphinx_amt":
        context.user_data["awaiting"] = "sphinx_amount"
        await q.edit_message_text("🦁 أرسل مبلغ SPHINX:", reply_markup=await main_menu())

    elif d == "notifications":
        notif = "✅" if u.get("notifications", True) else "❌"
        await q.edit_message_text(f"🔔 الإشعارات: {notif}", reply_markup=await main_menu())

    elif d == "tips":
        await q.edit_message_text(
            "💡 <b>نصائح UT Bot</b>\n\n"
            "1️⃣ فريم 15 دقيقة = توازن بين السرعة والدقة\n"
            "2️⃣ Buy = فتح مركز | Sell = إغلاق (SPOT)\n"
            "3️⃣ ATR Multiplier = 2.0 (افتراضي)\n"
            "4️⃣ لا تستخدم رافعة — SPOT فقط\n"
            "5️⃣ استخدم مبلغ صغير ($10-$20) للاختبار",
            reply_markup=await main_menu(), parse_mode="HTML"
        )

    elif d == "help":
        await q.edit_message_text(
            "❓ <b>المساعدة</b>\n\n"
            "<b>UT Bot:</b>\n"
            "يستخدم ATR Trailing Stop\n"
            "لتحديد نقاط الدخول والخروج\n\n"
            "<b>SPOT فقط:</b>\n"
            "لا يدعم Short\n"
            "Sell = بيع ما تملك فقط",
            reply_markup=await main_menu(), parse_mode="HTML"
        )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data.get("awaiting")
    if not field:
        return
    try:
        amt = float(update.message.text.strip())
        if amt <= 0 or amt > 1000:
            raise ValueError("مبلغ غير منطقي")
        await update_user(update.effective_user.id, {field: amt})
        context.user_data["awaiting"] = None
        names = {
            "ema_amount": "📈 EMA",
            "harpoon_amount": "🐋 Harpoon",
            "ut_bot_amount": "🎯 UT Bot",
            "sphinx_amount": "🦁 SPHINX"
        }
        await update.message.reply_text(f"✅ {names.get(field)}: ${amt}", reply_markup=await main_menu())
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
