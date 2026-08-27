from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"


def test_candidate_protocol_contract_runs_in_an_independent_required_ci_job() -> None:
    workflow = CI.read_text(encoding="utf-8")

    assert "  mcp-2026-compat:" in workflow
    assert "name: MCP 2026 Compatibility" in workflow
    assert "uv sync --all-extras --frozen" in workflow
    assert (
        "uv run pytest tests/unit/test_mcp_2026_config.py "
        "tests/unit/test_protocol_compat.py "
        "tests/unit/test_mcp_protocol_2026_contract.py -q"
    ) in " ".join(workflow.split())
    assert "Run supported-host MCP 2026 smoke cases" in workflow
    assert "uv run pytest tests/integration/test_mcp_2026_host_smoke.py -q" in " ".join(
        workflow.split()
    )
    jobs = yaml.safe_load(workflow)["jobs"]
    required_needs = set(jobs["required-pr-gate"]["needs"])
    assert {"release-metadata", "mcp-2026-compat"} <= required_needs
    assert '[mcp-2026-compat]="${{ needs.mcp-2026-compat.result }}"' in workflow
    assert (
        "for job in changes release-metadata mcp-server coverage mcp-npm chatgpt-app "
        "protocol-schemas mcp-2026-compat workflow-policy security"
    ) in " ".join(workflow.split())
