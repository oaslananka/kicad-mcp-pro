"""Tests for Connector lifecycle management and safe active project selection."""

import json
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
    root.mkdir()
    (root / "projects").mkdir()
    (root / "keys").mkdir()
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
    (root / "projects" / "11111111-1111-1111-1111-111111111111.json").write_text(json.dumps(proj_a))
    (root / "projects" / "22222222-2222-2222-2222-222222222222.json").write_text(json.dumps(proj_b))
    return root


@pytest.mark.asyncio
async def test_connector_lifecycle_start_and_stop(mock_registry) -> None:
    mgr = ConnectorLifecycleManager(registry_root=mock_registry)
    assert mgr.get_status().state == ConnectorState.OFF

    with patch("kicad_mcp.cloud_managed_connector._run_connector", new_callable=AsyncMock):
        started = await mgr.start()
        assert started is True
        assert mgr.is_running() is True

        await mgr.stop()
        assert mgr.is_running() is False
        assert mgr.get_status().state == ConnectorState.OFF


@pytest.mark.asyncio
async def test_connector_prevents_duplicate_instance(mock_registry) -> None:
    mgr = ConnectorLifecycleManager(registry_root=mock_registry)
    with patch("kicad_mcp.cloud_managed_connector._run_connector", new_callable=AsyncMock):
        assert await mgr.start() is True
        # Second start call is a no-op / returns False or current running status
        assert await mgr.start() is False


@pytest.mark.asyncio
async def test_active_project_selection_and_switch(mock_registry) -> None:
    mgr = ConnectorLifecycleManager(registry_root=mock_registry)
    # Default active project
    assert mgr.get_active_project_id() is None or mgr.get_active_project_id() in (
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    )

    # Explicit switch to proj_b
    switched = await mgr.switch_active_project("22222222-2222-2222-2222-222222222222")
    assert switched is True
    assert mgr.get_active_project_id() == "22222222-2222-2222-2222-222222222222"

    # Switching to unknown project fails closed
    unknown = await mgr.switch_active_project("99999999-9999-9999-9999-999999999999")
    assert unknown is False
    assert mgr.get_active_project_id() == "22222222-2222-2222-2222-222222222222"
