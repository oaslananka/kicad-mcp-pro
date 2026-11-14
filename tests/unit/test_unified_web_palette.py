"""Shared product color and information-density contract for HTTP surfaces."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUD = ROOT / "apps/cloud/src/ui-styles.ts"
LOCAL = ROOT / "src/kicad_mcp/web/dashboard.py"


def test_cloud_and_local_share_calm_graphite_blue_tokens() -> None:
    cloud = CLOUD.read_text(encoding="utf-8")
    local = LOCAL.read_text(encoding="utf-8")
    assert re.search(r"--accent:\s*#72d6b2\s*;", cloud, flags=re.I)
    assert re.search(r"--bg:\s*#0c0f10\s*;", cloud, flags=re.I)
    assert re.search(r"--accent:\s*#279fff\s*;", local, flags=re.I)
    assert re.search(r"--bg:\s*#090a0d\s*;", local, flags=re.I)
    for source in (cloud, local):
        assert "#00daf3" not in source.lower()
        assert "#00d8f5" not in source.lower()
        assert "rgba(0,218,243" not in source.replace(" ", "").lower()
        assert "focus-visible" in source


def test_cloud_has_compact_link_rows_not_three_large_tiles() -> None:
    css = CLOUD.read_text(encoding="utf-8")
    assert ".overview-tiles{display:block;" in css
    assert ".snapshot-grid{display:grid;" in css
    assert ".premium-focus-panel" in css
    assert "prefers-reduced-motion" in css


def test_local_first_steps_are_compact_and_distinct_from_buttons() -> None:
    source = LOCAL.read_text(encoding="utf-8")
    assert "gp-steps" in source
    assert 'class="gp-card gp-project"' in source
    assert 'id="gpSaveProject"' in source
    assert 'id="gpAiPreview"' in source
    assert 'id="gpCloudPair"' in source
    assert "gp-card" in source
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in source.replace(" ", "")
    assert "prefers-reduced-motion" in source
