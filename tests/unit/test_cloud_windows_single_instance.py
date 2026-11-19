"""Owner-local Windows Connector singleton: no background tasks or Cloud traffic."""

from __future__ import annotations

import sys
from uuid import uuid4

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Windows named mutex")
def test_windows_connector_guard_blocks_second_instance_then_releases(monkeypatch) -> None:
    from kicad_mcp import cloud_windows_single_instance as guard

    monkeypatch.setattr(guard, "_MUTEX_NAME", f"Local\\KiCadMcpProTest_{uuid4().hex}")
    with guard.owner_connector_instance():
        with pytest.raises(guard.CloudConnectorAlreadyRunningError):
            with guard.owner_connector_instance():
                pytest.fail("second Connector obtained the same mutex")
    with guard.owner_connector_instance():
        pass


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Windows named mutex")
def test_windows_connector_guard_releases_after_exception(monkeypatch) -> None:
    from kicad_mcp import cloud_windows_single_instance as guard

    monkeypatch.setattr(guard, "_MUTEX_NAME", f"Local\\KiCadMcpProTest_{uuid4().hex}")
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with guard.owner_connector_instance():
            raise RuntimeError("synthetic failure")
    with guard.owner_connector_instance():
        pass


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Windows named mutex")
def test_windows_mutex_unavailable_fails_closed(monkeypatch) -> None:
    import ctypes

    from kicad_mcp import cloud_windows_single_instance as guard

    def refuse_dll(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic platform error")

    monkeypatch.setattr(ctypes, "WinDLL", refuse_dll)
    with pytest.raises(guard.CloudConnectorLockUnavailableError):
        with guard.owner_connector_instance():
            pytest.fail("Connector must not start without a verified lock")


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Windows named mutex")
def test_windows_mutex_prevents_independent_second_process(monkeypatch) -> None:
    import os
    import subprocess

    from kicad_mcp import cloud_windows_single_instance as guard

    key = f"Local\\KiCadMcpProTest_{uuid4().hex}"
    monkeypatch.setattr(guard, "_MUTEX_NAME", key)
    child = (
        "import os,sys;"
        "from kicad_mcp import cloud_windows_single_instance as guard;"
        "guard._MUTEX_NAME=os.environ['KICAD_TEST_SINGLE_INSTANCE_MUTEX']\\n"
        "try:\\n"
        "    with guard.owner_connector_instance():sys.exit(9)\\n"
        "except guard.CloudConnectorAlreadyRunningError:sys.exit(0)\\n"
    )
    # Exchanging only this test-specific name; no Cloud registration involved.
    child = child.replace("\\n", "\n")
    with guard.owner_connector_instance():
        result = subprocess.run(
            [sys.executable, "-c", child],
            env={**os.environ, "KICAD_TEST_SINGLE_INSTANCE_MUTEX": key},
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    with guard.owner_connector_instance():
        pass


@pytest.mark.asyncio
async def test_running_connector_requires_single_instance_before_any_signed_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager
    from types import SimpleNamespace

    from kicad_mcp import cloud_windows_connector as connector
    from kicad_mcp.cloud_windows_single_instance import CloudConnectorAlreadyRunningError

    monkeypatch.setattr(connector, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        connector,
        "_active",
        lambda: SimpleNamespace(project=SimpleNamespace(device_id="test-device")),
    )
    calls: list[str] = []

    @contextmanager
    def reject_duplicate():
        calls.append("guard")
        raise CloudConnectorAlreadyRunningError("another Connector is active")
        yield  # pragma: no cover

    async def no_session(**_kwargs: object) -> None:
        calls.append("signed_session")
        raise AssertionError("duplicate should not reach Cloud")

    monkeypatch.setattr(connector, "owner_connector_instance", reject_duplicate)
    with pytest.raises(CloudConnectorAlreadyRunningError, match="already active|another Connector"):
        await connector.run_connector(stop=__import__("asyncio").Event(), session_runner=no_session)
    assert calls == ["guard"]
