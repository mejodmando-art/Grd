import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

from config import ADMIN_IDS, AMOUNT_PRESETS
from database.client import (
    get_user, create_user, update_user,
    save_signal, get_recent_signals,
    save_trade, get_open_trades, get_trade_history,
    update_trade, get_trade_by_id, get_all_active_users,
)
from trading.mexc_client import (
    get_balance, place_buy_order, validate_api_keys, get_ticker_price
)
from trading.monitor import close_trade_on_exchange
from signals.processor import Signal
from bot.keyboards import (
    main_menu_keyboard, amount_selection_keyboard,
    trade_action_keyboard, confirm_close_keyboard,
    settings_keyboard, back_to_menu_keyboard, signal_form_keyboard,
)
from bot.messages import (
    WELCOME_MSG, SETTINGS_MSG, API_KEY_INSTRUCTIONS,
    SIGNAL_STEP1, SIGNAL_STEP2, SIGNAL_STEP3,
)

logger = logging.getLogger(__name__)

# Conversation states
(
    AWAIT_API_KEYS,
    AWAIT_DEFAULT_AMOUNT,
    AWAIT_CUSTOM_AMOUNT,
    AWAIT_SIGNAL_SYMBOL,
    AWAIT_SIGNAL_DIRECTION,
    AWAIT_SIGNAL_LEVELS,
) = range(6)

# Temp storage for multi-step conversations
_pending: dict = {}


# ─── HELPERS ──────────────────────────────────────────────────────────────────

async def ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict:
    user_tg = update.effective_user
    user = await get_user(user_tg.id)
    if not user:
        user = await create_user(user_tg.id, user_tg.username or user_tg.first_name or "")
    return user


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def send_main_menu(update: Update, text: str = "القائمة الرئيسية:"):
    msg = update.message or update.callback_query.message
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="HTML")
    else:
        await msg.reply_text(text, reply_markup=main_menu_keyboard(), parse_mode="HTML")


# ─── START ────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update, context)
    await update.message.reply_text(WELCOME_MSG, reply_markup=main_menu_keyboard(), parse_mode="HTML")


# ─── CALLBACK ROUTER ──────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    user = await ensure_user(update, context)

    # ── Main menu ──
    if data == "main_menu":
        await query.edit_message_text("القائمة الرئيسية:", reply_markup=main_menu_keyboard(), parse_mode="HTML")

    # ── Balance ──
    elif data == "balance":
        await show_balance(update, context, user)

    # ── My trades ──
    elif data == "my_trades":
        await show_my_trades(update, context, user_id)

    # ── Recent signals ──
    elif data == "recent_signals":
        await show_recent_signals(update, context)

    # ── Settings ──
    elif data == "settings":
        await query.edit_message_text(SETTINGS_MSG, reply_markup=settings_keyboard(), parse_mode="HTML")

    elif data == "set_api_keys":
        context.user_data["state"] = AWAIT_API_KEYS
        await query.edit_message_text(API_KEY_INSTRUCTIONS, reply_markup=back_to_menu_keyboard(), parse_mode="HTML")

    elif data == "set_default_amount":
        context.user_data["state"] = AWAIT_DEFAULT_AMOUNT
        await query.edit_message_text(
            f"💵 <b>تغيير المبلغ الافتراضي</b>\n\nالمبلغ الحالي: <code>${user.get('default_amount', 10)}</code>\n\nأرسل المبلغ الجديد (USDT):",
            reply_markup=back_to_menu_keyboard(),
            parse_mode="HTML",
        )

    # ── Toggle auto trade ──
    elif data == "toggle_auto":
        new_val = not bool(user.get("auto_trade", False))
        await update_user(user_id, {"auto_trade": new_val})
        status = "✅ مفعّل" if new_val else "❌ معطّل"
        await query.edit_message_text(
            f"🤖 <b>التداول التلقائي: {status}</b>\n\nعند تفعيله سيتم تنفيذ الإشارات تلقائياً بالمبلغ الافتراضي.",
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML",
        )

    # ── Execute signal with preset amount ──
    elif data.startswith("exec_"):
        parts = data.split("_")
        signal_id = parts[1]
        amount = float(parts[2])
        await execute_signal_for_user(update, context, user, signal_id, amount)

    # ── Custom amount for signal ──
    elif data.startswith("custom_"):
        signal_id = data.split("_", 1)[1]
        context.user_data["state"] = AWAIT_CUSTOM_AMOUNT
        context.user_data["pending_signal_id"] = signal_id
        await query.edit_message_text(
            "✏️ أرسل المبلغ الذي تريد استثماره (USDT):",
            reply_markup=back_to_menu_keyboard(),
            parse_mode="HTML",
        )

    elif data == "skip_signal":
        await query.edit_message_text("⏭️ تم تخطي الإشارة.", reply_markup=main_menu_keyboard())

    # ── Trade detail ──
    elif data.startswith("trade_detail_"):
        trade_id = data.replace("trade_detail_", "")
        await show_trade_detail(update, context, trade_id)

    # ── Close trade (ask confirmation) ──
    elif data.startswith("close_trade_"):
        trade_id = data.replace("close_trade_", "")
        trade = await get_trade_by_id(trade_id)
        if not trade or trade["user_id"] != user_id:
            await query.edit_message_text("❌ الصفقة غير موجودة.")
            return
        await query.edit_message_text(
            f"⚠️ هل أنت متأكد من إغلاق صفقة <b>{trade['symbol']}</b>؟",
            reply_markup=confirm_close_keyboard(trade_id),
            parse_mode="HTML",
        )

    elif data.startswith("confirm_close_"):
        trade_id = data.replace("confirm_close_", "")
        await manual_close_trade(update, context, user, trade_id)

    # ── Send signal (admin) ──
    elif data == "send_signal":
        if not is_admin(user_id):
            await query.edit_message_text("❌ هذا الخيار للأدمن فقط.")
            return
        context.user_data["state"] = AWAIT_SIGNAL_SYMBOL
        await query.edit_message_text(SIGNAL_STEP1, reply_markup=back_to_menu_keyboard(), parse_mode="HTML")

    elif data in ("sig_dir_long", "sig_dir_short"):
        direction = "long" if data == "sig_dir_long" else "short"
        context.user_data["signal_direction"] = direction
        context.user_data["state"] = AWAIT_SIGNAL_LEVELS
        await query.edit_message_text(SIGNAL_STEP3, reply_markup=back_to_menu_keyboard(), parse_mode="HTML")


# ─── MESSAGE HANDLER ──────────────────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    user_id = update.effective_user.id
    text = update.message.text.strip()
    user = await ensure_user(update, context)

    if state == AWAIT_API_KEYS:
        await handle_api_keys_input(update, context, user_id, text)

    elif state == AWAIT_DEFAULT_AMOUNT:
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError
            await update_user(user_id, {"default_amount": amount})
            context.user_data.pop("state", None)
            await update.message.reply_text(
                f"✅ تم تحديث المبلغ الافتراضي إلى <code>${amount}</code>",
                reply_markup=main_menu_keyboard(),
                parse_mode="HTML",
            )
        except ValueError:
            await update.message.reply_text("❌ أرسل رقماً صحيحاً.")

    elif state == AWAIT_CUSTOM_AMOUNT:
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError
            signal_id = context.user_data.pop("pending_signal_id", None)
            context.user_data.pop("state", None)
            if signal_id:
                await execute_signal_for_user_msg(update, context, user, signal_id, amount)
            else:
                await update.message.reply_text("❌ انتهت صلاحية الإشارة.", reply_markup=main_menu_keyboard())
        except ValueError:
            await update.message.reply_text("❌ أرسل رقماً صحيحاً.")

    elif state == AWAIT_SIGNAL_SYMBOL:
        context.user_data["signal_symbol"] = text.upper()
        context.user_data["state"] = AWAIT_SIGNAL_DIRECTION
        await update.message.reply_text(SIGNAL_STEP2, reply_markup=signal_form_keyboard(), parse_mode="HTML")

    elif state == AWAIT_SIGNAL_LEVELS:
        await handle_signal_levels_input(update, context, user_id, text)

    else:
        await update.message.reply_text("استخدم القائمة أدناه:", reply_markup=main_menu_keyboard())


# ─── ACTION HANDLERS ──────────────────────────────────────────────────────────

async def handle_api_keys_input(update, context, user_id, text):
    parts = text.split("|")
    if len(parts) != 2:
        await update.message.reply_text(
            "❌ التنسيق خاطئ. أرسل: <code>API_KEY|API_SECRET</code>",
            parse_mode="HTML",
        )
        return
    api_key, api_secret = parts[0].strip(), parts[1].strip()
    msg = await update.message.reply_text("⏳ جاري التحقق من المفاتيح...")
    valid = await validate_api_keys(api_key, api_secret)
    if not valid:
        await msg.edit_text("❌ المفاتيح غير صحيحة. تحقق منها وحاول مجدداً.")
        return
    await update_user(user_id, {"mexc_api_key": api_key, "mexc_api_secret": api_secret})
    context.user_data.pop("state", None)
    await msg.edit_text("✅ تم حفظ مفاتيح API بنجاح!", reply_markup=main_menu_keyboard())


async def handle_signal_levels_input(update, context, user_id, text):
    symbol = context.user_data.get("signal_symbol", "")
    direction = context.user_data.get("signal_direction", "long")

    entry = tp = sl = None
    if text.lower() != "skip":
        parts = text.split("|")
        try:
            if len(parts) >= 1 and parts[0]:
                entry = float(parts[0])
            if len(parts) >= 2 and parts[1]:
                tp = float(parts[1])
            if len(parts) >= 3 and parts[2]:
                sl = float(parts[2])
        except ValueError:
            await update.message.reply_text("❌ التنسيق خاطئ. مثال: <code>45000|47000|44000</code>", parse_mode="HTML")
            return

    signal = Signal(
        symbol=symbol,
        direction=direction,
        entry_price=entry,
        take_profit=tp,
        stop_loss=sl,
    )
    saved = await save_signal(signal.to_dict())
    signal_id = saved.get("id", str(uuid.uuid4()))

    context.user_data.pop("state", None)
    context.user_data.pop("signal_symbol", None)
    context.user_data.pop("signal_direction", None)

    # Broadcast to all active users
    await update.message.reply_text("✅ تم حفظ الإشارة وجاري الإرسال للمشتركين...")
    await broadcast_signal(update.get_bot(), signal, signal_id)


async def broadcast_signal(bot, signal: Signal, signal_id: str):
    users = await get_all_active_users()
    text = signal.format_message()
    keyboard = amount_selection_keyboard(signal_id)

    for user in users:
        try:
            # Auto-trade users → execute immediately
            if user.get("auto_trade") and user.get("mexc_api_key"):
                amount = float(user.get("default_amount", 10))
                try:
                    result = await place_buy_order(
                        api_key=user["mexc_api_key"],
                        api_secret=user["mexc_api_secret"],
                        symbol=signal.normalize_symbol(),
                        usdt_amount=amount,
                    )
                    trade = {
                        "user_id": user["id"],
                        "symbol": signal.normalize_symbol(),
                        "side": signal.side(),
                        "entry_price": result["entry_price"],
                        "amount": amount,
                        "quantity": result["quantity"],
                        "take_profit": signal.take_profit,
                        "stop_loss": signal.stop_loss,
                        "status": "open",
                        "order_id": result["order_id"],
                        "signal_id": signal_id,
                    }
                    await save_trade(trade)
                    msg = (
                        f"🤖 <b>تنفيذ تلقائي!</b>\n\n"
                        + signal.format_message()
                        + f"\n\n✅ تم شراء بمبلغ <code>${amount}</code>\n"
                        f"💰 سعر الدخول: <code>{result['entry_price']}</code>"
                    )
                    await bot.send_message(chat_id=user["id"], text=msg, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Auto-trade failed for user {user['id']}: {e}")
                    await bot.send_message(
                        chat_id=user["id"],
                        text=text + "\n\n⚠️ فشل التنفيذ التلقائي. يمكنك التنفيذ يدوياً.",
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
            else:
                await bot.send_message(
                    chat_id=user["id"],
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
        except Exception as e:
            logger.warning(f"Failed to send signal to user {user['id']}: {e}")


async def execute_signal_for_user(update: Update, context, user: dict, signal_id: str, amount: float):
    query = update.callback_query
    if not user.get("mexc_api_key"):
        await query.edit_message_text(
            "❌ لم تقم بإضافة مفاتيح API بعد.\nاذهب إلى ⚙️ الإعدادات لإضافتها.",
            reply_markup=settings_keyboard(),
        )
        return

    # Find the signal
    signals = await get_recent_signals(50)
    signal_data = next((s for s in signals if str(s.get("id")) == signal_id), None)
    if not signal_data:
        await query.edit_message_text("❌ لم يتم العثور على الإشارة.", reply_markup=main_menu_keyboard())
        return

    await query.edit_message_text(f"⏳ جاري تنفيذ الصفقة بمبلغ <code>${amount}</code>...", parse_mode="HTML")

    try:
        result = await place_buy_order(
            api_key=user["mexc_api_key"],
            api_secret=user["mexc_api_secret"],
            symbol=signal_data["symbol"],
            usdt_amount=amount,
        )
        trade = {
            "user_id": user["id"],
            "symbol": signal_data["symbol"],
            "side": "buy" if signal_data["direction"] == "long" else "sell",
            "entry_price": result["entry_price"],
            "amount": amount,
            "quantity": result["quantity"],
            "take_profit": signal_data.get("take_profit"),
            "stop_loss": signal_data.get("stop_loss"),
            "status": "open",
            "order_id": result["order_id"],
            "signal_id": signal_id,
        }
        saved = await save_trade(trade)
        trade_id = saved.get("id", "")

        msg = (
            f"✅ <b>تم تنفيذ الصفقة بنجاح!</b>\n\n"
            f"🪙 <b>العملة:</b> {signal_data['symbol']}\n"
            f"💵 <b>المبلغ:</b> <code>${amount}</code>\n"
            f"📥 <b>سعر الدخول:</b> <code>{result['entry_price']}</code>\n"
            f"📦 <b>الكمية:</b> <code>{result['quantity']:.6f}</code>\n"
        )
        if signal_data.get("take_profit"):
            msg += f"🎯 <b>TP:</b> <code>{signal_data['take_profit']}</code>\n"
        if signal_data.get("stop_loss"):
            msg += f"🛑 <b>SL:</b> <code>{signal_data['stop_loss']}</code>\n"
        msg += "\n🔄 البوت يراقب الصفقة تلقائياً."

        await query.edit_message_text(msg, reply_markup=trade_action_keyboard(trade_id), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Trade execution error: {e}")
        await query.edit_message_text(
            f"❌ فشل تنفيذ الصفقة:\n<code>{str(e)[:200]}</code>",
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML",
        )


async def execute_signal_for_user_msg(update: Update, context, user: dict, signal_id: str, amount: float):
    """Same as above but triggered from a text message (custom amount)."""
    if not user.get("mexc_api_key"):
        await update.message.reply_text(
            "❌ لم تقم بإضافة مفاتيح API.\nاذهب إلى ⚙️ الإعدادات.",
            reply_markup=settings_keyboard(),
        )
        return

    signals = await get_recent_signals(50)
    signal_data = next((s for s in signals if str(s.get("id")) == signal_id), None)
    if not signal_data:
        await update.message.reply_text("❌ انتهت صلاحية الإشارة.", reply_markup=main_menu_keyboard())
        return

    msg_obj = await update.message.reply_text(f"⏳ جاري تنفيذ الصفقة بمبلغ <code>${amount}</code>...", parse_mode="HTML")
    try:
        result = await place_buy_order(
            api_key=user["mexc_api_key"],
            api_secret=user["mexc_api_secret"],
            symbol=signal_data["symbol"],
            usdt_amount=amount,
        )
        trade = {
            "user_id": user["id"],
            "symbol": signal_data["symbol"],
            "side": "buy",
            "entry_price": result["entry_price"],
            "amount": amount,
            "quantity": result["quantity"],
            "take_profit": signal_data.get("take_profit"),
            "stop_loss": signal_data.get("stop_loss"),
            "status": "open",
            "order_id": result["order_id"],
            "signal_id": signal_id,
        }
        saved = await save_trade(trade)
        trade_id = saved.get("id", "")
        reply = (
            f"✅ <b>تم تنفيذ الصفقة!</b>\n\n"
            f"🪙 {signal_data['symbol']} | 💵 ${amount}\n"
            f"📥 سعر الدخول: <code>{result['entry_price']}</code>"
        )
        await msg_obj.edit_text(reply, reply_markup=trade_action_keyboard(trade_id), parse_mode="HTML")
    except Exception as e:
        await msg_obj.edit_text(f"❌ فشل: <code>{str(e)[:200]}</code>", parse_mode="HTML", reply_markup=main_menu_keyboard())


# ─── DISPLAY HANDLERS ─────────────────────────────────────────────────────────

async def show_balance(update: Update, context, user: dict):
    query = update.callback_query
    if not user.get("mexc_api_key"):
        await query.edit_message_text("❌ أضف مفاتيح API أولاً.", reply_markup=settings_keyboard())
        return
    await query.edit_message_text("⏳ جاري جلب الرصيد...")
    try:
        bal = await get_balance(user["mexc_api_key"], user["mexc_api_secret"])
        msg = (
            f"💰 <b>رصيدك على MEXC</b>\n\n"
            f"🟢 المتاح: <code>{bal['free']:.4f} USDT</code>\n"
            f"🔒 المحجوز: <code>{bal['used']:.4f} USDT</code>\n"
            f"📊 الإجمالي: <code>{bal['total']:.4f} USDT</code>"
        )
        await query.edit_message_text(msg, reply_markup=back_to_menu_keyboard(), parse_mode="HTML")
    except Exception as e:
        await query.edit_message_text(f"❌ فشل جلب الرصيد:\n<code>{e}</code>", reply_markup=back_to_menu_keyboard(), parse_mode="HTML")


async def show_my_trades(update: Update, context, user_id: int):
    query = update.callback_query
    open_trades = await get_open_trades(user_id)
    history = await get_trade_history(user_id, 5)

    if not open_trades and not history:
        await query.edit_message_text("📊 لا توجد صفقات بعد.", reply_markup=back_to_menu_keyboard())
        return

    msg = "📊 <b>صفقاتي</b>\n\n"
    if open_trades:
        msg += f"🟢 <b>مفتوحة ({len(open_trades)}):</b>\n"
        for t in open_trades:
            msg += f"• {t['symbol']} | دخول: <code>{t['entry_price']}</code> | ${t['amount']}\n"
    if history:
        msg += f"\n📜 <b>التاريخ (آخر {len(history)}):</b>\n"
        for t in history:
            pnl = t.get("pnl", 0) or 0
            emoji = "🟢" if float(pnl) >= 0 else "🔴"
            msg += f"• {t['symbol']} | {emoji} {float(pnl):+.2f} USDT\n"

    # Build inline keyboard for open trades
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    buttons = [[InlineKeyboardButton(f"📋 {t['symbol']}", callback_data=f"trade_detail_{t['id']}")] for t in open_trades]
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")


async def show_trade_detail(update: Update, context, trade_id: str):
    query = update.callback_query
    trade = await get_trade_by_id(trade_id)
    if not trade:
        await query.edit_message_text("❌ الصفقة غير موجودة.", reply_markup=back_to_menu_keyboard())
        return

    try:
        current_price = await get_ticker_price(trade["symbol"])
        entry = float(trade["entry_price"])
        qty = float(trade["quantity"])
        unrealized_pnl = (current_price - entry) * qty
        pnl_emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
    except Exception:
        current_price = "N/A"
        unrealized_pnl = None
        pnl_emoji = ""

    msg = (
        f"📊 <b>تفاصيل الصفقة</b>\n\n"
        f"🪙 <b>العملة:</b> {trade['symbol']}\n"
        f"📥 <b>سعر الدخول:</b> <code>{trade['entry_price']}</code>\n"
        f"📦 <b>الكمية:</b> <code>{trade['quantity']}</code>\n"
        f"💵 <b>المبلغ:</b> <code>${trade['amount']}</code>\n"
    )
    if trade.get("take_profit"):
        msg += f"🎯 <b>TP:</b> <code>{trade['take_profit']}</code>\n"
    if trade.get("stop_loss"):
        msg += f"🛑 <b>SL:</b> <code>{trade['stop_loss']}</code>\n"
    msg += f"\n💹 <b>السعر الحالي:</b> <code>{current_price}</code>\n"
    if unrealized_pnl is not None:
        msg += f"{pnl_emoji} <b>P&L غير المحقق:</b> <code>{unrealized_pnl:+.4f} USDT</code>"

    await query.edit_message_text(msg, reply_markup=trade_action_keyboard(trade_id), parse_mode="HTML")


async def show_recent_signals(update: Update, context):
    query = update.callback_query
    signals = await get_recent_signals(10)
    if not signals:
        await query.edit_message_text("📈 لا توجد إشارات بعد.", reply_markup=back_to_menu_keyboard())
        return

    msg = "📈 <b>آخر الإشارات:</b>\n\n"
    for s in signals:
        direction_emoji = "🟢" if s.get("direction") == "long" else "🔴"
        msg += (
            f"{direction_emoji} <b>{s['symbol']}</b> | "
            f"{'LONG' if s.get('direction') == 'long' else 'SHORT'}\n"
        )
        if s.get("entry_price"):
            msg += f"   دخول: <code>{s['entry_price']}</code>"
        if s.get("take_profit"):
            msg += f" | TP: <code>{s['take_profit']}</code>"
        if s.get("stop_loss"):
            msg += f" | SL: <code>{s['stop_loss']}</code>"
        msg += "\n\n"

    await query.edit_message_text(msg, reply_markup=back_to_menu_keyboard(), parse_mode="HTML")


async def manual_close_trade(update: Update, context, user: dict, trade_id: str):
    query = update.callback_query
    trade = await get_trade_by_id(trade_id)
    if not trade or trade["user_id"] != user["id"]:
        await query.edit_message_text("❌ الصفقة غير موجودة.", reply_markup=back_to_menu_keyboard())
        return

    await query.edit_message_text("⏳ جاري إغلاق الصفقة...")
    try:
        current_price = await get_ticker_price(trade["symbol"])
        closed = await close_trade_on_exchange(trade, current_price, "manual")
        pnl = closed.get("pnl", 0)
        pnl_emoji = "🟢" if float(pnl) >= 0 else "🔴"
        msg = (
            f"✅ <b>تم إغلاق الصفقة يدوياً</b>\n\n"
            f"🪙 {trade['symbol']}\n"
            f"📥 دخول: <code>{trade['entry_price']}</code>\n"
            f"📤 خروج: <code>{current_price:.6f}</code>\n"
            f"{pnl_emoji} P&L: <code>{float(pnl):+.4f} USDT</code>"
        )
        await query.edit_message_text(msg, reply_markup=back_to_menu_keyboard(), parse_mode="HTML")
    except Exception as e:
        await query.edit_message_text(
            f"❌ فشل الإغلاق:\n<code>{str(e)[:200]}</code>",
            reply_markup=trade_action_keyboard(trade_id),
            parse_mode="HTML",
        )


# ─── REGISTER HANDLERS ────────────────────────────────────────────────────────

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
