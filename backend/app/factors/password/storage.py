"""Where password hashes are kept (password/DESIGN.md §5).

Table `password_credentials`: one argon2 hash per user, never the password itself.
It uses the platform's shared SQLAlchemy `Base`, so the core creates it at start-up.

Two stores with the same methods:
- SqlPasswordStore      PostgreSQL, used by the running platform
- InMemoryPasswordStore a dict, used in unit tests
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import SessionLocal
from app.core.models import Base, utc_now


class PasswordCredential(Base):
    __tablename__ = "password_credentials"

    user_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    hash: Mapped[str] = mapped_column(String(255))  # "$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PasswordStore(Protocol):
    def get_hash(self, user_id: str) -> str | None: ...

    def set_hash(self, user_id: str, password_hash: str) -> None: ...


class SqlPasswordStore:
    def __init__(self, session_factory=SessionLocal) -> None:
        self.session_factory = session_factory

    def get_hash(self, user_id: str) -> str | None:
        with self.session_factory() as db:
            row = db.get(PasswordCredential, user_id)
            return row.hash if row else None

    def set_hash(self, user_id: str, password_hash: str) -> None:
        with self.session_factory() as db:
            row = db.get(PasswordCredential, user_id)
            if row is None:
                db.add(PasswordCredential(user_id=user_id, hash=password_hash))
            else:
                row.hash = password_hash
                row.updated_at = utc_now()
            db.commit()


class InMemoryPasswordStore:
    def __init__(self) -> None:
        self.hashes: dict[str, str] = {}

    def get_hash(self, user_id: str) -> str | None:
        return self.hashes.get(user_id)

    def set_hash(self, user_id: str, password_hash: str) -> None:
        self.hashes[user_id] = password_hash
