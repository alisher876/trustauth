"""Tests for app.factors.base: models, registry, FACTOR_MODE and the MockFactor helper."""

import asyncio

import pytest
from pydantic import ValidationError

from app.factors.base import (
    FACTOR_NAMES,
    EnrollResult,
    Factor,
    FactorResult,
    LoginContext,
    MockFactor,
    clear_registry,
    factor_mode,
    get_factor,
    register,
    registered_factors,
)


class MockFace(MockFactor):
    name = "face"
    binary = False
    mock_context = {"light": "normal", "liveness_passed": True}


class MockPassword(MockFactor):
    name = "password"
    mock_context = {"leaked": False}


@pytest.fixture(autouse=True)
def empty_registry():
    clear_registry()
    yield
    clear_registry()


def ctx(**overrides) -> LoginContext:
    return LoginContext(login_id="L1", device_type="laptop", **overrides)


def run(coroutine):
    return asyncio.run(coroutine)


# --- LoginContext ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({}, "laptop_normal"),
        ({"light_hint": "dim"}, "laptop_dim"),
        ({"light_hint": "dim", "light": "normal"}, "laptop_normal"),  # measured light wins
        ({"device_type": "phone", "light": "dim"}, "phone_dim"),
    ],
)
def test_condition_key(fields, expected):
    base = {"login_id": "L1", "device_type": "laptop"} | fields
    assert LoginContext(**base).condition == expected


def test_login_context_rejects_invalid_values():
    with pytest.raises(ValidationError):
        LoginContext(login_id="L1", device_type="tablet")
    with pytest.raises(ValidationError):
        LoginContext(login_id="L1", device_type="laptop", hour=24)


# --- FactorResult ----------------------------------------------------------------


def test_factor_result_valid_and_json_shape():
    result = FactorResult(factor="face", accepted=True, score=0.87, duration_ms=2400,
                          context={"light": "dim", "liveness_passed": True})
    assert result.model_dump() == {
        "factor": "face", "accepted": True, "score": 0.87, "duration_ms": 2400,
        "context": {"light": "dim", "liveness_passed": True}, "error": None,
    }


@pytest.mark.parametrize(
    "fields",
    [
        {"factor": "voice"},  # unknown factor
        {"score": 1.5},
        {"score": -0.1},
        {"duration_ms": -1},
        {"error": "exploded"},  # unknown error code
        {"accepted": True, "error": "timeout"},  # an error cannot be accepted
    ],
)
def test_factor_result_rejects_invalid(fields):
    base = {"factor": "password", "accepted": False, "score": 0.0, "duration_ms": 10}
    with pytest.raises(ValidationError):
        FactorResult(**(base | fields))


def test_enroll_result():
    assert EnrollResult(done=False, remaining=7).reason is None
    with pytest.raises(ValidationError):
        EnrollResult(done=False, remaining=-1)


# --- Registry ----------------------------------------------------------------------


def test_register_and_get():
    face = register(MockFace())
    assert get_factor("face") is face
    assert set(registered_factors()) == {"face"}
    assert isinstance(face, Factor)


def test_register_rejects_duplicates_unknown_names_and_non_factors():
    register(MockFace())
    with pytest.raises(ValueError):
        register(MockFace())

    class MockVoice(MockFactor):
        name = "voice"

    with pytest.raises(ValueError):
        register(MockVoice())
    with pytest.raises(TypeError):
        register(object())


def test_get_unknown_factor():
    with pytest.raises(KeyError):
        get_factor("password")


def test_all_five_factors_can_be_registered():
    for factor_name in FACTOR_NAMES:
        register(type(f"Mock_{factor_name}", (MockFactor,), {"name": factor_name})())
    assert set(registered_factors()) == set(FACTOR_NAMES)


# --- FACTOR_MODE -------------------------------------------------------------------


def test_factor_mode(monkeypatch):
    monkeypatch.delenv("FACTOR_MODE", raising=False)
    assert factor_mode() == "mock"
    monkeypatch.setenv("FACTOR_MODE", " Real ")
    assert factor_mode() == "real"
    monkeypatch.setenv("FACTOR_MODE", "fake")
    with pytest.raises(ValueError):
        factor_mode()


# --- MockFactor --------------------------------------------------------------------


def test_mock_accept_and_reject_scores():
    face, password = MockFace(), MockPassword()

    accepted = run(face.verify("u1", {"mock_accept": True, "mock_duration_ms": 2400}, ctx()))
    assert (accepted.accepted, accepted.score, accepted.duration_ms, accepted.error) == (True, 0.9, 2400, None)
    assert accepted.context == {"light": "normal", "liveness_passed": True}

    rejected = run(face.verify("u1", {"mock_accept": False}, ctx()))
    assert (rejected.accepted, rejected.score, rejected.error) == (False, 0.1, None)

    assert run(password.verify("u1", {"mock_accept": True}, ctx())).score == 1.0
    assert run(password.verify("u1", {}, ctx())).score == 0.0  # no flag = reject


def test_mock_error_paths():
    face = MockFace()
    timed_out = run(face.verify("u1", {"mock_error": "timeout"}, ctx()))
    assert (timed_out.accepted, timed_out.error, timed_out.context) == (False, "timeout", {})

    assert run(face.verify("u1", {"mock_error": "boom"}, ctx())).error == "bad_payload"
    assert run(face.verify("u1", "not a dict", ctx())).error == "bad_payload"
    assert run(face.verify("u1", {"mock_duration_ms": -5}, ctx())).error == "bad_payload"
    assert run(face.verify("u1", {"mock_accept": "yes"}, ctx())).accepted is False  # only true counts


def test_mock_enrollment_and_availability():
    face = MockFace(enrolled=False, available=False)
    assert run(face.is_enrolled("u1")) is False
    assert face.is_available(ctx()) is False
    assert run(face.verify("u1", {"mock_accept": True}, ctx())).error == "not_enrolled"

    assert run(face.enroll_start("u1", ctx()))["mock"] is True
    assert run(face.enroll_finish("u1", {}, ctx())) == EnrollResult(done=True, remaining=0)
    assert run(face.is_enrolled("u1")) is True


def test_start_is_json_serialisable():
    import json

    challenge = run(MockFace().start("u1", ctx()))
    assert json.loads(json.dumps(challenge)) == challenge
