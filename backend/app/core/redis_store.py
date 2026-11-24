"""Redis connection, for short-lived data: login sessions, challenges, phone-approval tokens.

Named redis_store (not redis) so it does not hide the `redis` library when imported.
"""

import os

import redis

# Set by docker-compose.yml; the default lets the app start without Docker (e.g. in tests).
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# decode_responses=True: values come back as str instead of bytes.
# Short timeouts so a missing Redis makes /health answer quickly instead of hanging.
client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)


def redis_is_up() -> bool:
    """Return True if Redis answers a PING."""
    try:
        return bool(client.ping())
    except redis.RedisError:
        return False
