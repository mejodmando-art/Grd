import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters,
)
from config import ADMIN_IDS
from database.client import get_user, create_user, update_user, get_open_trades, get_trade_history
from trading.mexc_client import get_balance as mexc_balance
from trading.gate_client import get_balance as gate_balance

logger = logging.getLogger(__name__)

AWAIT_EMA_AMOUNT = 0
AWAIT_HARPOON_AMOUNT = 1


async def ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict:
    user_tg = update.effective_user
    user = await get_user(user_tg.id)
    if not user:
        user = await create_user(user_tg.id, user_tg.username or user_tg.first_name or "")
    return user


async def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 رصيدي", callback_data="balance"),
         InlineKeyboardButton("📊 صفقاتي", callback_data="my_trades")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
        [InlineKeyboardButton("🏦 اختيار المنصة", callback_data="exchange")],
    ])


async def settings_keyboard(user: dict):
    ema_status = "✅" if user.get("ema_trade", True) else "❌"
    harpoon_status = "✅" if user.get("harpoon_trade", True) else "❌"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🤖 EMA: {ema_status}", callback_data="toggle_ema")],
        [InlineKeyboardButton(f"🎯 هاربون: {harpoon_status}", callback_data="toggle_harpoon")],
        [InlineKeyboardButton("💵 مبلغ EMA", callback_data="set_ema_amount")],
        [InlineKeyboardButton("💵 مبلغ هاربون", callback_data="set_harpoon_amount")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
    ])


def exchange_keyboard(user: dict):
    current = user.get("exchange", "mexc")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"MEXC {'✅' if current == 'mexc' else ''}", callback_data="ex_mexc")],
        [InlineKeyboardButton(f"Gate.io {'✅' if current == 'gate' else ''}", callback_data="ex_gate")],
        [InlineKeyboardButton(f"المنصتين {'✅' if current == 'both' else ''}", callback_data="ex_both")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
    ])


WELCOME_MSG = "🤖 <b>بوت التداول الآلي المتقدم</b>\n\nاختر من القائمة:"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update, context)
    await update.message.reply_text(WELCOME_MSG, reply_markup=await main_menu_keyboard(), parse_mode="HTML")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    user = await ensure_user(update, context)

    if data == "main_menu":
        await query.edit_message_text("القائمة الرئيسية:", reply_markup=await main_menu_keyboard(), parse_mode="HTML")

    elif data == "balance":
        exchange = user.get("exchange", "mexc")
        msg = "💰 <b>الرصيد</b>\n\n"

        if exchange in ["mexc", "both"]:
            api_key = os.getenv("MEXC_API_KEY", "")
            api_secret = os.getenv("MEXC_API_SECRET", "")
            if api_key:
                try:
                    bal = await mexc_balance(api_key, api_secret)
                    msg += f"🔵 <b>MEXC:</b> <code>{bal['free']:.2f} USDT</code>\n"
                except:
                    msg += f"🔵 <b>MEXC:</b> ❌ فشل\n"

        if exchange in ["gate", "both"]:
            api_key = os.getenv("GATE_API_KEY", "")
            api_secret = os.getenv("GATE_API_SECRET", "")
            if api_key:
                try:
                    bal = await gate_balance(api_key, api_secret)
                    msg += f"🟢 <b>Gate.io:</b> <code>{bal['free']:.2f} USDT</code>\n"
                except:
                    msg += f"🟢 <b>Gate.io:</b> ❌ فشل\n"

        if "MEXC" not in msg and "Gate" not in msg:
            msg += "❌ لا توجد مفاتيح API."
        await query.edit_message_text(msg, reply_markup=await main_menu_keyboard(), parse_mode="HTML")

    elif data == "exchange":
        await query.edit_message_text("🏦 <b>اختر منصة التداول:</b>", reply_markup=exchange_keyboard(user), parse_mode="HTML")

    elif data == "ex_mexc":
        await update_user(user_id, {"exchange": "mexc"})
        user = await get_user(user_id)
        await query.edit_message_text("✅ تم التبديل إلى <b>MEXC</b>", reply_markup=exchange_keyboard(user), parse_mode="HTML")

    elif data == "ex_gate":
        await update_user(user_id, {"exchange": "gate"})
        user = await get_user(user_id)
        await query.edit_message_text("✅ تم التبديل إلى <b>Gate.io</b>", reply_markup=exchange_keyboard(user), parse_mode="HTML")

    elif data == "ex_both":
        await update_user(user_id, {"exchange": "both"})
        user = await get_user(user_id)
        await query.edit_message_text("✅ تم التبديل إلى <b>المنصتين معاً</b>", reply_markup=exchange_keyboard(user), parse_mode="HTML")

    elif data == "my_trades":
        open_trades = await get_open_trades(user_id)
        history = await get_trade_history(user_id, 5)
        if not open_trades and not history:
            await query.edit_message_text("📊 لا توجد صفقات.", reply_markup=await main_menu_keyboard())
            return
        msg = "📊 <b>صفقاتي</b>\n\n"
        if open_trades:
            msg += f"🟢 <b>مفتوحة:</b>\n"
            for t in open_trades:
                strategy = t.get("strategy", "EMA")
                exchange = t.get("exchange", "MEXC")
                msg += f"• [{exchange}] [{strategy}] {t['symbol']} | ${t['amount']}\n"
        if history:
            msg += f"\n📜 <b>آخر الصفقات:</b>\n"
            for t in history:
                pnl = t.get("pnl", 0) or 0
                emoji = "🟢" if float(pnl) >= 0 else "🔴"
                strategy = t.get("strategy", "EMA")
                exchange = t.get("exchange", "MEXC")
                msg += f"• [{exchange}] [{strategy}] {t['symbol']} | {emoji} {float(pnl):+.2f} USDT\n"
        await query.edit_message_text(msg, reply_markup=await main_menu_keyboard(), parse_mode="HTML")

    elif data == "settings":
        ema_status = "مفعّل ✅" if user.get("ema_trade", True) else "معطّل ❌"
        harpoon_status = "مفعّل ✅" if user.get("harpoon_trade", True) else "معطّل ❌"
        exchange = user.get("exchange", "mexc").upper()
        msg = f"⚙️ <b>الإعدادات</b>\n\n🏦 المنصة: {exchange}\n🤖 EMA: {ema_status}\n🎯 هاربون: {harpoon_status}\n💵 EMA: ${user.get('ema_amount', 10)}\n💵 هاربون: ${user.get('harpoon_amount', 10)}"
        await query.edit_message_text(msg, reply_markup=await settings_keyboard(user), parse_mode="HTML")

    elif data == "toggle_ema":
        new_val = not bool(user.get("ema_trade", True))
        await update_user(user_id, {"ema_trade": new_val})
        user = await get_user(user_id)
        ema_status = "مفعّل ✅" if user.get("ema_trade", True) else "معطّل ❌"
        harpoon_status = "مفعّل ✅" if user.get("harpoon_trade", True) else "معطّل ❌"
        exchange = user.get("exchange", "mexc").upper()
        msg = f"⚙️ <b>الإعدادات</b>\n\n🏦 المنصة: {exchange}\n🤖 EMA: {ema_status}\n🎯 هاربون: {harpoon_status}\n💵 EMA: ${user.get('ema_amount', 10)}\n💵 هاربون: ${user.get('harpoon_amount', 10)}"
        await query.edit_message_text(msg, reply_markup=await settings_keyboard(user), parse_mode="HTML")

    elif data == "toggle_harpoon":
        new_val = not bool(user.get("harpoon_trade", True))
        await update_user(user_id, {"harpoon_trade": new_val})
        user = await get_user(user_id)
        ema_status = "مفعّل ✅" if user.get("ema_trade", True) else "معطّل ❌"
        harpoon_status = "مفعّل ✅" if user.get("harpoon_trade", True) else "معطّل ❌"
        exchange = user.get("exchange", "mexc").upper()
        msg = f"⚙️ <b>الإعدادات</b>\n\n🏦 المنصة: {exchange}\n🤖 EMA: {ema_status}\n🎯 هاربون: {harpoon_status}\n💵 EMA: ${user.get('ema_amount', 10)}\n💵 هاربون: ${user.get('harpoon_amount', 10)}"
        await query.edit_message_text(msg, reply_markup=await settings_keyboard(user), parse_mode="HTML")

    elif data == "set_ema_amount":
        context.user_data["state"] = AWAIT_EMA_AMOUNT
        await query.edit_message_text(
            f"💵 المبلغ الحالي لـ EMA: <code>${user.get('ema_amount', 10)}</code>\n\nأرسل المبلغ الجديد (USDT):",
            reply_markup=await main_menu_keyboard(),
            parse_mode="HTML",
        )

    elif data == "set_harpoon_amount":
        context.user_data["state"] = AWAIT_HARPOON_AMOUNT
        await query.edit_message_text(
            f"💵 المبلغ الحالي للهاربون: <code>${user.get('harpoon_amount', 10)}</code>\n\nأرسل المبلغ الجديد (USDT):",
            reply_markup=await main_menu_keyboard(),
            parse_mode="HTML",
        )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if state == AWAIT_EMA_AMOUNT:
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError
            await update_user(user_id, {"ema_amount": amount})
            context.user_data.pop("state", None)
            await update.message.reply_text(f"✅ تم تحديث مبلغ EMA إلى <code>${amount}</code>", reply_markup=await main_menu_keyboard(), parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ أرسل رقماً صحيحاً.")

    elif state == AWAIT_HARPOON_AMOUNT:
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError
            await update_user(user_id, {"harpoon_amount": amount})
            context.user_data.pop("state", None)
            await update.message.reply_text(f"✅ تم تحديث مبلغ الهاربون إلى <code>${amount}</code>", reply_markup=await main_menu_keyboard(), parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ أرسل رقماً صحيحاً.")

    else:
        await update.message.reply_text("استخدم القائمة:", reply_markup=await main_menu_keyboard())


def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))