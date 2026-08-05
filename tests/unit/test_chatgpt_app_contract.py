"""Repository contracts for the supported ChatGPT App surface."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github/workflows/ci.yml"
APP_DOC = ROOT / "docs/agents/chatgpt-app.md"
APP_README = ROOT / "integrations/chatgpt-app/README.md"
APP_MANIFEST = ROOT / "integrations/chatgpt-app/apps-sdk/app-manifest.md"
THREAT_MODEL = ROOT / "docs/security/threat-model.md"


def test_chatgpt_app_smoke_is_a_required_ci_job() -> None:
    workflow = CI.read_text(encoding="utf-8")

    assert "chatgpt_app: ${{ steps.filter.outputs.chatgpt_app }}" in workflow
    assert "- 'integrations/chatgpt-app/apps-sdk/**'" in workflow
    assert "  chatgpt-app:" in workflow
    assert "working-directory: integrations/chatgpt-app/apps-sdk" in workflow
    assert "npm ci --ignore-scripts=false" in workflow
    assert "npm run typecheck" in workflow
    assert "npm run build" in workflow
    assert "npm run test:smoke" in workflow
    assert "chatgpt-app" in workflow.split("required-pr-gate:", 1)[1]


def test_chatgpt_app_docs_do_not_overclaim_the_local_bridge() -> None:
    app_doc = APP_DOC.read_text(encoding="utf-8")
    app_readme = APP_README.read_text(encoding="utf-8")

    for content in (app_doc, app_readme):
        content = " ".join(content.split())
        assert "Public-safe profile (supported)" in content
        assert "Remote-to-local bridge (not currently supported)" in content
        assert "127.0.0.1" in content
        assert "does not provide a hosted relay" in content
        assert "does not implement per-tool local approval" in content


def test_bridge_threat_model_matches_the_128_bit_pairing_code() -> None:
    threat_model = THREAT_MODEL.read_text(encoding="utf-8")

    assert "128-bit" in threat_model
    assert "24-bit" not in threat_model
    assert "localhost-only" in threat_model


def test_app_manifest_describes_the_verified_read_only_scope() -> None:
    manifest = APP_MANIFEST.read_text(encoding="utf-8")

    assert "# KiCad MCP Pro ChatGPT App Manifest" in manifest
    assert "Supported profile: public-safe, read-only" in manifest
    assert "Local mutation bridge: not currently supported" in manifest
    assert "npm run test:smoke" in manifest


def test_submission_preflight_requires_chatgpt_app_ui_evidence() -> None:
    from scripts import check_submission_readiness

    filename = "06-chatgpt-app-dashboard.png"
    screenshot_manifest = (ROOT / "docs/assets/screenshots/README.md").read_text(encoding="utf-8")

    assert filename in check_submission_readiness.SCREENSHOTS
    assert filename in screenshot_manifest
    assert (ROOT / "docs/assets/screenshots" / filename).is_file()
