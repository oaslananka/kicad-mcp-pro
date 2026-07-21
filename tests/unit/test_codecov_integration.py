from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import yaml

ROOT = Path(__file__).resolve().parents[2]
CODECOV_ACTION_SHA = "fb8b3582c8e4def4969c97caa2f19720cb33a72f"


def _load_run_pytest() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_pytest", ROOT / "scripts" / "run_pytest.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_test_driver_forwards_junit_args_and_preserves_external_basetemp(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_run_pytest()
    captured: list[str] = []
    external = tmp_path / "external-basetemp"
    monkeypatch.setattr(module, "_basetemp", lambda _suite: external)
    monkeypatch.setattr(module.pytest, "main", lambda args: captured.extend(args) or 0)

    result = module.main(
        ["run_pytest.py", "unit", "--junitxml=python.junit.xml", "-o", "junit_family=legacy"]
    )

    assert result == 0
    assert "--junitxml=python.junit.xml" in captured
    assert "junit_family=legacy" in captured
    assert captured[-2:] == ["--basetemp", str(external)]


def test_ci_uploads_coverage_and_failed_test_results_with_oidc() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "name: CI Tests / Coverage" in workflow
    assert workflow.count(f"codecov/codecov-action@{CODECOV_ACTION_SHA}") == 2
    assert workflow.count("use_oidc: ${{ github.event_name != 'pull_request'") == 2
    assert "report_type: test_results" in workflow
    assert "continue-on-error: true" in workflow
    assert "--junitxml=python.junit.xml" in workflow
    assert "steps.python-tests.outcome == 'failure'" in workflow
    assert "needs.changes.outputs.python != 'true'" in workflow
    assert "needs.changes.outputs.workflows != 'true'" in workflow
    assert "needs: [changes, mcp-server, coverage, mcp-npm" in workflow


def test_codecov_yaml_starts_in_informational_mode() -> None:
    config = yaml.safe_load((ROOT / "codecov.yml").read_text(encoding="utf-8"))

    assert config["codecov"]["branch"] == "main"
    assert config["coverage"]["status"]["project"]["default"]["target"] == "auto"
    assert config["coverage"]["status"]["project"]["default"]["informational"] is True
    assert config["coverage"]["status"]["patch"]["default"]["informational"] is True
    assert config["flags"]["python-full"]["paths"] == ["src/kicad_mcp/"]
    assert "bundle_analysis" not in config
