import logging
import os
from datetime import datetime, timezone
from typing import Optional, Dict

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

from trading.gate_client import get_balance as gate_balance, place_sell_order as gate_sell
from trading.mexc_client import place_sell_order as mexc_sell
from database.client import (
    get_user, create_user, update_user,
    get_open_trades, get_trade_history, get_trade_by_id, update_trade
)
from bot.keyboards import (
    main_menu_keyboard, strategies_keyboard, ema_menu_keyboard,
    harpoon_menu_keyboard, exchange_keyboard, trades_keyboard,
    trade_detail_keyboard, confirm_close_keyboard, back_keyboard
)

logger = logging.getLogger("Handlers")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]


# ─── /start ───────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = await get_user(user.id)
    if not u:
        u = await create_user(user.id, user.username or user.first_name or "")

    name = user.first_name or user.username or "مستخدم"
    await update.message.reply_text(
        f"🤖 <b>أهلاً {name}!</b>\n\n"
        f"بوت التداول الآلي جاهز.\n"
        f"اختر من القائمة:",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML"
    )


# ─── /status ──────────────────────────────────────────────────────────────────

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = await get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text("استخدم /start أولاً.")
        return

    ema = "✅" if u.get("ema_trade") else "❌"
    harp = "✅" if u.get("harpoon_trade") else "❌"
    msg = (
        f"📊 <b>حالة البوت</b>\n\n"
        f"• EMA: {ema} | ${u.get('ema_amount', 10)}\n"
        f"• HARPOON: {harp} | ${u.get('harpoon_amount', 10)}\n"
        f"• البورصة: {u.get('exchange', 'gate').upper()}"
    )
    await update.message.reply_text(
        msg,
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )


# ─── Button Handler ────────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    uid = q.from_user.id
    u = await get_user(uid)
    if not u:
        u = await create_user(uid, q.from_user.username or "")

    # ── القائمة الرئيسية ──
    if d == "main_menu":
        await q.edit_message_text(
            "🤖 <b>القائمة الرئيسية</b>",
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML"
        )

    # ── الرصيد ──
    elif d == "balance":
        await q.edit_message_text("⏳ جاري جلب الرصيد...")
        try:
            # Determine exchange
            exchange = u.get("exchange", "gate")
            if exchange == "mexc":
                ak = os.getenv("MEXC_API_KEY", "")
                sk = os.getenv("MEXC_API_SECRET", "")
                from trading.mexc_client import get_balance as mexc_balance
                data = await mexc_balance(ak, sk)
                msg = (
                    f"💰 <b>محفظتك على MEXC</b>\n\n"
                    f"• USDT Free: {data['free']:.2f}\n"
                    f"• USDT Used: {data['used']:.2f}\n"
                    f"• USDT Total: {data['total']:.2f}"
                )
            else:
                ak = os.getenv("GATE_API_KEY", "")
                sk = os.getenv("GATE_API_SECRET", "")
                data = await gate_balance(ak, sk)
                msg = "💰 <b>محفظتك على Gate.io</b>\n\n"
                for coin in data['all_coins'][:10]:
                    msg += f"• <code>{coin['coin']}</code>: {coin['free']:.6f} | ≈ ${coin['value']:.2f}\n"
                msg += f"\n💎 <b>القيمة الإجمالية:</b> ${data['total_value']:.2f}"

            await q.edit_message_text(
                msg,
                reply_markup=back_keyboard(),
                parse_mode="HTML"
            )
        except Exception as e:
            await q.edit_message_text(
                f"❌ <b>فشل جلب الرصيد</b>\n⚠️ {str(e)[:200]}",
                reply_markup=back_keyboard(),
                parse_mode="HTML"
            )

    # ── صفقاتي المفتوحة ──
    elif d == "my_trades":
        trades = await get_open_trades(uid)
        if not trades:
            await q.edit_message_text(
                "📊 <b>لا توجد صفقات مفتوحة حالياً.</b>",
                reply_markup=back_keyboard(),
                parse_mode="HTML"
            )
            return

        msg = f"📊 <b>صفقاتك المفتوحة ({len(trades)})</b>\n\n"
        for t in trades[:8]:
            strategy = t.get("strategy", "EMA")
            msg += f"• [{strategy}] <code>{t['symbol']}</code> | دخول: {t['entry_price']} | ${t.get('amount', 0)}\n"

        await q.edit_message_text(
            msg,
            reply_markup=trades_keyboard(trades),
            parse_mode="HTML"
        )

    # ── تفاصيل صفقة ──
    elif d.startswith("trade_detail_"):
        trade_id = d.replace("trade_detail_", "")
        t = await get_trade_by_id(trade_id)
        if not t:
            await q.edit_message_text(
                "❌ الصفقة غير موجودة.",
                reply_markup=back_keyboard("my_trades")
            )
            return

        strategy = t.get("strategy", "EMA")
        exchange = t.get("exchange", "GATE")
        entry = float(t.get("entry_price", 0))
        tp = float(t.get("take_profit", 0))
        sl = float(t.get("stop_loss", 0))
        qty = float(t.get("quantity", 0))
        amt = float(t.get("amount", 0))

        msg = (
            f"📋 <b>تفاصيل الصفقة</b>\n\n"
            f"🪙 العملة: <code>{t['symbol']}</code>\n"
            f"🏦 البورصة: {exchange}\n"
            f"🤖 الاستراتيجية: {strategy}\n"
            f"📥 سعر الدخول: <code>{entry}</code>\n"
            f"📦 الكمية: <code>{qty}</code>\n"
            f"💵 المبلغ: ${amt}\n"
            f"🎯 Take Profit: <code>{tp}</code>\n"
            f"🛑 Stop Loss: <code>{sl}</code>\n"
            f"📅 التاريخ: {t.get('created_at', '')[:16]}"
        )
        await q.edit_message_text(
            msg,
            reply_markup=trade_detail_keyboard(trade_id),
            parse_mode="HTML"
        )

    # ── تأكيد إغلاق صفقة ──
    elif d.startswith("close_confirm_"):
        trade_id = d.replace("close_confirm_", "")
        t = await get_trade_by_id(trade_id)
        if not t:
            await q.edit_message_text(
                "❌ الصفقة غير موجودة.",
                reply_markup=back_keyboard("my_trades")
            )
            return

        await q.edit_message_text(
            f"⚠️ <b>تأكيد إغلاق الصفقة؟</b>\n\n"
            f"🪙 {t['symbol']} | ${t.get('amount', 0)}\n\n"
            f"هيتم بيع الكمية بسعر السوق الحالي.",
            reply_markup=confirm_close_keyboard(trade_id),
            parse_mode="HTML"
        )

    # ── تنفيذ إغلاق الصفقة ──
    elif d.startswith("close_exec_"):
        trade_id = d.replace("close_exec_", "")
        t = await get_trade_by_id(trade_id)
        if not t or t.get("status") != "open":
            await q.edit_message_text(
                "❌ الصفقة مغلقة أو غير موجودة.",
                reply_markup=back_keyboard("my_trades")
            )
            return

        await q.edit_message_text(f"⏳ جاري إغلاق {t['symbol']}...")

        try:
            exchange = t.get("exchange", "GATE").lower()
            if exchange == "gate":
                ak = os.getenv("GATE_API_KEY", "")
                sk = os.getenv("GATE_API_SECRET", "")
                result = await gate_sell(ak, sk, t["symbol"], float(t["quantity"]))
            else:
                ak = os.getenv("MEXC_API_KEY", "")
                sk = os.getenv("MEXC_API_SECRET", "")
                result = await mexc_sell(ak, sk, t["symbol"], float(t["quantity"]))

            close_price = result.get("close_price", 0)

            # Calculate P&L correctly
            entry_total = float(t["entry_price"]) * float(t["quantity"])
            current_total = close_price * float(t["quantity"])
            pnl = current_total - entry_total

            await update_trade(trade_id, {
                "status": "closed",
                "close_price": close_price,
                "pnl": round(pnl, 4),
                "closed_at": datetime.now(timezone.utc).isoformat(),
                "close_reason": "manual",
            })

            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            await q.edit_message_text(
                f"✅ <b>تم الإغلاق!</b>\n"
                f"🪙 {t['symbol']}\n"
                f"💲 سعر الإغلاق: <code>{close_price}</code>\n"
                f"{pnl_emoji} P&L: <code>{pnl:+.4f} USDT</code>",
                reply_markup=back_keyboard("my_trades"),
                parse_mode="HTML"
            )
        except Exception as e:
            await q.edit_message_text(
                f"❌ <b>فشل الإغلاق:</b>\n{str(e)[:200]}",
                reply_markup=back_keyboard("my_trades"),
                parse_mode="HTML"
            )

    # ── سجل الصفقات ──
    elif d == "trade_history":
        history = await get_trade_history(uid, limit=10)
        if not history:
            await q.edit_message_text(
                "📈 لا يوجد سجل صفقات بعد.",
                reply_markup=back_keyboard(),
                parse_mode="HTML"
            )
            return

        total_pnl = sum(float(t.get("pnl") or 0) for t in history)
        msg = f"📈 <b>آخر {len(history)} صفقات</b>\n💰 إجمالي P&L: <code>{total_pnl:+.4f} USDT</code>\n\n"

        for t in history:
            pnl = float(t.get("pnl") or 0)
            emoji = "🟢" if pnl >= 0 else "🔴"
            strategy = t.get("strategy", "EMA")
            reason = t.get("close_reason", "")
            reason_icon = "🎯" if reason == "take_profit" else "🛑" if reason == "stop_loss" else "✋"
            msg += f"{emoji} [{strategy}] <code>{t['symbol']}</code> | {reason_icon} {pnl:+.4f} USDT\n"

        await q.edit_message_text(
            msg,
            reply_markup=back_keyboard(),
            parse_mode="HTML"
        )

    # ── الاستراتيجيات ──
    elif d == "strategies":
        ema = "✅" if u.get("ema_trade") else "❌"
        harp = "✅" if u.get("harpoon_trade") else "❌"
        await q.edit_message_text(
            f"🤖 <b>الاستراتيجيات</b>\n\n"
            f"📈 <b>EMA</b> - تقاطع المتوسطات المتحركة\n"
            f"الحالة: {ema} | المبلغ: ${u.get('ema_amount', 10)}\n\n"
            f"🎯 <b>HARPOON</b> - متعدد التأكيدات (RSI + EMA + أنماط)\n"
            f"الحالة: {harp} | المبلغ: ${u.get('harpoon_amount', 10)}\n"
            f"المبلغ يتضاعف بعدد التأكيدات (x2 أو x3)",
            reply_markup=strategies_keyboard(u),
            parse_mode="HTML"
        )

    # ── قائمة EMA ──
    elif d == "ema_menu":
        await q.edit_message_text(
            f"📈 <b>استراتيجية EMA</b>\n\n"
            f"تقاطع EMA({5}) فوق EMA({13}) مع تأكيد حجم التداول.\n"
            f"TP: 2% | SL: 1% | Gate.io أو MEXC",
            reply_markup=ema_menu_keyboard(u),
            parse_mode="HTML"
        )

    # ── تفعيل/إيقاف EMA ──
    elif d == "toggle_ema":
        new_val = not u.get("ema_trade", False)
        await update_user(uid, {"ema_trade": new_val})
        u = await get_user(uid)
        status = "تفعيل ✅" if new_val else "إيقاف ❌"
        await q.edit_message_text(
            f"📈 <b>EMA: {status}</b>",
            reply_markup=ema_menu_keyboard(u),
            parse_mode="HTML"
        )

    # ── تعيين مبلغ EMA من الأزرار ──
    elif d.startswith("ema_amt_"):
        amt = float(d.replace("ema_amt_", ""))
        await update_user(uid, {"ema_amount": amt})
        u = await get_user(uid)
        await q.edit_message_text(
            f"📈 <b>EMA: تم تعيين المبلغ ${amt}</b>",
            reply_markup=ema_menu_keyboard(u),
            parse_mode="HTML"
        )

    # ── مبلغ EMA مخصص ──
    elif d == "set_ema_amount":
        context.user_data["awaiting"] = "ema_amount"
        await q.edit_message_text(
            "💵 أرسل المبلغ المخصص لـ EMA (USDT):",
            reply_markup=back_keyboard("ema_menu")
        )

    # ── قائمة HARPOON ──
    elif d == "harpoon_menu":
        await q.edit_message_text(
            f"🎯 <b>استراتيجية HARPOON</b>\n\n"
            f"متعدد التأكيدات: EMA + RSI + أنماط الشموع.\n"
            f"المبلغ يتضاعف:\n"
            f"• تأكيد واحد: المبلغ الأساسي\n"
            f"• تأكيدان: المبلغ × 2\n"
            f"• ثلاثة تأكيدات: المبلغ × 3\n"
            f"TP: 3% | SL: 1.5%",
            reply_markup=harpoon_menu_keyboard(u),
            parse_mode="HTML"
        )

    # ── تفعيل/إيقاف HARPOON ──
    elif d == "toggle_harpoon":
        new_val = not u.get("harpoon_trade", False)
        await update_user(uid, {"harpoon_trade": new_val})
        u = await get_user(uid)
        status = "تفعيل ✅" if new_val else "إيقاف ❌"
        await q.edit_message_text(
            f"🎯 <b>HARPOON: {status}</b>",
            reply_markup=harpoon_menu_keyboard(u),
            parse_mode="HTML"
        )

    # ── تعيين مبلغ HARPOON من الأزرار ──
    elif d.startswith("harp_amt_"):
        amt = float(d.replace("harp_amt_", ""))
        await update_user(uid, {"harpoon_amount": amt})
        u = await get_user(uid)
        await q.edit_message_text(
            f"🎯 <b>HARPOON: تم تعيين المبلغ ${amt}</b>",
            reply_markup=harpoon_menu_keyboard(u),
            parse_mode="HTML"
        )

    # ── مبلغ HARPOON مخصص ──
    elif d == "set_harpoon_amount":
        context.user_data["awaiting"] = "harpoon_amount"
        await q.edit_message_text(
            "💵 أرسل المبلغ الأساسي لـ HARPOON (USDT):",
            reply_markup=back_keyboard("harpoon_menu")
        )

    # ── اختيار البورصة ──
    elif d == "exchange_menu":
        current = u.get("exchange", "gate")
        await q.edit_message_text(
            "🏦 <b>اختر البورصة</b>\n\nHARPOON يمكنه التداول على Gate.io أو MEXC أو كليهما.",
            reply_markup=exchange_keyboard(current),
            parse_mode="HTML"
        )

    elif d.startswith("set_exchange_"):
        exchange = d.replace("set_exchange_", "")
        await update_user(uid, {"exchange": exchange})
        u = await get_user(uid)
        await q.edit_message_text(
            f"🏦 <b>تم اختيار: {exchange.upper()}</b>",
            reply_markup=harpoon_menu_keyboard(u),
            parse_mode="HTML"
        )

    # ── الإعدادات ──
    elif d == "settings":
        ema = "✅" if u.get("ema_trade") else "❌"
        harp = "✅" if u.get("harpoon_trade") else "❌"
        exchange = u.get("exchange", "gate").upper()
        await q.edit_message_text(
            f"⚙️ <b>الإعدادات</b>\n\n"
            f"• EMA: {ema} | ${u.get('ema_amount', 10)}\n"
            f"• HARPOON: {harp} | ${u.get('harpoon_amount', 10)}\n"
            f"• البورصة: {exchange}\n\n"
            f"للتعديل اذهب إلى: الاستراتيجيات",
            reply_markup=back_keyboard(),
            parse_mode="HTML"
        )

    # ── الإشارات الأخيرة ──
    elif d == "recent_signals":
        from database.client import get_recent_signals
        signals = await get_recent_signals(limit=8)
        if not signals:
            await q.edit_message_text(
                "📡 لا توجد إشارات بعد.",
                reply_markup=back_keyboard(),
                parse_mode="HTML"
            )
            return

        msg = "📡 <b>آخر الإشارات</b>\n\n"
        for s in signals:
            direction = "🟢 LONG" if s.get("direction") == "long" else "🔴 SHORT"
            msg += f"{direction} <code>{s['symbol']}</code> | دخول: {s.get('entry_price', 'N/A')}\n"

        await q.edit_message_text(
            msg,
            reply_markup=back_keyboard(),
            parse_mode="HTML"
        )


# ─── Message Handler ───────────────────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get("awaiting")
    uid = update.effective_user.id

    if awaiting in ("ema_amount", "harpoon_amount"):
        try:
            amt = float(update.message.text.strip())
            if amt <= 0:
                raise ValueError("المبلغ يجب أن يكون أكبر من صفر")

            await update_user(uid, {awaiting: amt})
            context.user_data.pop("awaiting", None)

            field = "EMA" if awaiting == "ema_amount" else "HARPOON"
            await update.message.reply_text(
                f"✅ <b>تم تعيين مبلغ {field}: ${amt}</b>",
                reply_markup=main_menu_keyboard(),
                parse_mode="HTML"
            )
        except ValueError:
            await update.message.reply_text("❌ أرسل رقماً صحيحاً أكبر من صفر.")


def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))