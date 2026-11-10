from pathlib import Path

import pytest

from scripts import check_submission_readiness


def test_readme_listing_references_use_current_package_version() -> None:
    result = check_submission_readiness._readme_check()

    assert result.name == "README listing references"
    assert result.status == "PASS"


def test_submission_readiness_rejects_python_http_server_version_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src" / "kicad_mcp").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "3.25.0"\n', encoding="utf-8")
    (tmp_path / "server.json").write_text('{"version":"3.14.1"}\n', encoding="utf-8")
    (tmp_path / "src" / "kicad_mcp" / "__init__.py").write_text(
        '__version__ = "3.25.0"\n', encoding="utf-8"
    )
    (tmp_path / ".release-please-manifest.json").write_text('{"." : "3.25.0"}', encoding="utf-8")
    monkeypatch.setattr(check_submission_readiness, "ROOT", tmp_path)
    result = check_submission_readiness._version_check()
    assert result.status == "FAIL"
    assert result.name == "version metadata sync"
    assert "server.json" in result.detail


def test_chatgpt_app_readiness_contract_passes() -> None:
    result = check_submission_readiness._chatgpt_app_check()

    assert result.status == "PASS"
    assert "0.2.0" in result.detail


@pytest.mark.parametrize(
    ("check", "expected_name"),
    [
        (check_submission_readiness._privacy_check, "privacy policy"),
        (check_submission_readiness._demo_cast_check, "demo cast"),
        (check_submission_readiness._reviewer_prompts_check, "reviewer prompts"),
        (check_submission_readiness._chatgpt_app_check, "ChatGPT App contract"),
        (check_submission_readiness._server_schema_check, "server schema"),
    ],
)
def test_readiness_check_labels_remain_stable(check, expected_name: str) -> None:
    # External readiness reports key on these names even when a check fails.
    assert check().name == expected_name


@pytest.mark.parametrize(
    ("check_name", "metadata"),
    [
        ("_version_check", None),
        ("_version_check", "[project\ninvalid"),
        ("_pypi_check", None),
        ("_pypi_check", "[project\ninvalid"),
        ("_readme_check", None),
        ("_readme_check", "[project\ninvalid"),
    ],
)
def test_readiness_manifest_errors_are_reported_not_raised(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    check_name: str,
    metadata: str | None,
) -> None:
    # No read/submission failure may accidentally become an unhandled crash.
    if metadata is not None:
        (tmp_path / "pyproject.toml").write_text(metadata, encoding="utf-8")
    monkeypatch.setattr(check_submission_readiness, "ROOT", tmp_path)
    result = getattr(check_submission_readiness, check_name)()
    assert result.status == "FAIL"
    assert "unreadable" in result.detail


def test_version_check_rejects_invalid_http_server_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src" / "kicad_mcp").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion="4.0.2"\n', encoding="utf-8")
    (tmp_path / "server.json").write_text("{corrupt", encoding="utf-8")
    monkeypatch.setattr(check_submission_readiness, "ROOT", tmp_path)
    result = check_submission_readiness._version_check()
    assert result.name == "version metadata sync"
    assert result.status == "FAIL"
    assert "unreadable" in result.detail
