-- drop_phantom_is_active.sql
--
-- Drop the phantom `is_active` column from tracked_x_accounts if it exists.
--
-- Background: the canonical column on this table has always been `active`
-- (BOOLEAN). At some point an out-of-band SQL run may have added a parallel
-- `is_active` column that nothing in the codebase reads or writes. Leaving
-- it in place makes the schema confusing and risks future "wrong column"
-- bugs. This migration removes it.
--
-- Idempotent: DROP COLUMN IF EXISTS is a no-op when the column is absent,
-- so it's safe to re-run. The same statement also runs automatically at
-- worker startup (see backend/worker.py) so this file is a documentation
-- artifact — you can run it manually with:
--   psql "$DATABASE_PUBLIC_URL" -f backend/migrations/drop_phantom_is_active.sql
-- but the worker will already have applied it on its next restart.

BEGIN;

ALTER TABLE tracked_x_accounts DROP COLUMN IF EXISTS is_active;

-- Sanity: confirm `active` still exists and tracked_x_accounts is still healthy
SELECT COUNT(*) AS row_count,
       SUM(CASE WHEN active THEN 1 ELSE 0 END) AS active_count
FROM tracked_x_accounts;

COMMIT;
