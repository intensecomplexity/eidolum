-- Ship: company name aliases (2026-04-18, follow-up to 0013 grounding classifier)
-- Adds a third alias table alongside macro_concept_aliases (concept→ETF)
-- and sector_etf_aliases (sector→ETF): single-name company aliases
-- (ticker → spoken / written name).
--
-- The existing two tables are UNIQUE-on-alias which makes them unfit
-- for single-name companies — "apple" / "amazon" / "microsoft" belong
-- to exactly one ticker each and there's no concept or sector wrapper
-- for them. This table is UNIQUE on (lower(ticker), lower(alias)) so
-- the same alias cannot be registered twice for the same ticker, and
-- the ON CONFLICT DO NOTHING pattern makes the populate step
-- idempotent.
--
-- Read by classifiers/grounding.py via the alias_map it builds from
-- all three tables — the classifier itself is agnostic to which
-- table an alias came from.

CREATE TABLE IF NOT EXISTS company_name_aliases (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(16) NOT NULL,
    alias VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Functional unique so "Apple" and "apple" don't both land; a single
-- ticker/alias pair stays idempotent under ON CONFLICT DO NOTHING.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_company_name_aliases_lower
    ON company_name_aliases (LOWER(ticker), LOWER(alias));

-- Lookup index — the classifier builds an in-memory alias_map once
-- per batch, but admin scans by-ticker.
CREATE INDEX IF NOT EXISTS idx_company_name_aliases_ticker
    ON company_name_aliases (ticker);
