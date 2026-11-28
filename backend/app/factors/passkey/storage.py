"""Where passkeys are kept (passkey/DESIGN.md §5).

Table `webauthn_credentials`: one row per registered device (a user may register several).
Only PUBLIC keys are stored: a leaked table does not let anyone log in.
It uses the platform's shared SQLAlchemy `Base`, so the core creates it at start-up.

Two stores with the same methods:
- SqlPasskeyStore       PostgreSQL, used by the running platform
- InMemoryPasskeyStore  dicts, used in unit tests
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import SessionLocal
from app.core.models import Base, JSONType, User, utc_now


class WebAuthnCredential(Base):
    __tablename__ = "webauthn_credentials"

    credential_id: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)  # chosen by the authenticator
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    user_handle: Mapped[bytes] = mapped_column(LargeBinary)  # random 32 bytes, the same for all of a user's passkeys
    public_key: Mapped[bytes] = mapped_column(LargeBinary)  # COSE public key
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    transports: Mapped[list] = mapped_column(JSONType, default=list)  # e.g. ["internal", "hybrid"]
    backed_up: Mapped[bool] = mapped_column(Boolean, default=False)  # synced passkey (iCloud, Google) or device-bound
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@dataclass
class StoredCredential:
    """One registered passkey, independent of the database (what the factor works with)."""

    credential_id: bytes
    user_id: str
    user_handle: bytes
    public_key: bytes
    sign_count: int = 0
    transports: list[str] = field(default_factory=list)
    backed_up: bool = False


class PasskeyStore(Protocol):
    def credentials(self, user_id: str) -> list[StoredCredential]: ...

    def credential_exists(self, credential_id: bytes) -> bool: ...

    def add(self, credential: StoredCredential) -> None: ...

    def user_name(self, user_id: str) -> str: ...


def _to_stored(row: WebAuthnCredential) -> StoredCredential:
    return StoredCredential(credential_id=row.credential_id, user_id=row.user_id, user_handle=row.user_handle,
                            public_key=row.public_key, sign_count=row.sign_count, transports=list(row.transports or []),
                            backed_up=row.backed_up)


class SqlPasskeyStore:
    def __init__(self, session_factory=SessionLocal) -> None:
        self.session_factory = session_factory

    def credentials(self, user_id: str) -> list[StoredCredential]:
        with self.session_factory() as db:
            rows = db.scalars(select(WebAuthnCredential).where(WebAuthnCredential.user_id == user_id)
                              .order_by(WebAuthnCredential.created_at))
            return [_to_stored(row) for row in rows]

    def credential_exists(self, credential_id: bytes) -> bool:
        with self.session_factory() as db:
            return db.get(WebAuthnCredential, credential_id) is not None

    def add(self, credential: StoredCredential) -> None:
        with self.session_factory() as db:
            db.add(WebAuthnCredential(credential_id=credential.credential_id, user_id=credential.user_id,
                                      user_handle=credential.user_handle, public_key=credential.public_key,
                                      sign_count=credential.sign_count, transports=credential.transports,
                                      backed_up=credential.backed_up))
            db.commit()

    def user_name(self, user_id: str) -> str:
        """The TrustAuth username, shown in the device's passkey list (DESIGN.md §3)."""
        with self.session_factory() as db:
            user = db.get(User, user_id)
            return user.username if user else user_id


class InMemoryPasskeyStore:
    def __init__(self) -> None:
        self.rows: dict[bytes, StoredCredential] = {}
        self.names: dict[str, str] = {}

    def credentials(self, user_id: str) -> list[StoredCredential]:
        return [c for c in self.rows.values() if c.user_id == user_id]

    def credential_exists(self, credential_id: bytes) -> bool:
        return credential_id in self.rows

    def add(self, credential: StoredCredential) -> None:
        self.rows[credential.credential_id] = credential

    def user_name(self, user_id: str) -> str:
        return self.names.get(user_id, user_id)
