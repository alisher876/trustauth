"""Mock keystroke factor (week 3). Stands in for the real typing-rhythm factor until weeks 8-11.

Same name, availability rule, start() shape and context keys as the real factor
(keystroke/DESIGN.md §7). Keystroke is only selected together with password
(interface §6.3); the core takes care of that, not this class.
"""

from app.factors.base import LoginContext, MockFactor

CMU_PASSWORD_KEYS = 11  # ".tie5Roanl" + Enter; the real value comes from the user's enrollment


class MockKeystroke(MockFactor):
    name = "keystroke"
    binary = False  # biometric: score 0.9 accepted / 0.1 rejected
    mock_context = {"n_keys": CMU_PASSWORD_KEYS}

    def is_available(self, ctx: LoginContext) -> bool:
        # v1: on-screen phone keyboards give unreliable timings (keystroke/DESIGN.md §6).
        return self.available and ctx.device_type == "laptop"

    async def start(self, user_id: str, ctx: LoginContext) -> dict:
        return {"mode": "with_password", "expected_keys": CMU_PASSWORD_KEYS, "mock": True}
