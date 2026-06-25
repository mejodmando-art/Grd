from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from trading.gate_client import get_balance, get_usdt_free
from database.client import get_user, create_user, update_user, get_open_trades, get_trade_history
import logging

logger = logging.getLogger("BotHandlers")

# ─── Helper Functions ───────────────────────────────────────────────────────

def get_strategy_emoji(strategy):
    return {"EMA": "📈", "HARPOON": "🐋", "SPHINX": "🦁"}.get(strategy, "🚀")

def get_status_emoji(status):
    return {"open": "🟢", "closed": "🔴", "cancelled": "⚫"}.get(status, "⚪")

# ─── Main Menus ──────────────────────────────────────────────────────────────

async def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 المحفظة", callback_data="balance"),
         InlineKeyboardButton("📊 الصفقات المفتوحة", callback_data="trades")],
        [InlineKeyboardButton("📈 الأداء", callback_data="performance"),
         InlineKeyboardButton("📉 تاريخ الصفقات", callback_data="history")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings"),
         InlineKeyboardButton("🔔 الإشعارات", callback_data="notifications")],
        [InlineKeyboardButton("💡 نصائح", callback_data="tips"),
         InlineKeyboardButton("🌍 اللغة", callback_data="language")],
        [InlineKeyboardButton("❓ المساعدة", callback_data="help")],
    ])

async def settings_menu(user):
    ema = "✅" if user.get("ema_trade", True) else "❌"
    harp = "✅" if user.get("harpoon_trade", False) else "❌"
    sphinx = "✅" if user.get("sphinx_trade", False) else "❌"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📈 EMA: {ema}", callback_data="toggle_ema")],
        [InlineKeyboardButton(f"🐋 Harpoon: {harp}", callback_data="toggle_harpoon")],
        [InlineKeyboardButton(f"🦁 SPHINX: {sphinx}", callback_data="toggle_sphinx")],
        [InlineKeyboardButton("💵 تغيير المبالغ", callback_data="amounts_menu")],
        [InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="main_menu")],
    ])

async def amounts_menu(user):
    ema_amt = user.get('ema_amount', 10)
    harp_amt = user.get('harpoon_amount', 10)
    sphinx_amt = user.get('sphinx_amount', 25)

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📈 EMA: ${ema_amt}", callback_data="set_ema_amt")],
        [InlineKeyboardButton(f"🐋 Harpoon: ${harp_amt}", callback_data="set_harp_amt")],
        [InlineKeyboardButton(f"🦁 SPHINX: ${sphinx_amt}", callback_data="set_sphinx_amt")],
        [InlineKeyboardButton("🔙 رجوع للإعدادات", callback_data="settings")],
    ])

async def notifications_menu(user):
    notif = "✅" if user.get("notifications", True) else "❌"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔔 الإشعارات: {notif}", callback_data="toggle_notif")],
        [InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="main_menu")],
    ])

# ─── Start Command ───────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = await get_user(user.id)
    if not u:
        await create_user(user.id, user.username or user.first_name or "")

    welcome_text = (
        "🤖 <b>GRD Trading Bot v3.0 Pro</b>\n\n"
        "مرحباً بك في بوت التداول الآلي المتقدم!\n\n"
        "📈 <b>EMA</b> — متابعة الترند\n"
        "🐋 <b>Harpoon</b> — صيد الحركات السريعة\n"
        "🦁 <b>SPHINX</b> — مسح السيولة + تباعد الزخم\n\n"
        "💰 <b>رصيدك:</b> اضغط لمعرفة رصيدك\n"
        "⚙️ <b>الإعدادات:</b> فعل/عطل الاستراتيجيات\n"
        "📊 <b>الصفقات:</b> تابع صفقاتك المفتوحة\n\n"
        "اختر من القائمة:"
    )

    await update.message.reply_text(welcome_text, reply_markup=await main_menu(), parse_mode="HTML")

# ─── Button Handler ─────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    u = await get_user(q.from_user.id)

    # ─── Main Menu Actions ─────────────────────────────────────────────────
    if d == "main_menu":
        await q.edit_message_text(
            "🤖 <b>القائمة الرئيسية</b>\nاختر ما تريد:",
            reply_markup=await main_menu(), parse_mode="HTML"
        )

    # ─── Balance ────────────────────────────────────────────────────────────
    elif d == "balance":
        await q.edit_message_text("⏳ جاري جلب المحفظة...")
        try:
            data = await get_balance()
            msg = "💰 <b>محفظتك على Gate.io</b>\n\n"

            if not data['all_coins']:
                msg += "📭 المحفظة فارغة\n"
            else:
                for i, coin in enumerate(data['all_coins'][:15]):
                    msg += f"{i+1}. <b>{coin['coin']}</b>\n"
                    msg += f"   💵 {coin['free']:.6f} | ≈ ${coin['value']:.2f}\n"

            msg += f"\n📊 <b>الإجمالي:</b> ≈ ${data['total_value']:.2f}"
            await q.edit_message_text(msg, reply_markup=await main_menu(), parse_mode="HTML")
        except Exception as e:
            await q.edit_message_text(f"❌ فشل: {str(e)[:200]}", reply_markup=await main_menu())

    # ─── Open Trades ────────────────────────────────────────────────────────
    elif d == "trades":
        open_trades = await get_open_trades(q.from_user.id)
        if not open_trades:
            await q.edit_message_text(
                "📊 <b>لا توجد صفقات مفتوحة</b>\n\n"
                "الاستراتيجيات تعمل... استنى إشارة!",
                reply_markup=await main_menu(), parse_mode="HTML"
            )
            return

        msg = f"📊 <b>صفقات مفتوحة ({len(open_trades)}):</b>\n\n"
        for t in open_trades:
            strat = t.get('strategy', 'EMA')
            emoji = get_strategy_emoji(strat)
            pnl = float(t.get('pnl', 0)) if t.get('pnl') else 0
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"

            msg += (
                f"{emoji} <b>{t['symbol']}</b> | {strat}\n"
                f"💵 دخول: ${float(t['entry_price']):.6f}\n"
                f"🎯 TP: ${float(t['take_profit']):.6f}\n"
                f"🛑 SL: ${float(t['stop_loss']):.6f}\n"
                f"{pnl_emoji} P&L: {pnl:+.4f} USDT\n"
                f"📊 كمية: {float(t['quantity']):.6f}\n\n"
            )

        await q.edit_message_text(msg, reply_markup=await main_menu(), parse_mode="HTML")

    # ─── Performance ───────────────────────────────────────────────────────
    elif d == "performance":
        trades = await get_trade_history(q.from_user.id, limit=50)
        if not trades:
            await q.edit_message_text(
                "📈 <b>لا توجد بيانات أداء</b>\n\n"
                "افتح صفقات أولاً!",
                reply_markup=await main_menu(), parse_mode="HTML"
            )
            return

        total_pnl = sum(float(t.get('pnl', 0)) for t in trades if t.get('pnl'))
        wins = sum(1 for t in trades if t.get('pnl') and float(t['pnl']) > 0)
        losses = sum(1 for t in trades if t.get('pnl') and float(t['pnl']) < 0)
        total = wins + losses
        win_rate = (wins / total * 100) if total > 0 else 0

        msg = (
            "📈 <b>أداءك</b>\n\n"
            f"💰 <b>إجمالي الربح/الخسارة:</b>\n"
            f"{'🟢' if total_pnl >= 0 else '🔴'} ${total_pnl:+.2f}\n\n"
            f"✅ <b>صفقات رابحة:</b> {wins}\n"
            f"❌ <b>صفقات خاسرة:</b> {losses}\n"
            f"📊 <b>نسبة النجاح:</b> {win_rate:.1f}%\n"
            f"📈 <b>إجمالي الصفقات:</b> {total}"
        )

        await q.edit_message_text(msg, reply_markup=await main_menu(), parse_mode="HTML")

    # ─── History ───────────────────────────────────────────────────────────
    elif d == "history":
        trades = await get_trade_history(q.from_user.id, limit=20)
        if not trades:
            await q.edit_message_text(
                "📉 <b>لا توجد صفقات سابقة</b>",
                reply_markup=await main_menu(), parse_mode="HTML"
            )
            return

        msg = "📉 <b>آخر 20 صفقة:</b>\n\n"
        for t in trades:
            strat = t.get('strategy', 'EMA')
            emoji = get_strategy_emoji(strat)
            status = t.get('status', 'closed')
            status_emoji = get_status_emoji(status)
            pnl = float(t.get('pnl', 0)) if t.get('pnl') else 0
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"

            msg += (
                f"{status_emoji} {emoji} <b>{t['symbol']}</b>\n"
                f"💵 دخول: ${float(t['entry_price']):.6f}\n"
                f"🔴 خروج: ${float(t.get('close_price', 0)):.6f}\n"
                f"{pnl_emoji} P&L: {pnl:+.4f}\n"
                f"📊 السبب: {t.get('close_reason', 'N/A')}\n\n"
            )

        await q.edit_message_text(msg, reply_markup=await main_menu(), parse_mode="HTML")

    # ─── Settings ──────────────────────────────────────────────────────────
    elif d == "settings":
        await q.edit_message_text(
            "⚙️ <b>الإعدادات</b>\n\n"
            "📈 <b>EMA:</b> متابعة الترند البطيء\n"
            "🐋 <b>Harpoon:</b> صيد الحركات السريعة\n"
            "🦁 <b>SPHINX:</b> مسح السيولة + تباعد الزخم\n\n"
            "اختر الاستراتيجية:",
            reply_markup=await settings_menu(u), parse_mode="HTML"
        )

    # ─── Toggle Strategies ────────────────────────────────────────────────
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

    elif d == "toggle_sphinx":
        new_val = not u.get("sphinx_trade", False)
        await update_user(u["id"], {"sphinx_trade": new_val})
        u = await get_user(q.from_user.id)
        status = "✅ تم التفعيل" if new_val else "❌ تم التعطيل"
        await q.edit_message_text(f"🦁 SPHINX\n{status}", reply_markup=await settings_menu(u))

    # ─── Amounts ───────────────────────────────────────────────────────────
    elif d == "amounts_menu":
        await q.edit_message_text(
            "💵 <b>تغيير المبالغ</b>\n\n"
            "اختر الاستراتيجية:",
            reply_markup=await amounts_menu(u), parse_mode="HTML"
        )

    elif d == "set_ema_amt":
        context.user_data["awaiting"] = "ema_amount"
        await q.edit_message_text("📈 أرسل مبلغ EMA الجديد (USDT):", reply_markup=await main_menu())

    elif d == "set_harp_amt":
        context.user_data["awaiting"] = "harpoon_amount"
        await q.edit_message_text("🐋 أرسل مبلغ Harpoon الجديد (USDT):", reply_markup=await main_menu())

    elif d == "set_sphinx_amt":
        context.user_data["awaiting"] = "sphinx_amount"
        await q.edit_message_text(
            "🦁 أرسل مبلغ SPHINX الجديد (USDT):\n"
            "<i>موصى به: $25-$50</i>",
            reply_markup=await main_menu(), parse_mode="HTML"
        )

    # ─── Notifications ────────────────────────────────────────────────────
    elif d == "notifications":
        await q.edit_message_text(
            "🔔 <b>إعدادات الإشعارات</b>",
            reply_markup=await notifications_menu(u), parse_mode="HTML"
        )

    elif d == "toggle_notif":
        new_val = not u.get("notifications", True)
        await update_user(u["id"], {"notifications": new_val})
        u = await get_user(q.from_user.id)
        status = "✅ مفعلة" if new_val else "❌ معطلة"
        await q.edit_message_text(f"🔔 الإشعارات\n{status}", reply_markup=await notifications_menu(u))

    # ─── Tips ──────────────────────────────────────────────────────────────
    elif d == "tips":
        tips_text = (
            "💡 <b>نصائح للتداول الناجح</b>\n\n"
            "1️⃣ <b>لا تخاطر بأكثر من 10%</b> من رأس مالك في صفقة واحدة\n\n"
            "2️⃣ <b>SPHINX</b> أقل تكراراً لكن أعلى دقة\n"
            "   استخدمها للصفقات الكبيرة ($25-$50)\n\n"
            "3️⃣ <b>Harpoon</b> سريعة ومضاربية\n"
            "   مناسبة للمبالغ الصغيرة ($10-$20)\n\n"
            "4️⃣ <b>EMA</b> الأكثر تكراراً\n"
            "   جيدة للمبتدئين\n\n"
            "5️⃣ <b>Always use Stop Loss!</b>\n"
            "   لا تتداول بدون وقف خسارة"
        )
        await q.edit_message_text(tips_text, reply_markup=await main_menu(), parse_mode="HTML")

    # ─── Language ──────────────────────────────────────────────────────────
    elif d == "language":
        await q.edit_message_text(
            "🌍 <b>اللغة</b>\n\n"
            "اللغة الحالية: 🇸🇦 العربية\n"
            "(English coming soon)",
            reply_markup=await main_menu(), parse_mode="HTML"
        )

    # ─── Help ──────────────────────────────────────────────────────────────
    elif d == "help":
        help_text = (
            "❓ <b>المساعدة</b>\n\n"
            "<b>كيف يعمل البوت؟</b>\n"
            "البوت يحلل السوق تلقائياً ويفتح صفقات\n"
            "بناءً على الاستراتيجيات المفعلة\n\n"
            "<b>الاستراتيجيات:</b>\n"
            "📈 EMA — متابعة الترند\n"
            "🐋 Harpoon — صيد الحركات السريعة\n"
            "🦁 SPHINX — مسح السيولة + تباعد الزخم\n\n"
            "<b>الفلاتر:</b>\n"
            "🚫 عملات مستقرة (USDC/USDT)\n"
            "🚫 ماركت كاب > 5 مليار\n\n"
            "<b>للدعم:</b>\n"
            "تواصل مع المشرف"
        )
        await q.edit_message_text(help_text, reply_markup=await main_menu(), parse_mode="HTML")

# ─── Message Handler ────────────────────────────────────────────────────────

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
            "sphinx_amount": "🦁 SPHINX"
        }

        await update.message.reply_text(
            f"✅ {names.get(field, 'المبلغ')}: ${amt}",
            reply_markup=await main_menu()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)}")

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))