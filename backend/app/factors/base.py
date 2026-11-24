"""Shared factor contract: data models, the Factor interface, the registry and a mock helper.

This file implements docs/interface.md sections 2-5 (v0.2). Every factor
(password, passkey, keystroke, face, phone_approval) follows it, and the core
talks to factors only through it. Maintained by M4; changes need team agreement.
"""

from __future__ import annotations

import os
from typing import Any, Literal, Protocol, get_args, runtime_checkable

from pydantic import BaseModel, Field, model_validator

# --- Shared codes (interface §2, §5) ----------------------------------------

FactorName = Literal["password", "passkey", "phone_approval", "face", "keystroke"]
ErrorCode = Literal["not_enrolled", "unavailable", "timeout", "cancelled", "bad_payload", "internal"]

FACTOR_NAMES: tuple[str, ...] = get_args(FactorName)
ERROR_CODES: tuple[str, ...] = get_args(ErrorCode)

# Interface §2: a factor that can only be selected together with another one.
REQUIRES: dict[str, str] = {"keystroke": "password"}


# --- Data models --------------------------------------------------------------


class LoginContext(BaseModel):
    """Facts about one login, built by the core and passed to the engine and every factor (interface §3)."""

    login_id: str
    device_type: Literal["laptop", "phone"]
    browser: str = "unknown"
    ip: str = "0.0.0.0"
    network: Literal["known", "unknown"] = "unknown"
    known_device: bool = False
    hour: int = Field(default=12, ge=0, le=23)
    has_camera: bool = False
    webauthn_supported: bool = False
    light_hint: Literal["normal", "dim"] | None = None
    light: Literal["normal", "dim"] | None = None
    recent_failures: int = Field(default=0, ge=0)

    @property
    def condition(self) -> str:
        """Trust-table / log condition key, e.g. "phone_dim". Face's measured light wins over the hint."""
        return f"{self.device_type}_{self.light or self.light_hint or 'normal'}"


class FactorResult(BaseModel):
    """What every verify() returns (interface §5)."""

    factor: FactorName
    accepted: bool
    score: float = Field(ge=0.0, le=1.0)  # higher = more like the genuine user
    duration_ms: int = Field(ge=0)
    context: dict[str, Any] = Field(default_factory=dict)
    error: ErrorCode | None = None

    @model_validator(mode="after")
    def _error_means_not_accepted(self) -> "FactorResult":
        # An error means the factor could not complete, so it cannot have accepted the user.
        if self.error is not None and self.accepted:
            raise ValueError("a FactorResult with an error cannot be accepted")
        return self


class EnrollResult(BaseModel):
    """What enroll_finish() returns (interface §4). May take several calls (e.g. keystroke: 10 samples)."""

    done: bool
    remaining: int | None = Field(default=None, ge=0)
    reason: str | None = None  # e.g. "leaked", "too_few_good_frames"; shown to the user


# --- The contract every factor follows ---------------------------------------


@runtime_checkable
class Factor(Protocol):
    """Interface §4. Real factors and mocks both look like this."""

    name: FactorName

    async def is_enrolled(self, user_id: str) -> bool: ...

    def is_available(self, ctx: LoginContext) -> bool: ...

    async def start(self, user_id: str, ctx: LoginContext) -> dict: ...

    async def verify(self, user_id: str, payload: dict, ctx: LoginContext) -> FactorResult: ...

    async def enroll_start(self, user_id: str, ctx: LoginContext) -> dict: ...

    async def enroll_finish(self, user_id: str, payload: dict, ctx: LoginContext) -> EnrollResult: ...


# --- Registry -------------------------------------------------------------------

_registry: dict[str, Factor] = {}


def register(factor: Factor) -> Factor:
    """Add a factor so the core can find it by name. Returns the factor (handy as a one-liner)."""
    if not isinstance(factor, Factor):
        raise TypeError(f"{factor!r} does not implement the Factor interface")
    if factor.name not in FACTOR_NAMES:
        raise ValueError(f"unknown factor name {factor.name!r}; must be one of {FACTOR_NAMES}")
    if factor.name in _registry:
        raise ValueError(f"factor {factor.name!r} is already registered")
    _registry[factor.name] = factor
    return factor


def get_factor(name: str) -> Factor:
    """Look up a registered factor by name."""
    try:
        return _registry[name]
    except KeyError:
        raise KeyError(f"factor {name!r} is not registered") from None


def registered_factors() -> dict[str, Factor]:
    """A copy of the registry: {name: factor}."""
    return dict(_registry)


def clear_registry() -> None:
    """Remove all factors. For tests and for switching between mock and real mode."""
    _registry.clear()


def factor_mode() -> Literal["mock", "real"]:
    """FACTOR_MODE environment variable: "mock" (default until real factors exist) or "real"."""
    mode = os.getenv("FACTOR_MODE", "mock").strip().lower()
    if mode not in ("mock", "real"):
        raise ValueError(f"FACTOR_MODE must be 'mock' or 'real', got {mode!r}")
    return mode  # type: ignore[return-value]


# --- Mock helper -----------------------------------------------------------------


class MockFactor:
    """Base class for mock factors (interface §4, "Mocks").

    A factor owner subclasses it and sets `name`, `binary` and `mock_context`:

        class MockFace(MockFactor):
            name = "face"
            binary = False
            mock_context = {"light": "normal", "liveness_passed": True}

    verify() payload controls the outcome, so the core can test every path:
        {"mock_accept": true}               -> accepted
        {"mock_accept": false}              -> rejected (error=null)
        {"mock_error": "timeout"}           -> rejected with that error code
        {"mock_duration_ms": 2400}          -> duration to report (default 1000)
    """

    name: FactorName
    binary: bool = True  # True: score 1.0 / 0.0. False (biometric): 0.9 / 0.1
    mock_context: dict[str, Any] = {}

    def __init__(self, enrolled: bool = True, available: bool = True) -> None:
        self.enrolled = enrolled
        self.available = available

    async def is_enrolled(self, user_id: str) -> bool:
        return self.enrolled

    def is_available(self, ctx: LoginContext) -> bool:
        return self.available

    async def start(self, user_id: str, ctx: LoginContext) -> dict:
        return {"mock": True, "factor": self.name}

    async def verify(self, user_id: str, payload: dict, ctx: LoginContext) -> FactorResult:
        if not isinstance(payload, dict):
            return self._result(False, 0, "bad_payload")
        duration = payload.get("mock_duration_ms", 1000)
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
            return self._result(False, 0, "bad_payload")
        if not self.enrolled:
            return self._result(False, duration, "not_enrolled")
        error = payload.get("mock_error")
        if error is not None:
            if error not in ERROR_CODES:
                return self._result(False, duration, "bad_payload")
            return self._result(False, duration, error)
        return self._result(payload.get("mock_accept") is True, duration, None)

    async def enroll_start(self, user_id: str, ctx: LoginContext) -> dict:
        return {"mock": True, "factor": self.name}

    async def enroll_finish(self, user_id: str, payload: dict, ctx: LoginContext) -> EnrollResult:
        self.enrolled = True
        return EnrollResult(done=True, remaining=0)

    def _result(self, accepted: bool, duration_ms: int, error: str | None) -> FactorResult:
        if self.binary:
            score = 1.0 if accepted else 0.0
        else:
            score = 0.9 if accepted else 0.1
        # Errors mean the factor did not run, so its observations (context) are not reported.
        context = dict(self.mock_context) if error is None else {}
        return FactorResult(factor=self.name, accepted=accepted, score=score,
                            duration_ms=duration_ms, context=context, error=error)
