-- 2026-06-10 Live presence — "who's on the site right now" for the admin
-- dashboard. One row per active visitor session, refreshed by the public
-- POST /api/presence/ping heartbeat (60s cadence from the frontend).
--
--   session_key: anon visitors use a client-random id (sessionStorage);
--                signed-in users collapse to 'u:<user_id>' so multiple
--                tabs/devices of the same account count once.
--   No IP is stored (privacy). username is the only PII, admin-only read.
--
-- Online = last_seen > NOW() - INTERVAL '2 minutes' (computed at read time).
-- Rows older than 1 hour are deleted inline by the admin presence query.
--
-- RUN_STARTUP_DDL is false in prod — this file must be run MANUALLY against
-- the prod DB (DATABASE_PUBLIC_URL) as the owner role.

CREATE TABLE IF NOT EXISTS presence_sessions (
    session_key      VARCHAR(64) PRIMARY KEY,
    user_id          BIGINT,                          -- NULL for anonymous
    username         VARCHAR(50),                     -- NULL for anonymous
    is_authenticated BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_presence_sessions_last_seen
    ON presence_sessions(last_seen);

-- The services are moving to the least-privilege app_worker role (DML only).
-- Grant it access if the role exists; no-op otherwise.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_worker') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON presence_sessions TO app_worker;
    END IF;
END $$;
