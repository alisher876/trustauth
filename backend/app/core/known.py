"""Known networks and known devices (context collector v1, interface §3).

network = "known"    the user has logged in successfully from this IP before
known_device = true  the browser sends a device cookie we gave this user after a successful login

Both are recorded only after a FULLY successful login, so an attacker cannot make their
network or browser "known" by failing logins.
"""

from __future__ import annotations

import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import KnownDevice, KnownNetwork, utc_now

DEVICE_COOKIE = "ta_device"
DEVICE_COOKIE_MAX_AGE_S = 180 * 24 * 60 * 60  # 180 days


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def is_known_network(db: Session, user_id: str, ip: str) -> bool:
    return db.scalar(select(KnownNetwork).where(KnownNetwork.user_id == user_id, KnownNetwork.ip == ip)) is not None


def is_known_device(db: Session, user_id: str, device_token: str | None) -> bool:
    """True only if the cookie exists AND was issued to this user (a cookie from another account does not count)."""
    if not device_token:
        return False
    device = db.scalar(select(KnownDevice).where(KnownDevice.token_hash == _hash(device_token)))
    return device is not None and device.user_id == user_id


def remember_login(db: Session, user_id: str, ip: str, device_token: str | None) -> str:
    """After a successful login: mark the IP and the device as known. Returns the device cookie value.

    Reuses the browser's cookie if it already belongs to this user, otherwise issues a new one.
    """
    now = utc_now()

    network = db.scalar(select(KnownNetwork).where(KnownNetwork.user_id == user_id, KnownNetwork.ip == ip))
    if network is None:
        db.add(KnownNetwork(user_id=user_id, ip=ip))
    else:
        network.last_seen = now

    device = None
    if device_token:
        device = db.scalar(select(KnownDevice).where(KnownDevice.token_hash == _hash(device_token)))
    if device is not None and device.user_id == user_id:
        device.last_seen = now
        token = device_token
    else:
        token = secrets.token_urlsafe(32)
        db.add(KnownDevice(user_id=user_id, token_hash=_hash(token)))

    db.commit()
    return token
