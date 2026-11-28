"""Real password factor (week 4): argon2id hashing + leaked-password check.

Implements the Factor interface (docs/interface.md §4) as designed in password/DESIGN.md.
The password itself is never stored, logged or put into a FactorResult.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.factors.base import EnrollResult, FactorResult, LoginContext
from app.factors.password.leaked import LeakedPasswordList
from app.factors.password.policy import MAX_LENGTH, MIN_LENGTH, policy_problem
from app.factors.password.storage import PasswordStore, SqlPasswordStore

# argon2-cffi's defaults = RFC 9106 "low-memory" profile: argon2id, time_cost=3,
# memory_cost=64 MiB, parallelism=4, 32-byte hash, 16-byte random salt (DESIGN.md §1).
_hasher = PasswordHasher()

# A fixed hash to verify against when the user has no password, so "not enrolled" takes
# about as long as a wrong password and response time does not reveal it (DESIGN.md §1).
_DUMMY_HASH = _hasher.hash("dummy password, never matches any real one")


class PasswordFactor:
    name = "password"

    def __init__(self, store: PasswordStore | None = None, leaked: LeakedPasswordList | None = None,
                 hasher: PasswordHasher = _hasher) -> None:
        self.store = store or SqlPasswordStore()
        self.leaked = leaked if leaked is not None else LeakedPasswordList.from_file()
        self.hasher = hasher

    async def is_enrolled(self, user_id: str) -> bool:
        return self.store.get_hash(user_id) is not None

    def is_available(self, ctx: LoginContext) -> bool:
        return True  # every browser can type a password

    async def start(self, user_id: str, ctx: LoginContext) -> dict:
        return {}  # the password screen needs no challenge data

    async def verify(self, user_id: str, payload: dict, ctx: LoginContext) -> FactorResult:
        password = payload.get("password") if isinstance(payload, dict) else None
        if not isinstance(password, str) or not password or len(password) > MAX_LENGTH:
            return self._result(False, error="bad_payload")

        stored = self.store.get_hash(user_id)
        if stored is None:
            self._verify_quietly(_DUMMY_HASH, password)  # same work as a real check
            return self._result(False, error="not_enrolled")

        try:
            self.hasher.verify(stored, password)
        except VerifyMismatchError:
            return self._result(False)  # wrong password: the factor ran, the user failed
        except (VerificationError, InvalidHashError):
            return self._result(False, error="internal")  # the stored hash is damaged

        # Correct password. Upgrade the hash if our argon2 parameters were raised since it was made.
        if self.hasher.check_needs_rehash(stored):
            self.store.set_hash(user_id, self.hasher.hash(password))
        return self._result(True, leaked=self.leaked.contains(password))

    async def enroll_start(self, user_id: str, ctx: LoginContext) -> dict:
        return {"min_length": MIN_LENGTH, "max_length": MAX_LENGTH}

    async def enroll_finish(self, user_id: str, payload: dict, ctx: LoginContext) -> EnrollResult:
        """Set (or change) the password: rules first, then the leaked list, then hash and store."""
        password = payload.get("password") if isinstance(payload, dict) else None
        if not isinstance(password, str):
            return EnrollResult(done=False, reason="bad_payload")
        problem = policy_problem(password)
        if problem is not None:
            return EnrollResult(done=False, reason=problem)
        if self.leaked.contains(password):
            return EnrollResult(done=False, reason="leaked")
        self.store.set_hash(user_id, self.hasher.hash(password))
        return EnrollResult(done=True, remaining=0)

    def _verify_quietly(self, password_hash: str, password: str) -> None:
        try:
            self.hasher.verify(password_hash, password)
        except VerificationError:
            pass

    def _result(self, accepted: bool, error: str | None = None, leaked: bool = False) -> FactorResult:
        # duration_ms = 0: the core measures the time from challenge to answer (interface §5).
        context = {"leaked": leaked} if error is None else {}
        return FactorResult(factor=self.name, accepted=accepted, score=1.0 if accepted else 0.0,
                            duration_ms=0, context=context, error=error)
