from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "packages/kicad-plugin/kicad_mcp_companion.py"


def test_companion_plugin_defaults_preserve_public_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ActionPlugin:
        pass

    monkeypatch.setitem(sys.modules, "pcbnew", types.SimpleNamespace(ActionPlugin=_ActionPlugin))

    spec = importlib.util.spec_from_file_location("kicad_mcp_companion_defaults_test", PLUGIN)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    plugin = module.KiCadMcpCompanionPlugin()
    plugin.defaults()

    assert plugin.name == "kicad-mcp companion"
    assert plugin.category == "kicad-mcp"
    assert plugin.description == "Publish active board context to a running kicad-mcp-pro server."
    assert plugin.show_toolbar_button is True
