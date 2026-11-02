"""Execute the CI runtime-reference contract to prevent manifest/workflow drift."""

from __future__ import annotations

import json
import runpy
import shutil
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _contract_script(tmp_path: Path) -> str:
    workflow = yaml.safe_load((ROOT / ".github/workflows/agent-runtime-config.yml").read_text())
    step = next(
        step
        for step in workflow["jobs"]["validate"]["steps"]
        if step.get("name") == "Validate agent runtime references"
    )
    script = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    path = tmp_path / "runtime_contract.py"
    path.write_text(script, encoding="utf-8")
    return str(path)


def test_ci_runtime_reference_contract_accepts_product_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    runpy.run_path(_contract_script(tmp_path))


@pytest.mark.parametrize("manifest", [".mcp.json", "mcp.json"])
def test_ci_runtime_reference_contract_rejects_write_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifest: str
) -> None:
    for relative in (
        ".claude-plugin/plugin.json",
        ".mcp.json",
        "plugin.json",
        "mcp.json",
        "pyproject.toml",
        ".codex/config.example.toml",
        "integrations/opencode/opencode.example.json",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    for relative in (
        "skills",
        ".agents/skills",
        ".opencode/skills",
        "integrations/gemini-cli/kicad-mcp-pro/skills",
        "src/kicad_mcp/data/agent_skills",
    ):
        shutil.copytree(
            ROOT / relative, tmp_path / relative, ignore=shutil.ignore_patterns("__pycache__")
        )
    script = _contract_script(tmp_path)
    monkeypatch.chdir(tmp_path)
    runpy.run_path(script)
    config = json.loads((tmp_path / manifest).read_text())
    server = next(iter(config["mcpServers"].values()))
    server["env"]["KICAD_MCP_OPERATING_MODE"] = "write"
    (tmp_path / manifest).write_text(json.dumps(config))
    with pytest.raises(AssertionError):
        runpy.run_path(script)
