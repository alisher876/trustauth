"""End-to-end tests of registration and the login challenge loop, with mock factors.

Runs without Docker: the database is in-memory SQLite and Redis is fakeredis.
The mocks are defined here (from MockFactor), so these tests do not depend on
the members' mock files.
"""

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import create_tables, get_db
from app.core.login_store import LoginStore, get_store
from app.core.models import Attempt
from app.factors.base import MockFactor, clear_registry, register
from app.main import app

LAPTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"


class Password(MockFactor):
    name = "password"
    mock_context = {"leaked": False}


class Passkey(MockFactor):
    name = "passkey"
    mock_context = {"user_verified": True}


class Face(MockFactor):
    name = "face"
    binary = False
    mock_context = {"light": "dim", "liveness_passed": True}


@pytest.fixture
def db_session():
    # One shared in-memory database for the whole test (StaticPool keeps the single connection).
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    assert create_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def client(db_session):
    store = LoginStore(fakeredis.FakeRedis(decode_responses=True))

    def override_db():
        db = db_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_store] = lambda: store
    clear_registry()
    for factor in (Password(), Passkey(), Face()):
        register(factor)
    # Not used as a context manager, so the startup code (real PostgreSQL) does not run.
    yield TestClient(app, headers={"User-Agent": LAPTOP_UA})
    app.dependency_overrides.clear()
    clear_registry()


def start(client, username="alice"):
    return client.post("/auth/login/start", json={"username": username, "client": {"has_camera": True}})


def verify(client, login_id, factor, accept=True, **extra):
    payload = {"mock_accept": accept, **extra}
    return client.post(f"/auth/login/{login_id}/verify", json={"factor": factor, "payload": payload})


def attempts(db_session):
    with db_session() as db:
        return db.scalars(select(Attempt).order_by(Attempt.timestamp)).all()


# --- registration ------------------------------------------------------------------------


def test_register(client):
    response = client.post("/auth/register", json={"username": "Alice"})
    assert response.status_code == 201
    assert response.json()["user_id"].startswith("u_")
    assert client.post("/auth/register", json={"username": "alice"}).status_code == 409  # case-insensitive


@pytest.mark.parametrize("username", ["ab", "a" * 33, "alice smith", "alice@x", ""])
def test_register_rejects_bad_usernames(client, username):
    assert client.post("/auth/register", json={"username": username}).status_code == 422


# --- happy path --------------------------------------------------------------------------


def test_full_login_gives_a_working_session(client, db_session):
    client.post("/auth/register", json={"username": "alice"})
    started = start(client).json()
    assert started["factors"] == ["password", "passkey"]
    assert started["next"]["factor"] == "password"
    login_id = started["login_id"]

    first = verify(client, login_id, "password").json()
    assert first["status"] == "next" and first["next"]["factor"] == "passkey"

    done = verify(client, login_id, "passkey").json()
    assert done["status"] == "authenticated"

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {done['session']}"})
    assert me.status_code == 200 and me.json()["username"] == "alice"

    # The finished login is gone.
    assert verify(client, login_id, "passkey").status_code == 404


def test_attempts_are_logged(client, db_session):
    client.post("/auth/register", json={"username": "alice"})
    login_id = start(client).json()["login_id"]
    verify(client, login_id, "password", mock_duration_ms=4200)

    rows = attempts(db_session)
    assert len(rows) == 1
    row = rows[0]
    assert (row.factor, row.accepted, row.score, row.duration_ms, row.error) == ("password", True, 1.0, 4200, None)
    assert row.user_id.startswith("u_") and str(row.login_id) == login_id
    assert (row.condition, row.risk_level, row.selector) == ("laptop_normal", "low", "fixed")
    assert row.selected_factors == ["password", "passkey"]
    assert row.context["factor"] == {"leaked": False}
    assert row.is_genuine is None and row.attack_type is None


# --- retries and failures ----------------------------------------------------------------


def test_retry_then_replacement_then_success(client):
    client.post("/auth/register", json={"username": "alice"})
    login_id = start(client).json()["login_id"]

    retry = verify(client, login_id, "password", accept=False).json()
    assert retry["status"] == "retry" and retry["reason"] == "rejected" and retry["next"]["factor"] == "password"

    replaced = verify(client, login_id, "password", accept=False).json()
    assert replaced["status"] == "retry" and replaced["reason"] == "replaced"
    assert replaced["next"]["factor"] == "face"

    assert verify(client, login_id, "face").json()["status"] == "next"
    assert verify(client, login_id, "passkey").json()["status"] == "authenticated"


def test_two_failed_factors_deny(client, db_session):
    client.post("/auth/register", json={"username": "alice"})
    login_id = start(client).json()["login_id"]
    verify(client, login_id, "password", mock_error="timeout")  # replaced by face
    denied = verify(client, login_id, "face", mock_error="unavailable").json()
    assert denied == {"status": "denied"}
    assert [row.error for row in attempts(db_session)] == ["timeout", "unavailable"]


def test_face_light_updates_the_logged_condition(client, db_session):
    client.post("/auth/register", json={"username": "alice"})
    login_id = start(client).json()["login_id"]
    verify(client, login_id, "password", mock_error="timeout")  # face comes in as replacement
    verify(client, login_id, "face")  # the face mock reports light = dim
    assert attempts(db_session)[-1].condition == "laptop_dim"


def test_wrong_factor_and_unknown_login(client):
    client.post("/auth/register", json={"username": "alice"})
    login_id = start(client).json()["login_id"]
    assert verify(client, login_id, "passkey").status_code == 409  # password is expected first
    assert verify(client, "00000000-0000-0000-0000-000000000000", "password").status_code == 404


def test_factor_crash_becomes_internal_error(client, db_session):
    class Broken(MockFactor):
        name = "password"

        async def verify(self, user_id, payload, ctx):
            raise RuntimeError("bug in factor")

    clear_registry()
    register(Broken())
    register(Passkey())
    client.post("/auth/register", json={"username": "alice"})
    login_id = start(client).json()["login_id"]
    response = verify(client, login_id, "password")
    assert response.status_code == 200
    assert attempts(db_session)[0].error == "internal"


# --- unknown usernames --------------------------------------------------------------------


def test_unknown_username_looks_the_same_but_never_succeeds(client, db_session):
    client.post("/auth/register", json={"username": "alice"})
    real = start(client, "alice").json()
    fake = start(client, "mallory").json()
    assert fake["factors"] == real["factors"] and fake["next"].keys() == real["next"].keys()

    login_id = fake["login_id"]
    # Same rules as a real login: retry, replace, retry, deny. Correct answers make no difference.
    statuses = [verify(client, login_id, factor).json()["status"]
                for factor in ("password", "password", "face", "face")]
    assert statuses == ["retry", "retry", "retry", "denied"]
    assert attempts(db_session) == []  # decoy attempts are not logged


def test_no_usable_factor(client):
    clear_registry()
    assert start(client).status_code == 422


def test_me_without_session(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
