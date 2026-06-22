async def get_klines(symbol: str, interval: str = "15m", limit: int = 60) -> list:
    """جلب بيانات الشموع من MEXC"""
    sym = _normalize(symbol)
    async with aiohttp.ClientSession() as s:
        data = await _get(s, "/api/v3/klines", {
            "symbol": sym,
            "interval": interval,
            "limit": limit
        })
    # تحويل البيانات إلى قائمة قواميس
    candles = []
    for k in data:
        candles.append({
            "open_time": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        })
    return candles
