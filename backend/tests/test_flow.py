"""Tests for the challenge-loop decisions (app.core.flow) and the fixed selector (app.engine.selection)."""

import pytest

from app.core.flow import Decision, LoginProgress, decide
from app.engine.selection import select_fixed
from app.factors.base import FactorResult


def result(factor, accepted, error=None, **context):
    score = 1.0 if accepted else 0.0
    return FactorResult(factor=factor, accepted=accepted, score=score, duration_ms=100,
                        context=context, error=error)


def progress(plan=("password", "passkey"), spare=("face", "phone_approval")):
    return LoginProgress(plan=list(plan), spare=list(spare))


# --- selection -------------------------------------------------------------------


def test_fixed_selector_uses_preference_order():
    assert select_fixed(["face", "passkey", "password", "keystroke"]) == ["password", "passkey"]
    assert select_fixed(["phone_approval", "face"]) == ["face", "phone_approval"]
    assert select_fixed(["face"]) == ["face"]
    assert select_fixed(["keystroke"]) == []  # keystroke never alone
    with pytest.raises(ValueError):
        select_fixed(["password"], k=0)


# --- decisions ---------------------------------------------------------------------


def test_all_pass_authenticates():
    p = progress()
    assert decide(p, result("password", True)) == Decision("next", factor="passkey")
    assert decide(p, result("passkey", True)) == Decision("authenticated")
    assert p.passed == ["password", "passkey"]


def test_rejected_gets_one_retry_then_replaced():
    p = progress()
    assert decide(p, result("password", False)) == Decision("retry", factor="password", reason="rejected")
    assert decide(p, result("password", False)) == Decision("retry", factor="face", reason="replaced")
    assert p.plan == ["face", "passkey"] and p.failed == ["password"]
    # The replacement then works normally.
    assert decide(p, result("face", True)) == Decision("next", factor="passkey")


def test_retry_that_succeeds_continues():
    p = progress()
    decide(p, result("password", False))
    assert decide(p, result("password", True)) == Decision("next", factor="passkey")
    assert p.retries == 0  # reset for the next factor


def test_error_is_replaced_without_retry():
    p = progress()
    assert decide(p, result("password", False, error="timeout")) == Decision("retry", factor="face", reason="replaced")


def test_face_in_dim_light_is_replaced_without_retry():
    p = progress(plan=("face", "passkey"), spare=("password",))
    decision = decide(p, result("face", False, light="dim", liveness_passed=True))
    assert decision == Decision("retry", factor="password", reason="replaced")


def test_face_in_normal_light_gets_a_retry():
    p = progress(plan=("face", "passkey"), spare=("password",))
    assert decide(p, result("face", False, light="normal")).reason == "rejected"


def test_two_failed_factors_deny():
    p = progress()
    decide(p, result("password", False, error="timeout"))  # failed 1, replaced by face
    assert decide(p, result("face", False, error="unavailable")) == Decision("denied")


def test_denied_when_no_spare_left():
    p = progress(spare=())
    assert decide(p, result("password", False, error="cancelled")) == Decision("denied")


def test_spare_already_used_is_skipped():
    p = progress(plan=("password", "passkey"), spare=("passkey", "face"))
    assert decide(p, result("password", False, error="timeout")).factor == "face"


def test_result_for_wrong_factor_is_refused():
    with pytest.raises(ValueError):
        decide(progress(), result("face", True))


def test_progress_round_trips_through_dict():
    p = progress()
    decide(p, result("password", False))
    assert LoginProgress.from_dict(p.to_dict()) == p
