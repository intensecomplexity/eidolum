import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./eidolum.db")

# Railway provides postgres:// but SQLAlchemy requires postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

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
        cursor.close()

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
