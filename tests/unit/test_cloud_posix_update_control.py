"""Owner-local update requests address only the current foreground generation."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest

from kicad_mcp.cloud_managed_connector import _connector_session_lock
from kicad_mcp.cloud_pair_keys import _write_private_json
from kicad_mcp.cloud_windows_write_issuer import _KICAD_CLOUD_ORIGIN as ORIGIN

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX private registry")


@pytest.mark.asyncio
async def test_request_targets_exact_live_generation(tmp_path: Path, monkeypatch) -> None:
    from kicad_mcp import cloud_posix_update_control as control

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    generation = uuid4().hex
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_GENERATION", generation)
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_SLOT", "a")
    with _connector_session_lock(root):
        async with control.watch(root, ORIGIN) as drain:
            assert drain is not None
            assert control.probe(root) == (generation, "a")
            assert not control.request(root, uuid4().hex, "a")
            assert not control.request(root, generation, "b")
            assert not drain.is_set()
            assert control.request(root, generation, "a")
            await asyncio.wait_for(drain.wait(), 2)
        assert control.probe(root) is None
    assert not control.request(root, generation, "a")


@pytest.mark.asyncio
async def test_stale_request_and_custom_origin_do_not_drain(tmp_path: Path, monkeypatch) -> None:
    from kicad_mcp import cloud_posix_update_control as control

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    generation = uuid4().hex
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_GENERATION", generation)
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_SLOT", "b")
    _write_private_json(root, control.REQUEST, {"generation": uuid4().hex, "slot": "b"})
    with _connector_session_lock(root):
        async with control.watch(root, "https://other.example") as drain:
            assert drain is None
        async with control.watch(root, ORIGIN) as drain:
            assert drain is not None
            await asyncio.sleep(0.4)
            assert not drain.is_set()
            assert control.request(root, generation, "b")
            await asyncio.wait_for(drain.wait(), 2)
    assert control.probe(root) is None


def test_stale_lease_cannot_claim_background_session(tmp_path: Path) -> None:
    from kicad_mcp import cloud_posix_update_control as control

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    generation = uuid4().hex
    _write_private_json(root, control.LEASE, {"generation": generation, "slot": "a"})
    with _connector_session_lock(root, name=control.LOCK):
        assert control.probe(root) is None
    with _connector_session_lock(root):
        assert control.probe(root) is None
        assert not control.request(root, generation, "a")


@pytest.mark.asyncio
async def test_real_cli_probe_and_request_use_private_current_generation(
    tmp_path, monkeypatch
) -> None:
    from typer.testing import CliRunner

    from kicad_mcp import cloud_posix_update_control as control
    from kicad_mcp.server import app

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    generation = uuid4().hex
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: root)
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_GENERATION", generation)
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_SLOT", "a")
    runner = CliRunner()
    with _connector_session_lock(root):
        async with control.watch(root, ORIGIN) as drain:
            assert drain is not None
            result = runner.invoke(app, ["cloud", "_update-control", "probe"])
            assert result.exit_code == 0, result.output
            assert result.output.strip() == generation + " a"
            result = runner.invoke(
                app,
                ["cloud", "_update-control", "request", "--generation", uuid4().hex, "--slot", "a"],
            )
            assert result.exit_code == 1
            assert not drain.is_set()
            result = runner.invoke(
                app,
                ["cloud", "_update-control", "request", "--generation", generation, "--slot", "a"],
            )
            assert result.exit_code == 0, result.output
            await asyncio.wait_for(drain.wait(), 2)
    assert runner.invoke(app, ["cloud", "_update-control", "probe"]).exit_code == 1


@pytest.mark.asyncio
async def test_private_control_ignores_symlink_and_public_request(tmp_path, monkeypatch) -> None:
    from kicad_mcp import cloud_posix_update_control as control

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    generation = uuid4().hex
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_GENERATION", generation)
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_SLOT", "a")
    payload = {"generation": generation, "slot": "a"}
    _write_private_json(root, "untrusted.json", payload)
    with _connector_session_lock(root):
        async with control.watch(root, ORIGIN) as drain:
            assert drain is not None
            request_path = root / control.REQUEST
            request_path.symlink_to(root / "untrusted.json")
            await asyncio.sleep(0.3)
            assert not drain.is_set()
            request_path.unlink()
            _write_private_json(root, control.REQUEST, payload)
            request_path.chmod(0o644)
            await asyncio.sleep(0.3)
            assert not drain.is_set()
            assert control.request(root, generation, "a")
            await asyncio.wait_for(drain.wait(), 2)
