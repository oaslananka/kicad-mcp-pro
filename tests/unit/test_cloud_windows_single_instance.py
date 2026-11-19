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


def _assert_mutex_owned_by_parent(mutex_name: str) -> None:
    """Win32 spawn target: expected duplicate exits normally; lock acquisition fails the test."""
    from kicad_mcp import cloud_windows_single_instance as guard

    guard._MUTEX_NAME = mutex_name
    try:
        with guard.owner_connector_instance():
            raise SystemExit(9)
    except guard.CloudConnectorAlreadyRunningError:
        return


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Windows named mutex")
def test_windows_mutex_prevents_independent_second_process(monkeypatch) -> None:
    from multiprocessing import get_context

    from kicad_mcp import cloud_windows_single_instance as guard

    key = f"Local\\KiCadMcpProTest_{uuid4().hex}"
    monkeypatch.setattr(guard, "_MUTEX_NAME", key)
    child = get_context("spawn").Process(
        target=_assert_mutex_owned_by_parent,
        args=(key,),
    )
    with guard.owner_connector_instance():
        child.start()
        try:
            child.join(timeout=12)
            assert not child.is_alive(), "child did not exit while parent held the mutex"
            assert child.exitcode == 0, "child unexpectedly obtained the owner's mutex"
        finally:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
    with guard.owner_connector_instance():
        pass


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Windows named mutex")
def test_foreground_owner_guard_is_reused_by_async_connector_not_other_callers(monkeypatch) -> None:
    import asyncio

    from kicad_mcp import cloud_windows_single_instance as guard

    monkeypatch.setattr(guard, "_MUTEX_NAME", f"Local\\KiCadMcpProTest_{uuid4().hex}")

    async def inner():
        with guard.owner_connector_instance(reuse_if_held=True):
            return "same-foreground-owner"

    with guard.owner_connector_instance():
        assert asyncio.run(inner()) == "same-foreground-owner"
        with pytest.raises(guard.CloudConnectorAlreadyRunningError):
            with guard.owner_connector_instance():
                pytest.fail("new independent caller must not reuse the lock")


@pytest.mark.asyncio
async def test_running_connector_requires_single_instance_before_any_signed_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    def reject_duplicate(**_kwargs: object) -> None:
        calls.append("guard")
        raise CloudConnectorAlreadyRunningError("another Connector is active")

    async def no_session(**_kwargs: object) -> None:
        calls.append("signed_session")
        raise AssertionError("duplicate should not reach Cloud")

    monkeypatch.setattr(connector, "owner_connector_instance", reject_duplicate)
    with pytest.raises(CloudConnectorAlreadyRunningError, match="already active|another Connector"):
        await connector.run_connector(stop=__import__("asyncio").Event(), session_runner=no_session)
    assert calls == ["guard"]
