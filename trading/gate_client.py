async def get_balance(*a):
    b = _client().fetch_balance()
    all_coins = []
    total_value = 0.0
    for coin, data in b.items():
        if data['free'] > 0 or data['used'] > 0:
            # الحصول على سعر العملة مقابل USDT
            try:
                if coin == 'USDT':
                    price = 1.0
                else:
                    ticker = _client().fetch_ticker(f"{coin}/USDT")
                    price = ticker['last']
            except:
                price = 0.0
            value = (data['free'] + data['used']) * price
            total_value += value
            all_coins.append({
                'coin': coin,
                'free': data['free'],
                'used': data['used'],
                'total': data['total'],
                'price': price,
                'value': value
            })
    # ترتيب حسب القيمة تنازلياً
    all_coins.sort(key=lambda x: x['value'], reverse=True)
    return {'all_coins': all_coins, 'total_value': total_value}