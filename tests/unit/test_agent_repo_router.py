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


def test_root_agents_router_points_to_canonical_engineering_sources() -> None:
    router = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    for target in (
        "ARCHITECTURE.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "Taskfile.yml",
        "docs/agents/progressive-disclosure.md",
        "docs/tools-agent-workflow.md",
    ):
        assert target in router
    assert len(router.splitlines()) <= 80


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
