"""Real passkey factor. Week 5: registration (enrollment). Week 6: login (start / verify).

Implements the Factor interface (docs/interface.md §4) as designed in passkey/DESIGN.md, with the
py_webauthn library (no custom crypto). Until login is finished, is_available() returns False, so the
engine never selects the real passkey at login, but users can already register passkeys.

Registration, in short (DESIGN.md §3):
  enroll_start   make a random challenge, remember it in Redis (5 min, single use), return the options
                 the browser passes to navigator.credentials.create()
  enroll_finish  the browser sends back the new credential; py_webauthn checks the challenge, origin,
                 RP ID and the user-verified flag; we store the PUBLIC key and credential ID
"""

from __future__ import annotations

import json
import logging
import secrets

from webauthn import generate_registration_options, options_to_json, verify_registration_response
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import InvalidRegistrationResponse, WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.factors.base import EnrollResult, FactorResult, LoginContext
from app.factors.passkey.challenges import REGISTRATION_TTL_S, ChallengeStore
from app.factors.passkey.config import PasskeySettings
from app.factors.passkey.storage import PasskeyStore, SqlPasskeyStore, StoredCredential

logger = logging.getLogger(__name__)

LOGIN_READY = False  # week 6: set to True when start() / verify() are implemented
USER_HANDLE_BYTES = 32  # random, so the handle stored on the device says nothing about the user
REGISTRATION_TIMEOUT_MS = 120_000  # how long the browser prompt stays open
KNOWN_TRANSPORTS = {t.value for t in AuthenticatorTransport}


class PasskeyFactor:
    name = "passkey"

    def __init__(self, store: PasskeyStore | None = None, challenges: ChallengeStore | None = None,
                 settings: PasskeySettings | None = None) -> None:
        self.store = store or SqlPasskeyStore()
        self.challenges = challenges or ChallengeStore()
        self.settings = settings or PasskeySettings.from_env()

    async def is_enrolled(self, user_id: str) -> bool:
        return bool(self.store.credentials(user_id))

    def is_available(self, ctx: LoginContext) -> bool:
        # Week 6: `return ctx.webauthn_supported`. Until then the real passkey is never selected at login.
        return LOGIN_READY and ctx.webauthn_supported

    async def start(self, user_id: str, ctx: LoginContext) -> dict:
        return {}  # week 6: generate_authentication_options(...)

    async def verify(self, user_id: str, payload: dict, ctx: LoginContext) -> FactorResult:
        # Week 6: verify_authentication_response(...). Never selected before then (is_available).
        return FactorResult(factor=self.name, accepted=False, score=0.0, duration_ms=0, error="unavailable")

    # --- registration (week 5) ------------------------------------------------------------

    async def enroll_start(self, user_id: str, ctx: LoginContext) -> dict:
        """Registration options for @simplewebauthn/browser startRegistration() / credentials.create()."""
        existing = self.store.credentials(user_id)
        # All of a user's passkeys share one user handle; a new user gets a fresh random one.
        handle = existing[0].user_handle if existing else secrets.token_bytes(USER_HANDLE_BYTES)
        user_name = self.store.user_name(user_id)

        options = generate_registration_options(
            rp_id=self.settings.rp_id,
            rp_name=self.settings.rp_name,
            user_id=handle,
            user_name=user_name,
            user_display_name=user_name,
            timeout=REGISTRATION_TIMEOUT_MS,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,  # a real (discoverable) passkey where possible
                user_verification=UserVerificationRequirement.REQUIRED,  # fingerprint / face / PIN, not just a tap
            ),
            # attestation stays at the default "none": we do not need the device model (privacy, DESIGN.md §3).
            # The same device must not be registered twice for this user.
            exclude_credentials=[PublicKeyCredentialDescriptor(id=c.credential_id) for c in existing],
        )
        self.challenges.save("reg", user_id, {
            "challenge": bytes_to_base64url(options.challenge),
            "user_handle": bytes_to_base64url(handle),
        }, ttl_s=REGISTRATION_TTL_S)
        return {"options": json.loads(options_to_json(options))}

    async def enroll_finish(self, user_id: str, payload: dict, ctx: LoginContext) -> EnrollResult:
        """Check the new credential and store its public key. Reasons: see the table in UPLOAD.md."""
        # Take the challenge first, whatever the payload: every attempt uses it up (single use).
        pending = self.challenges.take("reg", user_id)
        if not isinstance(payload, dict):
            return EnrollResult(done=False, reason="bad_payload")
        if "client_error" in payload:
            # The browser prompt failed: NotAllowedError = user closed it or it timed out (DESIGN.md §6).
            return EnrollResult(done=False, reason="cancelled")
        credential = payload.get("credential")
        if not isinstance(credential, dict):
            return EnrollResult(done=False, reason="bad_payload")
        if pending is None:
            return EnrollResult(done=False, reason="expired")  # no enroll_start, too slow, or already used

        try:
            verified = verify_registration_response(
                credential=credential,
                expected_challenge=base64url_to_bytes(pending["challenge"]),
                expected_rp_id=self.settings.rp_id,
                expected_origin=list(self.settings.origins),
                require_user_verification=True,
            )
        except InvalidRegistrationResponse as error:
            # Well-formed but wrong: other challenge, other origin/RP ID (phishing page), no user verification.
            logger.info("passkey registration rejected for %s: %s", user_id, error)
            return EnrollResult(done=False, reason="rejected")
        except (WebAuthnException, ValueError, KeyError, TypeError) as error:
            logger.info("malformed passkey registration for %s: %s", user_id, error)
            return EnrollResult(done=False, reason="bad_payload")

        if self.store.credential_exists(verified.credential_id):
            return EnrollResult(done=False, reason="already_registered")

        self.store.add(StoredCredential(
            credential_id=verified.credential_id,
            user_id=user_id,
            user_handle=base64url_to_bytes(pending["user_handle"]),
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            transports=_transports(credential),
            backed_up=verified.credential_backed_up,
        ))
        return EnrollResult(done=True, remaining=0)


def _transports(credential: dict) -> list[str]:
    """The browser's hint how the device connects (used in allowCredentials at login). Unknown values dropped."""
    response = credential.get("response")
    values = response.get("transports") if isinstance(response, dict) else None
    if not isinstance(values, list):
        return []
    return [t for t in values if isinstance(t, str) and t in KNOWN_TRANSPORTS]
