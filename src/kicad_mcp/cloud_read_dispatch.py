"""Fail-closed local-only sequenced read dispatcher. No network transport.

Only a separately reviewed and authenticated transport can supply the trusted
device/session binding and operator-approved local project mapping.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from kicad_mcp.cloud_readonly_boundary import (
    LocalReadDeniedError,
    OperatorProject,
    VerifiedLocalBinding,
    _validate_frame,
    inspect_readonly,
)

_READ_DENIED = "request denied"

MAX_READS_PER_SESSION = 32


class LocalReadDispatch:
    """One session; serialized reads, expiry, disconnect and replay fencing.

    This object does NOT authenticate TLS, OAuth, keys, grants or a Cloud socket.
    No production transport calls it yet. A future transport must independently
    establish trust, supply current authoritative grant/session checks, and
    close this dispatcher on disconnect and revocation.
    """

    def __init__(
        self,
        *,
        verified: VerifiedLocalBinding,
        operator_project: OperatorProject,
        current_authorization: Callable[[], bool],
        clock_ms: Callable[[], int] | None = None,
        max_reads: int = MAX_READS_PER_SESSION,
    ) -> None:
        if type(max_reads) is not int or not 1 <= max_reads <= MAX_READS_PER_SESSION:
            raise LocalReadDeniedError(_READ_DENIED)
        self._max_reads = max_reads
        self._verified = verified
        self._project = operator_project
        if not callable(current_authorization):
            raise LocalReadDeniedError(_READ_DENIED)
        # Never derive this predicate from a Cloud message or local wire claim.
        # It must query the independently trusted, current grant/session state.
        self._current_authorization = current_authorization
        self._seen_request_ids: set[str] = set()
        self._clock_ms = clock_ms if clock_ms is not None else lambda: time.time_ns() // 1_000_000
        self._lock = threading.Lock()
        self._closed = False
        self._busy = False
        self._last_sequence = 0

    def _authorize_now(self) -> None:
        try:
            authorized = self._current_authorization()
        except Exception as exc:
            raise LocalReadDeniedError(_READ_DENIED) from exc
        if authorized is not True:
            raise LocalReadDeniedError(_READ_DENIED)

    def assert_transport_session(self, *, device_id: str, session_id: str) -> None:
        """Fence an externally authenticated socket to this local dispatcher."""
        with self._lock:
            if (
                self._closed
                or self._verified.device_id != device_id
                or self._verified.session_id != session_id
                or self._project.device_id != device_id
                or self._project.project_id != self._verified.project_id
            ):
                raise LocalReadDeniedError(_READ_DENIED)

    def assert_delivery_authorized(self, frame: bytes, *, device_id: str, session_id: str) -> None:
        """Revalidate the local grant and request deadline just before WSS delivery.

        Passing read() is not permission to send later: the operator grant,
        signed request deadline, and active session can change while the
        async transport waits for its worker thread to return.
        """
        self.assert_transport_session(device_id=device_id, session_id=session_id)
        self._authorize_now()
        body = _validate_frame(frame, self._verified, self._project, self._clock_ms())
        with self._lock:
            if self._closed or self._busy or body["requestId"] not in self._seen_request_ids:
                raise LocalReadDeniedError(_READ_DENIED)
        self._authorize_now()
        self.assert_transport_session(device_id=device_id, session_id=session_id)

    def close(self) -> None:
        """Invalidate this session, including any pending read response."""
        with self._lock:
            self._closed = True

    def read(self, frame: bytes, *, sequence: int) -> dict[str, object]:
        """Inspect only approved local project file presence; deny all other work.

        The current authorization is checked both before and after inspection,
        but does not grant a network-send ticket: a future transport must also
        verify session and grant state atomically immediately before delivery.
        """
        with self._lock:
            if (
                self._closed
                or self._busy
                or type(sequence) is not int
                or sequence != self._last_sequence + 1
                or sequence > self._max_reads
            ):
                raise LocalReadDeniedError(_READ_DENIED)
            self._busy = True
            # Consumed before inspection, including any failed authorization.
            self._last_sequence = sequence

        try:
            self._authorize_now()
            initial = _validate_frame(frame, self._verified, self._project, self._clock_ms())
            request_id = initial["requestId"]
            if not isinstance(request_id, str):
                raise LocalReadDeniedError(_READ_DENIED)
            with self._lock:
                if self._closed or request_id in self._seen_request_ids:
                    raise LocalReadDeniedError(_READ_DENIED)
                self._seen_request_ids.add(request_id)

            response = inspect_readonly(
                frame,
                verified=self._verified,
                operator_project=self._project,
                now_unix_ms=self._clock_ms(),
            )
            # Recheck signed request expiry before return, including if local
            # file metadata inspection was blocked or time advanced.
            body = _validate_frame(frame, self._verified, self._project, self._clock_ms())
            if body["requestId"] != response["requestId"]:
                raise LocalReadDeniedError(_READ_DENIED)
            # An owner/client/device/project grant may be revoked while the
            # OS metadata inspection runs. Never return a result after cutoff.
            self._authorize_now()
            with self._lock:
                if self._closed:
                    raise LocalReadDeniedError(_READ_DENIED)
                return response
        finally:
            with self._lock:
                self._busy = False
