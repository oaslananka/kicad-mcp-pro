"""Static-only agent integration trust and published extension invariants."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts import check_agent_host_evidence as verifier
from scripts import sync_mcp_metadata as metadata_sync

ROOT = Path(__file__).resolve().parents[2]


def _temp_host_repo(tmp_path: Path) -> Path:
    catalog = json.loads(verifier.EVIDENCE.read_text(encoding="utf-8"))
    paths = {
        "integrations/common/agent-host-evidence.json",
        "integrations/gemini-cli/kicad-mcp-pro/gemini-extension.json",
        "packages/mcp-npm/package.json",
    }
    for row in catalog["hosts"]:
        paths.add(row["configuration"])
        paths.add(row["guide"])
    for relative in paths:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    return tmp_path


def _update_json(repo: Path, relative: str, transform) -> None:
    path = repo / relative
    data = json.loads(path.read_text(encoding="utf-8"))
    transform(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_checked_in_host_manifest_has_no_unverified_host_claims() -> None:
    assert verifier.check() == []
    manifest = json.loads(verifier.EVIDENCE.read_text(encoding="utf-8"))
    assert {row["id"] for row in manifest["hosts"]} == {
        "claude-code",
        "codex",
        "gemini-cli",
        "cursor",
        "vscode-copilot",
        "opencode",
    }
    assert {row["smokeStatus"] for row in manifest["hosts"]} == {"not-run"}


def test_missing_guide_or_config_is_detected(tmp_path: Path) -> None:
    repo = _temp_host_repo(tmp_path)
    (repo / "docs/agents/codex.md").unlink()
    assert any("Missing guide file for codex" in msg for msg in verifier.check(repo))


def test_duplicate_host_or_unreviewed_host_smoke_is_rejected(tmp_path: Path) -> None:
    repo = _temp_host_repo(tmp_path)
    relative = "integrations/common/agent-host-evidence.json"
    _update_json(repo, relative, lambda d: d["hosts"].append(dict(d["hosts"][0])))
    _update_json(repo, relative, lambda d: d["hosts"][0].update(smokeStatus="passed"))
    failures = verifier.check(repo)
    assert any("Duplicate" in value for value in failures)
    assert any("separately reviewed evidence" in value for value in failures)


def test_untrusted_paths_and_missing_schema_are_rejected(tmp_path: Path) -> None:
    repo = _temp_host_repo(tmp_path)
    relative = "integrations/common/agent-host-evidence.json"
    _update_json(repo, relative, lambda d: d.update(schemaVersion=0))
    _update_json(
        repo, relative, lambda d: d["hosts"][0].update(configuration="../../../../tmp/secret.json")
    )
    failures = verifier.check(repo)
    assert any("Invalid evidence schema" in item for item in failures)
    assert any("Invalid configuration path" in item for item in failures)


def test_gemini_extension_must_remain_statically_readonly(tmp_path: Path) -> None:
    repo = _temp_host_repo(tmp_path)
    relative = "integrations/gemini-cli/kicad-mcp-pro/gemini-extension.json"
    _update_json(
        repo,
        relative,
        lambda d: d["mcpServers"]["kicad"].update(
            env={"KICAD_MCP_OPERATING_MODE": "write", "KICAD_MCP_PROFILE": "agent_full"},
            trust=True,
        ),
    )
    failures = verifier.check(repo)
    assert any("readonly/default" in item for item in failures)
    assert any("Unreviewed Gemini" in item for item in failures)


def test_extension_version_must_match_package_metadata(tmp_path: Path) -> None:
    repo = _temp_host_repo(tmp_path)
    relative = "integrations/gemini-cli/kicad-mcp-pro/gemini-extension.json"
    _update_json(repo, relative, lambda d: d.update(version="0.0.1"))
    assert any("version have drifted" in item for item in verifier.check(repo))


def test_version_sync_renders_extension_without_modifying_source_file() -> None:
    content = json.loads(
        (ROOT / "integrations/gemini-cli/kicad-mcp-pro/gemini-extension.json").read_text()
    )
    assert content["version"] == metadata_sync._project_metadata()["version"]
    assert content["mcpServers"]["kicad"]["env"]["KICAD_MCP_OPERATING_MODE"] == "readonly"
    assert "GEMINI_EXTENSION" in metadata_sync._planned_updates.__code__.co_names


def test_missing_catalog_fails_closed(tmp_path: Path) -> None:
    _temp_host_repo(tmp_path)
    (tmp_path / "integrations/common/agent-host-evidence.json").unlink()
    with pytest.raises(ValueError, match="Missing"):
        verifier.check(tmp_path)


def test_static_check_rejects_fewer_than_six_hosts(tmp_path: Path) -> None:
    repo = _temp_host_repo(tmp_path)
    _update_json(
        repo,
        "integrations/common/agent-host-evidence.json",
        lambda data: data.update(hosts=[]),
    )
    assert any("six maintained" in item for item in verifier.check(repo))


def test_static_check_rejects_nondict_host_rows(tmp_path: Path) -> None:
    repo = _temp_host_repo(tmp_path)
    _update_json(
        repo,
        "integrations/common/agent-host-evidence.json",
        lambda data: data["hosts"].append("not a host record"),
    )
    assert any("not an object" in item for item in verifier.check(repo))


def test_static_check_rejects_invalid_config_body(tmp_path: Path) -> None:
    repo = _temp_host_repo(tmp_path)
    path = repo / ".codex/config.example.toml"
    path.write_text("[unrelated]\nname = 'not a server'\n", encoding="utf-8")
    assert any("No MCP servers" in msg for msg in verifier.check(repo))
    path.write_text("wrong = [", encoding="utf-8")
    assert any("Invalid configuration" in msg for msg in verifier.check(repo))
    json_path = repo / "integrations/common/agent-host-evidence.json"
    json_path.write_text('["an array"]', encoding="utf-8")
    with pytest.raises(ValueError, match="configuration object"):
        verifier.check(repo)


def test_static_check_rejects_renamed_or_remote_gemini_server(tmp_path: Path) -> None:
    repo = _temp_host_repo(tmp_path)
    relative = "integrations/gemini-cli/kicad-mcp-pro/gemini-extension.json"
    _update_json(repo, relative, lambda data: data.update(name="unexpected"))
    _update_json(
        repo,
        relative,
        lambda data: data["mcpServers"]["kicad"].update(
            command="curl", args=["https://example.test"]
        ),
    )
    failures = verifier.check(repo)
    assert any("extension name" in item for item in failures)
    assert any("local stdio" in item for item in failures)


def test_host_evidence_cli_reports_fail_closed(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(verifier, "check", lambda: ["missing manifest"])
    assert verifier.main() == 1
    assert "missing manifest" in capsys.readouterr().out
    monkeypatch.setattr(verifier, "check", lambda: [])
    assert verifier.main() == 0
    assert "static only" in capsys.readouterr().out


def test_symlinked_host_config_is_rejected_before_parsing(tmp_path: Path) -> None:
    repo = _temp_host_repo(tmp_path)
    config = repo / ".codex/config.example.toml"
    config.unlink()
    try:
        config.symlink_to(repo / "packages/mcp-npm/package.json")
    except (OSError, NotImplementedError):
        pytest.skip("Filesystem disallows symlink creation")

    failures = verifier.check(repo)
    assert any("Missing configuration file for codex:" in msg for msg in failures)
    assert any("Invalid configuration for codex:" in msg for msg in failures)


def test_host_path_traversal_and_absolute_path_fail_closed(tmp_path: Path) -> None:
    repo = _temp_host_repo(tmp_path)
    relative = "integrations/common/agent-host-evidence.json"
    _update_json(
        repo,
        relative,
        lambda data: data["hosts"][0].update(
            configuration="../outside.json", guide="/etc/irrelevant"
        ),
    )
    failures = verifier.check(repo)
    assert any("Invalid configuration path for claude-code" in msg for msg in failures)
    assert any("Invalid guide path for claude-code" in msg for msg in failures)
