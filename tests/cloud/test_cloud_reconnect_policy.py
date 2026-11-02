"""Reconnect cadence is bounded independently of device signing."""

import math

import pytest

from kicad_mcp.cloud_reconnect_policy import reconnect_delay_seconds


@pytest.mark.parametrize(
    ("failures", "expected"),
    [(0, 15.0), (1, 30.0), (2, 60.0), (3, 120.0), (4, 120.0), (10**5, 120.0)],
)
def test_retries_respect_enrolled_device_rate_limit(failures: int, expected: float) -> None:
    assert reconnect_delay_seconds(failures) == expected


def test_jitter_is_bounded_and_never_removes_minimum_spacing() -> None:
    assert reconnect_delay_seconds(0, 0.5) == 16.0
    assert reconnect_delay_seconds(0, 1.0) == 17.0
    assert reconnect_delay_seconds(200, 1.0) == 122.0


@pytest.mark.parametrize("invalid", [-1, True, 1.0, "1", None])
def test_invalid_failure_counts_are_denied(invalid: object) -> None:
    with pytest.raises(ValueError):
        reconnect_delay_seconds(invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid", [-0.01, 1.01, math.nan, math.inf, -math.inf, True, "0.5"])
def test_invalid_jitter_is_denied(invalid: object) -> None:
    with pytest.raises(ValueError):
        reconnect_delay_seconds(0, invalid)  # type: ignore[arg-type]
