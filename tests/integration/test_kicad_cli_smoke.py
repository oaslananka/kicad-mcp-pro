"""Real KiCad CLI smoke tests.

These tests intentionally skip unless KICAD_MCP_KICAD_CLI points to a real
kicad-cli executable. They are not subprocess mocks; CI should run them only in
a KiCad 10-capable environment.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

KICAD_MAJOR_VERSION = 10


@pytest.fixture(scope="session")
def kicad_cli_path() -> Path:
    """Return the configured KiCad CLI path or skip when unavailable."""
    raw_path = os.environ.get("KICAD_MCP_KICAD_CLI", "").strip()
    if not raw_path:
        pytest.skip("KICAD_MCP_KICAD_CLI is not set; skipping real KiCad CLI smoke tests.")

    cli_path = Path(raw_path).expanduser()
    if not cli_path.exists():
        pytest.skip(f"KICAD_MCP_KICAD_CLI does not exist: {cli_path}")
    if not cli_path.is_file():
        pytest.skip(f"KICAD_MCP_KICAD_CLI is not a file: {cli_path}")
    return cli_path


def _run_kicad_cli(cli_path: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
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
    (32 "B.Adhes" user "B.Adhesive")
    (33 "F.Adhes" user "F.Adhesive")
    (34 "B.Paste" user)
    (35 "F.Paste" user)
    (36 "B.SilkS" user "B.Silkscreen")
    (37 "F.SilkS" user "F.Silkscreen")
    (38 "B.Mask" user)
    (39 "F.Mask" user)
    (44 "Edge.Cuts" user)
  )
  (setup
    (pad_to_mask_clearance 0)
    (allow_soldermask_bridges_in_footprints no)
  )
)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return board_file


def test_kicad_cli_version_is_discoverable(kicad_cli_path: Path) -> None:
    """Verify that the configured binary is a KiCad 10 CLI."""
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
