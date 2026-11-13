"""Real KiCad CLI smoke tests.

These tests intentionally skip unless a real ``kicad-cli`` executable is
discoverable from ``KICAD_MCP_KICAD_CLI``, ``KICAD_CLI_PATH``, ``PATH``, or the
project's existing discovery/configuration layer. They are not subprocess mocks;
CI should run them only in a KiCad 10-capable environment.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from kicad_mcp.config import get_config, reset_config
from kicad_mcp.models.pcb import StackupLayerSpec
from kicad_mcp.tools.pcb import _apply_stackup_to_board, _parse_stackup_specs_from_board_text

KICAD_MAJOR_VERSION = 10


def _candidate_cli_paths() -> list[Path]:
    """Return ordered KiCad CLI candidates from env, PATH, then project discovery."""
    candidates: list[Path] = []
    for env_name in ("KICAD_MCP_KICAD_CLI", "KICAD_CLI_PATH"):
        raw_path = os.environ.get(env_name, "").strip()
        if raw_path:
            candidates.append(Path(raw_path).expanduser())

    discovered = shutil.which("kicad-cli")
    if discovered:
        candidates.append(Path(discovered))

    try:
        reset_config()
        candidates.append(get_config().kicad_cli)
    except Exception:  # noqa: S110
        pass

    deduplicated: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            deduplicated.append(candidate)
            seen.add(key)
    return deduplicated


@pytest.fixture(scope="session")
def kicad_cli_path() -> Path:
    """Return the configured/discovered KiCad CLI path or skip when unavailable."""
    for cli_path in _candidate_cli_paths():
        if cli_path.exists() and cli_path.is_file():
            return cli_path
    searched = ", ".join(str(path) for path in _candidate_cli_paths()) or "<none>"
    pytest.skip(f"kicad-cli not found via env, PATH, or discovery. Candidates: {searched}")
    raise RuntimeError("pytest.skip() returned unexpectedly")


def _run_kicad_cli(
    cli_path: Path,
    *args: str,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run kicad-cli and return a completed process with captured text output."""
    return subprocess.run(
        [str(cli_path), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (result.stdout, result.stderr) if part)


def _write_minimal_project(project_dir: Path) -> Path:
    """Create a deterministic minimal KiCad project with an empty board file."""
    project_dir.mkdir(parents=True, exist_ok=True)
    project_file = project_dir / "smoke.kicad_pro"
    board_file = project_dir / "smoke.kicad_pcb"
    project_file.write_text(
        """
{
  "board": {
    "design_settings": {
      "defaults": {},
      "diff_pair_dimensions": [],
      "drc_exclusions": [],
      "rules": {}
    }
  },
  "meta": {
    "filename": "smoke.kicad_pro",
    "version": 1
  },
  "net_settings": {
    "classes": [],
    "meta": {
      "version": 3
    },
    "nets": []
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    board_file.write_text(
        """
(kicad_pcb
  (version 20240108)
  (generator "kicad-mcp-pro-smoke")
  (general)
  (paper "A4")
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (44 "Edge.Cuts" user)
  )
  (setup (pad_to_mask_clearance 0))
)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return board_file


def test_kicad_cli_version_is_discoverable(kicad_cli_path: Path) -> None:
    """Verify that the discovered binary is a KiCad 10 CLI."""
    result = _run_kicad_cli(kicad_cli_path, "version")
    output = _combined_output(result)

    assert result.returncode == 0, output
    match = re.search(r"\b(\d+)\.\d+(?:\.\d+)?\b", output)
    assert match is not None, output
    assert int(match.group(1)) == KICAD_MAJOR_VERSION, output


def test_kicad_cli_exports_board_stats_without_gui(kicad_cli_path: Path, tmp_path: Path) -> None:
    """Run a GUI-free CLI export path against a minimal board fixture."""
    project_dir = tmp_path / "project"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    board_file = _write_minimal_project(project_dir)
    stats_file = artifacts_dir / "board_stats.txt"

    result = _run_kicad_cli(
        kicad_cli_path,
        "pcb",
        "export",
        "stats",
        "--output",
        str(stats_file),
        str(board_file),
        cwd=project_dir,
    )
    output = _combined_output(result)
    (artifacts_dir / "kicad-cli-stdout.log").write_text(result.stdout, encoding="utf-8")
    (artifacts_dir / "kicad-cli-stderr.log").write_text(result.stderr, encoding="utf-8")

    assert result.returncode == 0, output
    assert stats_file.exists(), output
    assert stats_file.stat().st_size > 0, output


def _four_layer_stackup_specs() -> list[StackupLayerSpec]:
    def dielectric(name: str, layer_type: str, thickness_mm: float) -> StackupLayerSpec:
        return StackupLayerSpec(
            name=name, type=layer_type, thickness_mm=thickness_mm, material="FR4", epsilon_r=4.4
        )

    return [
        StackupLayerSpec(name="F.Mask", thickness_mm=0.01),
        StackupLayerSpec(name="F.Cu", thickness_mm=0.035),
        dielectric("dielectric_1", "prepreg", 0.1),
        StackupLayerSpec(name="In1.Cu", thickness_mm=0.0152),
        dielectric("dielectric_2", "core", 0.4796),
        StackupLayerSpec(name="In2.Cu", thickness_mm=0.0152),
        dielectric("dielectric_3", "prepreg", 0.1),
        StackupLayerSpec(name="B.Cu", thickness_mm=0.035),
        StackupLayerSpec(name="B.Mask", thickness_mm=0.01),
    ]


def _resaved_by_kicad(cli_path: Path, board_file: Path) -> str:
    result = _run_kicad_cli(cli_path, "pcb", "upgrade", "--force", str(board_file))
    assert result.returncode == 0, _combined_output(result)
    return board_file.read_text(encoding="utf-8")


def _copper_in_layer_table(board_text: str) -> list[str]:
    table_start = board_text.index("(layers")
    table = board_text[table_start : board_text.index("(setup", table_start)]
    return re.findall(r'\(\d+\s+"((?:F|B|In\d+)\.Cu)"', table)


@pytest.mark.parametrize("kicad10_layer_ids", [False, True], ids=["kicad8-ids", "kicad10-ids"])
def test_pcb_stackup_writer_survives_a_kicad_resave(
    kicad_cli_path: Path, tmp_path: Path, kicad10_layer_ids: bool
) -> None:
    """KiCad must keep the inner copper layers the stackup writer adds (issue: they became
    dielectrics because the layer table was never updated)."""
    board_file = _write_minimal_project(tmp_path / "project")
    if kicad10_layer_ids:
        _resaved_by_kicad(kicad_cli_path, board_file)  # renumber B.Cu 31 -> 2 first

    board_file.write_text(
        _apply_stackup_to_board(
            board_file.read_text(encoding="utf-8"), _four_layer_stackup_specs()
        ),
        encoding="utf-8",
    )
    resaved = _resaved_by_kicad(kicad_cli_path, board_file)

    assert sorted(_copper_in_layer_table(resaved)) == ["B.Cu", "F.Cu", "In1.Cu", "In2.Cu"]
    parsed = _parse_stackup_specs_from_board_text(resaved)
    assert parsed is not None
    assert [layer.name for layer in parsed if layer.name.endswith("_Cu")] == [
        "F_Cu",
        "In1_Cu",
        "In2_Cu",
        "B_Cu",
    ]
    assert [layer.name for layer in parsed if layer.name.startswith("dielectric")] == [
        "dielectric_1",
        "dielectric_2",
        "dielectric_3",
    ]
    general = re.search(r"\(general\s*\(thickness\s+([\d.]+)\)", resaved)
    assert general is not None
    assert float(general.group(1)) == pytest.approx(0.8)
