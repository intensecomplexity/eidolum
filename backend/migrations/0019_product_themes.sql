-- 2026-06-09 Product Themes v1 — a second, overlapping "by product" axis
-- (Phones / EVs / AI Chips / Cloud ...) alongside the exclusive sector
-- axis. Themes are MANY-TO-MANY with tickers (QCOM is both Phones and
-- AI Chips). v1 is filter + tag only: no scoring columns, no
-- predictions-table changes — per-forecaster theme accuracy can later
-- aggregate over predictions WHERE ticker IN (theme's tickers) with
-- zero migration churn. Membership is hand-curated via /admin/themes.

CREATE TABLE IF NOT EXISTS themes (
    id            SERIAL PRIMARY KEY,
    slug          VARCHAR(48) UNIQUE NOT NULL,   -- 'phones', 'ai-chips'
    name          VARCHAR(80) NOT NULL,          -- 'Phones', 'AI Chips'
    description   TEXT,
    display_order INT NOT NULL DEFAULT 100,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS theme_tickers (
    theme_id   INT NOT NULL REFERENCES themes(id) ON DELETE CASCADE,
    ticker     VARCHAR(20) NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,    -- flagship members (AAPL for Phones)
    added_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (theme_id, ticker)
);

CREATE INDEX IF NOT EXISTS ix_theme_tickers_ticker ON theme_tickers(ticker);
CREATE INDEX IF NOT EXISTS ix_theme_tickers_theme  ON theme_tickers(theme_id);
