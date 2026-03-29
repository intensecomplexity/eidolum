import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./eidolum.db")

# Railway provides postgres:// but SQLAlchemy requires postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {"options": "-c statement_timeout=10000"}  # 10s query timeout
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_size=5,
    max_overflow=10,
    pool_timeout=10,       # Wait max 10s for a connection
    pool_recycle=300,       # Recycle connections every 5 min
    pool_pre_ping=True,     # Verify connections before use
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
