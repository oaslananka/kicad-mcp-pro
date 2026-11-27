"""Windows local update rendezvous does not grant project or device authority."""

from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager
from types import ModuleType
from uuid import uuid4

import pytest

from kicad_mcp.cloud_windows_write_issuer import _KICAD_CLOUD_ORIGIN as ORIGIN


@pytest.fixture
def control_fixture(monkeypatch) -> tuple[ModuleType, dict[tuple[str, str], bytes]]:
    from kicad_mcp import cloud_windows_update_control as control

    store = {}
    held = set()
    monkeypatch.setattr(control, "_supported", lambda: True)
    monkeypatch.setattr(control, "_owner_held", lambda: True)
    monkeypatch.setattr(control, "read_credential", lambda slot, part: store.get((slot, part)))
    monkeypatch.setattr(
        control, "delete_credential", lambda slot, part: store.pop((slot, part), None) is not None
    )

    def create(slot, part, blob):
        assert (slot, part) not in store
        store[(slot, part)] = blob

    @contextmanager
    def own(generation):
        assert generation not in held
        held.add(generation)
        try:
            yield
        finally:
            held.remove(generation)

    monkeypatch.setattr(control, "create_credential", create)
    monkeypatch.setattr(control, "_generation_mutex", own)
    monkeypatch.setattr(control, "_generation_live", lambda generation: generation in held)
    return control, store


@pytest.mark.asyncio
async def test_windows_update_control_only_current_generation(control_fixture, monkeypatch) -> None:
    control, store = control_fixture
    generation = uuid4().hex
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_GENERATION", generation)
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_SLOT", "a")
    async with control.watch(ORIGIN) as drain:
        assert drain is not None
        assert control.probe() == (generation, "a")
        assert not control.request(uuid4().hex, "a")
        assert not control.request(generation, "b")
        assert not drain.is_set()
        assert control.request(generation, "a")
        await asyncio.wait_for(drain.wait(), 2)
    assert control.probe() is None
    assert not control.request(generation, "a")
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_GENERATION", uuid4().hex)
    async with control.watch(ORIGIN) as drain:
        assert drain is not None
        assert not drain.is_set()
        await asyncio.sleep(0.3)
        assert not drain.is_set()
    assert all(part != "update_lease" for _, part in store)


@pytest.mark.asyncio
async def test_windows_custom_origin_has_no_control(control_fixture, monkeypatch) -> None:
    control, store = control_fixture
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_GENERATION", uuid4().hex)
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_SLOT", "a")
    async with control.watch("https://other.example") as drain:
        assert drain is None
    assert not store


@pytest.mark.asyncio
async def test_windows_cli_and_foreground_wrapper(control_fixture, monkeypatch) -> None:
    from contextlib import nullcontext

    from typer.testing import CliRunner

    from kicad_mcp import cloud_user_cli
    from kicad_mcp.server import app

    control, store = control_fixture
    generation = uuid4().hex
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_GENERATION", generation)
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_SLOT", "a")
    monkeypatch.setattr(cloud_user_cli, "_is_windows", lambda: True)
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr(cloud_user_cli, "owner_connector_instance", lambda **_: nullcontext())
    runner = CliRunner()
    calls = []

    async def session(*, drain: asyncio.Event) -> None:
        result = runner.invoke(app, ["cloud", "_update-control", "probe"])
        assert result.exit_code == 0
        assert result.output.strip() == generation + " a"
        result = runner.invoke(
            app, ["cloud", "_update-control", "request", "--generation", generation, "--slot", "a"]
        )
        assert result.exit_code == 0
        await asyncio.wait_for(drain.wait(), 2)
        calls.append("drained")

    assert await cloud_user_cli._windows_update_session(ORIGIN, session)
    assert calls == ["drained"]
    assert control.probe() is None
    assert not store


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows vault and mutex")
@pytest.mark.asyncio
async def test_native_windows_update_control_uses_isolated_vault_and_mutex(monkeypatch) -> None:
    from kicad_mcp import cloud_windows_single_instance as guard
    from kicad_mcp import cloud_windows_update_control as control

    generation, record = uuid4().hex, uuid4().hex
    monkeypatch.setattr(guard, "_MUTEX_NAME", "Local\\KiCadMcpProUpdateTest-" + uuid4().hex)
    monkeypatch.setattr(control, "_SLOT", record)
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_GENERATION", generation)
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_SLOT", "b")
    try:
        with guard.owner_connector_instance():
            async with control.watch(ORIGIN) as drain:
                assert drain is not None
                assert control.probe() == (generation, "b")
                assert control.request(generation, "b")
                await asyncio.wait_for(drain.wait(), 2)
            assert control.probe() is None
        assert control.read_credential(record, "update_lease") is None
        assert control.read_credential(generation, "update_request") is None
    finally:
        control.delete_credential(record, "update_lease")
        control.delete_credential(generation, "update_request")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["headless", "background_restore"])
async def test_update_wrapper_does_not_publish_lease_for_ineligible_session(
    control_fixture, monkeypatch, mode
) -> None:
    from kicad_mcp import cloud_user_cli

    control, store = control_fixture
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_GENERATION", uuid4().hex)
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_SLOT", "a")
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: mode != "headless")
    token = cloud_user_cli._BACKGROUND_CONNECTOR_HANDOFF.set(
        object() if mode == "background_restore" else None
    )
    calls = []

    async def session() -> None:
        calls.append("ordinary")

    try:
        assert not await cloud_user_cli._windows_update_session(ORIGIN, session)
        assert calls == ["ordinary"]
        assert not store
        assert control.probe() is None
    finally:
        cloud_user_cli._BACKGROUND_CONNECTOR_HANDOFF.reset(token)


@pytest.mark.asyncio
async def test_update_lease_requires_owner_and_discards_only_stale_generation(
    control_fixture, monkeypatch
) -> None:
    from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError

    control, store = control_fixture
    old, current = uuid4().hex, uuid4().hex
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_GENERATION", current)
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_SLOT", "a")
    store[(control._SLOT, "update_lease")] = control._payload(old, "b")
    store[(old, "update_request")] = control._payload(old, "b")
    before = store.copy()
    monkeypatch.setattr(control, "_owner_held", lambda: False)

    async def start_without_authority():
        async with control.watch(ORIGIN):
            pytest.fail("unauthorized owner")

    with pytest.raises(LocalApprovalDeniedError):
        await start_without_authority()
    assert store == before
    monkeypatch.setattr(control, "_owner_held", lambda: True)
    live = control._generation_live
    monkeypatch.setattr(control, "_generation_live", lambda generation: generation == old)

    async def replace_live_generation():
        async with control.watch(ORIGIN):
            pytest.fail("must not replace live generation")

    with pytest.raises(LocalApprovalDeniedError):
        await replace_live_generation()
    assert store == before
    monkeypatch.setattr(control, "_generation_live", live)
    async with control.watch(ORIGIN) as drain:
        assert drain is not None
        assert not drain.is_set()
        assert (old, "update_request") not in store
        assert control.probe() == (current, "a")
        assert control.request(current, "a")
        assert control.request(current, "a")
        await asyncio.wait_for(drain.wait(), 2)
    assert not store


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["foreign", "malformed", "missing"])
async def test_update_watch_stops_on_lost_or_invalid_lease(
    control_fixture, monkeypatch, fault
) -> None:
    control, store = control_fixture
    current = uuid4().hex
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_GENERATION", current)
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_SLOT", "a")
    async with control.watch(ORIGIN) as drain:
        assert drain is not None
        assert not drain.is_set()
        slot = (control._SLOT, "update_lease")
        if fault == "missing":
            store.pop(slot)
        elif fault == "foreign":
            store[slot] = control._payload(uuid4().hex, "b")
        else:
            store[slot] = b'{"generation":3,"slot":"bad"}'
        assert control.probe() is None
        assert not control.request(current, "a")
        before = store.copy()
        await asyncio.wait_for(drain.wait(), 2)
        # Restore a parseable record only for cleanup of this test's lease.
        if fault == "malformed":
            store.pop(slot)
            before = store.copy()
    assert store == before


@pytest.mark.parametrize("raw", [b"[]", b"{}", b'{"generation":1,"slot":"a"}', b"not-json"])
def test_malformed_update_lease_does_not_authorize_request(control_fixture, raw) -> None:
    control, store = control_fixture
    store[(control._SLOT, "update_lease")] = raw
    before = store.copy()
    assert control.probe() is None
    assert not control.request(uuid4().hex, "a")
    assert store == before


@pytest.mark.asyncio
async def test_update_request_survives_same_generation_transition(
    control_fixture, monkeypatch
) -> None:
    control, store = control_fixture
    current = uuid4().hex
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_GENERATION", current)
    monkeypatch.setenv("KICAD_CLOUD_UPDATE_SLOT", "b")
    async with control.watch(ORIGIN) as drain:
        assert drain is not None
        assert not drain.is_set()
        # The device-only session completes immediately after the installer request.
        assert control.request(current, "b")
    assert store[(current, "update_request")] == control._payload(current, "b")
    async with control.watch(ORIGIN) as drain:
        assert drain is not None
        assert drain.is_set()
    assert not store


def test_update_control_rejects_unsupported_platform_and_invalid_generation(monkeypatch) -> None:
    from kicad_mcp import cloud_windows_update_control as control
    from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError

    monkeypatch.setattr(control, "_supported", lambda: False)
    assert control.probe() is None
    with pytest.raises(LocalApprovalDeniedError):
        control._kernel()
    with pytest.raises(LocalApprovalDeniedError):
        control._name("invalid")


@pytest.mark.parametrize("error", [2, 5, 183])
def test_generation_mutex_denies_unverifiable_kernel_results(monkeypatch, error) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_windows_credentials as credentials
    from kicad_mcp import cloud_windows_update_control as control
    from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError

    closed = []
    kernel = SimpleNamespace(
        CreateMutexW=lambda *_: 123 if error == 183 else None,
        OpenMutexW=lambda *_: None,
        CloseHandle=closed.append,
        ReleaseMutex=lambda *_: pytest.fail("must not release a mutex we did not acquire"),
    )
    monkeypatch.setattr(control, "_kernel", lambda: kernel)
    monkeypatch.setattr(credentials, "_last_error", lambda: error)
    generation = uuid4().hex

    def acquire_unverified_mutex():
        with control._generation_mutex(generation):
            pytest.fail("unverified mutex must not be acquired")

    with pytest.raises(LocalApprovalDeniedError):
        acquire_unverified_mutex()
    assert closed == ([123] if error == 183 else [])
    if error == 2:
        assert not control._generation_live(generation)
    else:
        with pytest.raises(LocalApprovalDeniedError):
            control._generation_live(generation)
