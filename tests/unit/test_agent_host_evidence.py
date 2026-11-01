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
        "docs/evidence/agent-host/2026-10-31-linux-codex-native-smoke.json",
        "docs/evidence/agent-host/2026-10-31-linux-codex-native-sanitized-log.json",
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


def test_gemini_pinned_pypi_connection_remains_partial_not_host_acceptance() -> None:
    observed = json.loads(
        (
            ROOT / "docs/evidence/agent-host/2026-10-28-linux-gemini-pinned-stdio-partial.json"
        ).read_text(encoding="utf-8")
    )
    extension = json.loads(
        (ROOT / "integrations/gemini-cli/kicad-mcp-pro/gemini-extension.json").read_text(
            encoding="utf-8"
        )
    )
    catalog = json.loads(verifier.EVIDENCE.read_text(encoding="utf-8"))

    assert observed["schemaVersion"] == "agent-native-host-partial.v1"
    assert observed["host"]["id"] == "gemini-cli"
    assert observed["host"]["version"] == "0.60.0"
    assert observed["host"]["mcpServerStatus"] == "connected"
    # The observation attests the published 4.4.0 runtime, not the version
    # currently being prepared by Release Please.
    assert observed["serverVersion"] == "4.4.0"
    assert observed["serverLaunchArgs"] == [
        "--from",
        f"kicad-mcp-pro=={observed['serverVersion']}",
        "kicad-mcp-pro",
        "--transport",
        "stdio",
    ]
    # Independently keep the checked-in extension pinned to the current
    # package version; neither check upgrades historical host evidence.
    assert extension["version"] == metadata_sync._project_metadata()["version"]
    assert extension["mcpServers"]["kicad"]["args"] == [
        "--from",
        f"kicad-mcp-pro=={extension['version']}",
        "kicad-mcp-pro",
        "--transport",
        "stdio",
    ]
    assert (
        observed["serverOperatingMode"]
        == extension["mcpServers"]["kicad"]["env"]["KICAD_MCP_OPERATING_MODE"]
    )
    assert observed["serverProfile"] == extension["mcpServers"]["kicad"]["env"]["KICAD_MCP_PROFILE"]
    assert observed["publishedWheel"]["sha256"] == (
        "3717a59c083925179d14fe2721b32c237702d8e5825786fb6310bcc2896c7240"
    )
    assert observed["publishedWheel"]["matchingUvCacheCopies"] == 2
    assert observed["publishedWheel"]["matchingWheelMemberFilesPerCopy"] == 460
    assert observed["publishedWheel"]["excludedMutableInstallMetadata"] == [
        "kicad_mcp_pro-4.4.0.dist-info/RECORD"
    ]
    assert observed["publisherProvenance"]["independentPep740Verification"] == (
        "passed-for-wheel-and-sdist"
    )
    assert observed["nativeToolCall"] == "not-run"
    assert observed["hostSkillDiscoveryDuringThisProbe"] == "not-run"
    assert observed["readonlyWriteToolAbsence"] == "not-run"
    assert observed["sanitizedNativeHostLogSha256"] is None
    assert observed["independentRunningProcessBinaryAttestation"] is False
    assert observed["fullNativeHostSmokeAttested"] is False
    assert observed["catalogPromotionAuthorized"] is False
    assert next(h for h in catalog["hosts"] if h["id"] == "gemini-cli")["smokeStatus"] == "not-run"


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


def test_opencode_v2_default_example_is_readonly_and_static() -> None:
    config = json.loads(
        (ROOT / "integrations/opencode/opencode.example.json").read_text(encoding="utf-8")
    )
    entry = config["mcp"]["servers"]["kicad"]
    assert entry["codemode"] is False
    assert "enabled" not in entry
    assert entry["environment"]["KICAD_MCP_OPERATING_MODE"] == "readonly"
    assert verifier.check() == []


@pytest.mark.parametrize(
    ("changed", "diagnostic"),
    [
        ({"codemode": True}, "Unsafe or unexpected kicad MCP launch"),
        ({"enabled": True}, "Unsafe or unexpected kicad MCP launch"),
        ({"args": ["--unsafe"]}, "Unsafe or unexpected kicad MCP launch"),
        ({"command": ["sh", "-c", "echo unsafe"]}, "Unsafe or unexpected kicad MCP launch"),
        (
            {"environment": {"KICAD_MCP_PROFILE": "full", "KICAD_MCP_OPERATING_MODE": "write"}},
            "readonly/default",
        ),
    ],
)
def test_unreviewed_opencode_v2_changes_fail_closed(
    changed: dict[str, object], diagnostic: str, tmp_path: Path
) -> None:
    repo = _temp_host_repo(tmp_path)
    relative = "integrations/opencode/opencode.example.json"
    _update_json(repo, relative, lambda d: d["mcp"]["servers"]["kicad"].update(changed))
    assert any(diagnostic in message for message in verifier.check(repo))


def test_legacy_opencode_v1_shape_cannot_replace_default_v2_catalog(tmp_path: Path) -> None:
    repo = _temp_host_repo(tmp_path)
    relative = "integrations/opencode/opencode.example.json"
    _update_json(repo, relative, lambda d: d.update(mcp={"kicad": d["mcp"]["servers"]["kicad"]}))
    assert any("No MCP servers defined for opencode" in msg for msg in verifier.check(repo))

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
    assert content["mcpServers"]["kicad"]["args"] == [
        "--from",
        "kicad-mcp-pro==" + content["version"],
        "kicad-mcp-pro",
        "--transport",
        "stdio",
    ]
    assert content["mcpServers"]["kicad"]["env"]["KICAD_MCP_OPERATING_MODE"] == "readonly"
    assert "GEMINI_EXTENSION" in metadata_sync._planned_updates.__code__.co_names


@pytest.mark.parametrize(
    "args",
    [
        ["kicad-mcp-pro", "--transport", "stdio"],
        ["--from", "kicad-mcp-pro==4.3.0", "kicad-mcp-pro", "--transport", "stdio"],
        ["--from", "kicad-mcp-pro>=4.4.0", "kicad-mcp-pro", "--transport", "stdio"],
        [
            "--from",
            "kicad-mcp-pro==4.4.0",
            "kicad-mcp-pro",
            "--transport",
            "stdio",
            "--unsafe",
        ],
    ],
)
def test_gemini_rejects_floating_wrong_or_unreviewed_package(
    args: list[str], tmp_path: Path
) -> None:
    repo = _temp_host_repo(tmp_path)
    relative = "integrations/gemini-cli/kicad-mcp-pro/gemini-extension.json"
    _update_json(repo, relative, lambda data: data["mcpServers"]["kicad"].update(args=args))
    failures = verifier.check(repo)
    assert any("Unsafe or unexpected kicad MCP launch" in msg for msg in failures)
    assert any("Gemini extension must launch" in msg for msg in failures)


def test_gemini_version_sync_updates_runtime_package_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    metadata = metadata_sync._project_metadata()
    monkeypatch.setattr(
        metadata_sync, "_project_metadata", lambda: {**metadata, "version": "9.8.7"}
    )
    planned = json.loads(metadata_sync._planned_updates()[metadata_sync.GEMINI_EXTENSION])
    assert planned["version"] == "9.8.7"
    assert planned["mcpServers"]["kicad"]["args"] == [
        "--from",
        "kicad-mcp-pro==9.8.7",
        "kicad-mcp-pro",
        "--transport",
        "stdio",
    ]


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


# A model-free configuration gate must detect unsafe agent-host launch drift.
_HOST_CONFIGS = (
    ("claude-code", "mcpServers", "env"),
    ("codex", "mcp_servers", "env"),
    ("gemini-cli", "mcpServers", "env"),
    ("cursor", "mcpServers", "env"),
    ("vscode-copilot", "servers", "env"),
    ("opencode", "mcp", "environment"),
)


def _alter_host_server(repo: Path, host: str, container: str, change) -> None:
    catalog = json.loads((repo / "integrations/common/agent-host-evidence.json").read_text())
    row = next(item for item in catalog["hosts"] if item["id"] == host)
    path = repo / row["configuration"]
    if path.suffix == ".toml":
        text = path.read_text(encoding="utf-8")
        replaced = change(text)
        assert text != replaced
        path.write_text(replaced, encoding="utf-8")
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        servers = data[container]
        if host == "opencode":
            servers = servers["servers"]
        change(servers["kicad"])
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize(("host", "container", "env_key"), _HOST_CONFIGS)
@pytest.mark.parametrize(
    ("field", "unsafe"), [("KICAD_MCP_OPERATING_MODE", "write"), ("KICAD_MCP_PROFILE", "expert")]
)
def test_every_host_fails_closed_on_unsafe_mode_or_profile(
    tmp_path: Path, host: str, container: str, env_key: str, field: str, unsafe: str
) -> None:
    repo = _temp_host_repo(tmp_path)
    if host == "codex":
        _alter_host_server(
            repo,
            host,
            container,
            lambda text: text.replace(
                f'{field} = "{"readonly" if field.endswith("MODE") else "default"}"',
                f'{field} = "{unsafe}"',
            ),
        )
    else:
        _alter_host_server(
            repo,
            host,
            container,
            lambda server: server[env_key].update({field: unsafe}),
        )
    assert any("readonly/default" in msg for msg in verifier.check(repo))


@pytest.mark.parametrize(("host", "container", "_"), _HOST_CONFIGS)
def test_every_host_rejects_unreviewed_launch_command(
    tmp_path: Path, host: str, container: str, _: str
) -> None:
    repo = _temp_host_repo(tmp_path)
    if host == "codex":
        _alter_host_server(
            repo,
            host,
            container,
            lambda text: text.replace('command = "uvx"', 'command = "curl"'),
        )
    else:
        _alter_host_server(repo, host, container, lambda server: server.update(command="curl"))
    assert any("Unsafe or unexpected kicad MCP launch" in msg for msg in verifier.check(repo))


@pytest.mark.parametrize(("host", "container", "_"), _HOST_CONFIGS)
def test_every_host_rejects_unreviewed_launch_args(
    tmp_path: Path, host: str, container: str, _: str
) -> None:
    repo = _temp_host_repo(tmp_path)
    if host == "codex":
        _alter_host_server(
            repo,
            host,
            container,
            lambda text: text.replace('"stdio"]', '"stdio", "--unsafe"]'),
        )
    else:
        _alter_host_server(
            repo,
            host,
            container,
            lambda server: server.update(
                **(
                    {"command": ["uvx", "kicad-mcp-pro", "--unsafe"]}
                    if host == "opencode"
                    else {"args": ["kicad-mcp-pro", "--unsafe"]}
                )
            ),
        )
    assert any("Unsafe or unexpected kicad MCP launch" in msg for msg in verifier.check(repo))


def test_host_catalog_cannot_substitute_an_unreviewed_host(tmp_path: Path) -> None:
    repo = _temp_host_repo(tmp_path)
    _update_json(
        repo,
        "integrations/common/agent-host-evidence.json",
        lambda data: data["hosts"][0].update(id="unreviewed-host"),
    )
    assert any("Missing or unreviewed agent host" in msg for msg in verifier.check(repo))


def test_opencode_disabled_server_is_not_approved(tmp_path: Path) -> None:
    repo = _temp_host_repo(tmp_path)
    _alter_host_server(repo, "opencode", "mcp", lambda server: server.update(enabled=False))
    assert any("Unsafe or unexpected kicad MCP launch" in msg for msg in verifier.check(repo))


def test_replacing_kicad_with_unrelated_server_is_rejected(tmp_path: Path) -> None:
    repo = _temp_host_repo(tmp_path)
    path = repo / "integrations/cursor/mcp.example.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["mcpServers"]["unrelated"] = data["mcpServers"].pop("kicad")
    path.write_text(json.dumps(data), encoding="utf-8")
    assert any("Missing kicad MCP server" in msg for msg in verifier.check(repo))


def test_catalog_cannot_relabel_another_hosts_valid_config(tmp_path: Path) -> None:
    repo = _temp_host_repo(tmp_path)
    relative = "integrations/common/agent-host-evidence.json"

    def redirect(data: dict) -> None:
        by_id = {row["id"]: row for row in data["hosts"]}
        by_id["cursor"]["configuration"] = by_id["claude-code"]["configuration"]

    _update_json(repo, relative, redirect)
    assert any(
        "Unexpected reviewed configuration path for cursor" in msg for msg in verifier.check(repo)
    )
