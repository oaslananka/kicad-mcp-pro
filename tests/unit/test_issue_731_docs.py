from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_companion_docs_cover_pcm_lifecycle_health_and_uvx_fallback() -> None:
    doc = (ROOT / "docs" / "integration" / "companion-plugin.md").read_text(encoding="utf-8")

    for required in (
        "Install from File",
        "runtime: `swig`",
        "backend_unreachable",
        "backend_incompatible",
        "setup-restore",
        "--write",
        "uvx kicad-mcp-pro",
        "Uninstall",
        "Rollback",
    ):
        assert required in doc
    assert "modern KiCad plugin API" in doc


def test_distribution_readiness_records_linux_and_windows_pcm_evidence() -> None:
    doc = (ROOT / "docs" / "status" / "distribution-readiness.md").read_text(encoding="utf-8")

    assert "KiCad PCM" in doc
    assert "Physical Linux + Windows verified; macOS physical host pending" in doc
    assert "../evidence/kicad-pcm/2026-08-29/linux-kicad-10.0.5.md" in doc
    assert "../evidence/kicad-pcm/2026-08-29/windows-kicad-10.0.5.md" in doc
    assert "two independent Linux hosts" in doc
    assert "Windows physical PCM flow verified" in doc
    assert "macOS physical host unavailable" in doc
    assert "**KiCad PCM** | **Verified**" not in doc
    assert "Claude Code" in doc
    assert "Codex" in doc
    assert "Cursor" in doc
    assert "tests/unit/test_issue_731_onboarding.py" in doc
    assert "tests/unit/test_kicad_pcm_packaging.py" in doc
    assert "publish-kicad-pcm.yml" in doc
    assert "Official PCM listing" in doc
    assert "Not submitted" in doc


def test_distribution_readiness_records_guided_client_evidence() -> None:
    doc = (ROOT / "docs" / "status" / "distribution-readiness.md").read_text(encoding="utf-8")

    assert "Claude Code guided config | Real client connect verified" in doc
    assert "Codex guided config | Real client connect verified" in doc
    assert "Cursor guided config | Physical guided transaction verified" in doc
    legacy_status = "Transaction contract verified; physical flow pending"
    assert f"Claude Code guided config | {legacy_status}" not in doc
    assert f"Codex guided config | {legacy_status}" not in doc
    assert f"Cursor guided config | {legacy_status}" not in doc


def test_pcm_submission_doc_is_explicitly_pre_submission() -> None:
    doc = (ROOT / "docs" / "submission" / "kicad-pcm.md").read_text(encoding="utf-8")

    assert "Status: not submitted" in doc
    assert "gitlab.com/kicad/addons/metadata" in doc
    assert "download_url" in doc
    assert "download_sha256" in doc
    assert "download_size" in doc
    assert "install_size" in doc
    assert "packages/com.github.oaslananka.kicad-mcp-pro" in doc
    assert "Do not submit" in doc


def test_linux_evidence_records_real_supported_client_connect() -> None:
    doc = (
        ROOT / "docs" / "evidence" / "kicad-pcm" / "2026-08-29" / "linux-kicad-10.0.5.md"
    ).read_text(encoding="utf-8")

    assert "Claude Code `2.1.238`" in doc
    assert "Status: Connected" in doc
    assert "temporary `HOME`" in doc
    assert "user Claude configuration was not modified" in doc
    assert "Codex CLI `0.150.1`" in doc
    assert "kicad_get_version" in doc
    assert "Cursor project configuration" in doc
    assert "restore returned the original file hash" in doc
