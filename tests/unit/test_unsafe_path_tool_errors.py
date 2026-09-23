"""Path-safety rejections must raise, not return success-shaped text.

Several CLI wrapper tools catch ``resolve_under`` failures and returned a plain
``"Unsafe ... path: ..."`` string. That string never matches the server's failure
heuristics (``server._tool_failure_message``), so a rejected path traversal attempt
was reported to the caller as an ordinary (non-error) tool result. These tools must
instead raise, so the MCP protocol layer marks the response ``isError``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.tools import footprint, jobset, manufacturing, symbol, upgrade


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self) -> Callable[[Callable[..., object]], Callable[..., object]]:
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


def _register(module) -> dict[str, object]:
    mcp = FakeMCP()
    module.register(mcp)
    return mcp.tools


def _config(project_dir: Path, **overrides: object) -> SimpleNamespace:
    base = {
        "project_dir": project_dir,
        "sch_file": None,
        "pcb_file": None,
        "project_file": None,
        "kicad_cli": Path("/usr/bin/kicad-cli"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# symbol.py
# ---------------------------------------------------------------------------


def test_sym_export_svg_rejects_unsafe_input_file(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    tools = _register(symbol)
    monkeypatch.setattr(symbol, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe input file path"):
        tools["sym_export_svg"](input_file="../outside.kicad_sym")


def test_sym_export_svg_rejects_unsafe_output_dir(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    symbol_file = project_dir / "lib.kicad_sym"
    symbol_file.write_text("(kicad_symbol_lib)", encoding="utf-8")
    tools = _register(symbol)
    monkeypatch.setattr(symbol, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe output directory"):
        tools["sym_export_svg"](input_file="lib.kicad_sym", output_dir="../outside")


def test_sym_upgrade_rejects_unsafe_input_file(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    tools = _register(symbol)
    monkeypatch.setattr(symbol, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe input file path"):
        tools["sym_upgrade"](input_file="../outside.kicad_sym")


def test_sym_upgrade_rejects_unsafe_output_path(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    tools = _register(symbol)
    monkeypatch.setattr(symbol, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe output path"):
        tools["sym_upgrade"](input_file="lib.kicad_sym", output_file="../outside.kicad_sym")


# ---------------------------------------------------------------------------
# footprint.py
# ---------------------------------------------------------------------------


def test_fp_export_svg_rejects_unsafe_input_path(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    tools = _register(footprint)
    monkeypatch.setattr(footprint, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe input path"):
        tools["fp_export_svg"](input_path="../outside.kicad_mod")


def test_fp_export_svg_rejects_unsafe_output_dir(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    footprint_file = project_dir / "fp.kicad_mod"
    footprint_file.write_text("(footprint)", encoding="utf-8")
    tools = _register(footprint)
    monkeypatch.setattr(footprint, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe output directory"):
        tools["fp_export_svg"](input_path="fp.kicad_mod", output_dir="../outside")


def test_fp_upgrade_rejects_unsafe_input_path(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    tools = _register(footprint)
    monkeypatch.setattr(footprint, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe input path"):
        tools["fp_upgrade"](input_path="../outside.pretty")


def test_fp_upgrade_rejects_unsafe_output_path(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    tools = _register(footprint)
    monkeypatch.setattr(footprint, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe output path"):
        tools["fp_upgrade"](input_path="fp.pretty", output_file="../outside.pretty")


# ---------------------------------------------------------------------------
# jobset.py
# ---------------------------------------------------------------------------


def test_jobset_run_rejects_unsafe_jobset_path(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project_file = tmp_path / "board.kicad_pro"
    project_file.write_text("{}", encoding="utf-8")
    tools = _register(jobset)
    monkeypatch.setattr(jobset, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe jobset path"):
        tools["jobset_run"](
            project_file=str(project_file),
            jobset_file="../outside.kicad_jobset",
        )


def test_jobset_run_rejects_unsafe_output_path(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project_file = tmp_path / "board.kicad_pro"
    project_file.write_text("{}", encoding="utf-8")
    jobset_file = project_dir / "jobs.kicad_jobset"
    jobset_file.write_text("{}", encoding="utf-8")
    tools = _register(jobset)
    monkeypatch.setattr(jobset, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe output path"):
        tools["jobset_run"](
            project_file=str(project_file),
            jobset_file="jobs.kicad_jobset",
            output="../outside",
        )


def test_jobset_validate_rejects_unsafe_jobset_path(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    tools = _register(jobset)
    monkeypatch.setattr(jobset, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe jobset path"):
        tools["jobset_validate"](jobset_file="../outside.kicad_jobset")


# ---------------------------------------------------------------------------
# upgrade.py
# ---------------------------------------------------------------------------


def test_sch_upgrade_rejects_unsafe_input_path(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    tools = _register(upgrade)
    monkeypatch.setattr(upgrade, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe input path"):
        tools["sch_upgrade"](input_file="../outside.kicad_sch")


def test_sch_upgrade_rejects_unsafe_output_path(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    tools = _register(upgrade)
    monkeypatch.setattr(upgrade, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe output path"):
        tools["sch_upgrade"](input_file="board.kicad_sch", output_file="../outside.kicad_sch")


def test_pcb_upgrade_rejects_unsafe_input_path(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    tools = _register(upgrade)
    monkeypatch.setattr(upgrade, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe input path"):
        tools["pcb_upgrade"](input_file="../outside.kicad_pcb")


def test_pcb_upgrade_rejects_unsafe_output_path(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    tools = _register(upgrade)
    monkeypatch.setattr(upgrade, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe output path"):
        tools["pcb_upgrade"](input_file="board.kicad_pcb", output_file="../outside.kicad_pcb")


# ---------------------------------------------------------------------------
# manufacturing.py
# ---------------------------------------------------------------------------


def test_pcb_import_board_rejects_unsafe_input_path(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    tools = _register(manufacturing)
    monkeypatch.setattr(manufacturing, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe input file path"):
        tools["pcb_import_board"](input_file="../outside.brd")


def test_pcb_import_board_rejects_unsafe_report_file_path(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    board_file = project_dir / "board.brd"
    board_file.write_text("board", encoding="utf-8")
    tools = _register(manufacturing)
    monkeypatch.setattr(manufacturing, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe report file path"):
        tools["pcb_import_board"](
            input_file="board.brd",
            report_format="json",
            report_file="../outside-report.json",
        )


def test_pcb_import_board_rejects_unsafe_output_file_path(monkeypatch, tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    board_file = project_dir / "board.brd"
    board_file.write_text("board", encoding="utf-8")
    tools = _register(manufacturing)
    monkeypatch.setattr(manufacturing, "get_config", lambda: _config(project_dir))

    with pytest.raises(ValueError, match="Unsafe output file path"):
        tools["pcb_import_board"](
            input_file="board.brd",
            output_file="../outside.kicad_pcb",
        )
