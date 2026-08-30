"""Regression coverage for the architecture checker's TYPE_CHECKING handling."""

from __future__ import annotations

from pathlib import Path

from scripts import check_architecture_boundaries as boundaries

_MODULE_NAME = "kicad_mcp.pure.example"


def test_imports_for_ignores_type_checking_only_import(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text(
        "from __future__ import annotations\n"
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from kipy.board import Board\n"
        "def f(board: Board) -> None: ...\n",
        encoding="utf-8",
    )

    imports = boundaries._imports_for(_MODULE_NAME, source)

    assert "kipy.board" not in imports


def test_imports_for_still_reports_runtime_import(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    source.write_text("from kipy.board import Board\n", encoding="utf-8")

    imports = boundaries._imports_for(_MODULE_NAME, source)

    assert "kipy.board" in imports


def test_imports_for_still_reports_a_sibling_import_alongside_a_type_checking_block(
    tmp_path: Path,
) -> None:
    source = tmp_path / "example.py"
    source.write_text(
        "from __future__ import annotations\n"
        "from typing import TYPE_CHECKING\n"
        "import hashlib\n"
        "if TYPE_CHECKING:\n"
        "    from kipy.board import Board\n",
        encoding="utf-8",
    )

    imports = boundaries._imports_for(_MODULE_NAME, source)

    assert "hashlib" in imports
    assert "kipy.board" not in imports


def test_pcb_transaction_lifecycle_no_longer_imports_kipy_at_runtime() -> None:
    module_name = "kicad_mcp.pcb.transaction_lifecycle"
    path = boundaries.DOMAIN_MODULES[module_name]

    imports = boundaries._imports_for(module_name, path)

    assert not any(name.startswith("kipy") for name in imports)
