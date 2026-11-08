"""Real Windows-only no-follow KiCad presence boundary acceptance."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kicad_mcp.cloud_readonly_boundary import LocalReadDeniedError
from kicad_mcp.cloud_windows_project_path import (
    _path_parts,
    read_windows_project_presence,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Native Windows handle checks required")


def test_native_project_presence_uses_exact_three_children(tmp_path: Path) -> None:
    project = tmp_path / "pcb"
    project.mkdir()
    (project / "demo.kicad_pro").write_text("{}", encoding="utf-8")
    (project / "demo.kicad_pcb").write_text("pcb", encoding="utf-8")
    (project / "unrelated.kicad_sch").write_text("other", encoding="utf-8")
    assert read_windows_project_presence(project, "demo") == {
        "projectPresent": True,
        "boardPresent": True,
        "schematicPresent": False,
    }
    assert read_windows_project_presence(project, "missing") == {
        "projectPresent": False,
        "boardPresent": False,
        "schematicPresent": False,
    }


@pytest.mark.parametrize(
    "name",
    ["../outside", "..", ".", "", "x/sneak", "x\\\\sneak", "x:ads", "X" * 81],
)
def test_native_file_selector_rejects_traversal(tmp_path: Path, name: str) -> None:
    with pytest.raises(LocalReadDeniedError):
        read_windows_project_presence(tmp_path, name)


def test_native_project_path_rejects_ancestor_traversal(tmp_path: Path) -> None:
    escaped = tmp_path / ".." / tmp_path.name
    with pytest.raises(LocalReadDeniedError):
        read_windows_project_presence(escaped, "demo")


def test_native_file_directory_substitution_is_denied(tmp_path: Path) -> None:
    (tmp_path / "demo.kicad_pcb").mkdir()
    with pytest.raises(LocalReadDeniedError):
        read_windows_project_presence(tmp_path, "demo")


def test_native_hardlinked_child_is_denied(tmp_path: Path) -> None:
    outside = tmp_path / "source"
    outside.write_text("other", encoding="utf-8")
    os.link(outside, tmp_path / "demo.kicad_pcb")
    with pytest.raises(LocalReadDeniedError):
        read_windows_project_presence(tmp_path, "demo")


def test_native_reparse_child_is_denied_if_symlinks_supported(tmp_path: Path) -> None:
    target = tmp_path / "target.kicad_pcb"
    target.write_text("pcb", encoding="utf-8")
    link = tmp_path / "demo.kicad_pcb"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Developer Mode or symlink privilege is unavailable")
    with pytest.raises(LocalReadDeniedError):
        read_windows_project_presence(tmp_path, "demo")


def test_native_reparse_directory_is_denied_if_symlinks_supported(tmp_path: Path) -> None:
    original = tmp_path / "original"
    original.mkdir()
    (original / "demo.kicad_pro").touch()
    link = tmp_path / "linked"
    try:
        link.symlink_to(original, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Developer Mode or symlink privilege is unavailable")
    with pytest.raises(LocalReadDeniedError):
        read_windows_project_presence(link, "demo")


def test_native_network_share_and_win32_device_paths_refused(tmp_path: Path) -> None:
    invalid = [r"\\server\share\board", r"\\?\C:\project", r"C:relative", r"C:\a\..\b"]
    for path in invalid:
        with pytest.raises(LocalReadDeniedError):
            read_windows_project_presence(Path(path), "demo")
    assert _path_parts(tmp_path)[0].endswith("\\")


def test_native_absent_project_directory_denied(tmp_path: Path) -> None:
    with pytest.raises(LocalReadDeniedError):
        read_windows_project_presence(tmp_path / "not-created", "demo")


def test_native_cloud_readonly_boundary_can_read_only_local_presence(tmp_path: Path) -> None:
    import json
    import time

    from kicad_mcp.cloud_readonly_boundary import (
        OperatorProject,
        VerifiedLocalBinding,
        inspect_readonly,
    )

    (tmp_path / "demo.kicad_pro").touch()
    now_ms = time.time_ns() // 1_000_000
    device = "19ee4be9-0aec-448e-9873-721ae113ec02"
    project = "29ee4be9-0aec-448e-9873-721ae113ec02"
    request_id = "39ee4be9-0aec-448e-9873-721ae113ec02"
    session_id = "49ee4be9-0aec-448e-9873-721ae113ec02"
    boundary = VerifiedLocalBinding(
        device_id=device,
        project_id=project,
        operations=frozenset({"project_summary"}),
        session_id=session_id,
        session_expires_unix_ms=now_ms + 60_000,
    )
    selected = OperatorProject(
        device_id=device,
        project_id=project,
        directory=tmp_path,
        filename_stem="demo",
    )
    frame = json.dumps(
        {
            "kind": "connector.read_request",
            "version": 1,
            "requestId": request_id,
            "deviceId": device,
            "projectId": project,
            "operation": "project_summary",
            "deadlineUnixMs": now_ms + 10_000,
        }
    ).encode("utf-8")
    result = inspect_readonly(
        frame, verified=boundary, operator_project=selected, now_unix_ms=now_ms
    )
    assert result["files"] == {
        "projectPresent": True,
        "boardPresent": False,
        "schematicPresent": False,
    }
    assert "directory" not in result
    assert "contents" not in result


def test_native_cloud_readonly_boundary_denies_unapproved_command(tmp_path: Path) -> None:
    import json
    import time

    from kicad_mcp.cloud_readonly_boundary import (
        OperatorProject,
        VerifiedLocalBinding,
        inspect_readonly,
    )

    now_ms = time.time_ns() // 1_000_000
    device = "19ee4be9-0aec-448e-9873-721ae113ec02"
    project = "29ee4be9-0aec-448e-9873-721ae113ec02"
    frame = json.dumps(
        {
            "kind": "connector.read_request",
            "version": 1,
            "requestId": "39ee4be9-0aec-448e-9873-721ae113ec02",
            "deviceId": device,
            "projectId": project,
            "operation": "run_drc",
            "deadlineUnixMs": now_ms + 10_000,
        }
    ).encode()
    verified = VerifiedLocalBinding(
        device_id=device,
        project_id=project,
        operations=frozenset({"project_summary"}),
        session_id="49ee4be9-0aec-448e-9873-721ae113ec02",
        session_expires_unix_ms=now_ms + 60_000,
    )
    operator_project = OperatorProject(
        device_id=device,
        project_id=project,
        directory=tmp_path,
        filename_stem="demo",
    )
    with pytest.raises(LocalReadDeniedError):
        inspect_readonly(
            frame,
            verified=verified,
            operator_project=operator_project,
            now_unix_ms=now_ms,
        )


def test_native_junction_directory_is_denied(tmp_path: Path) -> None:
    """Windows junctions usually work without developer-mode symlink privilege."""
    import subprocess

    original = tmp_path / "original"
    original.mkdir()
    (original / "demo.kicad_pro").touch()
    junction = tmp_path / "linked_junction"
    cmd = Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"
    result = subprocess.run(
        [str(cmd), "/d", "/c", "mklink", "/J", str(junction), str(original)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("Junction creation unavailable in this Windows environment")
    with pytest.raises(LocalReadDeniedError):
        read_windows_project_presence(junction, "demo")
