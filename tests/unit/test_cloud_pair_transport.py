"""Cross-platform transport and diagnostic error tests for cloud_pair._post."""

from __future__ import annotations

import pytest

from kicad_mcp import cloud_pair


def test_https_pairing_post_captures_error_payload_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ErrorResponse:
        status = 403
        headers = {"Content-Type": "application/json"}

        def read(self, _maximum: int) -> bytes:
            return b'{"error": "untrusted_ingress"}'

        def release_conn(self) -> None:
            pass

    class ErrorPool:
        def __init__(self, _host: str, _port: int, **_options: object) -> None:
            pass

        def request(self, _method: str, _path: str, **_options: object) -> ErrorResponse:
            return ErrorResponse()

        def close(self) -> None:
            pass

    monkeypatch.setattr(cloud_pair.urllib3, "HTTPSConnectionPool", ErrorPool)
    with pytest.raises(cloud_pair.CloudPairingError) as exc_info:
        cloud_pair._post(
            ("localhost", 443, "https://localhost"),
            "/api/v1/pairing/device/challenge",
            {"alias": "Demo"},
            201,
        )
    assert "pairing denied (HTTP 403: untrusted_ingress)" in str(exc_info.value)


def test_https_pairing_post_handles_non_json_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NonJsonResponse:
        status = 502
        headers = {"Content-Type": "text/html"}

        def read(self, _maximum: int) -> bytes:
            return b"<html>Bad Gateway</html>"

        def release_conn(self) -> None:
            pass

    class ErrorPool:
        def __init__(self, _host: str, _port: int, **_options: object) -> None:
            pass

        def request(self, _method: str, _path: str, **_options: object) -> NonJsonResponse:
            return NonJsonResponse()

        def close(self) -> None:
            pass

    monkeypatch.setattr(cloud_pair.urllib3, "HTTPSConnectionPool", ErrorPool)
    with pytest.raises(cloud_pair.CloudPairingError) as exc_info:
        cloud_pair._post(
            ("localhost", 443, "https://localhost"),
            "/api/v1/pairing/device/challenge",
            {"alias": "Demo"},
            201,
        )
    assert "pairing denied (HTTP 502)" in str(exc_info.value)


def test_https_pairing_post_wraps_network_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingPool:
        def __init__(self, _host: str, _port: int, **_options: object) -> None:
            pass

        def request(self, _method: str, _path: str, **_options: object) -> None:
            raise OSError("network down")

        def close(self) -> None:
            pass

    monkeypatch.setattr(cloud_pair.urllib3, "HTTPSConnectionPool", FailingPool)
    with pytest.raises(cloud_pair.CloudPairingError) as exc_info:
        cloud_pair._post(
            ("localhost", 443, "https://localhost"),
            "/api/v1/pairing/device/challenge",
            {"alias": "Demo"},
            201,
        )
    assert "pairing denied: network down" in str(exc_info.value)


@pytest.mark.parametrize(
    ("expiry_offset_ms", "accepted"),
    [
        (300_020, True),  # Observed: DB-issued 5-minute deadline 20 ms ahead of laptop.
        (330_000, True),  # Bounded local/server clock skew, not an extended Cloud grant.
        (330_001, False),
        (0, False),
        (-1, False),
    ],
)
def test_pairing_challenge_tolerates_bounded_clock_skew(
    monkeypatch: pytest.MonkeyPatch, expiry_offset_ms: int, accepted: bool
) -> None:
    now_ms = 1_800_000_000_000
    monkeypatch.setattr(cloud_pair.time, "time_ns", lambda: now_ms * 1_000_000)
    key = cloud_pair.Ed25519PrivateKey.generate()
    public_der = key.public_key().public_bytes(
        cloud_pair.Encoding.DER, cloud_pair.PublicFormat.SubjectPublicKeyInfo
    )
    result = {
        "challengeId": "11111111-1111-4111-8111-111111111111",
        "userCode": "ABCDEF-123456",
        "deviceCode": "A" * 43,
        "deviceFingerprint": cloud_pair.hashlib.sha256(public_der).hexdigest(),
        "expiresAtMs": now_ms + expiry_offset_ms,
    }
    if accepted:
        challenge, *_ = cloud_pair._challenge(result, key)
        assert challenge == result["challengeId"]
    else:
        with pytest.raises(cloud_pair.CloudPairingError, match="pairing denied"):
            cloud_pair._challenge(result, key)
