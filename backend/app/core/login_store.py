"""Short-lived login state and sessions, kept in Redis.

login:<login_id>   JSON state of a login in progress (context, plan, progress); expires after 10 min
session:<token>    user_id of a logged-in user; expires after 8 h
pwfail:<user_id>   failed password attempts in the last 15 min (LoginContext.recent_failures)
study:label        the study label the researcher set in the dashboard (copied into attempt rows)

Redis keys expire by themselves (TTL), so abandoned logins clean up automatically.
"""

from __future__ import annotations

import json
import secrets

from redis import Redis

LOGIN_TTL_S = 10 * 60
SESSION_TTL_S = 8 * 60 * 60
FAILURE_WINDOW_S = 15 * 60


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

    # --- recent password failures ---

    def add_password_failure(self, user_id: str) -> int:
        """Count one failed password. The window starts at the first failure and lasts 15 minutes."""
        key = f"pwfail:{user_id}"
        count = self.redis.incr(key)
        if count == 1:
            self.redis.expire(key, FAILURE_WINDOW_S)
        return int(count)

    def recent_failures(self, user_id: str) -> int:
        return int(self.redis.get(f"pwfail:{user_id}") or 0)

    def clear_failures(self, user_id: str) -> None:
        self.redis.delete(f"pwfail:{user_id}")

    # --- study label (set by the researcher, docs/interface.md §9) ---

    def set_study_label(self, label: dict) -> None:
        self.redis.set("study:label", json.dumps(label))  # no expiry: stays until changed or cleared

    def study_label(self) -> dict | None:
        raw = self.redis.get("study:label")
        return json.loads(raw) if raw is not None else None

    def clear_study_label(self) -> None:
        self.redis.delete("study:label")


def get_store() -> LoginStore:
    """FastAPI dependency. Imported lazily so tests can replace it without a running Redis."""
    from app.core.redis_store import client

    return LoginStore(client)
