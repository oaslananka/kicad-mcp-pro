"""Build the reviewed tool-effect manifest consumed by security policy clients."""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path
from typing import Any

from kicad_mcp.tool_effect_manifest import (
    REVIEWED_SOURCE_SHA,
    REVIEWED_TOOL_EFFECTS,
    SCHEMA_VERSION,
    SOURCE_REPOSITORY,
    PathArgumentEffect,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "contracts" / "tool-effect-manifest.json"


def _package_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _path_argument_payload(path_argument: PathArgumentEffect) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "argument": path_argument.argument,
        "effects": list(path_argument.effects),
        "required": path_argument.required,
    }
    if path_argument.default is not None:
        payload["default"] = path_argument.default
    if path_argument.base_argument is not None:
        payload["base_argument"] = path_argument.base_argument
    return payload


def build() -> dict[str, Any]:
    tools = []
    for contract in REVIEWED_TOOL_EFFECTS:
        tools.append(
            {
                "name": contract.name,
                "arguments": list(contract.arguments),
                "effects": list(contract.effects),
                "path_arguments": [
                    _path_argument_payload(path_argument)
                    for path_argument in contract.path_arguments
                ],
                "destructive": contract.destructive,
                "idempotent": contract.idempotent,
                "supports_dry_run": contract.supports_dry_run,
                "supports_rollback": contract.supports_rollback,
                "transaction_support": contract.transaction_support,
                "verification_requirements": list(contract.verification_requirements),
                "reviewed_source_paths": list(contract.reviewed_source_paths),
            }
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "source": {
            "repository": SOURCE_REPOSITORY,
            "version": _package_version(),
            "reviewed_source_sha": REVIEWED_SOURCE_SHA,
        },
        "tools": tools,
    }


def render(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build reviewed tool-effect manifest.")
    parser.add_argument("--check", action="store_true", help="Fail if committed manifest drifts.")
    args = parser.parse_args(argv)

    rendered = render(build())
    drift = not MANIFEST_PATH.is_file() or MANIFEST_PATH.read_text(encoding="utf-8") != rendered
    if args.check:
        if drift:
            print("tool-effect-manifest.json drift detected")
            print("Run: uv run python scripts/build_tool_effect_manifest.py")
            return 1
        print("tool-effect-manifest.json OK")
        return 0

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {MANIFEST_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
