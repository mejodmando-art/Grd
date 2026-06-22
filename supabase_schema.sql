-- ============================================================
-- GRD Trading Bot - Supabase Schema
-- Run this in the Supabase SQL Editor to create all tables
-- ============================================================

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,          -- Telegram User ID
    username TEXT,
    is_active BOOLEAN DEFAULT true,
    auto_trade BOOLEAN DEFAULT false,
    default_amount DECIMAL(18, 4) DEFAULT 10.0,
    mexc_api_key TEXT DEFAULT '',
    mexc_api_secret TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Signals table
CREATE TABLE IF NOT EXISTS signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('long', 'short')),
    entry_price DECIMAL(18, 8),
    take_profit DECIMAL(18, 8),
    stop_loss DECIMAL(18, 8),
    message TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trades table
CREATE TABLE IF NOT EXISTS trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    entry_price DECIMAL(18, 8),
    amount DECIMAL(18, 4),
    quantity DECIMAL(18, 8),
    take_profit DECIMAL(18, 8),
    stop_loss DECIMAL(18, 8),
    status TEXT DEFAULT 'open' CHECK (status IN ('open', 'closed', 'cancelled')),
    close_price DECIMAL(18, 8),
    close_reason TEXT,
    pnl DECIMAL(18, 4),
    order_id TEXT,
    signal_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_trades_user_id ON trades(user_id);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades(created_at DESC);

-- Enable Row Level Security
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE signals ENABLE ROW LEVEL SECURITY;

-- Allow service role full access (used by the bot backend)
-- USING covers SELECT/UPDATE/DELETE row filtering
-- WITH CHECK covers INSERT/UPDATE row validation
DROP POLICY IF EXISTS "service_role_all" ON users;
DROP POLICY IF EXISTS "service_role_all" ON trades;
DROP POLICY IF EXISTS "service_role_all" ON signals;

CREATE POLICY "service_role_all" ON users
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "service_role_all" ON trades
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "service_role_all" ON signals
    FOR ALL USING (true) WITH CHECK (true);
