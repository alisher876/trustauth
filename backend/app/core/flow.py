"""Challenge-loop decisions: what happens after each factor result.

Pure logic (no database, Redis or HTTP), so every rule can be unit-tested.
Implements the retry and fallback rules of docs/interface.md §7 (v0.2, [confirm]):

1. A rejected factor (accepted=false, error=null) gets 1 retry.
2. After the retry fails, or after an error, the factor is replaced by the next
   usable factor that has not been used yet.
3. Face rejected in dim light is replaced straight away, without a retry.
4. The login is denied once 2 different factors have failed (or nothing is left to try).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from app.factors.base import FactorResult

MAX_FAILED_FACTORS = 2
MAX_RETRIES_PER_FACTOR = 1

Status = Literal["next", "retry", "authenticated", "denied"]


@dataclass
class LoginProgress:
    """Where one login stands. Stored in Redis between requests (as a dict)."""

    plan: list[str]  # the factors to pass, in order (a failed one gets replaced in place)
    spare: list[str]  # usable factors not in the plan, in preference order (for replacements)
    position: int = 0  # index in `plan` of the factor being asked now
    retries: int = 0  # retries used for the current factor
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def current(self) -> str:
        return self.plan[self.position]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LoginProgress":
        return cls(**data)


@dataclass(frozen=True)
class Decision:
    status: Status
    factor: str | None = None  # the factor to ask next (for "next" and "retry")
    reason: str | None = None  # for "retry": "rejected" (same factor) or "replaced" (another factor)


def decide(progress: LoginProgress, result: FactorResult) -> Decision:
    """Update `progress` with one factor result and return what the browser should do next.

    `progress` is changed in place (the caller saves it).
    """
    if result.factor != progress.current:
        raise ValueError(f"result is for {result.factor!r}, but {progress.current!r} was asked")

    # Passed: move on, or finish.
    if result.accepted:
        progress.passed.append(progress.current)
        progress.position += 1
        progress.retries = 0
        if progress.position >= len(progress.plan):
            return Decision("authenticated")
        return Decision("next", factor=progress.current)

    # Rejected while the factor ran normally: one retry, except face in dim light (rule 3).
    dim_face = result.factor == "face" and result.context.get("light") == "dim"
    if result.error is None and progress.retries < MAX_RETRIES_PER_FACTOR and not dim_face:
        progress.retries += 1
        return Decision("retry", factor=progress.current, reason="rejected")

    # This factor has failed for this login.
    progress.failed.append(progress.current)
    if len(progress.failed) >= MAX_FAILED_FACTORS:
        return Decision("denied")

    replacement = _next_spare(progress)
    if replacement is None:
        return Decision("denied")
    progress.plan[progress.position] = replacement
    progress.retries = 0
    return Decision("retry", factor=replacement, reason="replaced")


def _next_spare(progress: LoginProgress) -> str | None:
    """Take the first spare factor not already used in this login."""
    used = set(progress.plan) | set(progress.passed) | set(progress.failed)
    while progress.spare:
        candidate = progress.spare.pop(0)
        if candidate not in used:
            return candidate
    return None
