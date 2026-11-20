"""Bounded device-pairing clock skew; all proof and expiry checks stay fail closed."""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from kicad_mcp import cloud_pair

_NOW_MS = 1_795_199_000_000
_CHALLENGE = "11111111-1111-4111-8111-111111111111"


def _valid_response(key: Ed25519PrivateKey, expires_at_ms: object) -> dict[str, object]:
    public = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return {
        "challengeId": _CHALLENGE,
        "userCode": "ABCDEF-123456",
        "deviceCode": "A" * 43,
        "deviceFingerprint": hashlib.sha256(public).hexdigest(),
        "expiresAtMs": expires_at_ms,
    }


@pytest.mark.parametrize("server_clock_ahead_ms", [0, 183, 29_999, 30_000])
def test_pairing_challenge_tolerates_bounded_server_clock_offset(
    server_clock_ahead_ms: int,
) -> None:
    """Live Windows failure was 183 ms above the exact five-minute TTL cap."""
    key = Ed25519PrivateKey.generate()
    expires = _NOW_MS + 300_000 + server_clock_ahead_ms
    with patch.object(cloud_pair.time, "time_ns", return_value=_NOW_MS * 1_000_000):
        challenge, code, secret, fingerprint, expiration = cloud_pair._challenge(
            _valid_response(key, expires), key
        )
    assert (challenge, code, secret, expiration) == (_CHALLENGE, "ABCDEF-123456", "A" * 43, expires)
    assert fingerprint == _valid_response(key, expires)["deviceFingerprint"]


@pytest.mark.parametrize(
    "expires_at",
    [_NOW_MS, _NOW_MS - 1, _NOW_MS + 330_001, _NOW_MS + 600_000, True, 1.5],
)
def test_pairing_rejects_expired_excessively_future_or_noninteger_deadlines(
    expires_at: object,
) -> None:
    key = Ed25519PrivateKey.generate()
    response = _valid_response(key, expires_at)
    with patch.object(cloud_pair.time, "time_ns", return_value=_NOW_MS * 1_000_000):
        with pytest.raises(cloud_pair.CloudPairingError, match="pairing denied"):
            cloud_pair._challenge(response, key)


def test_pairing_rejects_forged_key_even_inside_clock_tolerance() -> None:
    trusted_key = Ed25519PrivateKey.generate()
    forged_reply = _valid_response(Ed25519PrivateKey.generate(), _NOW_MS + 300_183)
    with patch.object(cloud_pair.time, "time_ns", return_value=_NOW_MS * 1_000_000):
        with pytest.raises(cloud_pair.CloudPairingError, match="pairing denied"):
            cloud_pair._challenge(forged_reply, trusted_key)


def test_pairing_rejects_unexpected_response_fields_even_with_clock_tolerance() -> None:
    key = Ed25519PrivateKey.generate()
    reply = _valid_response(key, _NOW_MS + 300_183)
    reply["extraPermission"] = "write"
    with patch.object(cloud_pair.time, "time_ns", return_value=_NOW_MS * 1_000_000):
        with pytest.raises(cloud_pair.CloudPairingError, match="pairing denied"):
            cloud_pair._challenge(reply, key)
