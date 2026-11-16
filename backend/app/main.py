"""TrustAuth backend entry point."""

from fastapi import FastAPI

from app.core.db import database_is_up

app = FastAPI(title="TrustAuth")


@app.get("/health")
def health() -> dict:
    """Liveness check used by the frontend and by Docker.

    The API itself is "ok" if it can answer; the database status is reported separately
    so a database problem is visible without taking the whole API down.
    """
    return {"status": "ok", "database": "ok" if database_is_up() else "unavailable"}
