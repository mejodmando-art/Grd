-- GRD Trading Bot v4.0 — UT Bot Edition

CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,
    username TEXT,
    is_active BOOLEAN DEFAULT true,
    -- Strategies
    ema_trade BOOLEAN DEFAULT true,
    ema_amount DECIMAL(18, 4) DEFAULT 10.0,
    harpoon_trade BOOLEAN DEFAULT false,
    harpoon_amount DECIMAL(18, 4) DEFAULT 10.0,
    ut_bot_trade BOOLEAN DEFAULT false,
    ut_bot_amount DECIMAL(18, 4) DEFAULT 20.0,
    sphinx_trade BOOLEAN DEFAULT false,
    sphinx_amount DECIMAL(18, 4) DEFAULT 25.0,
    -- Settings
    notifications BOOLEAN DEFAULT true,
    exchange TEXT DEFAULT 'gate',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Migration
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='ut_bot_trade') THEN
        ALTER TABLE users ADD COLUMN ut_bot_trade BOOLEAN DEFAULT false;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='ut_bot_amount') THEN
        ALTER TABLE users ADD COLUMN ut_bot_amount DECIMAL(18,4) DEFAULT 20.0;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='notifications') THEN
        ALTER TABLE users ADD COLUMN notifications BOOLEAN DEFAULT true;
    END IF;
END $$;

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
    strategy TEXT DEFAULT 'EMA',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_trades_user_id ON trades(user_id);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all" ON users;
DROP POLICY IF EXISTS "service_role_all" ON trades;
CREATE POLICY "service_role_all" ON users FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON trades FOR ALL USING (true) WITH CHECK (true);
