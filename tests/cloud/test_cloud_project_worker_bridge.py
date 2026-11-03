"""Trusted local device/session binding for the per-project MCP worker."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.cloud_project_worker_bridge import BoundConnectorProjectWorker
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.project.stdio_worker import ProjectWorkerDeniedError

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
NOW = 1_900_000_000_000


def _bridge(
    root: Path,
    *,
    operation: str = "project_worker_inspection",
    authorization=None,
    clock=None,
    device: str = DEVICE,
) -> BoundConnectorProjectWorker:
    return BoundConnectorProjectWorker(
        verified=VerifiedLocalBinding(
            device_id=DEVICE,
            project_id=PROJECT,
            operations=frozenset({operation}),
            session_id=SESSION,
            session_expires_unix_ms=NOW + 60_000,
        ),
        operator_project=OperatorProject(
            device_id=device, project_id=PROJECT, directory=root, filename_stem="demo"
        ),
        current_authorization=authorization or (lambda: True),
        clock_ms=clock or (lambda: NOW),
    )


@pytest.mark.anyio
async def test_bound_worker_starts_real_scoped_mcp_and_rechecks_grants(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    root.mkdir()
    (root / "demo.kicad_pro").write_text("{}", encoding="utf-8")
    granted = True
    bridge = _bridge(root, authorization=lambda: granted)
    async with bridge.connect(device_id=DEVICE, project_id=PROJECT, session_id=SESSION) as worker:
        result = await worker.inspect("kicad_get_project_info")
        assert result.is_error is not True
        assert str(root) in str(result)
        with pytest.raises(ProjectWorkerDeniedError):
            await worker.inspect("kicad_set_project")
        granted = False
        with pytest.raises(ProjectWorkerDeniedError):
            await worker.inspect("kicad_get_version")
    with pytest.raises(ProjectWorkerDeniedError):
        async with bridge.connect(device_id=DEVICE, project_id=PROJECT, session_id=SESSION):
            pass


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("device", "project", "session"),
    [
        ("44444444-4444-4444-8444-444444444444", PROJECT, SESSION),
        (DEVICE, "55555555-5555-4555-8555-555555555555", SESSION),
        (DEVICE, PROJECT, "66666666-6666-4666-8666-666666666666"),
    ],
)
async def test_wrong_connector_binding_cannot_start_worker(
    tmp_path: Path, device: str, project: str, session: str
) -> None:
    bridge = _bridge(tmp_path)
    with pytest.raises(ProjectWorkerDeniedError):
        async with bridge.connect(device_id=device, project_id=project, session_id=session):
            pass


@pytest.mark.anyio
async def test_expired_connector_session_does_not_start_worker(tmp_path: Path) -> None:
    bridge = _bridge(tmp_path, clock=lambda: NOW + 60_000)
    with pytest.raises(ProjectWorkerDeniedError):
        async with bridge.connect(device_id=DEVICE, project_id=PROJECT, session_id=SESSION):
            pass


@pytest.mark.parametrize("operation", ["project_summary", "run_drc"])
def test_existing_pilot_grants_cannot_enable_extra_mcp_inspection(
    tmp_path: Path, operation: str
) -> None:
    with pytest.raises(ProjectWorkerDeniedError):
        _bridge(tmp_path, operation=operation)


def test_mismatched_registered_device_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProjectWorkerDeniedError):
        _bridge(tmp_path, device="44444444-4444-4444-8444-444444444444")
