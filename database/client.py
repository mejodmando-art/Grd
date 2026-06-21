from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
import logging

logger = logging.getLogger(__name__)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ─── SETUP ────────────────────────────────────────────────────────────────────

async def init_db():
    """Create tables if they don't exist via Supabase RPC."""
    logger.info("Database initialized (tables managed via Supabase dashboard)")


# ─── USERS ────────────────────────────────────────────────────────────────────

async def get_user(user_id: int) -> dict | None:
    res = supabase.table("users").select("*").eq("id", user_id).execute()
    return res.data[0] if res.data else None


async def create_user(user_id: int, username: str) -> dict:
    data = {
        "id": user_id,
        "username": username,
        "is_active": True,
        "auto_trade": False,
        "default_amount": 10.0,
        "mexc_api_key": "",
        "mexc_api_secret": "",
    }
    res = supabase.table("users").upsert(data).execute()
    return res.data[0] if res.data else data


async def update_user(user_id: int, updates: dict) -> dict:
    res = supabase.table("users").update(updates).eq("id", user_id).execute()
    return res.data[0] if res.data else {}


async def get_all_active_users() -> list:
    res = supabase.table("users").select("*").eq("is_active", True).execute()
    return res.data or []


# ─── SIGNALS ──────────────────────────────────────────────────────────────────

async def save_signal(signal: dict) -> dict:
    res = supabase.table("signals").insert(signal).execute()
    return res.data[0] if res.data else signal


async def get_recent_signals(limit: int = 10) -> list:
    res = (
        supabase.table("signals")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


# ─── TRADES ───────────────────────────────────────────────────────────────────

async def save_trade(trade: dict) -> dict:
    res = supabase.table("trades").insert(trade).execute()
    return res.data[0] if res.data else trade


async def get_open_trades(user_id: int) -> list:
    res = (
        supabase.table("trades")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "open")
        .execute()
    )
    return res.data or []


async def get_all_open_trades() -> list:
    res = supabase.table("trades").select("*").eq("status", "open").execute()
    return res.data or []


async def get_trade_history(user_id: int, limit: int = 10) -> list:
    res = (
        supabase.table("trades")
        .select("*")
        .eq("user_id", user_id)
        .neq("status", "open")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


async def update_trade(trade_id: str, updates: dict) -> dict:
    res = supabase.table("trades").update(updates).eq("id", trade_id).execute()
    return res.data[0] if res.data else {}


async def get_trade_by_id(trade_id: str) -> dict | None:
    res = supabase.table("trades").select("*").eq("id", trade_id).execute()
    return res.data[0] if res.data else None
