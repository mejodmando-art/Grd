-- ============================================================
-- GRD Trading Bot - Supabase Schema (v3)
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,
    username TEXT,
    is_active BOOLEAN DEFAULT true,
    -- Strategy: EMA
    ema_trade BOOLEAN DEFAULT true,
    ema_amount DECIMAL(18, 4) DEFAULT 10.0,
    -- Strategy: HARPOON
    harpoon_trade BOOLEAN DEFAULT false,
    harpoon_amount DECIMAL(18, 4) DEFAULT 10.0,
    -- Exchange preference
    exchange TEXT DEFAULT 'gate' CHECK (exchange IN ('gate', 'mexc', 'both')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Migration: add columns if table exists
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='ema_trade') THEN
        ALTER TABLE users ADD COLUMN ema_trade BOOLEAN DEFAULT true;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='ema_amount') THEN
        ALTER TABLE users ADD COLUMN ema_amount DECIMAL(18,4) DEFAULT 10.0;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='harpoon_trade') THEN
        ALTER TABLE users ADD COLUMN harpoon_trade BOOLEAN DEFAULT false;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='harpoon_amount') THEN
        ALTER TABLE users ADD COLUMN harpoon_amount DECIMAL(18,4) DEFAULT 10.0;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='exchange') THEN
        ALTER TABLE users ADD COLUMN exchange TEXT DEFAULT 'gate';
    END IF;
END $$;

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
    signal_id TEXT,
    strategy TEXT DEFAULT 'EMA',
    exchange TEXT DEFAULT 'GATE',
    confirmations INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);

-- Migration for trades
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='trades' AND column_name='strategy') THEN
        ALTER TABLE trades ADD COLUMN strategy TEXT DEFAULT 'EMA';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='trades' AND column_name='exchange') THEN
        ALTER TABLE trades ADD COLUMN exchange TEXT DEFAULT 'GATE';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='trades' AND column_name='confirmations') THEN
        ALTER TABLE trades ADD COLUMN confirmations INT DEFAULT 0;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='trades' AND column_name='signal_id' AND data_type='uuid') THEN
        ALTER TABLE trades ALTER COLUMN signal_id TYPE TEXT USING signal_id::TEXT;
    END IF;
END $$;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_trades_user_id ON trades(user_id);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);
CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades(created_at DESC);

-- Row Level Security
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE signals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all" ON users;
DROP POLICY IF EXISTS "service_role_all" ON trades;
DROP POLICY IF EXISTS "service_role_all" ON signals;

CREATE POLICY "service_role_all" ON users FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON trades FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON signals FOR ALL USING (true) WITH CHECK (true);