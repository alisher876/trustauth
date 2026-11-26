"""Build the LoginContext for a new login (interface §3).

v1 (week 4): device type and browser from the User-Agent, IP, hour, what the browser
reports (camera, WebAuthn, light hint), and the history-based fields the caller looks up:
`network` / `known_device` (app.core.known) and `recent_failures` (Redis counter).
For an unknown username these stay at their safe defaults (unknown network, unknown device, 0).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel

from app.factors.base import LoginContext

# Asia/Tashkent is UTC+5 all year (no daylight saving), so a fixed offset is exact
# and needs no time-zone database in the Docker image.
TASHKENT = timezone(timedelta(hours=5))

_PHONE_MARKERS = ("Mobi", "Android", "iPhone", "iPad")
# Order matters: Edge and Opera also contain "Chrome", Chrome also contains "Safari".
_BROWSERS = (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"),
             ("Version/", "Safari"))


class ClientInfo(BaseModel):
    """What the browser reports at login start (interface §7, `client`)."""

    has_camera: bool = False
    webauthn_supported: bool = False
    light_hint: Literal["normal", "dim"] | None = None


def device_type(user_agent: str) -> Literal["laptop", "phone"]:
    """"phone" if the User-Agent looks like a mobile browser, otherwise "laptop"."""
    return "phone" if any(marker in user_agent for marker in _PHONE_MARKERS) else "laptop"


def browser_name(user_agent: str) -> str:
    """Browser and major version, e.g. "Chrome 131"; "unknown" if not recognised."""
    for marker, name in _BROWSERS:
        match = re.search(re.escape(marker) + r"(\d+)", user_agent)
        if match:
            return f"{name} {match.group(1)}"
    return "unknown"


def build_login_context(login_id: str, user_agent: str, ip: str, client: ClientInfo,
                        known_network: bool = False, known_device: bool = False, recent_failures: int = 0,
                        now: datetime | None = None) -> LoginContext:
    """LoginContext for one login. The history values are looked up by the caller; `now` is for tests."""
    now = now or datetime.now(TASHKENT)
    return LoginContext(
        login_id=login_id,
        device_type=device_type(user_agent),
        browser=browser_name(user_agent),
        ip=ip,
        network="known" if known_network else "unknown",
        known_device=known_device,
        hour=now.astimezone(TASHKENT).hour,
        has_camera=client.has_camera,
        webauthn_supported=client.webauthn_supported,
        light_hint=client.light_hint,
        recent_failures=recent_failures,
    )
