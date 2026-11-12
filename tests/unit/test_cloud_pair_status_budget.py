"""Pairing retry should not exhaust the Cloud's fixed source status budget."""

from __future__ import annotations

import pytest

from kicad_mcp import cloud_pair


def test_two_full_five_minute_owner_review_windows_fit_cloud_source_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    now_epoch = 1_900_000_000
    requests = [0]
    review_windows = [0]
    delays: list[float] = []

    monkeypatch.setattr(cloud_pair.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        cloud_pair.time,
        "time_ns",
        lambda: int((now_epoch + clock[0]) * 1_000_000_000),
    )

    def advance(seconds: float) -> None:
        assert seconds > 0
        delays.append(seconds)
        clock[0] += seconds

    def pending(_origin: tuple[str, int, str], path: str, body: dict, status: int) -> dict:
        assert path == "/api/v1/pairing/device/status"
        assert status == 200
        assert body["signature"]
        requests[0] += 1
        if requests[0] > 40:
            raise cloud_pair.CloudPairingError("pairing denied (HTTP 429: rate_limited)")
        return {"approved": False}

    monkeypatch.setattr(cloud_pair.time, "sleep", advance)
    monkeypatch.setattr(cloud_pair, "_post", pending)
    key = cloud_pair.Ed25519PrivateKey.generate()
    for count in range(2):
        challenge = f"00000000-0000-4000-8000-{count + 1:012d}"
        expires = int((now_epoch + clock[0] + 300) * 1000)
        with pytest.raises(cloud_pair.CloudPairingTimeoutError):
            cloud_pair._wait_for_owner_approval(
                ("localhost", 443, "https://localhost"),
                challenge,
                "A" * 43,
                key,
                expires,
                lambda: review_windows.__setitem__(0, review_windows[0] + 1),
            )
    assert review_windows == [2]
    assert requests[0] == 32
    assert delays[:4] == [8.0] * 4
    assert 24.0 in delays
    assert clock[0] == 600.0
