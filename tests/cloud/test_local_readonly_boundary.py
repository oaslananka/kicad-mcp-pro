"""Offline contracts for a future connector. No running KiCad or Cloud needed."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from kicad_mcp.cloud_readonly_boundary import (
    LocalReadDeniedError,
    OperatorProject,
    VerifiedLocalBinding,
    inspect_readonly,
)

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="Secure no-follow directory traversal currently supported on POSIX only",
)

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
REQUEST = "33333333-3333-4333-8333-333333333333"
NOW = 1_800_000_000_000
SESSION = "44444444-4444-4444-8444-444444444444"


def bound(
    device: str = DEVICE,
    project: str = PROJECT,
    operations: frozenset[str] = frozenset({"project_summary"}),
    session: str = SESSION,
    expires: int = NOW + 60_000,
) -> VerifiedLocalBinding:
    return VerifiedLocalBinding(device, project, operations, session, expires)


@pytest.fixture
def approved(tmp_path: Path) -> tuple[VerifiedLocalBinding, OperatorProject]:
    folder = tmp_path / "approved"
    folder.mkdir()
    for ext in (".kicad_pro", ".kicad_pcb", ".kicad_sch"):
        (folder / ("Example" + ext)).write_text("confidential content", encoding="utf-8")
    return (
        bound(),
        OperatorProject(DEVICE, PROJECT, folder, "Example"),
    )


def packet(**changes: object) -> bytes:
    frame: dict[str, object] = dict(
        kind="connector.read_request",
        version=1,
        requestId=REQUEST,
        deviceId=DEVICE,
        projectId=PROJECT,
        operation="project_summary",
        deadlineUnixMs=NOW + 1000,
    )
    frame.update(changes)
    return json.dumps(frame, separators=(",", ":")).encode("utf-8")


def invoke(frame: bytes, pair: tuple[VerifiedLocalBinding, OperatorProject]) -> dict[str, object]:
    return inspect_readonly(frame, verified=pair[0], operator_project=pair[1], now_unix_ms=NOW)


def test_approved_metadata_only_no_paths_or_project_contents(approved) -> None:
    result = invoke(packet(), approved)
    assert result == {
        "kind": "connector.local_read_preview",
        "version": 1,
        "requestId": REQUEST,
        "projectId": PROJECT,
        "operation": "project_summary",
        "files": {"projectPresent": True, "boardPresent": True, "schematicPresent": True},
    }
    as_text = json.dumps(result)
    assert "Example" not in as_text
    assert "confidential" not in as_text
    assert str(approved[1].directory) not in as_text


@pytest.mark.parametrize(
    "change",
    [
        {"deviceId": "44444444-4444-4444-8444-444444444444"},
        {"projectId": "55555555-5555-4555-8555-555555555555"},
        {"operation": "run_drc"},
        {"operation": "run_erc"},
        {"operation": ["project_summary"]},
        {"operation": {"name": "project_summary"}},
        {"operation": "write_board"},
        {"operation": "pcb_export"},
        {"deadlineUnixMs": NOW},
        {"deadlineUnixMs": NOW + 30_001},
        {"deadlineUnixMs": NOW + 1.5},
        {"deadlineUnixMs": True},
        {"version": 2},
        {"version": True},
        {"requestId": "../../tmp"},
        {"kind": "device.hello"},
        {"path": "/etc/passwd"},
    ],
)
def test_adversarial_frames_denied(approved, change) -> None:
    _raise_argument_1 = packet(**change)
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_1, approved)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{}",
        b"null",
        b"[]",
        b"not-json",
        b"\xff",
        b'{"kind":"connector.read_request","kind":"connector.read_request"}',
        b"x" * 1025,
        packet().replace(b"}", b',"arbitraryKey":"value"}'),
    ],
)
def test_malformed_or_noncanonical_frames_denied(approved, raw) -> None:
    with pytest.raises(LocalReadDeniedError):
        invoke(raw, approved)


def test_untrusted_binding_is_never_accepted(approved) -> None:
    wrong = bound(project="66666666-6666-4666-8666-666666666666")
    _raise_argument_2 = packet()
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_2, (wrong, approved[1]))
    no_cap = bound(operations=frozenset())
    _raise_argument_3 = packet()
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_3, (no_cap, approved[1]))


def test_symlinked_folder_and_symlinked_kicad_file_denied(approved, tmp_path) -> None:
    bridge = tmp_path / "link"
    bridge.symlink_to(approved[1].directory, target_is_directory=True)
    _raise_argument_4 = packet()
    _raise_argument_5 = (approved[0], OperatorProject(DEVICE, PROJECT, bridge, "Example"))
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_4, _raise_argument_5)
    file = approved[1].directory / "Example.kicad_pcb"
    file.unlink()
    file.symlink_to(tmp_path / "private")
    _raise_argument_6 = packet()
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_6, approved)


def test_symlinked_parent_component_denied(approved, tmp_path) -> None:
    intermediate = tmp_path / "parent_link"
    intermediate.symlink_to(approved[1].directory.parent, target_is_directory=True)
    changed = OperatorProject(DEVICE, PROJECT, intermediate / approved[1].directory.name, "Example")
    _raise_argument_7 = packet()
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_7, (approved[0], changed))


def test_project_presence_rejects_hardlinked_files_outside_approved_directory(
    approved: tuple[VerifiedLocalBinding, OperatorProject], tmp_path: Path
) -> None:
    """A regular inode aliased into the project is not an approved direct child.

    Cloud must not report the presence of a hard-linked file from another
    directory, even though os.stat(..., follow_symlinks=False) accepts it.
    """
    folder = approved[1].directory
    board = folder / "Example.kicad_pcb"
    board.unlink()
    outside = tmp_path / "unapproved-source.kicad_pcb"
    outside.write_text("different owner's layout", encoding="utf-8")
    os.link(outside, board)
    request = packet()
    with pytest.raises(LocalReadDeniedError):
        invoke(request, approved)
    board.unlink()
    assert invoke(packet(), approved)["files"] == {
        "projectPresent": True,
        "boardPresent": False,
        "schematicPresent": True,
    }


def test_project_presence_read_resists_directory_swap_after_fd_pin(
    approved, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_readonly_boundary

    selected = approved[1].directory
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    (decoy / "Example.kicad_pcb").write_text("attacker decoy")
    original_open = cloud_readonly_boundary._open_operator_directory

    def swap_after_open(path: Path) -> int:
        descriptor = original_open(path)
        selected.rename(tmp_path / "pinned-project")
        selected.symlink_to(decoy, target_is_directory=True)
        return descriptor

    monkeypatch.setattr(cloud_readonly_boundary, "_open_operator_directory", swap_after_open)
    result = invoke(packet(), approved)
    assert result["files"] == {
        "projectPresent": True,
        "boardPresent": True,
        "schematicPresent": True,
    }
    assert "attacker decoy" not in json.dumps(result)
    assert not any(str(path) in json.dumps(result) for path in (decoy, selected))


def test_replaced_file_with_directory_denied(approved) -> None:
    target = approved[1].directory / "Example.kicad_pcb"
    target.unlink()
    target.mkdir()
    _raise_argument_8 = packet()
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_8, approved)


def test_expired_request_and_invalid_local_context_denied(approved) -> None:
    _raise_argument_9 = packet()
    with pytest.raises(LocalReadDeniedError):
        inspect_readonly(
            _raise_argument_9,
            verified=approved[0],
            operator_project=approved[1],
            now_unix_ms=NOW + 1000,
        )
    bad = OperatorProject("not-a-uuid", PROJECT, approved[1].directory, "Example")
    _raise_argument_10 = packet()
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_10, (approved[0], bad))


def test_missing_board_is_explicit_and_still_read_only(approved) -> None:
    (approved[1].directory / "Example.kicad_pcb").unlink()
    result = invoke(packet(), approved)
    assert result["files"] == {
        "projectPresent": True,
        "boardPresent": False,
        "schematicPresent": True,
    }


def test_project_path_is_never_from_the_request(approved) -> None:
    with patch("subprocess.run", side_effect=AssertionError("no native process")):
        result = invoke(packet(), approved)
    assert result["operation"] == "project_summary"


def test_directory_entry_budget_denies_surprise_mass_scan(approved) -> None:
    folder = approved[1].directory
    for i in range(130):
        (folder / f"extra-{i}").touch()
    _raise_argument_11 = packet()
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_11, approved)


def test_operator_directory_rejects_lexical_parent_navigation(approved) -> None:
    folder = approved[1].directory
    # This resolves to the same legitimate directory on a normal POSIX
    # filesystem; a secure descriptor walk must still reject the parent hop.
    traversed = folder.parent / ".." / folder.parent.name / folder.name
    assert ".." in traversed.parts
    _raise_argument_12 = packet()
    _raise_argument_13 = (approved[0], OperatorProject(DEVICE, PROJECT, traversed, "Example"))
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_12, _raise_argument_13)


def test_operator_directory_rejects_overlong_components(approved) -> None:
    folder = approved[1].directory / ("x" * 256)
    _raise_argument_14 = packet()
    _raise_argument_15 = (approved[0], OperatorProject(DEVICE, PROJECT, folder, "Example"))
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_14, _raise_argument_15)


def test_operator_directory_walker_rejects_relative_input_directly() -> None:
    # The public read entrypoint already requires absolute paths. Exercise the
    # directory-FD helper's independent guard so future callers stay safe.
    from kicad_mcp.cloud_readonly_boundary import _open_operator_directory

    _raise_argument_16 = Path("relative")
    with pytest.raises(LocalReadDeniedError):
        _open_operator_directory(_raise_argument_16)
    with pytest.raises(LocalReadDeniedError):
        _open_operator_directory(None)  # type: ignore[arg-type]


def test_operator_directory_rejects_excessive_depth(approved) -> None:
    folder = approved[1].directory.joinpath(*(["subdir"] * 129))
    _raise_argument_17 = packet()
    _raise_argument_18 = (approved[0], OperatorProject(DEVICE, PROJECT, folder, "Example"))
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_17, _raise_argument_18)


def test_selected_directory_entry_limit_accepts_128_and_denies_129(approved) -> None:
    folder = approved[1].directory
    for i in range(125):
        (folder / f"extra-{i}").touch()
    assert invoke(packet(), approved)["files"] == {
        "projectPresent": True,
        "boardPresent": True,
        "schematicPresent": True,
    }
    (folder / "extra-125").touch()
    _raise_argument_19 = packet()
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_19, approved)


def test_huge_selected_directory_stops_enumerating_at_entry_budget(
    approved, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A local directory may contain millions of items. The read boundary
    # must not build the entire listing before checking its 128-entry budget.
    from kicad_mcp import cloud_readonly_boundary

    seen: list[int] = []

    class BoundedDirectory:
        def __enter__(self) -> BoundedDirectory:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def __iter__(self) -> Iterator[object]:
            for i in range(129):
                seen.append(i)
                yield type("DirectoryEntry", (), {"name": f"extra-{i}"})()
            raise AssertionError("Directory scan crossed its fixed entry budget")

    def reject_listdir(_fd: object) -> None:
        raise AssertionError("Eager os.listdir is an unbounded allocation")

    monkeypatch.setattr(cloud_readonly_boundary.os, "listdir", reject_listdir)
    monkeypatch.setattr(cloud_readonly_boundary.os, "scandir", lambda _fd: BoundedDirectory())
    _raise_argument_20 = packet()
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_20, approved)
    assert len(seen) == 129


def test_relative_operator_path_denied(approved) -> None:
    _raise_argument_21 = packet()
    _raise_argument_22 = (
        approved[0],
        OperatorProject(DEVICE, PROJECT, Path("relative"), "Example"),
    )
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_21, _raise_argument_22)


def test_committed_real_kicad10_sample_metadata_only() -> None:
    root = Path(__file__).resolve().parents[2]
    folder = root / "tests/fixtures/benchmark_projects/pass_minimal_mcu_board"
    assert (folder / "demo.kicad_pro").is_file()
    verified = bound()
    owner_policy = OperatorProject(DEVICE, PROJECT, folder, "demo")
    result = inspect_readonly(
        packet(), verified=verified, operator_project=owner_policy, now_unix_ms=NOW
    )
    assert result["files"] == {
        "projectPresent": True,
        "boardPresent": True,
        "schematicPresent": True,
    }
    assert "demo" not in json.dumps(result)


def test_invalid_operator_filename_type_fails_closed(approved) -> None:
    bad = OperatorProject(DEVICE, PROJECT, approved[1].directory, ["Example"])
    _raise_argument_23 = packet()
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_23, (approved[0], bad))


@pytest.mark.parametrize(
    "verified",
    [
        bound(session="bad-session"),
        bound(expires=NOW),
        bound(expires=NOW + 300_001),
        bound(expires=True),
        bound(expires=NOW + 500),
    ],
)
def test_session_expiration_and_deadline_bounded(approved, verified) -> None:
    _raise_argument_24 = packet()
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_24, (verified, approved[1]))


def test_request_deadline_cannot_outlive_session_lease(approved) -> None:
    valid = bound(expires=NOW + 500)
    assert invoke(packet(deadlineUnixMs=NOW + 200), (valid, approved[1]))["files"]["projectPresent"]
    _raise_argument_25 = packet(deadlineUnixMs=NOW + 1000)
    with pytest.raises(LocalReadDeniedError):
        invoke(_raise_argument_25, (valid, approved[1]))
