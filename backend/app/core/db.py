"""Database connection (PostgreSQL via SQLAlchemy)."""

import logging
import os
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

# Set by docker-compose.yml; the default lets the app start without Docker (e.g. in tests).
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://trustauth@localhost:5432/trustauth")

# pool_pre_ping: test a pooled connection before using it, so a database restart does not break requests.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def database_is_up() -> bool:
    """Return True if the database answers a trivial query."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request, closed afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables(bind: Engine = engine) -> bool:
    """Create missing tables (week 3; Alembic later). Returns False instead of crashing if the DB is down."""
    from app.core.models import Base  # imported here so this module has no import cycle

    try:
        Base.metadata.create_all(bind)
        return True
    except Exception:
        logger.exception("could not create database tables")
        return False
