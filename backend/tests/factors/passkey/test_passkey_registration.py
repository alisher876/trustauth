"""Passkey registration (week 5): PasskeyFactor.enroll_start / enroll_finish.

Uses SoftAuthenticator (a software "device") so py_webauthn runs its real checks, fakeredis for the
challenges, and in-memory / SQLite stores. No browser, phone or network needed.
"""

import asyncio

import fakeredis
import pytest
from fastapi.testclient import TestClient
from webauthn.helpers import bytes_to_base64url
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import create_tables, get_db
from app.core.login_store import LoginStore, get_store
from app.factors.base import LoginContext, MockFactor, clear_registry, register
from app.factors.passkey.challenges import ChallengeStore
from app.factors.passkey.config import PasskeySettings
from app.factors.passkey.factor import PasskeyFactor
from app.factors.passkey.storage import InMemoryPasskeyStore, SqlPasskeyStore, StoredCredential
from app.main import app
from tests.factors.passkey.soft_authenticator import SoftAuthenticator

ORIGIN = "http://localhost:5173"
SETTINGS = PasskeySettings(rp_id="localhost", rp_name="TrustAuth", origins=(ORIGIN,))
CTX = LoginContext(login_id="enroll-1", device_type="laptop", webauthn_supported=True)
USER = "u_0123456789abcdef"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def store():
    s = InMemoryPasskeyStore()
    s.names[USER] = "alice"
    return s


@pytest.fixture
def factor(store):
    return PasskeyFactor(store=store, challenges=ChallengeStore(fakeredis.FakeRedis(decode_responses=True)),
                         settings=SETTINGS)


def register_device(factor, device=None, user=USER, **create_args):
    """enroll_start -> device creates a credential -> enroll_finish. Returns (EnrollResult, options)."""
    device = device or SoftAuthenticator()
    options = run(factor.enroll_start(user, CTX))["options"]
    credential = device.create(options, create_args.pop("origin", ORIGIN), **create_args)
    return run(factor.enroll_finish(user, {"credential": credential}, CTX)), options


# --- enroll_start ------------------------------------------------------------------------------


def test_options_follow_the_design(factor):
    options = run(factor.enroll_start(USER, CTX))["options"]
    assert options["rp"] == {"id": "localhost", "name": "TrustAuth"}
    assert options["user"]["name"] == "alice" and options["user"]["displayName"] == "alice"
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert options["authenticatorSelection"]["residentKey"] == "preferred"
    assert options["attestation"] == "none"
    assert options["excludeCredentials"] == []
    assert len(options["challenge"]) >= 43  # at least 32 random bytes, base64url


def test_user_handle_is_random_not_the_username(factor):
    options = run(factor.enroll_start(USER, CTX))["options"]
    assert "alice" not in options["user"]["id"] and USER not in options["user"]["id"]


def test_every_start_gets_a_new_challenge(factor):
    first = run(factor.enroll_start(USER, CTX))["options"]["challenge"]
    second = run(factor.enroll_start(USER, CTX))["options"]["challenge"]
    assert first != second


# --- enroll_finish: success ------------------------------------------------------------------


def test_registration_stores_the_public_key(factor, store):
    assert run(factor.is_enrolled(USER)) is False
    result, options = register_device(factor)
    assert (result.done, result.remaining, result.reason) == (True, 0, None)
    assert run(factor.is_enrolled(USER)) is True

    [saved] = store.credentials(USER)
    assert saved.public_key and saved.sign_count == 0
    assert saved.transports == ["internal"]
    assert saved.backed_up is False
    assert bytes_to_base64url(saved.user_handle) == options["user"]["id"]  # the handle the device got


def test_synced_passkey_is_marked_backed_up(factor, store):
    register_device(factor, synced=True)
    assert store.credentials(USER)[0].backed_up is True


def test_second_device_keeps_the_user_handle_and_excludes_the_first(factor, store):
    first_device = SoftAuthenticator()
    register_device(factor, first_device)
    options = run(factor.enroll_start(USER, CTX))["options"]
    assert [c["id"] for c in options["excludeCredentials"]] == [bytes_to_base64url(first_device.credential_id)]

    credential = SoftAuthenticator().create(options, ORIGIN)
    assert run(factor.enroll_finish(USER, {"credential": credential}, CTX)).done is True
    handles = {c.user_handle for c in store.credentials(USER)}
    assert len(store.credentials(USER)) == 2 and len(handles) == 1


def test_unknown_transports_are_dropped(factor, store):
    register_device(factor, transports=("internal", "hybrid", "carrier-pigeon"))
    assert store.credentials(USER)[0].transports == ["internal", "hybrid"]


# --- enroll_finish: refused ------------------------------------------------------------------


def test_phishing_origin_is_rejected(factor, store):
    # A copy of our page on another site: the browser signs ITS origin, the server expects ours.
    result, _ = register_device(factor, origin="https://trustauth-login.example.com")
    assert (result.done, result.reason) == (False, "rejected")
    assert store.credentials(USER) == []


def test_other_rp_id_is_rejected(factor):
    result, _ = register_device(factor, rp_id="evil.example.com")
    assert result.reason == "rejected"


def test_no_user_verification_is_rejected(factor):
    # Only a tap, no fingerprint / face / PIN: we require user verification.
    result, _ = register_device(factor, user_verified=False)
    assert result.reason == "rejected"


def test_response_for_another_challenge_is_rejected(factor):
    result, _ = register_device(factor, challenge="QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE")
    assert result.reason == "rejected"


def test_challenge_can_be_used_only_once(factor, store):
    options = run(factor.enroll_start(USER, CTX))["options"]
    credential = SoftAuthenticator().create(options, ORIGIN)
    assert run(factor.enroll_finish(USER, {"credential": credential}, CTX)).done is True
    replay = run(factor.enroll_finish(USER, {"credential": credential}, CTX))  # captured and sent again
    assert (replay.done, replay.reason) == (False, "expired")
    assert len(store.credentials(USER)) == 1


def test_finish_without_start_is_expired(factor):
    credential = SoftAuthenticator().create({"rp": {"id": "localhost"}, "challenge": "abc"}, ORIGIN)
    assert run(factor.enroll_finish(USER, {"credential": credential}, CTX)).reason == "expired"


def test_challenge_of_another_user_does_not_count(factor):
    options = run(factor.enroll_start("u_someone_else", CTX))["options"]
    credential = SoftAuthenticator().create(options, ORIGIN)
    assert run(factor.enroll_finish(USER, {"credential": credential}, CTX)).reason == "expired"


def test_same_credential_for_another_user_is_refused(factor, store):
    device = SoftAuthenticator()
    register_device(factor, device)
    store.names["u_bob"] = "bob"
    result, _ = register_device(factor, device, user="u_bob")
    assert result.reason == "already_registered"


def test_browser_cancel(factor):
    run(factor.enroll_start(USER, CTX))
    result = run(factor.enroll_finish(USER, {"client_error": "NotAllowedError"}, CTX))
    assert (result.done, result.reason) == (False, "cancelled")


@pytest.mark.parametrize("payload", [
    {},
    {"credential": "not an object"},
    {"credential": {"id": "x"}},
])
def test_malformed_payloads(factor, payload):
    run(factor.enroll_start(USER, CTX))
    assert run(factor.enroll_finish(USER, payload, CTX)).reason == "bad_payload"


def test_garbage_response_data_is_rejected(factor, store):
    # Right shape, unreadable content: py_webauthn refuses it as an invalid registration.
    run(factor.enroll_start(USER, CTX))
    garbage = {"id": "AAAA", "rawId": "AAAA", "type": "public-key",
               "response": {"clientDataJSON": "!!!", "attestationObject": "!!!"}}
    assert run(factor.enroll_finish(USER, {"credential": garbage}, CTX)).reason == "rejected"
    assert store.credentials(USER) == []


# --- login is week 6 -----------------------------------------------------------------------------


def test_not_selected_at_login_before_week_6(factor):
    assert factor.is_available(CTX) is False
    result = run(factor.verify(USER, {}, CTX))
    assert (result.accepted, result.error) == (False, "unavailable")


# --- settings ----------------------------------------------------------------------------------------


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("WEBAUTHN_RP_ID", "trustauth-demo.ngrok-free.app")
    monkeypatch.setenv("WEBAUTHN_ORIGIN", "https://trustauth-demo.ngrok-free.app/")
    settings = PasskeySettings.from_env()
    assert settings.origins == ("https://trustauth-demo.ngrok-free.app",)  # trailing slash removed


@pytest.mark.parametrize(("rp_id", "origin"), [
    ("localhost", "https://trustauth-demo.ngrok-free.app"),  # origin on another domain
    ("trustauth-demo.ngrok-free.app", "http://trustauth-demo.ngrok-free.app"),  # http on a real domain
    ("https://localhost", "http://localhost:5173"),  # RP ID with a scheme
    ("localhost:5173", "http://localhost:5173"),  # RP ID with a port
])
def test_bad_settings_are_refused(monkeypatch, rp_id, origin):
    monkeypatch.setenv("WEBAUTHN_RP_ID", rp_id)
    monkeypatch.setenv("WEBAUTHN_ORIGIN", origin)
    with pytest.raises(ValueError):
        PasskeySettings.from_env()


# --- SQL store (SQLite in memory) --------------------------------------------------------------------


def test_sql_store_round_trip():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    assert create_tables(engine)
    sql = SqlPasskeyStore(sessionmaker(bind=engine, expire_on_commit=False))
    assert sql.credentials(USER) == [] and sql.user_name(USER) == USER  # unknown user: the id
    sql.add(StoredCredential(credential_id=b"\x01\x02", user_id=USER, user_handle=b"h" * 32, public_key=b"pk",
                             transports=["internal"], backed_up=True))
    assert sql.credential_exists(b"\x01\x02") and not sql.credential_exists(b"\x09")
    [row] = sql.credentials(USER)
    assert (row.public_key, row.transports, row.backed_up) == (b"pk", ["internal"], True)


# --- through the API: register -> enroll a passkey ---------------------------------------------------


class Password(MockFactor):
    name = "password"


def test_register_and_enroll_a_passkey_through_the_api():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    assert create_tables(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    redis = fakeredis.FakeRedis(decode_responses=True)

    def override_db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_store] = lambda: LoginStore(redis)
    clear_registry()
    register(Password())
    register(PasskeyFactor(store=SqlPasskeyStore(sessions), challenges=ChallengeStore(redis), settings=SETTINGS))
    try:
        client = TestClient(app)
        session = client.post("/auth/register", json={"username": "alice"}).json()["session"]
        auth = {"Authorization": f"Bearer {session}"}

        options = client.post("/auth/enroll/passkey/start", json={"client": {"webauthn_supported": True}},
                              headers=auth).json()["options"]
        assert options["user"]["name"] == "alice"  # looked up from the users table
        credential = SoftAuthenticator().create(options, ORIGIN)
        done = client.post("/auth/enroll/passkey/finish", json={"payload": {"credential": credential}}, headers=auth)
        assert done.json() == {"done": True, "remaining": 0, "reason": None}
    finally:
        app.dependency_overrides.clear()
        clear_registry()
