"""Bounded reconnection timing, independent from Cloud credentials and IO.

Existing Cloud accepts at most five device challenges per rolling minute.
The first retry must not create a handshake flood after a short connection.
"""

from __future__ import annotations

import math

MIN_RETRY_SECONDS = 15.0
MAX_RETRY_SECONDS = 120.0
MAX_JITTER_SECONDS = 2.0


def reconnect_delay_seconds(failures: int, jitter_fraction: float = 0.0) -> float:
    """Time until another connection attempt, including after a clean close.

    failures=0 is a clean closure; it still waits at least fifteen seconds.
    Non-negative consecutive failures increase delay, capped at two minutes.
    Jitter fraction must be supplied by the runtime's random source.
    This function never handles a key, socket, grant, or process.
    """
    if type(failures) is not int or failures < 0:
        raise ValueError("Invalid reconnect failure count")
    if (
        type(jitter_fraction) not in (float, int)
        or not math.isfinite(jitter_fraction)
        or not 0 <= jitter_fraction <= 1
    ):
        raise ValueError("Invalid reconnect jitter")
    multiplier = (1, 2, 4, 8)[min(failures, 3)]
    base = min(MAX_RETRY_SECONDS, MIN_RETRY_SECONDS * multiplier)
    return base + MAX_JITTER_SECONDS * float(jitter_fraction)
