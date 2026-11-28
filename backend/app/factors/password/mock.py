"""Mock password factor (week 3). Stands in for the real argon2 factor until week 4.

Behaves like the real factor from the outside (same name, start() data and
FactorResult context keys), but the outcome is chosen by the request:
    {"mock_accept": true}            -> correct password
    {"mock_accept": false}           -> wrong password
    {"mock_accept": true, "mock_leaked": true} -> correct, but found in the leaked list
See MockFactor in app/factors/base.py for mock_error and mock_duration_ms.
"""

from app.factors.base import FactorResult, LoginContext, MockFactor


class MockPassword(MockFactor):
    name = "password"
    binary = True  # score 1.0 / 0.0, like the real factor
    mock_context = {"leaked": False}

    def is_available(self, ctx: LoginContext) -> bool:
        # Every browser can type a password (password/DESIGN.md §5).
        return self.available

    async def start(self, user_id: str, ctx: LoginContext) -> dict:
        # The real password screen needs no challenge data (interface §6.3).
        return {}

    async def verify(self, user_id: str, payload: dict, ctx: LoginContext) -> FactorResult:
        result = await super().verify(user_id, payload, ctx)
        if result.error is None and payload.get("mock_leaked") is True:
            result.context["leaked"] = True
        return result
