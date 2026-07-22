"""Synchronize MCP registry metadata from monorepo package metadata."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
PACKAGE_INIT = ROOT / "src" / "kicad_mcp" / "__init__.py"
SERVER_JSON = ROOT / "server.json"
NPM_WRAPPER_PACKAGE = ROOT / "packages" / "mcp-npm" / "package.json"
COMPATIBILITY = ROOT / "compatibility.yaml"
FAQ = ROOT / "docs" / "faq.md"
ROADMAP = ROOT / "ROADMAP.md"
# Authoritative public tool count is produced (and CI-checked) by
# scripts/generate_tools_reference.py; we read it instead of hand-maintaining a
# number that silently drifts away from the real tool surface.
TOOLS_REFERENCE_GENERATED = ROOT / "docs" / "tools-reference.generated.md"
MCP_SERVER_NAME = "io.github.oaslananka/kicad-mcp-pro"
WEBSITE = "https://oaslananka.github.io/kicad-mcp-pro"
GHCR_IMAGE = "ghcr.io/oaslananka/kicad-mcp-pro"
REGISTRY_META_KEY = "io.github.oaslananka/kicad-mcp-pro"
FAQ_SUPPORT_START = "<!-- public-metadata:kicad-support:start -->"
FAQ_SUPPORT_END = "<!-- public-metadata:kicad-support:end -->"
ROADMAP_RUNTIME_START = "<!-- public-metadata:runtime-policy:start -->"
ROADMAP_RUNTIME_END = "<!-- public-metadata:runtime-policy:end -->"
SERVER_INFO_SCHEMA_VERSION = "1.3.0"
TOOL_SCHEMA_VERSION = "1.0.0"
SERVER_INFO_CAPABILITIES = [
    "fileBackedDrc",
    "fileBackedErc",
    "fileBackedExports",
    "livePcbRead",
    "livePcbWrite",
    "liveSchematicRead",
    "liveSchematicWrite",
    "chatgptConnectorCompatible",
    "cliExports",
]
# Override description; the pyproject.toml description is PyPI-focused while
# the MCP registry entry uses a more detailed production-grade description.
SERVER_DESCRIPTION = (
    "Production-grade MCP server for KiCad EDA\u2014PCB design, DRC, "
    "simulation, BOM, DFM, and manufacturing."
)
LONG_DESCRIPTION_TEMPLATE = (
    "KiCad MCP Pro is a production-grade MCP server for KiCad EDA. "
    "It provides {tool_count} tools for PCB design, schematic capture, DRC/ERC "
    "validation, BOM generation, simulation, DFM analysis, and manufacturing "
    "export. Integrates with Claude Code, ChatGPT, VS Code Copilot, Cursor, "
    "and other MCP hosts. Uses KiCad CLI for file-backed operations when "
    "KiCad is available on PATH."
)
REGISTRY_TAGS = [
    "kicad",
    "pcb",
    "schematic",
    "drc",
    "erc",
    "bom",
    "gerber",
    "mcp",
    "eda",
    "electronics",
]
SCREENSHOTS = [
    ("01-claude-desktop-quality-gate.png", "Quality gate report in Claude Desktop"),
    ("02-cursor-schematic-build.png", "Schematic build workflow in Cursor"),
    ("03-vscode-pcb-inspection.png", "PCB inspection in VS Code"),
    ("04-tools-reference.png", "Tools reference documentation"),
    ("05-export-manufacturing.png", "Export and manufacturing package generation"),
]


def _public_tool_count() -> int:
    """Return the authoritative public tool count from the generated catalog.

    ``scripts/generate_tools_reference.py`` builds the server across every
    profile and writes ``Total public tools: N.`` into the generated catalog,
    which CI verifies for freshness. Reading that number keeps the registry
    description honest instead of relying on a hand-edited figure.
    """
    text = TOOLS_REFERENCE_GENERATED.read_text(encoding="utf-8")
    match = re.search(r"Total public tools:\s*(\d+)", text)
    if match is None:
        raise ValueError(
            f"Could not read the tool count from {TOOLS_REFERENCE_GENERATED.name}. "
            "Regenerate it with: pnpm run docs:tools"
        )
    return int(match.group(1))


def _long_description() -> str:
    return LONG_DESCRIPTION_TEMPLATE.format(tool_count=_public_tool_count())


def _license_text(project: dict[str, Any]) -> str:
    license_value = project.get("license")
    if isinstance(license_value, str):
        return license_value
    if isinstance(license_value, dict):
        text = license_value.get("text")
        if isinstance(text, str):
            return text
    raise ValueError("project.license must be a PEP 639 string or a table with a text field")


def _project_metadata() -> dict[str, Any]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data["project"]
    repository_url = str(project["urls"]["Repository"]).rstrip("/")
    public_metadata = data["tool"]["kicad-mcp"]["public-metadata"]
    repository_id = str(public_metadata["repository-id"]).strip()
    if not repository_url.startswith("https://github.com/"):
        raise ValueError("project.urls.Repository must be a canonical GitHub HTTPS URL")
    if not repository_id:
        raise ValueError("tool.kicad-mcp.public-metadata.repository-id must be non-empty")
    return {
        "package_name": project["name"],
        "version": project["version"],
        "description": project["description"],
        "license": _license_text(project),
        "repository_url": repository_url,
        "repository_id": repository_id,
    }


def _compatibility_metadata() -> dict[str, Any]:
    data = yaml.safe_load(COMPATIBILITY.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("compatibility.yaml must contain a mapping")
    return data


def _ranges_for_state(matrix: dict[str, Any], state: str) -> list[str]:
    supported = matrix["kicad"]["supported"]
    return [str(entry["range"]) for entry in supported if entry.get("state") == state]


def _joined_ranges(ranges: list[str]) -> str:
    if len(ranges) == 1:
        return ranges[0]
    if len(ranges) == 2:
        return f"{ranges[0]} and {ranges[1]}"
    return ", ".join(ranges[:-1]) + f", and {ranges[-1]}"


def _render_faq_support_block(matrix: dict[str, Any]) -> str:
    kicad = matrix["kicad"]
    primary = str(kicad["primary"])
    deprecated = _ranges_for_state(matrix, "deprecated")
    dropped = [str(entry["range"]) for entry in kicad.get("dropped", [])]
    preview = [str(entry["range"]) for entry in kicad.get("preview", [])]
    sentences = [f"KiCad {primary} is the primary supported target."]
    if deprecated:
        sentences.append(
            f"KiCad {_joined_ranges(deprecated)} remains deprecated and is limited to "
            "file-level read and migration support."
        )
    if dropped:
        sentences.append(f"KiCad {_joined_ranges(dropped)} has been dropped and is not supported.")
    if preview:
        sentences.append(f"KiCad {_joined_ranges(preview)} is preview-only.")
    sentences.append("The executable support policy lives in `compatibility.yaml`.")
    return " ".join(sentences)


def _render_roadmap_runtime_block(matrix: dict[str, Any]) -> str:
    kicad = matrix["kicad"]
    deprecated = _ranges_for_state(matrix, "deprecated")
    dropped = [str(entry["range"]) for entry in kicad.get("dropped", [])]
    preview = [str(entry["range"]) for entry in kicad.get("preview", [])]
    lines = [
        f"- Primary KiCad line: `{kicad['primary']}`; latest verified patch: "
        f"`{kicad['latestVerified']}`.",
    ]
    if deprecated:
        lines.append(f"- Deprecated KiCad lines: `{_joined_ranges(deprecated)}`.")
    if dropped:
        lines.append(f"- Dropped KiCad lines: `{_joined_ranges(dropped)}`.")
    if preview:
        lines.append(f"- Preview KiCad lines: `{_joined_ranges(preview)}`.")
    lines.append(f"- MCP protocol contract: `{matrix['mcp']['protocolVersion']}`.")
    return "\n".join(lines)


def _replace_generated_block(original: str, start: str, end: str, rendered: str) -> str:
    if start not in original or end not in original:
        raise ValueError(f"generated metadata markers are missing: {start} / {end}")
    prefix, remainder = original.split(start, maxsplit=1)
    _current, suffix = remainder.split(end, maxsplit=1)
    return f"{prefix}{start}\n{rendered}\n{end}{suffix}"


def _roadmap_version_errors(roadmap: str, current_version: str) -> list[str]:
    if "## Upcoming" not in roadmap:
        return ["ROADMAP.md is missing the Upcoming section"]
    upcoming = roadmap.split("## Upcoming", maxsplit=1)[1].split("\n## ", maxsplit=1)[0]
    try:
        current = Version(current_version)
    except InvalidVersion:
        return [f"pyproject.toml contains invalid package version {current_version!r}"]
    errors: list[str] = []
    for value in re.findall(r"^###\s+(\d+\.\d+(?:\.\d+)?)\b", upcoming, re.M):
        version = Version(value)
        if version <= current:
            errors.append(
                "ROADMAP.md upcoming section lists already-published version "
                f"{value} while the current package version is {current_version}"
            )
    return errors


def _registry_prerequisite(matrix: dict[str, Any]) -> str:
    primary = str(matrix["kicad"]["primary"])
    deprecated = _ranges_for_state(matrix, "deprecated")
    message = f"KiCad CLI {primary} available on PATH for file-backed DRC, ERC, and export tools."
    if deprecated:
        message += (
            f" KiCad {_joined_ranges(deprecated)} is deprecated and limited to file-level read "
            "and migration workflows."
        )
    return message


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2) + "\n"


def _pypi_package(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "registryType": "pypi",
        "registryBaseUrl": "https://pypi.org",
        "identifier": metadata["package_name"],
        "version": metadata["version"],
        "transport": {"type": "stdio"},
        "runtimeHint": "uvx",
        "runtimeArguments": [
            {"type": "positional", "value": "kicad-mcp-pro"},
        ],
        "packageArguments": [
            {
                "type": "named",
                "name": "--transport",
                "description": (
                    "Transport protocol (stdio or streamable-http). Legacy SSE disabled by default."
                ),
                "isRequired": False,
                "default": "stdio",
            },
            {
                "type": "named",
                "name": "--host",
                "description": "Host to bind the HTTP server to",
                "isRequired": False,
                "default": "127.0.0.1",
            },
            {
                "type": "named",
                "name": "--port",
                "description": "Port to bind the HTTP server to",
                "isRequired": False,
                "default": "3334",
            },
        ],
        "environmentVariables": [
            {
                "name": "KICAD_MCP_LOG_LEVEL",
                "description": "Logging level (DEBUG, INFO, WARNING, ERROR)",
                "isRequired": False,
                "default": "INFO",
            },
        ],
    }


def _npm_package(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "registryType": "npm",
        "registryBaseUrl": "https://registry.npmjs.org",
        "identifier": "kicad-mcp-pro",
        "version": metadata["version"],
        "runtimeHint": "npx",
        "transport": {"type": "stdio"},
        "runtimeArguments": [
            {"type": "positional", "value": "-y"},
        ],
        "environmentVariables": [
            {
                "name": "KICAD_MCP_PRO_PYPI_VERSION",
                "description": "Override the Python package version pinned by the npm wrapper",
                "isRequired": False,
            },
        ],
    }


def _oci_package(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "registryType": "oci",
        "identifier": f"{GHCR_IMAGE}:{metadata['version']}",
        "registry": "container",
        "image": GHCR_IMAGE,
        "runtimeHint": "docker",
        "transport": {"type": "stdio"},
        "runtimeArguments": [
            {"type": "positional", "value": "run"},
            {"type": "positional", "value": "--rm"},
            {"type": "positional", "value": "-i"},
        ],
        "packageArguments": [
            {
                "type": "positional",
                "valueHint": "image",
                "description": "Docker image to run",
                "default": f"{GHCR_IMAGE}:{metadata['version']}",
                "isRequired": True,
            },
        ],
    }


def _remotes_metadata() -> list[dict[str, Any]]:
    # Remote endpoint (mcp.kicad-mcp.pro) is not yet deployed; return empty list
    # until the production service is available.
    return []


def _registry_metadata(metadata: dict[str, Any], compatibility: dict[str, Any]) -> dict[str, Any]:
    repository_url = metadata["repository_url"]
    mcp_protocol_version = str(compatibility["mcp"]["protocolVersion"])
    changelog_url = f"{repository_url}/blob/main/CHANGELOG.md"
    tools_reference_url = f"{repository_url}/blob/main/docs/tools-reference.generated.md"
    return {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": MCP_SERVER_NAME,
        "title": "KiCad MCP Pro",
        "description": SERVER_DESCRIPTION,
        "websiteUrl": WEBSITE,
        "license": metadata["license"],
        "icons": [
            {
                "src": f"{WEBSITE}/assets/icon-512.png",
                "mimeType": "image/png",
                "sizes": ["512x512"],
            },
            {
                "src": f"{WEBSITE}/assets/icon.svg",
                "mimeType": "image/svg+xml",
                "sizes": ["any"],
            },
        ],
        "repository": {
            "url": repository_url,
            "source": "github",
            "id": metadata["repository_id"],
        },
        "version": metadata["version"],
        "packages": [
            _pypi_package(metadata),
            _npm_package(metadata),
            _oci_package(metadata),
        ],
        "remotes": _remotes_metadata(),
        "_meta": {
            REGISTRY_META_KEY: {
                "longDescription": _long_description(),
                "categories": [
                    "developer-tools",
                    "electronic-design-automation",
                    "manufacturing",
                ],
                "tags": REGISTRY_TAGS,
                "screenshots": [
                    {
                        "src": f"{WEBSITE}/assets/screenshots/{filename}",
                        "caption": caption,
                    }
                    for filename, caption in SCREENSHOTS
                ],
                "toolCatalog": {
                    "summary": (
                        "EDA automation tools for KiCad project setup, schematic analysis, "
                        "PCB inspection, DRC/ERC validation, BOM/netlist generation, "
                        "routing review, simulation, DFM, and manufacturing export."
                    ),
                    "reference": tools_reference_url,
                },
                "prerequisites": [_registry_prerequisite(compatibility)],
                "supportedMcpProtocolVersions": [mcp_protocol_version],
                "maintainer": {
                    "name": "Osman Aslan",
                    "url": "https://github.com/oaslananka",
                },
                "canonicalRepository": repository_url,
                "license": metadata["license"],
                "changelog": changelog_url,
                "releaseNotes": changelog_url,
                "serverInfo": {
                    "schemaVersion": SERVER_INFO_SCHEMA_VERSION,
                    "mcpProtocolVersion": mcp_protocol_version,
                    "toolSchemaVersion": TOOL_SCHEMA_VERSION,
                    "capabilities": SERVER_INFO_CAPABILITIES,
                },
            }
        },
    }


def _updated_init(metadata: dict[str, Any], original: str) -> str:
    rendered = []
    replaced = False
    for line in original.splitlines():
        if line.startswith("__version__ = "):
            rendered.append(f'__version__ = "{metadata["version"]}"  # x-release-please-version')
            replaced = True
        else:
            rendered.append(line)
    if not replaced:
        rendered.append(f'__version__ = "{metadata["version"]}"  # x-release-please-version')
    return "\n".join(rendered) + "\n"


def _updated_npm_wrapper_package(
    metadata: dict[str, Any], original: dict[str, Any]
) -> dict[str, Any]:
    updated = deepcopy(original)
    updated["version"] = metadata["version"]
    updated["homepage"] = WEBSITE
    updated["mcpName"] = MCP_SERVER_NAME
    repository_url = metadata["repository_url"]
    updated["repository"] = {
        "type": "git",
        "url": f"git+{repository_url}.git",
        "directory": "packages/mcp-npm",
    }
    updated["bugs"] = {"url": f"{repository_url}/issues"}
    return updated


def _planned_updates() -> dict[Path, str]:
    metadata = _project_metadata()
    compatibility = _compatibility_metadata()
    registry = _registry_metadata(metadata, compatibility)
    faq = _replace_generated_block(
        FAQ.read_text(encoding="utf-8"),
        FAQ_SUPPORT_START,
        FAQ_SUPPORT_END,
        _render_faq_support_block(compatibility),
    )
    roadmap = _replace_generated_block(
        ROADMAP.read_text(encoding="utf-8"),
        ROADMAP_RUNTIME_START,
        ROADMAP_RUNTIME_END,
        _render_roadmap_runtime_block(compatibility),
    )
    return {
        PACKAGE_INIT: _updated_init(metadata, PACKAGE_INIT.read_text(encoding="utf-8")),
        SERVER_JSON: _dump_json(registry),
        NPM_WRAPPER_PACKAGE: _dump_json(
            _updated_npm_wrapper_package(metadata, _load_json(NPM_WRAPPER_PACKAGE))
        ),
        FAQ: faq,
        ROADMAP: roadmap,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Fail if generated metadata differs.")
    mode.add_argument("--write", action="store_true", help="Update generated metadata files.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    metadata = _project_metadata()
    roadmap_errors = _roadmap_version_errors(
        ROADMAP.read_text(encoding="utf-8"), metadata["version"]
    )
    if roadmap_errors:
        for error in roadmap_errors:
            print(error, file=sys.stderr)
        return 1
    updates = _planned_updates()
    drift: list[Path] = []

    for path, rendered in updates.items():
        if path.read_text(encoding="utf-8") != rendered:
            drift.append(path)
            if args.write:
                with path.open("w", encoding="utf-8", newline="\n") as manifest:
                    manifest.write(rendered)

    if drift and args.check:
        rel = ", ".join(
            str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
            for path in drift
        )
        print(f"Public metadata is out of sync: {rel}", file=sys.stderr)
        print("Run: pnpm run metadata:sync", file=sys.stderr)
        return 1

    if args.write:
        print("Public metadata already synchronized." if not drift else "Updated public metadata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
