"""Database tables (SQLAlchemy 2.0).

users     one row per account. The username only lives here; everything else uses the
          pseudonymous user_id (CLAUDE.md §13).
attempts  one row per factor attempt: the attempt log of docs/interface.md §9, which the
          Trust Lab analyses.

Week 3 creates the tables with `create_all` at start-up; Alembic migrations follow once the
schema is frozen (week 4).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JSONB on PostgreSQL (indexable, compact); plain JSON elsewhere (SQLite in tests).
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_user_id() -> str:
    """Random pseudonymous ID like "u_3f9a1c0b7d2e4a6f". Carries no personal information."""
    return "u_" + secrets.token_hex(8)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=new_user_id)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Attempt(Base):
    __tablename__ = "attempts"

    attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    login_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), index=True)
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    factor: Mapped[str] = mapped_column(String(20))
    accepted: Mapped[bool] = mapped_column(Boolean)
    score: Mapped[float] = mapped_column(Float)
    duration_ms: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Study labels: set from the admin dashboard during study sessions (later); null in normal use.
    is_genuine: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    attack_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    study_session_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    condition: Mapped[str] = mapped_column(String(20))
    context: Mapped[dict] = mapped_column(JSONType)
    risk_level: Mapped[str] = mapped_column(String(10))
    selected_factors: Mapped[list] = mapped_column(JSONType)
    selector: Mapped[str] = mapped_column(String(10))
