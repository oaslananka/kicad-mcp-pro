"""Test-only AST reader handles both sync and async architectural boundaries."""

from __future__ import annotations

from pathlib import Path

from tests.architecture_source_helpers import _function_span, _imports


def test_async_register_is_counted_by_architecture_span(tmp_path: Path) -> None:
    file = tmp_path / "adapter.py"
    file.write_text("async def register():\n    await build()\n", encoding="utf-8")
    assert _function_span(file, "register") == 2


def test_architecture_imports_include_async_function_bodies(tmp_path: Path) -> None:
    file = tmp_path / "adapter.py"
    file.write_text("async def register():\n    import json\n", encoding="utf-8")
    assert "json" in _imports(file)
