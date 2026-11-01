"""Bind a trusted connector session to one local, isolated MCP project worker.

This is a LOCAL adapter only. It does not authenticate a Cloud frame, permit
remote commands, or add a network transport. An authenticated transport must
supply its own independently verified session and current grant predicate.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.project.stdio_worker import (
    LocalProjectWorkerRouter,
    ProjectInspectionSession,
    ProjectWorkerDeniedError,
)

# This capability is deliberately NOT issued by the present one-shot Cloud
# connector. Existing project_summary/run_drc consent cannot be reused to
# authorize an additional native MCP operation.
_LOCAL_INSPECTION_CAPABILITIES = frozenset({"project_worker_inspection", "project_board_counts"})


class BoundConnectorProjectWorker:
    """Owner-approved project plus exact device/session and short-lived grant."""

    def __init__(
        self,
        *,
        verified: VerifiedLocalBinding,
        operator_project: OperatorProject,
        current_authorization: Callable[[], bool],
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._verified = verified
        self._operator_project = operator_project
        self._grant = current_authorization
        self._clock = clock_ms if clock_ms is not None else lambda: time.time_ns() // 1_000_000
        if (
            not callable(current_authorization)
            or verified.device_id != operator_project.device_id
            or verified.project_id != operator_project.project_id
            or len(verified.operations) != 1
            or not verified.operations.issubset(_LOCAL_INSPECTION_CAPABILITIES)
        ):
            raise ProjectWorkerDeniedError("project not authorized")
        # Resolve only the out-of-band, locally selected project. Cloud has no
        # opportunity to send a path or name a different project directory.
        self._router = LocalProjectWorkerRouter(
            {verified.project_id: operator_project.directory},
            current_authorization=lambda project_id: (
                project_id == verified.project_id and self._current_grant()
            ),
        )

    def _current_grant(self) -> bool:
        try:
            now = self._clock()
            if type(now) is not int or now <= 0 or now >= self._verified.session_expires_unix_ms:
                return False
            return self._grant() is True
        except Exception:
            return False

    @asynccontextmanager
    async def connect(
        self, *, device_id: str, project_id: str, session_id: str
    ) -> AsyncIterator[ProjectInspectionSession]:
        """Refuse any mismatched/revoked/expired session before worker startup."""
        self.assert_session_authorized(
            device_id=device_id, project_id=project_id, session_id=session_id
        )
        async with self._router.connect(self._verified.project_id) as worker:
            if not self._current_grant():
                raise ProjectWorkerDeniedError("project not authorized")
            yield worker

    def assert_operation_authorized(self, operation: str) -> None:
        if self._verified.operations != frozenset({operation}) or not self._current_grant():
            raise ProjectWorkerDeniedError("project not authorized")

    def assert_session_authorized(
        self, *, device_id: str, project_id: str, session_id: str
    ) -> None:
        """Revalidate exact local binding before dispatch and result delivery."""
        if (
            device_id != self._verified.device_id
            or project_id != self._verified.project_id
            or session_id != self._verified.session_id
            or not self._current_grant()
        ):
            raise ProjectWorkerDeniedError("project not authorized")
