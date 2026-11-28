"""Tests for M3's mock factors: password, passkey, keystroke."""

import asyncio
import json

import pytest

from app.factors.base import Factor, LoginContext
from app.factors.keystroke.mock import MockKeystroke
from app.factors.passkey.mock import MockPasskey
from app.factors.password.mock import MockPassword


def ctx(**fields) -> LoginContext:
    return LoginContext(**({"login_id": "L1", "device_type": "laptop"} | fields))


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.mark.parametrize("cls", [MockPassword, MockPasskey, MockKeystroke])
def test_mocks_follow_the_factor_interface(cls):
    factor = cls()
    assert isinstance(factor, Factor)
    challenge = run(factor.start("u1", ctx(webauthn_supported=True)))
    assert json.loads(json.dumps(challenge)) == challenge  # JSON-serialisable


def test_password_scores_and_leaked_flag():
    password = MockPassword()
    ok = run(password.verify("u1", {"mock_accept": True}, ctx()))
    assert (ok.factor, ok.accepted, ok.score, ok.context) == ("password", True, 1.0, {"leaked": False})

    leaked = run(password.verify("u1", {"mock_accept": True, "mock_leaked": True}, ctx()))
    assert leaked.accepted and leaked.context == {"leaked": True}

    wrong = run(password.verify("u1", {"mock_accept": False}, ctx()))
    assert (wrong.accepted, wrong.score, wrong.error) == (False, 0.0, None)
    assert run(password.start("u1", ctx())) == {}


def test_password_leaked_flag_does_not_leak_between_calls():
    password = MockPassword()
    run(password.verify("u1", {"mock_accept": True, "mock_leaked": True}, ctx()))
    again = run(password.verify("u1", {"mock_accept": True}, ctx()))
    assert again.context == {"leaked": False}


def test_passkey_needs_webauthn_and_reports_cancel():
    passkey = MockPasskey()
    assert passkey.is_available(ctx(webauthn_supported=True)) is True
    assert passkey.is_available(ctx(webauthn_supported=False)) is False

    ok = run(passkey.verify("u1", {"mock_accept": True}, ctx()))
    assert (ok.score, ok.context) == (1.0, {"user_verified": True})

    cancelled = run(passkey.verify("u1", {"mock_error": "cancelled"}, ctx()))
    assert (cancelled.accepted, cancelled.error) == (False, "cancelled")

    assert "options" in run(passkey.start("u1", ctx()))


def test_keystroke_laptop_only_and_biometric_scores():
    keystroke = MockKeystroke()
    assert keystroke.is_available(ctx(device_type="laptop")) is True
    assert keystroke.is_available(ctx(device_type="phone")) is False

    ok = run(keystroke.verify("u1", {"mock_accept": True}, ctx()))
    assert (ok.score, ok.context) == (0.9, {"n_keys": 11})
    assert run(keystroke.verify("u1", {"mock_accept": False}, ctx())).score == 0.1

    challenge = run(keystroke.start("u1", ctx()))
    assert challenge["mode"] == "with_password" and challenge["expected_keys"] == 11
