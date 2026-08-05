from pathlib import Path

import pytest

from scripts import check_submission_readiness


def test_readme_listing_references_use_current_package_version() -> None:
    result = check_submission_readiness._readme_check()

    assert result.status == "PASS"


def test_submission_readiness_rejects_tauri_bundle_version_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "src" / "kicad_mcp").mkdir(parents=True)
    (tmp_path / "src-tauri").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "3.25.0"\n', encoding="utf-8")
    (tmp_path / "server.json").write_text('{"version":"3.25.0"}\n', encoding="utf-8")
    (tmp_path / "src" / "kicad_mcp" / "__init__.py").write_text(
        '__version__ = "3.25.0"\n', encoding="utf-8"
    )
    (tmp_path / "src-tauri" / "Cargo.toml").write_text(
        '[package]\nversion = "3.25.0"\n', encoding="utf-8"
    )
    (tmp_path / "src-tauri" / "tauri.conf.json").write_text(
        '{"version":"3.14.1"}\n', encoding="utf-8"
    )
    (tmp_path / ".release-please-manifest.json").write_text(
        '{"src-tauri":"3.25.0"}\n', encoding="utf-8"
    )
    monkeypatch.setattr(check_submission_readiness, "ROOT", tmp_path)

    result = check_submission_readiness._version_check()

    assert result.status == "FAIL"
    assert "src-tauri/tauri.conf.json" in result.detail


def test_chatgpt_app_readiness_contract_passes() -> None:
    result = check_submission_readiness._chatgpt_app_check()

    assert result.status == "PASS"
    assert "0.2.0" in result.detail
