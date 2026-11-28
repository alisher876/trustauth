"""WebAuthn challenges, kept in Redis for a few minutes and usable only once (passkey/DESIGN.md §3-§4).

Key  passkey:<kind>:<key>   e.g. passkey:reg:u_3f9a1c0b7d2e4a6f
     kind "reg" = registration (keyed by user_id), "auth" = login (keyed by login_id, week 6)

take() reads AND deletes the value in one Redis command (GETDEL), so a captured browser response
cannot be sent a second time: the challenge it signed is already gone (replay protection).
"""

from __future__ import annotations

import json

REGISTRATION_TTL_S = 5 * 60


class ChallengeStore:
    def __init__(self, client=None) -> None:
        self._client = client  # None = the platform's Redis, looked up on first use

    @property
    def client(self):
        if self._client is None:
            from app.core.redis_store import client  # imported here so tests need no Redis

            self._client = client
        return self._client

    def save(self, kind: str, key: str, data: dict, ttl_s: int) -> None:
        """Store `data` for `ttl_s` seconds. A new save for the same key replaces the old one."""
        self.client.set(f"passkey:{kind}:{key}", json.dumps(data), ex=ttl_s)

    def take(self, kind: str, key: str) -> dict | None:
        """Return the stored data and delete it, or None if it expired or was already used."""
        raw = self.client.getdel(f"passkey:{kind}:{key}")
        return json.loads(raw) if raw is not None else None
