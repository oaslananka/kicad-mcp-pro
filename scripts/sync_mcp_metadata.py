"""Synchronize MCP registry metadata from pyproject.toml."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
MCP_JSON = ROOT / "mcp.json"
SERVER_JSON = ROOT / "server.json"


def _project_metadata() -> dict[str, Any]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data["project"]
    urls = project.get("urls", {})
    return {
        "package_name": project["name"],
        "version": project["version"],
        "description": project["description"],
        "license": project["license"]["text"],
        "repository": urls.get("Repository", urls.get("Homepage", "")),
        "homepage": urls.get("Documentation", urls.get("Homepage", "")),
    }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2) + "\n"


def _updated_mcp_json(metadata: dict[str, Any], original: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(original)
    updated["description"] = (
        "Compatibility metadata for KiCad MCP Pro. Prefer server.json for official MCP "
        "Registry publication."
    )
    updated["version"] = metadata["version"]
    updated["license"] = metadata["license"]
    updated["repository"] = metadata["repository"]
    updated["homepage"] = metadata["homepage"]
    return updated


def _updated_server_json(metadata: dict[str, Any], original: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(original)
    updated["description"] = metadata["description"]
    updated["version"] = metadata["version"]
    updated["repository"] = {
        "url": metadata["repository"],
        "source": "github",
    }
    updated["websiteUrl"] = metadata["homepage"]
    updated["license"] = metadata["license"]
    for package in updated.get("packages", []):
        if isinstance(package, dict) and package.get("identifier") == metadata["package_name"]:
            package["version"] = metadata["version"]
    return updated


def _planned_updates() -> dict[Path, str]:
    metadata = _project_metadata()
    return {
        MCP_JSON: _dump_json(_updated_mcp_json(metadata, _load_json(MCP_JSON))),
        SERVER_JSON: _dump_json(_updated_server_json(metadata, _load_json(SERVER_JSON))),
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
                path.write_text(rendered, encoding="utf-8")

    if drift and args.check:
        rel = ", ".join(str(path.relative_to(ROOT)) for path in drift)
        print(f"MCP metadata is out of sync: {rel}", file=sys.stderr)
        print("Run: npm run metadata:sync", file=sys.stderr)
        return 1

    if args.write:
        if drift:
            print(
                "Updated MCP metadata: " + ", ".join(str(path.relative_to(ROOT)) for path in drift)
            )
        else:
            print("MCP metadata already synchronized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
