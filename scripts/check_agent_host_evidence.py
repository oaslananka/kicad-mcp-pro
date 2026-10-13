"""Fail-closed static host catalog and Gemini extension contract validation.

This check never starts an agent host, installs dependencies or connects to
private credentials. Real-host smoke evidence must be reviewed separately.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any, TypeGuard

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "integrations" / "common" / "agent-host-evidence.json"
EXTENSION = ROOT / "integrations" / "gemini-cli" / "kicad-mcp-pro"


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
    target = root / relative
    if not target.is_file():
        return
    try:
        config = _read_object(target)
        servers = (
            config.get("mcp_servers")
            or config.get("mcpServers")
            or config.get("servers")
            or config.get("mcp")
        )
        if not isinstance(servers, dict) or not servers:
            problems.append(f"No MCP servers defined for {name}")
    except ValueError as exc:
        problems.append(f"Invalid configuration for {name}: {exc}")


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
    if extension.get("name") != "kicad-mcp-pro":
        problems.append("Gemini extension name does not match installed directory")
    servers = extension.get("mcpServers")
    server = servers.get("kicad", {}) if isinstance(servers, dict) else {}
    if (
        not isinstance(server, dict)
        or server.get("command") != "uvx"
        or server.get("args") != ["kicad-mcp-pro", "--transport", "stdio"]
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
    expected_version = _read_object(root / "packages/mcp-npm/package.json").get("version")
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
