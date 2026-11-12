"""Windows native DRC must inspect only owner-bound, isolated KiCad copies."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.cloud_readonly_boundary import LocalReadDeniedError, OperatorProject
from kicad_mcp.cloud_windows_project_path import copy_windows_drc_inputs

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows handle test only")

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def selected(tmp_path: Path) -> OperatorProject:
    source = tmp_path / "source"
    source.mkdir()
    (source / "LED.kicad_pcb").write_bytes(b"board contents")
    (source / "LED.kicad_pro").write_bytes(b"project settings")
    (source / "LED.kicad_dru").write_bytes(b"custom design rules")
    return OperatorProject(DEVICE, PROJECT, source, "LED")


def test_windows_copies_only_fixed_owner_bound_inputs(
    selected: OperatorProject, tmp_path: Path
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    copy_windows_drc_inputs(selected.directory, selected.filename_stem, scratch)
    assert {f.name for f in scratch.iterdir()} == {
        "LED.kicad_pcb",
        "LED.kicad_pro",
        "LED.kicad_dru",
    }
    for f in scratch.iterdir():
        assert f.read_bytes() == (selected.directory / f.name).read_bytes()
        assert f.resolve().parent == scratch


def test_windows_refuses_hardlinked_board(selected: OperatorProject, tmp_path: Path) -> None:
    board = selected.directory / "LED.kicad_pcb"
    os.link(board, tmp_path / "outside.kicad_pcb")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(LocalReadDeniedError):
        copy_windows_drc_inputs(selected.directory, selected.filename_stem, scratch)


def test_windows_refuses_linked_project(selected: OperatorProject, tmp_path: Path) -> None:
    project = selected.directory / "LED.kicad_pro"
    outside = tmp_path / "secret"
    outside.write_bytes(b"private")
    project.unlink()
    try:
        project.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Windows symlink privilege not enabled")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(LocalReadDeniedError):
        copy_windows_drc_inputs(selected.directory, selected.filename_stem, scratch)


def test_windows_refuses_missing_board(selected: OperatorProject, tmp_path: Path) -> None:
    (selected.directory / "LED.kicad_pcb").unlink()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(LocalReadDeniedError):
        copy_windows_drc_inputs(selected.directory, selected.filename_stem, scratch)


def test_windows_refuses_oversized_board(selected: OperatorProject, tmp_path: Path) -> None:
    board = selected.directory / "LED.kicad_pcb"
    with board.open("wb") as stream:
        stream.truncate(32 * 1024 * 1024 + 1)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(LocalReadDeniedError):
        copy_windows_drc_inputs(selected.directory, selected.filename_stem, scratch)


def test_windows_optional_project_file_can_be_missing(
    selected: OperatorProject, tmp_path: Path
) -> None:
    (selected.directory / "LED.kicad_pro").unlink()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    copy_windows_drc_inputs(selected.directory, selected.filename_stem, scratch)
    assert {f.name for f in scratch.iterdir()} == {"LED.kicad_pcb", "LED.kicad_dru"}


def test_windows_missing_binary_handle_capability_fails_closed(
    selected: OperatorProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(os, "O_BINARY", raising=False)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(LocalReadDeniedError):
        copy_windows_drc_inputs(selected.directory, selected.filename_stem, scratch)


def test_windows_missing_required_handle_fails_closed(
    selected: OperatorProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_windows_project_path

    original = cloud_windows_project_path._open_checked

    def missing_board(path: str, **kwargs: object) -> int | None:
        if path.endswith("LED.kicad_pcb"):
            return None
        return original(path, **kwargs)

    monkeypatch.setattr(cloud_windows_project_path, "_open_checked", missing_board)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(LocalReadDeniedError):
        copy_windows_drc_inputs(selected.directory, selected.filename_stem, scratch)


def test_windows_crt_conversion_failure_closes_handle(
    selected: OperatorProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import msvcrt

    def reject_handle(*_: object) -> int:
        raise OSError("simulated conversion failure")

    monkeypatch.setattr(msvcrt, "open_osfhandle", reject_handle)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(LocalReadDeniedError):
        copy_windows_drc_inputs(selected.directory, selected.filename_stem, scratch)


def test_windows_rejects_invalid_project_name_and_directory(
    selected: OperatorProject, tmp_path: Path
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(LocalReadDeniedError):
        copy_windows_drc_inputs(selected.directory, "../private", scratch)
    with pytest.raises(LocalReadDeniedError):
        copy_windows_drc_inputs(tmp_path / "not-present", "LED", scratch)


def test_windows_native_drc_discovers_installed_cli_without_path(
    selected: OperatorProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_native_drc, discovery

    trusted_cli = tmp_path / "trusted-kicad-cli.exe"
    trusted_cli.write_bytes(b"test executable placeholder")
    monkeypatch.setattr(cloud_native_drc.shutil, "which", lambda _: None)
    monkeypatch.setattr(discovery, "discover_kicad_cli", lambda: trusted_cli)

    def native(argv: list[str], **_: object) -> SimpleNamespace:
        assert argv[0] == str(trusted_cli)
        assert argv[1:4] == ["pcb", "drc", "--format"]
        Path(argv[-2]).write_text(
            json.dumps({"violations": [{}], "unconnected_items": [{}, {}]}),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=5)

    monkeypatch.setattr(cloud_native_drc.subprocess, "run", native)
    counts = cloud_native_drc.summarize_native_pcb_drc(selected)
    assert counts == {"violations": 1, "unconnectedItems": 2}


def test_native_windows_cli_drc_on_disposable_public_fixture(tmp_path: Path) -> None:
    """Real KiCad 10 through bounded post-authenticated managed READ framing.

    The WebSocket peer is simulated; this does not claim live Cloud OAuth or
    a real TLS session. It tests the native CLI and the actual reply boundary
    in one expensive invocation rather than running KiCad twice.
    """
    from kicad_mcp.cloud_managed_read_transport import serve_authenticated_reads
    from kicad_mcp.cloud_outbound_handshake import HandshakeReceipt
    from kicad_mcp.cloud_read_dispatch import LocalReadDispatch
    from kicad_mcp.cloud_readonly_boundary import VerifiedLocalBinding
    from kicad_mcp.discovery import discover_kicad_cli

    cli = discover_kicad_cli()
    if not cli.is_file():
        pytest.skip("KiCad CLI unavailable on this Windows host")
    fixture = Path(__file__).resolve().parents[2] / (
        "packages/kicad-fixtures/fixtures/clean-led-kicad10"
    )
    source = tmp_path / "fixture"
    source.mkdir()
    originals = {}
    for item in fixture.iterdir():
        originals[item.name] = item.read_bytes()
        shutil.copyfile(item, source / item.name)

    request_id = "44444444-4444-4444-8444-444444444444"
    session_id = "33333333-3333-4333-8333-333333333333"
    now = 1_800_000_000_000
    request = {
        "kind": "connector.read_request",
        "version": 1,
        "requestId": request_id,
        "deviceId": DEVICE,
        "projectId": PROJECT,
        "operation": "run_drc",
        "deadlineUnixMs": now + 46_000,
    }

    class SimulatedAuthenticatedSocket:
        def __init__(self) -> None:
            self.messages = [
                json.dumps(
                    {
                        "kind": "connector.authorized_read",
                        "version": 1,
                        "sequence": 1,
                        "request": request,
                    }
                ),
                json.dumps(
                    {
                        "kind": "connector.read_ack",
                        "version": 1,
                        "sequence": 1,
                        "requestId": request_id,
                    }
                ),
            ]
            self.sent: list[dict[str, object]] = []

        async def recv(self) -> str:
            return self.messages.pop(0)

        async def send(self, payload: str) -> None:
            self.sent.append(json.loads(payload))

    receipt = HandshakeReceipt(DEVICE, session_id)
    project = OperatorProject(DEVICE, PROJECT, source, "clean-led-kicad10")
    verified = VerifiedLocalBinding(
        DEVICE, PROJECT, frozenset({"run_drc"}), session_id, now + 120_000
    )
    reader = LocalReadDispatch(
        verified=verified,
        operator_project=project,
        current_authorization=lambda: True,
        clock_ms=lambda: now,
        max_reads=1,
        native_drc=True,
        managed_native_drc=True,
    )
    socket = SimulatedAuthenticatedSocket()
    assert (
        asyncio.run(
            serve_authenticated_reads(
                socket, receipt, lambda _: reader, max_reads=1, allow_native_drc=True
            )
        )
        == receipt
    )
    assert socket.messages == []
    assert len(socket.sent) == 1
    envelope = socket.sent[0]
    assert set(envelope) == {"kind", "version", "sequence", "result"}
    assert envelope["kind"] == "connector.read_result"
    result = envelope["result"]
    assert isinstance(result, dict)
    assert set(result) == {
        "kind",
        "version",
        "requestId",
        "projectId",
        "operation",
        "counts",
    }
    assert result["kind"] == "connector.local_drc_preview"
    assert result["operation"] == "run_drc"
    assert result["requestId"] == request_id
    counts = result["counts"]
    assert isinstance(counts, dict)
    assert counts.keys() == {"violations", "unconnectedItems"}
    assert all(type(value) is int and value >= 0 for value in counts.values())
    assert {f.name: f.read_bytes() for f in source.iterdir()} == originals
