"""Tests for the real password factor: policy, leaked list, storage, factor, and a full API login."""

import asyncio

import fakeredis
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import create_tables, get_db
from app.core.login_store import LoginStore, get_store
from app.factors.base import Factor, LoginContext, MockFactor, clear_registry, register
from app.factors.password.factor import PasswordFactor
from app.factors.password.leaked import LeakedPasswordList
from app.factors.password.policy import policy_problem
from app.factors.password.storage import InMemoryPasswordStore, SqlPasswordStore
from app.main import app

# Weak argon2 settings so the tests run fast. The real factor uses argon2-cffi's defaults.
FAST = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
LEAKED = LeakedPasswordList({"password", "qwerty123", "iloveyou"})
CTX = LoginContext(login_id="L1", device_type="laptop")


def run(coroutine):
    return asyncio.run(coroutine)


def factor(store=None):
    return PasswordFactor(store=store or InMemoryPasswordStore(), leaked=LEAKED, hasher=FAST)


# --- policy and leaked list -----------------------------------------------------------------


@pytest.mark.parametrize(("password", "problem"), [
    ("short", "too_short"), ("x" * 8, None), ("x" * 128, None), ("x" * 129, "too_long"),
    ("correct horse battery staple", None),
])
def test_policy(password, problem):
    assert policy_problem(password) == problem


def test_leaked_list_exact_and_lowercase():
    assert LEAKED.contains("password") and LEAKED.contains("PassWord")
    assert not LEAKED.contains("correct horse battery staple")


def test_leaked_list_from_file(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("123456\npassword\n\nqwerty\r\n", encoding="utf-8")
    loaded = LeakedPasswordList.from_file(path)
    assert len(loaded) == 3 and loaded.contains("qwerty") and loaded.is_loaded


def test_missing_leaked_list_switches_the_check_off(tmp_path):
    loaded = LeakedPasswordList.from_file(tmp_path / "missing.txt")
    assert not loaded.is_loaded and not loaded.contains("password")


# --- the factor --------------------------------------------------------------------------------


def test_follows_the_factor_interface():
    assert isinstance(factor(), Factor)


def test_enroll_then_verify():
    password = factor()
    assert run(password.is_enrolled("u1")) is False
    assert run(password.enroll_start("u1", CTX)) == {"min_length": 8, "max_length": 128}
    assert run(password.enroll_finish("u1", {"password": "correct horse battery staple"}, CTX)).done
    assert run(password.is_enrolled("u1")) is True

    ok = run(password.verify("u1", {"password": "correct horse battery staple"}, CTX))
    assert (ok.accepted, ok.score, ok.error, ok.context, ok.duration_ms) == (True, 1.0, None, {"leaked": False}, 0)

    wrong = run(password.verify("u1", {"password": "wrong horse battery staple"}, CTX))
    assert (wrong.accepted, wrong.score, wrong.error) == (False, 0.0, None)


def test_only_a_hash_is_stored():
    store = InMemoryPasswordStore()
    run(factor(store).enroll_finish("u1", {"password": "correct horse battery staple"}, CTX))
    assert store.hashes["u1"].startswith("$argon2id$")
    assert "correct horse" not in store.hashes["u1"]


@pytest.mark.parametrize(("payload", "reason"), [
    ({"password": "short"}, "too_short"),
    ({"password": "x" * 129}, "too_long"),
    ({"password": "Password"}, "leaked"),  # 8 characters: passes the rules, caught case-insensitively
    ({"password": "qwerty123"}, "leaked"),
    ({"password": "IloveYou"}, "leaked"),
    ({}, "bad_payload"),
    ({"password": 12345678}, "bad_payload"),
])
def test_enrollment_refusals(payload, reason):
    result = run(factor().enroll_finish("u1", payload, CTX))
    assert (result.done, result.reason) == (False, reason)


@pytest.mark.parametrize("payload", [{}, {"password": ""}, {"password": 123}, {"password": "x" * 129}, "nope"])
def test_bad_verify_payloads(payload):
    password = factor()
    run(password.enroll_finish("u1", {"password": "correct horse battery staple"}, CTX))
    assert run(password.verify("u1", payload, CTX)).error == "bad_payload"


def test_not_enrolled():
    result = run(factor().verify("nobody", {"password": "whatever123"}, CTX))
    assert (result.accepted, result.error) == (False, "not_enrolled")


def test_password_that_became_leaked_still_logs_in_but_is_flagged():
    store = InMemoryPasswordStore()
    run(factor(store).enroll_finish("u1", {"password": "correct horse battery staple"}, CTX))
    newer_list = LeakedPasswordList({"correct horse battery staple"})  # the list grew after registration
    later = PasswordFactor(store=store, leaked=newer_list, hasher=FAST)
    result = run(later.verify("u1", {"password": "correct horse battery staple"}, CTX))
    assert result.accepted and result.context == {"leaked": True}


def test_old_hash_is_upgraded_after_a_correct_login():
    store = InMemoryPasswordStore()
    run(factor(store).enroll_finish("u1", {"password": "correct horse battery staple"}, CTX))
    old_hash = store.hashes["u1"]
    stronger = PasswordFactor(store=store, leaked=LEAKED, hasher=PasswordHasher(time_cost=2, memory_cost=16, parallelism=1))
    assert run(stronger.verify("u1", {"password": "correct horse battery staple"}, CTX)).accepted
    assert store.hashes["u1"] != old_hash and "t=2" in store.hashes["u1"]


def test_damaged_hash_is_an_internal_error():
    store = InMemoryPasswordStore()
    store.set_hash("u1", "not an argon2 hash")
    assert run(factor(store).verify("u1", {"password": "correct horse battery staple"}, CTX)).error == "internal"


# --- SQL storage and a full login through the API ----------------------------------------------


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    assert create_tables(engine)  # includes password_credentials: storage.py was imported above
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_sql_store(db_session):
    store = SqlPasswordStore(db_session)
    assert store.get_hash("u1") is None
    store.set_hash("u1", "$argon2id$first")
    store.set_hash("u1", "$argon2id$second")
    assert store.get_hash("u1") == "$argon2id$second"


class Passkey(MockFactor):
    name = "passkey"


def test_register_enroll_and_login_with_the_real_password(db_session):
    def override_db():
        db = db_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    store = LoginStore(fakeredis.FakeRedis(decode_responses=True))
    app.dependency_overrides[get_store] = lambda: store
    clear_registry()
    register(PasswordFactor(store=SqlPasswordStore(db_session), leaked=LEAKED, hasher=FAST))
    register(Passkey())
    client = TestClient(app, headers={"User-Agent": "Mozilla/5.0 Chrome/131.0"})
    try:
        auth = {"Authorization": "Bearer " + client.post("/auth/register", json={"username": "alice"}).json()["session"]}
        refused = client.post("/auth/enroll/password/finish", json={"payload": {"password": "qwerty123"}}, headers=auth)
        assert refused.json()["reason"] == "leaked"
        enrolled = client.post("/auth/enroll/password/finish",
                               json={"payload": {"password": "correct horse battery staple"}}, headers=auth)
        assert enrolled.json()["done"] is True

        login_id = client.post("/auth/login/start", json={"username": "alice"}).json()["login_id"]
        wrong = client.post(f"/auth/login/{login_id}/verify",
                            json={"factor": "password", "payload": {"password": "nope nope nope"}}).json()
        assert wrong["status"] == "retry" and wrong["reason"] == "rejected"
        right = client.post(f"/auth/login/{login_id}/verify",
                            json={"factor": "password", "payload": {"password": "correct horse battery staple"}}).json()
        assert right["status"] == "next"
        done = client.post(f"/auth/login/{login_id}/verify",
                           json={"factor": "passkey", "payload": {"mock_accept": True}}).json()
        assert done["status"] == "authenticated"
    finally:
        app.dependency_overrides.clear()
        clear_registry()
