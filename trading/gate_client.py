import asyncio
import ccxt
import os
import logging
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# Cache clients to avoid creating new connections every request
_clients = {}


def _client(api_key: str = "", api_secret: str = "") -> ccxt.Exchange:
    """Get cached Gate.io client or create new one."""
    key = f"{api_key or os.getenv('GATE_API_KEY', '')}:{api_secret or os.getenv('GATE_API_SECRET', '')}"
    if key not in _clients or not _clients[key]:
        _clients[key] = ccxt.gate({
            'apiKey': api_key or os.getenv('GATE_API_KEY', ''),
            'secret': api_secret or os.getenv('GATE_API_SECRET', ''),
            'options': {'defaultType': 'spot'},
            'enableRateLimit': True,
            'rateLimit': 200,
        })
    return _clients[key]


def _normalize(symbol: str) -> str:
    """Normalize symbol to CCXT format: BTC/USDT"""
    if '/' in symbol:
        return symbol.upper()
    for quote in ['USDT', 'BTC', 'ETH', 'USD', 'USDC']:
        if symbol.upper().endswith(quote):
            return symbol.upper()[:-len(quote)] + '/' + quote
    return symbol.upper()


# ─── المحفظة ───────────────────────────────────────────────────

def _fetch_balance_sync(api_key: str = "", api_secret: str = "") -> dict:
    """Fetch balance with all coin values in USDT."""
    try:
        exchange = _client(api_key, api_secret)
        balance = exchange.fetch_balance()
        total_value = 0.0
        all_coins = []

        # Fetch all tickers at once to avoid rate limits
        all_tickers = exchange.fetch_tickers()

        currencies = balance.get('total', {})
        for coin, amount in currencies.items():
            if amount > 0:
                free = balance.get('free', {}).get(coin, 0)
                used = balance.get('used', {}).get(coin, 0)

                if coin == 'USDT':
                    price = 1.0
                else:
                    ticker = all_tickers.get(f"{coin}/USDT", {})
                    price = ticker.get('last', 0.0) or 0.0

                value = amount * price
                total_value += value
                all_coins.append({
                    'coin': coin,
                    'free': free,
                    'used': used,
                    'total': amount,
                    'price': price,
                    'value': value
                })

        all_coins.sort(key=lambda x: x['value'], reverse=True)
        return {'all_coins': all_coins, 'total_value': total_value}

    except ccxt.NetworkError as e:
        logger.warning(f"Network error fetching balance: {e}")
        raise
    except ccxt.ExchangeError as e:
        logger.error(f"Exchange error fetching balance: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching balance: {e}")
        raise


async def get_balance(api_key: str = "", api_secret: str = "") -> dict:
    """Async wrapper for get_balance."""
    return await asyncio.to_thread(_fetch_balance_sync, api_key, api_secret)


# ─── الأسعار ──────────────────────────────────────────────────

def _fetch_price_sync(api_key: str, api_secret: str, symbol: str) -> float:
    """Fetch current price for a symbol."""
    try:
        return _client(api_key, api_secret).fetch_ticker(_normalize(symbol))['last']
    except ccxt.NetworkError as e:
        logger.warning(f"Network error fetching price for {symbol}: {e}")
        raise
    except ccxt.ExchangeError as e:
        logger.error(f"Exchange error fetching price for {symbol}: {e}")
        raise


async def get_ticker_price(symbol: str, api_key: str = "", api_secret: str = "") -> float:
    """Async wrapper for get_ticker_price."""
    return await asyncio.to_thread(_fetch_price_sync, api_key, api_secret, symbol)


# ─── الأوامر ──────────────────────────────────────────────────

def _place_buy_sync(api_key: str, api_secret: str, symbol: str, usdt_amount: float) -> dict:
    """Place market buy order."""
    try:
        e = _client(api_key, api_secret)
        sym = _normalize(symbol)

        # Get current price
        p = e.fetch_ticker(sym)['last']

        # Calculate quantity
        qty = usdt_amount / p

        # Get market info for precision
        market = e.market(sym)
        amount_precision = market['precision']['amount'] if 'precision' in market else 8
        qty = round(qty, amount_precision)

        # Gate.io CCXT: create_market_buy_order needs price parameter!
        # For spot market buy, we use create_order with type='market'
        o = e.create_order(
            sym,
            'market',
            'buy',
            qty,
            None,  # price is None for market order
            {'createMarketBuyOrderRequiresPrice': False}  # Disable price requirement
        )

        filled = float(o.get('filled') or qty)
        cost = float(o.get('cost') or usdt_amount)

        logger.info(f"Gate.io buy order: {sym} | qty={filled} | cost={cost}")

        return {
            'order_id': str(o.get('id', '')),
            'symbol': symbol,
            'side': 'buy',
            'quantity': filled,
            'entry_price': round(cost / filled if filled else p, 8),
            'cost': usdt_amount,
        }
    except ccxt.InsufficientFunds as e:
        logger.error(f"Insufficient funds for buy order {symbol}: {e}")
        raise
    except ccxt.NetworkError as e:
        logger.warning(f"Network error placing buy order {symbol}: {e}")
        raise
    except ccxt.ExchangeError as e:
        logger.error(f"Exchange error placing buy order {symbol}: {e}")
        raise


async def place_buy_order(api_key: str, api_secret: str, symbol: str, usdt_amount: float) -> dict:
    """Async wrapper for place_buy_order."""
    return await asyncio.to_thread(_place_buy_sync, api_key, api_secret, symbol, usdt_amount)


def _place_sell_sync(api_key: str, api_secret: str, symbol: str, quantity: float) -> dict:
    """Place market sell order."""
    try:
        e = _client(api_key, api_secret)
        sym = _normalize(symbol)

        # Get market info for precision
        market = e.market(sym)
        amount_precision = market['precision']['amount'] if 'precision' in market else 8
        qty = round(quantity, amount_precision)

        o = e.create_market_sell_order(sym, qty)

        filled = float(o.get('filled') or qty)
        cost = float(o.get('cost') or 0)

        logger.info(f"Gate.io sell order: {sym} | qty={filled} | cost={cost}")

        return {
            'order_id': str(o.get('id', '')),
            'symbol': symbol,
            'side': 'sell',
            'quantity': filled,
            'close_price': round(cost / filled if filled else 0, 8),
            'cost': cost,
        }
    except ccxt.InsufficientFunds as e:
        logger.error(f"Insufficient funds for sell order {symbol}: {e}")
        raise
    except ccxt.NetworkError as e:
        logger.warning(f"Network error placing sell order {symbol}: {e}")
        raise
    except ccxt.ExchangeError as e:
        logger.error(f"Exchange error placing sell order {symbol}: {e}")
        raise


async def place_sell_order(api_key: str, api_secret: str, symbol: str, quantity: float) -> dict:
    """Async wrapper for place_sell_order."""
    return await asyncio.to_thread(_place_sell_sync, api_key, api_secret, symbol, quantity)


# ─── الشموع ────────────────────────────────────────────────────

def _fetch_klines_sync(api_key: str, api_secret: str, symbol: str, interval: str, limit: int) -> list:
    """Fetch OHLCV candles."""
    try:
        ohlcv = _client(api_key, api_secret).fetch_ohlcv(
            _normalize(symbol),
            timeframe=interval,
            limit=limit
        )
        return [
            {'open': o[1], 'high': o[2], 'low': o[3], 'close': o[4], 'volume': o[5]}
            for o in ohlcv
        ]
    except ccxt.NetworkError as e:
        logger.warning(f"Network error fetching klines for {symbol}: {e}")
        raise
    except ccxt.ExchangeError as e:
        logger.error(f"Exchange error fetching klines for {symbol}: {e}")
        raise


async def get_klines(symbol: str, interval: str = '5m', limit: int = 60,
                     api_key: str = "", api_secret: str = "") -> list:
    """Async wrapper for get_klines."""
    return await asyncio.to_thread(_fetch_klines_sync, api_key, api_secret, symbol, interval, limit)


# ─── أعلى العملات ─────────────────────────────────────────────

def _fetch_top_symbols_sync(api_key: str, api_secret: str, count: int) -> list:
    """Fetch top symbols by volume."""
    try:
        exchange = _client(api_key, api_secret)
        markets = exchange.load_markets()

        # Get USDT pairs only
        usdt_pairs = [s for s in markets if s.endswith('/USDT')]

        # Fetch tickers for specific pairs (more efficient than all tickers)
        tickers = exchange.fetch_tickers(usdt_pairs[:count * 2])

        syms = []
        for s, t in tickers.items():
            if s.endswith('/USDT'):
                try:
                    vol = float(t.get('quoteVolume') or t.get('quote_volume') or 0)
                    if vol > 0:
                        syms.append({'symbol': s.replace('/', ''), 'volume': vol})
                except Exception:
                    continue

        syms.sort(key=lambda x: x['volume'], reverse=True)
        return [s['symbol'] for s in syms[:count]]

    except ccxt.NetworkError as e:
        logger.warning(f"Network error fetching top symbols: {e}")
        raise
    except ccxt.ExchangeError as e:
        logger.error(f"Exchange error fetching top symbols: {e}")
        raise


async def get_top_symbols(count: int = 200, api_key: str = "", api_secret: str = "") -> list:
    """Async wrapper for get_top_symbols."""
    return await asyncio.to_thread(_fetch_top_symbols_sync, api_key, api_secret, count)