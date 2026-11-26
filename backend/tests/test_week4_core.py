"""Week 4 core features: known network / device, recent failures, measured duration,
study labels and CSV export, enrollment endpoints.

Same setup as test_auth_api.py: in-memory SQLite + fakeredis + local mock factors.
"""

import csv
import io

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import create_tables, get_db
from app.core.known import DEVICE_COOKIE
from app.core.login_store import LoginStore, get_store
from app.core.models import Attempt, KnownDevice
from app.factors.base import EnrollResult, MockFactor, clear_registry, register
from app.main import app

LAPTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
ADMIN = {"X-Admin-Token": "test-admin-token"}


class Password(MockFactor):
    name = "password"
    mock_context = {"leaked": False}


class Passkey(MockFactor):
    name = "passkey"


class SlowRealLikeFactor(MockFactor):
    """Behaves like a real factor: it returns duration_ms = 0 and lets the core measure."""

    name = "password"

    async def verify(self, user_id, payload, ctx):
        return await super().verify(user_id, {**payload, "mock_duration_ms": 0}, ctx)


class CountingEnrollment(MockFactor):
    """Needs 3 enrollment samples, like keystroke needs 10."""

    name = "passkey"

    def __init__(self):
        super().__init__(enrolled=False)
        self.samples = 0

    async def enroll_start(self, user_id, ctx):
        return {"samples_needed": 3}

    async def enroll_finish(self, user_id, payload, ctx):
        if payload.get("sample") is None:
            return EnrollResult(done=False, reason="bad_payload")
        self.samples += 1
        if self.samples < 3:
            return EnrollResult(done=False, remaining=3 - self.samples)
        self.enrolled = True
        return EnrollResult(done=True, remaining=0)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    assert create_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def store():
    return LoginStore(fakeredis.FakeRedis(decode_responses=True))


@pytest.fixture
def client(db_session, store, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")

    def override_db():
        db = db_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_store] = lambda: store
    clear_registry()
    register(Password())
    register(Passkey())
    yield TestClient(app, headers={"User-Agent": LAPTOP_UA})
    app.dependency_overrides.clear()
    clear_registry()


def login(client, username="alice", accept=True):
    """Run a full password + passkey login; return the last response."""
    login_id = client.post("/auth/login/start", json={"username": username}).json()["login_id"]
    client.post(f"/auth/login/{login_id}/verify", json={"factor": "password", "payload": {"mock_accept": accept}})
    if not accept:
        return None
    return client.post(f"/auth/login/{login_id}/verify", json={"factor": "passkey", "payload": {"mock_accept": True}})


def rows(db_session):
    with db_session() as db:
        return db.scalars(select(Attempt).order_by(Attempt.timestamp)).all()


# --- known network and device -------------------------------------------------------------


def test_first_login_unknown_second_login_known(client, db_session):
    client.post("/auth/register", json={"username": "alice"})
    first = login(client)
    assert first.json()["status"] == "authenticated"
    assert DEVICE_COOKIE in first.cookies  # the browser gets a device cookie
    first_ctx = rows(db_session)[0].context["login"]
    assert (first_ctx["network"], first_ctx["known_device"]) == ("unknown", False)

    login(client)  # TestClient keeps cookies like a browser
    second_ctx = rows(db_session)[-1].context["login"]
    assert (second_ctx["network"], second_ctx["known_device"]) == ("known", True)
    with db_session() as db:
        assert len(db.scalars(select(KnownDevice)).all()) == 1  # same cookie reused, not a new device


def test_failed_login_does_not_make_device_known(client, db_session):
    client.post("/auth/register", json={"username": "alice"})
    login(client, accept=False)
    assert DEVICE_COOKIE not in client.cookies
    login(client)
    ctx = rows(db_session)[-1].context["login"]
    assert ctx["known_device"] is False  # only known from the NEXT login


def test_another_users_cookie_does_not_count(client, db_session):
    client.post("/auth/register", json={"username": "alice"})
    client.post("/auth/register", json={"username": "bob"})
    login(client, "alice")  # browser now has alice's device cookie
    login(client, "bob")
    bob_ctx = rows(db_session)[-1].context["login"]
    assert bob_ctx["known_device"] is False


# --- recent password failures --------------------------------------------------------------


def test_password_failures_are_counted_and_cleared(client, db_session, store):
    user_id = client.post("/auth/register", json={"username": "alice"}).json()["user_id"]
    login(client, accept=False)  # rejected once -> retry offered, login left open
    assert store.recent_failures(user_id) == 1
    assert rows(db_session)[-1].context["login"]["recent_failures"] == 1

    login(client)
    second_start_ctx = rows(db_session)[-2].context["login"]
    assert second_start_ctx["recent_failures"] == 1  # the next login sees the earlier failure
    assert store.recent_failures(user_id) == 0  # a successful login clears it


# --- measured duration ---------------------------------------------------------------------


def test_core_measures_duration_when_factor_returns_zero(client, db_session):
    clear_registry()
    register(SlowRealLikeFactor())
    register(Passkey())
    client.post("/auth/register", json={"username": "alice"})
    login(client)
    password_row = rows(db_session)[0]
    assert password_row.duration_ms >= 0 and password_row.factor == "password"
    assert rows(db_session)[1].duration_ms == 1000  # the mock's own value is kept


# --- study labels and export ------------------------------------------------------------------


def test_study_label_is_copied_into_attempt_rows(client, db_session):
    client.post("/auth/register", json={"username": "alice"})
    label = {"is_genuine": False, "attack_type": "credential_stuffing", "study_session_id": "S07"}
    assert client.put("/admin/study-label", json=label, headers=ADMIN).status_code == 200
    login(client)
    assert {(r.is_genuine, r.attack_type, r.study_session_id) for r in rows(db_session)} == {
        (False, "credential_stuffing", "S07")}

    client.delete("/admin/study-label", headers=ADMIN)
    login(client)
    assert rows(db_session)[-1].is_genuine is None  # normal use again


@pytest.mark.parametrize("label", [
    {"is_genuine": True, "attack_type": "printed_photo", "study_session_id": "S1"},  # genuine + attack
    {"is_genuine": False, "attack_type": "made_up_attack", "study_session_id": "S1"},  # unknown code
    {"is_genuine": True, "study_session_id": ""},  # no session id
])
def test_invalid_study_labels_are_refused(client, label):
    assert client.put("/admin/study-label", json=label, headers=ADMIN).status_code == 422


def test_admin_endpoints_need_the_token(client, monkeypatch):
    assert client.get("/admin/study-label").status_code == 403
    assert client.get("/admin/study-label", headers={"X-Admin-Token": "wrong"}).status_code == 403
    monkeypatch.setenv("ADMIN_TOKEN", "")
    assert client.get("/admin/study-label", headers=ADMIN).status_code == 503  # switched off


def test_attempts_csv_export(client):
    client.post("/auth/register", json={"username": "alice"})
    login(client)
    response = client.get("/admin/attempts.csv", headers=ADMIN)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    exported = list(csv.DictReader(io.StringIO(response.text)))
    assert [row["factor"] for row in exported] == ["password", "passkey"]
    assert exported[0]["selected_factors"] == '["password", "passkey"]'
    assert exported[0]["is_genuine"] == ""  # null -> empty cell


# --- enrollment ---------------------------------------------------------------------------------


def test_register_returns_a_session_for_enrollment(client):
    session = client.post("/auth/register", json={"username": "alice"}).json()["session"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {session}"})
    assert me.json()["username"] == "alice"


def test_enrollment_with_several_samples(client):
    clear_registry()
    register(Password())
    enrolling = register(CountingEnrollment())
    session = client.post("/auth/register", json={"username": "alice"}).json()["session"]
    auth = {"Authorization": f"Bearer {session}"}

    assert client.post("/auth/enroll/passkey/start", json={}, headers=auth).json() == {"samples_needed": 3}
    steps = [client.post("/auth/enroll/passkey/finish", json={"payload": {"sample": i}}, headers=auth).json()
             for i in range(3)]
    assert steps == [{"done": False, "remaining": 2, "reason": None},
                     {"done": False, "remaining": 1, "reason": None},
                     {"done": True, "remaining": 0, "reason": None}]
    assert enrolling.enrolled


def test_enrollment_needs_login_and_known_factor(client):
    assert client.post("/auth/enroll/password/start", json={}).status_code == 401
    session = client.post("/auth/register", json={"username": "alice"}).json()["session"]
    auth = {"Authorization": f"Bearer {session}"}
    assert client.post("/auth/enroll/voice/start", json={}, headers=auth).status_code == 404
    assert client.post("/auth/enroll/face/start", json={}, headers=auth).status_code == 404  # not registered
