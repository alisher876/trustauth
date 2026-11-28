"""WebAuthn settings (passkey/DESIGN.md §2), read from environment variables.

WEBAUTHN_RP_ID      the domain the browser shows, WITHOUT scheme or port:
                    "localhost" for development, "<your-name>.ngrok-free.app" for phone tests
WEBAUTHN_ORIGIN     the full page address the browser shows (scheme + host + port), e.g.
                    "http://localhost:5173" or "https://<your-name>.ngrok-free.app".
                    Several origins may be given, separated by commas, but all must belong to RP_ID.
WEBAUTHN_RP_NAME    the name shown in the passkey prompt ("TrustAuth")

The browser refuses a passkey whose RP ID does not match the page's domain, and the server refuses
a response signed for another origin. These two checks are what makes passkeys phishing-resistant.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PasskeySettings:
    rp_id: str
    rp_name: str
    origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "PasskeySettings":
        rp_id = os.getenv("WEBAUTHN_RP_ID", "localhost").strip()
        origins = tuple(o.strip().rstrip("/") for o in os.getenv("WEBAUTHN_ORIGIN", "http://localhost:5173").split(",")
                        if o.strip())
        settings = cls(rp_id=rp_id, rp_name=os.getenv("WEBAUTHN_RP_NAME", "TrustAuth").strip(), origins=origins)
        settings.check()
        return settings

    def check(self) -> None:
        """Catch the most common set-up mistake early: an origin on a different domain than the RP ID."""
        if not self.rp_id or "/" in self.rp_id or ":" in self.rp_id:
            raise ValueError(f"WEBAUTHN_RP_ID must be a bare domain like 'localhost', got {self.rp_id!r}")
        if not self.origins:
            raise ValueError("WEBAUTHN_ORIGIN is empty")
        for origin in self.origins:
            host = origin.split("://", 1)[-1].split(":", 1)[0]
            if host != self.rp_id and not host.endswith("." + self.rp_id):
                raise ValueError(f"origin {origin!r} does not belong to WEBAUTHN_RP_ID {self.rp_id!r}")
            if not origin.startswith("https://") and host != "localhost":
                raise ValueError(f"origin {origin!r} must use https (only localhost may use http)")
