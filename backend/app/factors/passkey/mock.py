"""Mock passkey factor (week 3). Stands in for the real WebAuthn factor until weeks 5-6.

Same name, availability rule, start() shape and context keys as the real factor
(passkey/DESIGN.md §6). The outcome is chosen by the request; see MockFactor in
app/factors/base.py ({"mock_accept": true}, {"mock_error": "cancelled"}, ...).
"""

from app.factors.base import LoginContext, MockFactor


class MockPasskey(MockFactor):
    name = "passkey"
    binary = True
    mock_context = {"user_verified": True}

    def is_available(self, ctx: LoginContext) -> bool:
        # The real factor needs a browser with WebAuthn support.
        return self.available and ctx.webauthn_supported

    async def start(self, user_id: str, ctx: LoginContext) -> dict:
        # Same shape as the real start(): WebAuthn options. The values are fake.
        return {
            "options": {
                "challenge": "mock-challenge",
                "rpId": "localhost",
                "allowCredentials": [],
                "userVerification": "required",
            },
            "mock": True,
        }
