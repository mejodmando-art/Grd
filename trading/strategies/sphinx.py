"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  🤖 SPHINX STRATEGY v1.0                                                      ║
║  Smart Price-action Hybrid INtegrated eXecution                              ║
║  ابتكار خاص — استراتيجية السيولة الذكية                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

المنطق:
1.  يحدد الترند القوي على فريم 15 دقيقة (EMA 21 > 55)
2.  يراقب "مسح السيولة" (Liquidity Sweep) — هبوط مفاجئ تحت أدنى قاع حديث
    ثم إغلاق فوقه = إشارة أن الحيتان جمعت مراكز
3.  يتحقق من تباعد الزخم الإيجابي (RSI Divergence)
4.  يدخل شراء سوقي فوراً على شمعة الإغلاق
5.  SL ديناميكي: أسفل القاع بـ 1x ATR
6.  TP ديناميكي: 2.5x المخاطرة (Risk/Reward = 1:2.5)

مميزاتها:
• لا تتداول إلا مع "السمارت ماني" (Smart Money)
• SL واسع نسبياً لكن دقيق — يتجنب الإيقافات المبكرة
• TP سخي — تستهدف 2.5x
• تتجنب العملات الميتة (Volume > 1.5x المتوسط)
"""

import logging
from typing import Optional, Dict

logger = logging.getLogger("SphinxStrategy")


def ema(values, period):
    """حساب EMA"""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    ema_vals = [sum(values[:period]) / period]
    for price in values[period:]:
        ema_vals.append(price * k + ema_vals[-1] * (1 - k))
    return [None] * (period - 1) + ema_vals


def atr(highs, lows, closes, period=14):
    """حساب Average True Range"""
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs)
    atr_val = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr_val = (atr_val * (period - 1) + tr) / period
    return atr_val


def rsi(closes, period=14):
    """حساب RSI"""
    if len(closes) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi_vals = [None] * period

    if avg_loss == 0:
        rsi_vals.append(100)
    else:
        rs = avg_gain / avg_loss
        rsi_vals.append(100 - (100 / (1 + rs)))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_vals.append(100)
        else:
            rs = avg_gain / avg_loss
            rsi_vals.append(100 - (100 / (1 + rs)))
    return rsi_vals


async def analyze_sphinx(symbol, get_klines_func):
    """
    تحليل استراتيجية SPHINX

    Args:
        symbol: اسم العملة
        get_klines_func: دالة async ترجع شموع (signature: await get_klines(symbol, interval, limit))

    Returns:
        dict أو None
    """
    try:
        # ─── جلب شموع 15 دقيقة (للترند والسيولة) ─────────────────────────────
        kl_15m = await get_klines_func(symbol, "15m", 80)
        if len(kl_15m) < 60:
            return None

        cl_15 = [c["close"] for c in kl_15m]
        hi_15 = [c["high"] for c in kl_15m]
        lo_15 = [c["low"] for c in kl_15m]
        vl_15 = [c["volume"] for c in kl_15m]

        # ─── 1. فلتر الترند: EMA 21 > EMA 55 على 15m ──────────────────────────
        ema21_15 = ema(cl_15, 21)
        ema55_15 = ema(cl_15, 55)
        if not ema21_15 or not ema55_15 or ema21_15[-1] is None or ema55_15[-1] is None:
            return None
        if ema21_15[-1] <= ema55_15[-1]:
            return None  # الترند هابط أو جانبي — لا نتداول

        # ─── 2. مسح السيولة (Liquidity Sweep) ────────────────────────────────
        # نبحث عن آخر 20 شمعة: هل السعر هبط تحت أدنى قاع حديث ثم أغلق فوقه؟
        recent_lows = [lo_15[i] for i in range(-25, -5)]  # 20 شمعة قبل الأخيرة
        if not recent_lows:
            return None
        recent_low = min(recent_lows)

        # الشمعة الأخيرة (الحالية)
        last_idx = -1
        last_low = lo_15[last_idx]
        last_close = cl_15[last_idx]
        last_open = cl_15[last_idx-1] if len(cl_15) > 1 else last_close  # تقريبي

        # هل "الظل السفلي" كسر القاع الحديث؟
        wick_broke = last_low < recent_low * 0.998  # تحت القاع بـ 0.2%
        # هل الإغلاق فوق القاع؟
        closed_above = last_close > recent_low

        if not (wick_broke and closed_above):
            return None

        # ─── 3. تأكيد الحجم: الحجم > 1.5x المتوسط ────────────────────────────
        avg_vol = sum(vl_15[-20:-1]) / 19
        if vl_15[-1] < avg_vol * 1.5:
            return None

        # ─── 4. تباعد الزخم (RSI Divergence) ───────────────────────────────
        # نبحث عن: السعر عمل قاع أدنى، لكن RSI عمل قاع أعلى
        rsi_vals = rsi(cl_15, 14)
        if len(rsi_vals) < 30 or rsi_vals[-1] is None:
            return None

        # قارن آخر 3 قيعان في السعر مع قيعان RSI
        price_lows_idx = []
        for i in range(-15, -2):
            if lo_15[i] < lo_15[i-1] and lo_15[i] < lo_15[i+1]:
                price_lows_idx.append(i)

        if len(price_lows_idx) < 2:
            return None

        # آخر قاعين
        pl1, pl2 = price_lows_idx[-2], price_lows_idx[-1]
        price_lower_low = lo_15[pl2] < lo_15[pl1]

        rsi_pl1 = rsi_vals[pl1] if pl1 < len(rsi_vals) and rsi_vals[pl1] is not None else 50
        rsi_pl2 = rsi_vals[pl2] if pl2 < len(rsi_vals) and rsi_vals[pl2] is not None else 50
        rsi_higher_low = rsi_pl2 > rsi_pl1

        if not (price_lower_low and rsi_higher_low):
            return None  # لا يوجد تباعد

        # ─── 5. حساب SL و TP ديناميكي باستخدام ATR ─────────────────────────
        atr_val = atr(hi_15, lo_15, cl_15, 14)
        if atr_val <= 0:
            atr_val = last_close * 0.02  # fallback 2%

        entry = last_close
        sl = recent_low - (atr_val * 1.0)  # أسفل القاع بـ 1x ATR
        risk = entry - sl
        if risk <= 0:
            return None

        tp = entry + (risk * 2.5)  # Reward = 2.5x Risk

        # ─── 6. فلاتر نهائية ───────────────────────────────────────────────
        # SL لا يتجاوز 4% من السعر
        if risk / entry > 0.04:
            return None

        # RSI لا يكون في منطقة ذروة الشراء (>70)
        if rsi_vals[-1] > 65:
            return None

        logger.info(f"🦁 SPHINX Signal: {symbol} | Entry: {entry:.6f} | SL: {sl:.6f} | TP: {tp:.6f} | RR: 1:2.5")

        return {
            "symbol": symbol,
            "entry_price": round(entry, 8),
            "take_profit": round(tp, 8),
            "stop_loss": round(sl, 8),
            "strategy": "SPHINX",
            "rr_ratio": "1:2.5",
            "sweep_detected": True,
            "divergence": True,
            "atr": round(atr_val, 6)
        }

    except Exception as e:
        logger.error(f"Sphinx analysis error for {symbol}: {e}")
        return None
