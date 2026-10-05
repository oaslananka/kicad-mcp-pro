"""Coding-agent router and agent-facing documentation contracts."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT_DOCS = (
    ROOT / "README.md",
    ROOT / "docs/agents/progressive-disclosure.md",
    ROOT / "docs/agents/toolsets.md",
)
NESTED_AGENT_CONTRACTS = {
    "src/kicad_mcp/AGENTS.md": (
        "ARCHITECTURE.md",
        "docs/security/threat-model.md",
        "KiCad adapter seam",
        "shell=False",
    ),
    "src/kicad_mcp/tools/AGENTS.md": (
        "TOOL_CATEGORIES",
        "PROFILE_CATEGORIES",
        "Metadata is executable policy",
        "human-gated",
    ),
    ".github/AGENTS.md": (
        "Required PR Gate",
        ".github/actions-policy.json",
        "full commit SHAs",
        "SBOM",
    ),
    "integrations/AGENTS.md": (
        "docs/agent-runtime-config.md",
        "validate-mcp-config.py",
        "least-privileged",
        "operating-mode",
    ),
    "src-tauri/AGENTS.md": (
        "desktop API contract",
        "loopback",
        "cargo check --manifest-path src-tauri/Cargo.toml",
    ),
    "packages/AGENTS.md": (
        "mcp-npm/",
        "protocol-schemas/",
        "kicad-fixtures/",
        "kicad-plugin/",
    ),
}


def test_root_agents_router_points_to_canonical_engineering_sources() -> None:
    router = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    for target in (
        "ARCHITECTURE.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "Taskfile.yml",
        "docs/agents/progressive-disclosure.md",
        "docs/tools-agent-workflow.md",
        "compatibility.yaml",
    ):
        assert target in router

    assert "## Scope and precedence" in router
    assert "closest applicable file wins" in router
    for relative_path in NESTED_AGENT_CONTRACTS:
        assert relative_path in router

    assert len(router.splitlines()) <= 80


def test_nested_agent_files_cover_operational_boundaries() -> None:
    for relative_path, markers in NESTED_AGENT_CONTRACTS.items():
        path = ROOT / relative_path
        assert path.is_file(), f"missing nested agent instructions: {relative_path}"
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker in text, f"{relative_path} is missing contract marker: {marker}"


def test_opencode_agent_file_is_maintainer_scoped() -> None:
    text = (ROOT / "integrations/opencode/AGENTS.md").read_text(encoding="utf-8")

    for marker in (
        "repository maintenance",
        "integrations/AGENTS.md",
        "permission",
        "deprecated legacy",
        "optional and experimental",
        "validate-mcp-config.py",
    ):
        assert marker in text


def test_agent_docs_do_not_hard_code_expert_catalog_size() -> None:
    forbidden = (
        re.compile(r"\b\d{2,4}-tool expert catalog\b"),
        re.compile(r"\| `expert` \|[^|\n]*\| \d{2,4} \|"),
        re.compile(r"\| `full_write` \|[^|\n]*\| \d{2,4} \|"),
    )

    for path in AGENT_DOCS:
        text = path.read_text(encoding="utf-8")
        matches = [pattern.pattern for pattern in forbidden if pattern.search(text)]
        assert not matches, f"{path.relative_to(ROOT)} hard-codes catalog size: {matches}"

    evidence = "docs/evidence/progressive-disclosure-profile-snapshot.json"
    combined = "\n".join(path.read_text(encoding="utf-8") for path in AGENT_DOCS)
    assert evidence in combined
