"""Database connection (PostgreSQL via SQLAlchemy)."""

import os

from sqlalchemy import create_engine, text

# Set by docker-compose.yml; the default lets the app start without Docker (e.g. in tests).
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://trustauth@localhost:5432/trustauth")

# pool_pre_ping: test a pooled connection before using it, so a database restart does not break requests.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def database_is_up() -> bool:
    """Return True if the database answers a trivial query."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
