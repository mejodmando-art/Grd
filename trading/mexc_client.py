async def get_top_symbols(count: int = 300) -> list:
    """جلب أعلى العملات من حيث حجم التداول خلال 24 ساعة"""
    async with aiohttp.ClientSession() as s:
        # جلب جميع الأسعار
        prices = await _get(s, "/api/v3/ticker/price", {})
        # جلب جميع إحصائيات 24 ساعة
        stats = await _get(s, "/api/v3/ticker/24hr", {})
        
    # دمج البيانات وتصفية أزواج USDT فقط
    symbols = []
    for stat in stats:
        symbol = stat.get("symbol", "")
        if symbol.endswith("USDT"):
            try:
                volume = float(stat.get("quoteVolume", 0))
                symbols.append({
                    "symbol": symbol,
                    "volume": volume
                })
            except:
                continue
    
    # ترتيب حسب الحجم وأخذ أعلى count
    symbols.sort(key=lambda x: x["volume"], reverse=True)
    return [s["symbol"] for s in symbols[:count]]