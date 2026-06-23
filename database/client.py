import asyncio
import logging
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)

_supabase: Client | None = None


def _get_client() -> Client:
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY environment variables must be set!")
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


async def _run(query):
    return await asyncio.to_thread(query.execute)


# ─── SETUP ────────────────────────────────────────────────────────────────────

async def init_db():
    _get_client()
    logger.info("✅ Supabase client initialized successfully")


# ─── USERS ────────────────────────────────────────────────────────────────────

async def get_user(user_id: int) -> dict | None:
    res = await _run(_get_client().table("users").select("*").eq("id", user_id))
    return res.data[0] if res.data else None


async def create_user(user_id: int, username: str) -> dict:
    data = {
        "id": user_id,
        "username": username,
        "is_active": True,
        "ema_trade": False,
        "ema_amount": 10.0,
        "harpoon_trade": False,
        "harpoon_amount": 10.0,
        "exchange": "gate",
    }
    res = await _run(_get_client().table("users").upsert(data))
    return res.data[0] if res.data else data


async def update_user(user_id: int, updates: dict) -> dict:
    res = await _run(_get_client().table("users").update(updates).eq("id", user_id))
    return res.data[0] if res.data else {}


async def get_all_active_users() -> list:
    res = await _run(_get_client().table("users").select("*").eq("is_active", True))
    return res.data or []


# ─── SIGNALS ──────────────────────────────────────────────────────────────────

async def save_signal(signal: dict) -> dict:
    res = await _run(_get_client().table("signals").insert(signal))
    return res.data[0] if res.data else signal


async def get_recent_signals(limit: int = 10) -> list:
    res = await _run(
        _get_client().table("signals")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
    )
    return res.data or []


# ─── TRADES ───────────────────────────────────────────────────────────────────

async def save_trade(trade: dict) -> dict:
    res = await _run(_get_client().table("trades").insert(trade))
    return res.data[0] if res.data else trade


async def get_open_trades(user_id: int) -> list:
    res = await _run(
        _get_client().table("trades")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "open")
        .order("created_at", desc=True)
    )
    return res.data or []


async def get_all_open_trades() -> list:
    res = await _run(_get_client().table("trades").select("*").eq("status", "open"))
    return res.data or []


async def get_trade_history(user_id: int, limit: int = 10) -> list:
    res = await _run(
        _get_client().table("trades")
        .select("*")
        .eq("user_id", user_id)
        .neq("status", "open")
        .order("created_at", desc=True)
        .limit(limit)
    )
    return res.data or []


async def update_trade(trade_id: str, updates: dict) -> dict:
    res = await _run(_get_client().table("trades").update(updates).eq("id", trade_id))
    return res.data[0] if res.data else {}


async def get_trade_by_id(trade_id: str) -> dict | None:
    res = await _run(_get_client().table("trades").select("*").eq("id", trade_id))
    return res.data[0] if res.data else None
