"""Tests for Connector lifecycle management and safe active project selection."""

import json
import os
import stat
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from kicad_mcp.services.connector_lifecycle import (
    ConnectorLifecycleManager,
    ConnectorState,
)


@pytest.fixture
def mock_registry(tmp_path: Path) -> Path:
    root = tmp_path / "registry"
    root.mkdir(mode=stat.S_IRWXU)
    (root / "projects").mkdir(mode=stat.S_IRWXU)
    (root / "keys").mkdir(mode=stat.S_IRWXU)
    if hasattr(os, "chmod"):
        os.chmod(root, stat.S_IRWXU)  # nosec B103 # nosemgrep
        os.chmod(root / "projects", stat.S_IRWXU)  # nosec B103 # nosemgrep
        os.chmod(root / "keys", stat.S_IRWXU)  # nosec B103 # nosemgrep
    proj_a = {
        "ownerSub": "usr-1",
        "cloudOrigin": "https://kicad-mcp-pro.oaslananka.dev",
        "deviceId": "00000000-0000-0000-0000-000000000001",
        "projectId": "11111111-1111-1111-1111-111111111111",
        "keySlot": "slot-a",
        "directory": str(tmp_path / "project_a"),
        "filenameStem": "board_a",
    }
    proj_b = {
        "ownerSub": "usr-1",
        "cloudOrigin": "https://kicad-mcp-pro.oaslananka.dev",
        "deviceId": "00000000-0000-0000-0000-000000000001",
        "projectId": "22222222-2222-2222-2222-222222222222",
        "keySlot": "slot-b",
        "directory": str(tmp_path / "project_b"),
        "filenameStem": "board_b",
    }
    f1 = root / "projects" / "11111111-1111-1111-1111-111111111111.json"
    f2 = root / "projects" / "22222222-2222-2222-2222-222222222222.json"
    f1.write_text(json.dumps(proj_a), encoding="utf-8")
    f2.write_text(json.dumps(proj_b), encoding="utf-8")
    if hasattr(os, "chmod"):
        os.chmod(f1, 0o600)
        os.chmod(f2, 0o600)
    return root


@pytest.mark.asyncio
async def test_connector_lifecycle_start_and_stop(mock_registry) -> None:
    mgr = ConnectorLifecycleManager(registry_root=mock_registry)
    assert mgr.get_status().state == ConnectorState.OFF

    record = json.loads(next((mock_registry / "projects").glob("*.json")).read_text())
    with (
        patch(
            "kicad_mcp.services.connector_lifecycle._single_registered_identity",
            return_value=record,
        ),
        patch("kicad_mcp.services.connector_lifecycle._run_connector", new_callable=AsyncMock),
    ):
        started = await mgr.start()
        assert started is True
        assert mgr.is_running() is True

        await mgr.stop()
        assert mgr.is_running() is False
        assert mgr.get_status().state == ConnectorState.OFF


@pytest.mark.asyncio
async def test_connector_prevents_duplicate_instance(mock_registry) -> None:
    mgr = ConnectorLifecycleManager(registry_root=mock_registry)
    record = json.loads(next((mock_registry / "projects").glob("*.json")).read_text())
    with (
        patch(
            "kicad_mcp.services.connector_lifecycle._single_registered_identity",
            return_value=record,
        ),
        patch("kicad_mcp.services.connector_lifecycle._run_connector", new_callable=AsyncMock),
    ):
        assert await mgr.start() is True
        # Second start call is a no-op / returns False or current running status
        assert await mgr.start() is False


@pytest.mark.asyncio
async def test_multiple_registrations_and_traversal_fail_closed(mock_registry) -> None:
    mgr = ConnectorLifecycleManager(registry_root=mock_registry)
    assert mgr.get_active_project_id() is None
    assert not await mgr.switch_active_project("../../outside")
    assert not await mgr.switch_active_project("22222222-2222-2222-2222-222222222222")
    assert not (mock_registry / "active_project.json").exists()


@pytest.mark.asyncio
async def test_project_switch_refuses_active_connector_without_fencing(tmp_path) -> None:
    mgr = ConnectorLifecycleManager(registry_root=tmp_path)
    with (
        patch.object(mgr, "is_running", return_value=True),
        patch.object(mgr, "get_active_project_id", return_value="current"),
        patch.object(mgr, "set_active_project") as setter,
    ):
        assert not await mgr.switch_active_project("other")
        setter.assert_not_called()
        assert await mgr.switch_active_project("current")
