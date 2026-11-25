"""Short-lived login state and sessions, kept in Redis.

login:<login_id>   JSON state of a login in progress (context, plan, progress); expires after 10 min
session:<token>    user_id of a logged-in user; expires after 8 h

Redis keys expire by themselves (TTL), so abandoned logins clean up automatically.
"""

from __future__ import annotations

import json
import secrets

from redis import Redis

LOGIN_TTL_S = 10 * 60
SESSION_TTL_S = 8 * 60 * 60


class LoginStore:
    def __init__(self, client: Redis) -> None:
        self.redis = client

    # --- logins in progress ---

    def save_login(self, login_id: str, state: dict) -> None:
        self.redis.set(f"login:{login_id}", json.dumps(state), ex=LOGIN_TTL_S)

    def load_login(self, login_id: str) -> dict | None:
        raw = self.redis.get(f"login:{login_id}")
        return json.loads(raw) if raw is not None else None

    def delete_login(self, login_id: str) -> None:
        self.redis.delete(f"login:{login_id}")

    # --- sessions ---

    def create_session(self, user_id: str) -> str:
        """New random session token (256 bits) for a user who passed all factors."""
        token = secrets.token_urlsafe(32)
        self.redis.set(f"session:{token}", user_id, ex=SESSION_TTL_S)
        return token

    def session_user(self, token: str) -> str | None:
        return self.redis.get(f"session:{token}")


def get_store() -> LoginStore:
    """FastAPI dependency. Imported lazily so tests can replace it without a running Redis."""
    from app.core.redis_store import client

    return LoginStore(client)
