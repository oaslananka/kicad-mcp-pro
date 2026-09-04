from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from kicad_mcp.config import KiCadMCPConfig
from kicad_mcp.errors import KiCadNotRunningError, UnsafePathError, error_payload
from kicad_mcp.path_safety import resolve_repo_or_temp
from kicad_mcp.utils.paths import relative_subpath, resolve_under

REPO_ROOT = Path(__file__).resolve().parents[2]
PATH_REGRESSION_CASES = json.loads(
    (REPO_ROOT / "test-fixtures" / "path-regression-cases.json").read_text(encoding="utf-8")
)


def test_resolve_within_project_blocks_traversal(sample_project: Path) -> None:
    cfg = KiCadMCPConfig(project_dir=sample_project)

    with pytest.raises(UnsafePathError):
        cfg.resolve_within_project("../outside.txt")


def test_explicit_workspace_blocks_outside_absolute_path(tmp_path: Path, fake_cli: Path) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "project"
    outside = tmp_path / "outside.txt"
    project.mkdir(parents=True)
    outside.write_text("x", encoding="utf-8")

    cfg = KiCadMCPConfig(kicad_cli=fake_cli, workspace_root=workspace, project_dir=project)

    with pytest.raises(UnsafePathError):
        cfg.resolve_within_project(outside)


def test_output_subdir_blocks_parent_traversal(sample_project: Path) -> None:
    cfg = KiCadMCPConfig(project_dir=sample_project)

    with pytest.raises(UnsafePathError):
        cfg.ensure_output_dir("../escape")


def test_path_utils_wrapper_resolves_safe_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    nested = workspace / "project" / "board.kicad_pcb"
    nested.parent.mkdir(parents=True)
    nested.write_text("(kicad_pcb)", encoding="utf-8")

    assert resolve_under(workspace, "project/board.kicad_pcb") == nested
    assert resolve_under(workspace, nested) == nested
    assert relative_subpath("exports/gerbers") == Path("exports/gerbers")


def test_cross_platform_path_fixture_covers_required_mcp_scenarios() -> None:
    assert PATH_REGRESSION_CASES["trackingIssue"] == "OASLANA-112"
    assert [scenario["id"] for scenario in PATH_REGRESSION_CASES["scenarios"]] == [
        "project-path-with-spaces",
        "unicode-project-path",
        "reserved-url-characters",
        "mixed-separators",
        "long-path",
        "symlinked-project-root",
        "windows-unc-path",
    ]
    assert "windows-2025-vs2026" in PATH_REGRESSION_CASES["ciMatrix"]


@pytest.mark.parametrize(
    ("scenario_id", "directory_name", "file_base"),
    [
        (
            scenario["id"],
            scenario["directoryName"],
            scenario["fileBase"],
        )
        for scenario in PATH_REGRESSION_CASES["scenarios"]
        if {"directoryName", "fileBase"}.issubset(scenario)
        and "symlink" not in scenario["tags"]
        and "long-path" not in scenario["tags"]
    ],
)
def test_mcp_project_paths_accept_spaces_unicode_and_special_characters(
    tmp_path: Path,
    fake_cli: Path,
    scenario_id: str,
    directory_name: str,
    file_base: str,
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / directory_name
    project.mkdir(parents=True)
    board = project / f"{file_base}.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")

    cfg = KiCadMCPConfig(kicad_cli=fake_cli, workspace_root=workspace, project_dir=project)

    assert scenario_id
    assert cfg.resolve_within_project(board.name) == board.resolve()


def test_mcp_path_safety_accepts_symlinked_project_roots_when_the_os_allows_symlinks(
    tmp_path: Path, fake_cli: Path
) -> None:
    scenario = next(
        scenario
        for scenario in PATH_REGRESSION_CASES["scenarios"]
        if scenario["id"] == "symlinked-project-root"
    )
    workspace = tmp_path / "workspace"
    target = workspace / scenario["directoryName"]
    link = workspace / scenario["linkName"]
    target.mkdir(parents=True)
    board = target / f"{scenario['fileBase']}.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        assert exc.errno is not None
        return

    cfg = KiCadMCPConfig(kicad_cli=fake_cli, workspace_root=workspace, project_dir=link)

    assert cfg.resolve_within_project(board.name) == board.resolve()


def test_mcp_path_safety_rejects_windows_unc_paths_on_non_windows_hosts(tmp_path: Path) -> None:
    scenario = next(
        scenario
        for scenario in PATH_REGRESSION_CASES["scenarios"]
        if scenario["id"] == "windows-unc-path"
    )
    if os.name == "nt":
        pytest.skip("Windows hosts validate UNC paths with native pathlib semantics.")

    with pytest.raises(UnsafePathError, match=scenario["expectedNonWindowsError"]):
        resolve_under(tmp_path, scenario["rawPath"])

    with pytest.raises(UnsafePathError, match=scenario["expectedNonWindowsError"]):
        relative_subpath(scenario["rawPath"])

    with pytest.raises(UnsafePathError, match=scenario["expectedNonWindowsError"]):
        resolve_under(tmp_path, Path(scenario["rawPath"]))


def test_mcp_path_safety_accepts_posix_colon_relative_paths(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("Colon-separated relative paths are POSIX-specific.")

    expected = tmp_path / "a:b" / "board.kicad_pcb"

    assert resolve_under(tmp_path, "a:b/board.kicad_pcb") == expected.resolve()


def test_mcp_path_safety_handles_long_paths_or_surfaces_platform_limit(
    tmp_path: Path, fake_cli: Path
) -> None:
    scenario = next(
        scenario for scenario in PATH_REGRESSION_CASES["scenarios"] if scenario["id"] == "long-path"
    )
    workspace = tmp_path / "workspace"
    project = workspace / scenario["directoryName"]
    board = project / f"{scenario['fileBase']}.kicad_pcb"
    while len(str(board)) <= scenario["minimumPathLength"]:
        project = project / "deep-segment-with-extra-length"
        board = project / f"{scenario['fileBase']}.kicad_pcb"
    try:
        project.mkdir(parents=True)
        board.write_text("(kicad_pcb)", encoding="utf-8")
    except OSError as exc:
        assert exc.errno is not None
        return

    cfg = KiCadMCPConfig(kicad_cli=fake_cli, workspace_root=workspace, project_dir=project)

    assert len(str(board)) > scenario["minimumPathLength"]
    assert cfg.resolve_within_project(board.name) == board.resolve()


def test_error_payload_masks_domain_shape() -> None:
    payload = error_payload(RuntimeError("boom"))

    assert payload == {
        "code": "INTERNAL_ERROR",
        "message": "boom",
        "hint": "Run doctor for diagnostics and retry with corrected configuration.",
        "retryable": False,
        "transient_class": "none",
        "retry_after_ms": None,
    }


def test_relative_subpath_blocks_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        relative_subpath(tmp_path)


def test_error_payload_preserves_domain_error() -> None:
    payload = error_payload(KiCadNotRunningError("not reachable"))

    assert payload["code"] == "KICAD_NOT_RUNNING"
    assert payload["message"] == "not reachable"
    assert payload["retryable"] is True


def test_error_payload_falls_back_to_exception_name() -> None:
    payload = error_payload(RuntimeError())

    assert payload["message"] == "RuntimeError"


def test_resolve_repo_or_temp_allows_repo_and_temp_but_blocks_escape(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    inside_repo = repo_root / "artifact.json"
    inside_repo.write_text("{}", encoding="utf-8")

    assert resolve_repo_or_temp(inside_repo, repo_root=repo_root) == inside_repo.resolve()
    assert (
        resolve_repo_or_temp(tmp_path / "outside-temp.txt", repo_root=repo_root)
        == (tmp_path / "outside-temp.txt").resolve()
    )

    with pytest.raises(UnsafePathError):
        resolve_repo_or_temp(Path.home() / ".ssh" / "id_rsa", repo_root=repo_root)
