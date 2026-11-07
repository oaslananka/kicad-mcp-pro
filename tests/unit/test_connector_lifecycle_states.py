"""Connector manager status and active-project fail-closed transitions."""

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from kicad_mcp.services.connector_lifecycle import ConnectorLifecycleManager, ConnectorState

PROJECT = "00000000-0000-4000-8000-000000000002"
DEVICE = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def registry(tmp_path: Path) -> Path:
    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    (root / "projects").mkdir(mode=0o700)
    (root / "keys").mkdir(mode=0o700)
    return root


def identity(registry: Path) -> dict[str, str]:
    return {
        "ownerSub": "owner-one",
        "cloudOrigin": "https://kicad-mcp-pro.oaslananka.dev",
        "deviceId": DEVICE,
        "projectId": PROJECT,
        "keySlot": "key-slot",
        "directory": str(registry / "board"),
        "filenameStem": "board",
    }


def test_enabled_marker_without_owned_process_is_unavailable(registry: Path) -> None:
    mgr = ConnectorLifecycleManager(registry_root=registry)
    assert mgr.get_status().state == ConnectorState.OFF
    (registry / "connector-enabled.json").write_text("{}", encoding="utf-8")
    assert mgr.get_status().state == ConnectorState.UNAVAILABLE


@pytest.mark.parametrize("state", ["connected", "connecting"])
def test_fresh_status_requires_matching_process_and_schema(registry: Path, state: str) -> None:
    mgr = ConnectorLifecycleManager(registry_root=registry)
    with (
        patch.object(mgr, "is_running", return_value=True),
        patch.object(mgr, "get_active_project_id", return_value=PROJECT),
        patch(
            "kicad_mcp.services.connector_lifecycle._read_private_json",
            return_value={
                "state": state,
                "updatedAtUnixMs": time.time_ns() // 1_000_000,
                "pid": os.getpid(),
            },
        ),
    ):
        result = mgr.get_status()
    assert result.state == ConnectorState(state)
    assert result.active_project_id == PROJECT


@pytest.mark.parametrize(
    "payload",
    [
        {"state": "connected", "updatedAtUnixMs": 10, "pid": os.getpid()},
        {"state": "connected", "updatedAtUnixMs": "not-int", "pid": os.getpid()},
        {"state": "connected", "updatedAtUnixMs": 10, "pid": -1, "extra": "forged"},
    ],
)
def test_stale_corrupt_and_forged_status_never_becomes_connected(
    registry: Path, payload: dict[str, object]
) -> None:
    mgr = ConnectorLifecycleManager(registry_root=registry)
    with (
        patch.object(mgr, "is_running", return_value=True),
        patch.object(mgr, "get_active_project_id", return_value=PROJECT),
        patch("kicad_mcp.services.connector_lifecycle._read_private_json", return_value=payload),
    ):
        assert mgr.get_status().state == ConnectorState.UNAVAILABLE


def test_status_read_failure_stays_connecting_while_process_runs(registry: Path) -> None:
    mgr = ConnectorLifecycleManager(registry_root=registry)
    with (
        patch.object(mgr, "is_running", return_value=True),
        patch(
            "kicad_mcp.services.connector_lifecycle._read_private_json",
            side_effect=OSError("damaged status"),
        ),
    ):
        assert mgr.get_status().state == ConnectorState.CONNECTING


def test_active_project_requires_exact_verified_pointer(registry: Path) -> None:
    mgr = ConnectorLifecycleManager(registry_root=registry)
    with patch(
        "kicad_mcp.services.connector_lifecycle._single_registered_identity",
        return_value=identity(registry),
    ):
        assert mgr.get_active_project_id() == PROJECT
        with patch(
            "kicad_mcp.services.connector_lifecycle._read_private_json",
            return_value={"activeProjectId": "another-project"},
        ):
            assert mgr.get_active_project_id() is None
            with pytest.raises(ValueError, match="Active project"):
                mgr._resolve_active_record()
        with patch(
            "kicad_mcp.services.connector_lifecycle._read_private_json",
            return_value={"activeProjectId": PROJECT},
        ):
            assert mgr.get_active_project_id() == PROJECT


@pytest.mark.asyncio
async def test_project_switch_rejects_unknown_and_selects_registered_record(
    registry: Path,
) -> None:
    mgr = ConnectorLifecycleManager(registry_root=registry)
    with patch(
        "kicad_mcp.services.connector_lifecycle._single_registered_identity",
        return_value=identity(registry),
    ):
        assert not await mgr.switch_active_project("other")
        assert not (registry / "active_project.json").exists()
        assert await mgr.switch_active_project(PROJECT)
        assert mgr.get_active_project_id() == PROJECT


@pytest.mark.asyncio
async def test_start_fails_closed_without_valid_registration(registry: Path) -> None:
    mgr = ConnectorLifecycleManager(registry_root=registry)
    assert await mgr.start() is False
    assert mgr.get_status().state == ConnectorState.OFF


def test_enable_disable_preserve_explicit_local_authority(registry: Path) -> None:
    mgr = ConnectorLifecycleManager(registry_root=registry)
    with patch(
        "kicad_mcp.services.connector_lifecycle._single_registered_identity",
        return_value=identity(registry),
    ):
        mgr.enable_connector()
        assert (registry / "connector-enabled.json").exists()
        mgr.disable_connector()
        assert not (registry / "connector-enabled.json").exists()
