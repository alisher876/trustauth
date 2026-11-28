"""A software authenticator for tests: it does what a phone or Windows Hello does at registration.

It makes a real P-256 key pair and a real WebAuthn registration response ("none" attestation), so the
tests run py_webauthn's actual checks: challenge, origin, RP ID hash, flags, public key format.
Built from the WebAuthn spec (https://www.w3.org/TR/webauthn-2/#sctn-attestation):

    authenticatorData = SHA-256(rp_id) | flags | sign_count | AAGUID | len(cred_id) | cred_id | COSE key
    attestationObject = CBOR {"fmt": "none", "attStmt": {}, "authData": authenticatorData}
    clientDataJSON    = {"type": "webauthn.create", "challenge": ..., "origin": ...}

Only for tests: real devices keep the private key in secure hardware.
"""

from __future__ import annotations

import hashlib
import json
import secrets

import cbor2
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url

FLAG_UP = 0x01  # user present (touched the device)
FLAG_UV = 0x04  # user verified (fingerprint / face / PIN)
FLAG_BE = 0x08  # backup eligible (synced passkey)
FLAG_BS = 0x10  # backed up
FLAG_AT = 0x40  # attested credential data included


class SoftAuthenticator:
    def __init__(self) -> None:
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(16)

    def _cose_public_key(self) -> bytes:
        numbers = self.private_key.public_key().public_numbers()
        # COSE_Key: kty=2 (EC2), alg=-7 (ES256), crv=1 (P-256), x, y
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    def create(self, options: dict, origin: str, *, rp_id: str | None = None, user_verified: bool = True,
               synced: bool = False, challenge: str | None = None, transports=("internal",)) -> dict:
        """The JSON the browser sends after navigator.credentials.create(), for these server options.

        The keyword arguments make broken responses for the tests: another RP ID or challenge,
        no user verification. `origin` is the page the "browser" is on (a phishing page has another one).
        """
        flags = FLAG_UP | FLAG_AT | (FLAG_UV if user_verified else 0) | (FLAG_BE | FLAG_BS if synced else 0)
        auth_data = (
            hashlib.sha256((rp_id or options["rp"]["id"]).encode()).digest()
            + bytes([flags])
            + (0).to_bytes(4, "big")  # sign count
            + bytes(16)  # AAGUID: all zeros, as with "none" attestation
            + len(self.credential_id).to_bytes(2, "big")
            + self.credential_id
            + self._cose_public_key()
        )
        client_data = json.dumps({
            "type": "webauthn.create",
            "challenge": challenge or options["challenge"],
            "origin": origin,
            "crossOrigin": False,
        }).encode()
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        credential_id = bytes_to_base64url(self.credential_id)
        return {
            "id": credential_id,
            "rawId": credential_id,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": list(transports),
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }
