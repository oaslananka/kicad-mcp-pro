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

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
PACKAGE_INIT = ROOT / "src" / "kicad_mcp" / "__init__.py"
SERVER_JSON = ROOT / "server.json"
NPM_WRAPPER_PACKAGE = ROOT / "packages" / "mcp-npm" / "package.json"
# Authoritative public tool count is produced (and CI-checked) by
# scripts/generate_tools_reference.py; we read it instead of hand-maintaining a
# number that silently drifts away from the real tool surface.
TOOLS_REFERENCE_GENERATED = ROOT / "docs" / "tools-reference.generated.md"
MCP_SERVER_NAME = "io.github.oaslananka/kicad-mcp-pro"
REPOSITORY = "https://github.com/oaslananka/kicad-mcp-pro"
REPOSITORY_ID = "R_kgDOOIB7Lg"
WEBSITE = "https://oaslananka.github.io/kicad-mcp-pro"
GHCR_IMAGE = "ghcr.io/oaslananka/kicad-mcp-pro"
REGISTRY_META_KEY = "io.github.oaslananka/kicad-mcp-pro"
# In standalone kicad-mcp the root IS the package, so canonicalRepository
# is the bare repository URL (no /tree/main suffix).
CANONICAL_PACKAGE_URL = REPOSITORY
CHANGELOG_URL = f"{REPOSITORY}/blob/main/CHANGELOG.md"
TOOLS_REFERENCE_URL = f"{REPOSITORY}/blob/main/docs/tools-reference.generated.md"
MCP_PROTOCOL_VERSION = "2025-11-25"
SERVER_INFO_SCHEMA_VERSION = "1.1.0"
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
    return {
        "package_name": project["name"],
        "version": project["version"],
        "description": project["description"],
        "license": _license_text(project),
    }


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


def _registry_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
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
            "url": REPOSITORY,
            "source": "github",
            "id": REPOSITORY_ID,
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
                    "reference": TOOLS_REFERENCE_URL,
                },
                "prerequisites": [
                    "KiCad CLI 8.x, 9.x, or 10.x available on PATH for file-backed DRC, "
                    "ERC, and export tools."
                ],
                "supportedMcpProtocolVersions": [MCP_PROTOCOL_VERSION],
                "maintainer": {
                    "name": "Osman Aslan",
                    "url": "https://github.com/oaslananka",
                },
                "canonicalRepository": CANONICAL_PACKAGE_URL,
                "license": metadata["license"],
                "changelog": CHANGELOG_URL,
                "releaseNotes": CHANGELOG_URL,
                "serverInfo": {
                    "schemaVersion": SERVER_INFO_SCHEMA_VERSION,
                    "mcpProtocolVersion": MCP_PROTOCOL_VERSION,
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
    updated["repository"] = {
        "type": "git",
        "url": f"git+{REPOSITORY}.git",
        "directory": "packages/mcp-npm",
    }
    updated["bugs"] = {"url": f"{REPOSITORY}/issues"}
    return updated


def _planned_updates() -> dict[Path, str]:
    metadata = _project_metadata()
    registry = _registry_metadata(metadata)
    return {
        PACKAGE_INIT: _updated_init(metadata, PACKAGE_INIT.read_text(encoding="utf-8")),
        SERVER_JSON: _dump_json(registry),
        NPM_WRAPPER_PACKAGE: _dump_json(
            _updated_npm_wrapper_package(metadata, _load_json(NPM_WRAPPER_PACKAGE))
        ),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Fail if generated metadata differs.")
    mode.add_argument("--write", action="store_true", help="Update generated metadata files.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
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
        print(f"MCP metadata is out of sync: {rel}", file=sys.stderr)
        print("Run: pnpm run metadata:sync", file=sys.stderr)
        return 1

    if args.write:
        print("MCP metadata already synchronized." if not drift else "Updated MCP metadata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
