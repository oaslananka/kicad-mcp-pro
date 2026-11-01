"""Fail-closed static host catalog and Gemini extension contract validation.

This check never starts an agent host, installs dependencies or connects to
private credentials. Real-host smoke evidence must be reviewed separately.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Any, TypeGuard

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "integrations" / "common" / "agent-host-evidence.json"
EXTENSION = ROOT / "integrations" / "gemini-cli" / "kicad-mcp-pro"

# CI invokes this checker as a file, not a package. Resolve its own trusted
# checkout root before importing the pinned native-evidence validator.
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))

# Each maintained host has a different native configuration container.
_HOST_CONFIGS = {
    "claude-code": ("integrations/claude-code/.mcp.json.example", "mcpServers"),
    "codex": (".codex/config.example.toml", "mcp_servers"),
    "gemini-cli": ("integrations/gemini-cli/kicad-mcp-pro/gemini-extension.json", "mcpServers"),
    "cursor": ("integrations/cursor/mcp.example.json", "mcpServers"),
    "vscode-copilot": ("integrations/vscode/mcp.example.json", "servers"),
    "opencode": ("integrations/opencode/opencode.example.json", "mcp"),
}
_STDIO_ARGS = (["kicad-mcp-pro"], ["kicad-mcp-pro", "--transport", "stdio"])


def _gemini_stdio_args(version: object) -> list[str]:
    """Return only the reviewed, package-version-bound extension argv."""
    if not isinstance(version, str) or not version:
        return []
    return [
        "--from",
        f"kicad-mcp-pro=={version}",
        "kicad-mcp-pro",
        "--transport",
        "stdio",
    ]


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Missing or symlinked manifest: {path}")
    if path.suffix == ".toml":
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    else:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected a configuration object: {path}")
    return parsed


def _valid_host_path(relative: object) -> TypeGuard[str]:
    """Reject non-relative or parent-traversing host catalog paths."""
    return (
        isinstance(relative, str)
        and not relative.startswith("/")
        and ".." not in Path(relative).parts
    )


def _check_host_files(root: Path, item: dict[str, Any], name: str, problems: list[str]) -> None:
    for field in ("configuration", "guide"):
        relative = item.get(field)
        if not _valid_host_path(relative):
            problems.append(f"Invalid {field} path for {name}")
            continue
        target = root / relative
        if not target.is_file() or target.is_symlink():
            problems.append(f"Missing {field} file for {name}: {relative}")


def _check_host_configuration(
    root: Path, item: dict[str, Any], name: str, problems: list[str]
) -> None:
    relative = item.get("configuration")
    if not _valid_host_path(relative):
        return
    expected = _HOST_CONFIGS.get(name)
    if expected is None:
        problems.append(f"Unreviewed agent host: {name}")
        return
    expected_path, container = expected
    if relative != expected_path:
        problems.append(f"Unexpected reviewed configuration path for {name}")
        return

    target = root / relative
    if not target.is_file():
        return
    try:
        config = _read_object(target)
    except ValueError as exc:
        problems.append(f"Invalid configuration for {name}: {exc}")
        return

    servers = config.get(container)
    if name == "opencode" and isinstance(servers, dict):
        servers = servers.get("servers")
    if not isinstance(servers, dict) or not servers:
        problems.append(f"No MCP servers defined for {name}")
        return
    server = servers.get("kicad")
    if not isinstance(server, dict):
        problems.append(f"Missing kicad MCP server for {name}")
        return

    expected_version = (
        _read_object(root / "packages/mcp-npm/package.json").get("version")
        if name == "gemini-cli"
        else None
    )
    _check_local_server(name, server, problems, expected_version)


def _check_local_server(
    name: str, server: dict[str, Any], problems: list[str], version: object = None
) -> None:
    if name == "opencode":
        known_local_command = (
            server.get("type") == "local"
            and server.get("command")
            in (["uvx", "kicad-mcp-pro"], ["uvx", "kicad-mcp-pro", "--transport", "stdio"])
            and server.get("codemode") is False
            and "enabled" not in server
            and "args" not in server
        )
        env = server.get("environment")
    elif name == "gemini-cli":
        known_local_command = (
            server.get("type", "stdio") == "stdio"
            and server.get("command") == "uvx"
            and server.get("args") == _gemini_stdio_args(version)
        )
        env = server.get("env")
    else:
        known_local_command = (
            server.get("type", "stdio") == "stdio"
            and server.get("command") == "uvx"
            and server.get("args") in _STDIO_ARGS
        )
        env = server.get("env")

    if not known_local_command or any(key in server for key in ("url", "httpUrl", "trust")):
        problems.append(f"Unsafe or unexpected kicad MCP launch for {name}")
    if (
        not isinstance(env, dict)
        or env.get("KICAD_MCP_PROFILE") != "default"
        or env.get("KICAD_MCP_OPERATING_MODE") != "readonly"
    ):
        problems.append(f"Unsafe kicad MCP profile/mode for {name}: expected readonly/default")


# Only explicitly reviewed, fixed archives can appear in the catalog.
# Their native host execution is an observation, not independent attestation.
_CODEX_OBSERVATION = {
    "host": "codex",
    "hostVersion": "0.163.0",
    "os": "linux",
    "transport": "stdio",
    "sourceRevision": "9aa519b1bb82b3907eefedbba26285cf4431d856",
    "serverVersion": "4.5.0",
    "report": "2026-10-31-linux-codex-native-smoke.json",
    "verification": "structurally-complete-not-independently-attested",
}


def _check_reviewed_native_observation(
    root: Path, catalog: dict[str, Any], problems: list[str]
) -> None:
    """Bind one reviewed native Codex observation to its immutable log bytes.

    Never promote a structural observation into a compatibility claim.
    Missing, modified, symlinked, or unreviewed evidence fails closed in CI.
    """
    if catalog.get("reviewedNativeObservations") != [_CODEX_OBSERVATION]:
        problems.append("Invalid or unreviewed native observation catalog")
        return

    from scripts.check_agent_native_smoke_evidence import (  # noqa: PLC0415
        _read_bounded_regular_file,
        _unique_json_object,
        validate_report,
        validate_sanitized_log,
    )

    folder = root / "docs/evidence/agent-host"
    try:
        report_bytes = _read_bounded_regular_file(folder / _CODEX_OBSERVATION["report"], 16_384)
        log_bytes = _read_bounded_regular_file(
            folder / "2026-10-31-linux-codex-native-sanitized-log.json", 32_768
        )
        report = json.loads(report_bytes, object_pairs_hook=_unique_json_object)
    except (OSError, ValueError, RecursionError):
        problems.append("Invalid or missing reviewed native observation evidence")
        return

    if not isinstance(report, dict):
        problems.append("Invalid reviewed native observation report")
        return

    fields = {
        "host": "host_id",
        "hostVersion": "host_version",
        "os": "os",
        "transport": "transport",
        "sourceRevision": "source_revision",
        "serverVersion": "server_version",
    }
    if any(report.get(field) != _CODEX_OBSERVATION[key] for key, field in fields.items()):
        problems.append("Mismatched reviewed native observation identity")
        return
    if validate_report(report, known_hosts=set(_HOST_CONFIGS)):
        problems.append("Invalid reviewed native observation report")
        return
    if validate_sanitized_log(report, log_bytes):
        problems.append("Invalid reviewed native observation log or digest")


def _check_host_row(root: Path, item: object, ids: set[str], problems: list[str]) -> None:
    if not isinstance(item, dict):
        problems.append("Host row is not an object")
        return
    name = item.get("id")
    if not isinstance(name, str) or not name or name in ids:
        problems.append(f"Duplicate or malformed host id: {name}")
        return
    ids.add(name)
    if item.get("smokeStatus") != "not-run":
        problems.append(
            f"Host smoke cannot be claimed without separately reviewed evidence: {name}"
        )
    _check_host_files(root, item, name, problems)
    _check_host_configuration(root, item, name, problems)


def _check_extension(root: Path, problems: list[str]) -> None:
    extension = _read_object(root / EXTENSION.relative_to(ROOT) / "gemini-extension.json")
    expected_version = _read_object(root / "packages/mcp-npm/package.json").get("version")
    if extension.get("name") != "kicad-mcp-pro":
        problems.append("Gemini extension name does not match installed directory")
    servers = extension.get("mcpServers")
    server = servers.get("kicad", {}) if isinstance(servers, dict) else {}
    if (
        not isinstance(server, dict)
        or server.get("command") != "uvx"
        or server.get("args") != _gemini_stdio_args(expected_version)
    ):
        problems.append("Gemini extension must launch the known local stdio server")
    env = server.get("env", {}) if isinstance(server, dict) else {}
    if (
        not isinstance(env, dict)
        or env.get("KICAD_MCP_OPERATING_MODE") != "readonly"
        or env.get("KICAD_MCP_PROFILE") != "default"
    ):
        problems.append("Gemini extension must fail closed in readonly/default mode")
    for unsafe in ("trust", "url", "httpUrl", "settings"):
        if unsafe in server:
            problems.append(f"Unreviewed Gemini server capability: {unsafe}")
    if extension.get("version") != expected_version:
        problems.append("Gemini extension and current package version have drifted")


def check(root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    catalog = _read_object(root / EVIDENCE.relative_to(ROOT))
    if catalog.get("schemaVersion") != 1 or catalog.get("evidenceScope") != "repository-static":
        problems.append("Invalid evidence schema or static-only scope")
    hosts = catalog.get("hosts")
    if not isinstance(hosts, list) or len(hosts) < 6:
        return ["Agent host catalog needs the six maintained local host entries"]
    ids: set[str] = set()
    for item in hosts:
        _check_host_row(root, item, ids, problems)
    if ids != set(_HOST_CONFIGS):
        problems.append("Missing or unreviewed agent host in catalog")
    _check_reviewed_native_observation(root, catalog, problems)
    _check_extension(root, problems)
    return problems


def main() -> int:
    problems = check()
    for item in problems:
        print(f"Agent host configuration: {item}")
    if not problems:
        print("Six local host configurations valid (static only); runtime smokes: not run")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
