import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./eidolum.db")

# Railway provides postgres:// but SQLAlchemy requires postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# lock_timeout is set as a libpq STARTUP option (not a connect-event SET) so it
# is the session default and survives the rollback SQLAlchemy issues when a
# connection returns to the pool — a connect-event `SET lock_timeout` reverts on
# that rollback (it ran inside an aborted transaction), and a leaked
# `SET statement_timeout=0` from a batch job can't touch it. 3s caps how long any
# statement waits to ACQUIRE a lock: a boot `ALTER TABLE predictions ADD COLUMN …`
# (ACCESS EXCLUSIVE) that queues behind a long read aborts in 3s instead of
# blocking every new read on the table for ~90s (the 2026-06-08 stall).
connect_args = (
    {"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {"options": "-c lock_timeout=3000"}
)

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args=connect_args)
    bg_engine = engine  # Same engine for SQLite
else:
    # User-facing pool: pool_size=3 + max_overflow=5 = 8 max connections
    engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        pool_size=3,
        max_overflow=5,
        pool_timeout=5,
        pool_recycle=300,
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _set_user_timeout(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("SET statement_timeout = '5000'")  # 5 seconds for user queries
        # (lock_timeout is set via connect_args options above so it survives
        #  the pool-return rollback — see the connect_args comment.)
        cursor.close()

    # Background job pool: pool_size=2 + max_overflow=3 = 5 max connections
    # Grand total: 8 + 5 = 13 max connections
    bg_engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        pool_size=2,
        max_overflow=3,
        pool_timeout=30,
        pool_recycle=300,
        pool_pre_ping=True,
    )

    @event.listens_for(bg_engine, "connect")
    def _set_bg_timeout(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("SET statement_timeout = '30000'")  # 30 seconds for background jobs
        # (lock_timeout=3s comes from connect_args options — survives pool reuse.)
        cursor.close()

    # ── Deploy-safe startup DDL: skip ADD COLUMN IF NOT EXISTS that is a no-op ──
    # `ADD COLUMN IF NOT EXISTS` STILL takes ACCESS EXCLUSIVE to check the
    # catalog — so on every boot, the ~40 column-ensure ALTERs on the 460k-row
    # `predictions` table each grab the table lock even though the columns
    # already exist. Many concurrent deploys doing this is what piled the locks
    # (incident 2026-06-08).
    #
    # This listener rewrites such an ALTER to a no-op `SELECT 1` when the column
    # is already known to exist, so steady-state boots issue ZERO predictions DDL
    # and never request the lock at all — without touching the 40+ scattered
    # call sites. The column set is primed once per process (prime_known_columns,
    # called from the API + worker startup after create_all). Tables that were
    # never primed are left untouched, so a genuinely new column still runs its
    # real ALTER (then bounded by lock_timeout above).
    import re as _re
    _known_columns: dict[str, set] = {}
    _ADD_COL_RE = _re.compile(
        r"^\s*ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+(\w+)",
        _re.IGNORECASE,
    )

    def _skip_noop_add_column(conn, cursor, statement, parameters, context, executemany):
        # Cheap prefilter: only ALTER statements can match.
        if not statement or "ALTER" not in statement[:16].upper():
            return statement, parameters
        m = _ADD_COL_RE.match(statement)
        if m:
            table, col = m.group(1).lower(), m.group(2).lower()
            cols = _known_columns.get(table)
            if cols is not None and col in cols:
                return "SELECT 1", parameters  # column exists — no DDL, no lock
        return statement, parameters

    event.listen(engine, "before_cursor_execute", _skip_noop_add_column, retval=True)
    event.listen(bg_engine, "before_cursor_execute", _skip_noop_add_column, retval=True)


def prime_known_columns(tables):
    """Populate the column cache so steady-state boots skip no-op ADD COLUMN
    DDL (see the before_cursor_execute listener). Best-effort: on any failure
    the cache stays empty and the real ALTERs run (bounded by lock_timeout).
    No-op under SQLite (no engine listener / not the deploy target)."""
    if DATABASE_URL.startswith("sqlite"):
        return
    try:
        from sqlalchemy import text as _text
        for t in tables:
            try:
                with engine.connect() as c:
                    rows = c.execute(_text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = :t"
                    ), {"t": t}).fetchall()
                _known_columns[t.lower()] = {r[0].lower() for r in rows}
            except Exception:
                pass
    except Exception:
        pass


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
BgSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=bg_engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
