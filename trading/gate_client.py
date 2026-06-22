async def get_balance(api_key: str, api_secret: str) -> dict:
    """جلب رصيد USDT من Gate.io"""
    async with aiohttp.ClientSession() as s:
        try:
            data = await _signed_request(s, api_key, api_secret, "GET", "/spot/accounts")
        except Exception as e:
            logger.error(f"Gate balance error: {e}")
            raise
    
    # البحث عن USDT
    usdt = None
    for b in data:
        if b.get("currency") == "USDT":
            usdt = b
            break
    
    if not usdt:
        return {"free": 0.0, "used": 0.0, "total": 0.0}
    
    free = float(usdt.get("available", 0))
    locked = float(usdt.get("locked", 0))
    return {"free": free, "used": locked, "total": free + locked}