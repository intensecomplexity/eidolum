"""One-shot schema migration entrypoint — run as the DATABASE OWNER role.

    RUN_STARTUP_DDL=true python migrate.py

The app + worker normally boot with RUN_STARTUP_DDL unset/false: the DDL guard
in database.py neutralizes every CREATE/ALTER/DROP to a no-op, so they need no
DDL privileges and can connect as the least-privilege `app_worker` role.

This script (run with RUN_STARTUP_DDL=true, as the owner) applies pending
schema. `create_all` creates any NEW tables. For new COLUMNS/INDEXES that were
added to the inline startup migrations in worker.py / main.py `_startup_init`,
the operational path is: deploy the services once with RUN_STARTUP_DDL=true on
the env (boot runs those idempotent ADD COLUMN / CREATE INDEX statements
through the un-gated guard), then set RUN_STARTUP_DDL back to false. Either way
DDL only ever runs as the owner with the flag explicitly on.
"""
import os
import sys

if os.getenv("RUN_STARTUP_DDL", "false").lower() not in ("1", "true", "yes"):
    sys.exit(
        "Refusing to migrate: set RUN_STARTUP_DDL=true and run this as the DB owner role.\n"
        "  RUN_STARTUP_DDL=true python migrate.py"
    )

from database import engine, Base, startup_ddl_enabled  # noqa: E402
import models  # noqa: E402,F401 — import so every ORM table registers on Base.metadata

assert startup_ddl_enabled(), "RUN_STARTUP_DDL must be enabled"

print(f"[migrate] create_all on {engine.url.host}/{engine.url.database} as owner ...")
Base.metadata.create_all(bind=engine)
print("[migrate] create_all complete.")
