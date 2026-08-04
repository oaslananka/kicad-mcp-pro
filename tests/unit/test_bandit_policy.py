"""Tests for the narrow Bandit false-positive policy."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check_bandit_policy.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_bandit_policy", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load Bandit policy script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _finding(**overrides: object) -> dict[str, object]:
    finding: dict[str, object] = {
        "filename": str(ROOT / "src/kicad_mcp/evals/nvidia_nim_adapter.py"),
        "test_id": "B608",
        "issue_severity": "MEDIUM",
        "code": ('system = (\n    "You are a tool-selection classifier for KiCad MCP Pro. "\n)\n'),
    }
    finding.update(overrides)
    return finding


def test_expected_classifier_prompt_false_positive_is_allowlisted() -> None:
    module = _module()

    assert module.is_expected_false_positive(_finding(), ROOT) is True


def test_allowlist_rejects_other_tests_files_and_prompt_text() -> None:
    module = _module()

    assert module.is_expected_false_positive(_finding(test_id="B607"), ROOT) is False
    assert (
        module.is_expected_false_positive(
            _finding(filename=str(ROOT / "src/kicad_mcp/server.py")), ROOT
        )
        is False
    )
    assert module.is_expected_false_positive(_finding(code="SELECT * FROM users"), ROOT) is False


def test_package_script_uses_policy_wrapper() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert package["scripts"]["security:bandit"] == (
        "uv run --all-extras python scripts/check_bandit_policy.py"
    )
