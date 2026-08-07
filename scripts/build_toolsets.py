"""Generate integrations/common/toolsets.json from the router profile SOT (P1-T2).

``src/kicad_mcp/tools/router.py`` is the single source of truth for profiles. This
script derives the integration-facing ``toolsets.json`` from it so the two can never
drift and every listed tool is really registered.

Each toolset maps to a router profile (and operating mode). The four names that exist
on both sides — ``schematic``, ``manufacturing``, ``simulation``, ``high_speed`` —
resolve to the identically named router profile, so "same name, same tools" holds.

Usage:
  uv run python scripts/build_toolsets.py            # write toolsets.json
  uv run python scripts/build_toolsets.py --check    # fail on drift (CI)
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

from kicad_mcp.config import reset_config
from kicad_mcp.server import build_server

ROOT = Path(__file__).resolve().parents[1]
TOOLSETS_PATH = ROOT / "integrations" / "common" / "toolsets.json"

# toolset name -> (router profile, operating mode, description, dangerous)
TOOLSETS: dict[str, tuple[str, str, str, bool]] = {
    "default": (
        "default",
        "readonly",
        "Bounded general-agent surface for project review and safe next-action discovery.",
        False,
    ),
    "review": (
        "review",
        "readonly",
        "Read-only review surface with DRC, ERC, DFM, visual QA, and contract checks.",
        False,
    ),
    "build": (
        "build",
        "write",
        (
            "Plan/apply/verify workflows plus bounded PCB inspect/remove/DRC operations "
            "for trusted projects."
        ),
        False,
    ),
    "release": (
        "release",
        "manufacturing",
        "Release validation and human-gated manufacturing package generation.",
        False,
    ),
    "expert": (
        "expert",
        "experimental",
        "Complete expert catalog. DANGEROUS - use only with trusted projects and approval.",
        True,
    ),
    "readonly": (
        "review",
        "readonly",
        "Backward-compatible alias for the bounded review surface.",
        False,
    ),
    "schematic": (
        "schematic",
        "experimental",
        "Schematic design, editing, library, export, and validation tools.",
        False,
    ),
    "pcb_layout": (
        "pcb_only",
        "experimental",
        "PCB layout, routing, placement, and copper management tools.",
        False,
    ),
    "manufacturing": (
        "manufacturing",
        "experimental",
        "Manufacturing export, DFM, test, and release tools.",
        False,
    ),
    "simulation": (
        "simulation",
        "experimental",
        "SPICE simulation, analysis, and model management tools.",
        False,
    ),
    "high_speed": (
        "high_speed",
        "experimental",
        "High-speed signal integrity, EMC, and power integrity review tools.",
        False,
    ),
    "full_write": (
        "expert",
        "experimental",
        "Backward-compatible alias for the complete expert catalog.",
        True,
    ),
}


def _tools_for(profile: str, mode: str) -> list[str]:
    previous = os.environ.get("KICAD_MCP_OPERATING_MODE")
    os.environ["KICAD_MCP_OPERATING_MODE"] = mode
    reset_config()
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            server = build_server(profile=profile)
        server.filter_runtime_tools = False
        return sorted(tool.name for tool in server.list_tools_sync())
    finally:
        if previous is None:
            os.environ.pop("KICAD_MCP_OPERATING_MODE", None)
        else:
            os.environ["KICAD_MCP_OPERATING_MODE"] = previous
        reset_config()


def build() -> dict[str, Any]:
    toolsets: dict[str, Any] = {}
    for name, (profile, mode, description, dangerous) in TOOLSETS.items():
        entry: dict[str, Any] = {"description": description, "profile": profile, "mode": mode}
        if dangerous:
            entry["dangerous"] = True
        entry["tools"] = _tools_for(profile, mode)
        toolsets[name] = entry
    return {
        "version": "3.0.0",
        "description": (
            "Generated from router profile definitions (src/kicad_mcp/tools/router.py). "
            "Do not edit by hand; run scripts/build_toolsets.py."
        ),
        "toolsets": toolsets,
    }


def render(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build toolsets.json from router profiles.")
    parser.add_argument("--check", action="store_true", help="Fail if committed file drifts.")
    args = parser.parse_args(argv)

    rendered = render(build())
    drift = not TOOLSETS_PATH.is_file() or TOOLSETS_PATH.read_text(encoding="utf-8") != rendered

    if args.check:
        if drift:
            print("toolsets.json drift detected", file=sys.stderr)
            print("Run: uv run python scripts/build_toolsets.py", file=sys.stderr)
            return 1
        print("toolsets.json OK")
        return 0

    TOOLSETS_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {TOOLSETS_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
