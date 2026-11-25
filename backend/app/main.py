"""TrustAuth backend entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.auth_routes import router as auth_router
from app.core.db import create_tables, database_is_up
from app.core.factor_setup import register_factors
from app.core.redis_store import redis_is_up


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once when the server starts: create tables, register the factors."""
    create_tables()
    register_factors()
    yield


app = FastAPI(title="TrustAuth", lifespan=lifespan)
app.include_router(auth_router)


@app.get("/health")
def health() -> dict:
    """Liveness check used by the frontend and by Docker.

    The API itself is "ok" if it can answer; the database and Redis are reported separately
    so a problem in one of them is visible without taking the whole API down.
    """
    return {
        "status": "ok",
        "database": "ok" if database_is_up() else "unavailable",
        "redis": "ok" if redis_is_up() else "unavailable",
    }
