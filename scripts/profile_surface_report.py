#!/usr/bin/env python3
"""Generate deterministic evidence for progressive-disclosure MCP profiles."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
from pathlib import Path
from typing import Any

from kicad_mcp.config import reset_config
from kicad_mcp.evals.tool_selection import load_cases
from kicad_mcp.server import build_server
from kicad_mcp.tools.router import tools_for_profile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs" / "evidence" / "progressive-disclosure-profile-snapshot.json"
CASES_PATH = ROOT / "evals" / "tool_selection" / "cases.yaml"
PROFILE_MODES: dict[str, str] = {
    "default": "readonly",
    "review": "readonly",
    "build": "write",
    "release": "manufacturing",
    "expert": "experimental",
}


def _catalog(profile: str, mode: str) -> list[dict[str, Any]]:
    previous = os.environ.get("KICAD_MCP_OPERATING_MODE")
    os.environ["KICAD_MCP_OPERATING_MODE"] = mode
    reset_config()
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            server = build_server(profile=profile)
        server.filter_runtime_tools = False
        tools = server.list_tools_sync()
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema or {},
            }
            for tool in sorted(tools, key=lambda item: item.name)
        ]
    finally:
        if previous is None:
            os.environ.pop("KICAD_MCP_OPERATING_MODE", None)
        else:
            os.environ["KICAD_MCP_OPERATING_MODE"] = previous
        reset_config()


def build_report() -> dict[str, Any]:
    cases = load_cases(CASES_PATH)
    profile_data: dict[str, dict[str, Any]] = {}

    for profile, mode in PROFILE_MODES.items():
        declared = set(tools_for_profile(profile))
        catalog = _catalog(profile, mode)
        callable_names = {entry["name"] for entry in catalog}
        serialized = json.dumps(catalog, separators=(",", ":"), sort_keys=True)
        covered_cases = sum(
            1 for case in cases if set(case.expected_tools).issubset(callable_names)
        )
        forbidden_exposures = sum(
            len(set(case.forbidden_tools).intersection(callable_names)) for case in cases
        )
        profile_data[profile] = {
            "mode": mode,
            "declaredTools": len(declared),
            "callableTools": len(callable_names),
            "catalogCharacters": len(serialized),
            "estimatedCatalogTokens": math.ceil(len(serialized) / 4),
            "goldenCases": len(cases),
            "goldenCasesCovered": covered_cases,
            "goldenCoveragePct": round(covered_cases / len(cases) * 100, 1),
            "forbiddenToolExposures": forbidden_exposures,
            "tools": sorted(callable_names),
        }

    expert = profile_data["expert"]
    for _profile, data in profile_data.items():
        data["toolReductionVsExpertPct"] = round(
            (1 - data["callableTools"] / expert["callableTools"]) * 100,
            1,
        )
        data["catalogReductionVsExpertPct"] = round(
            (1 - data["catalogCharacters"] / expert["catalogCharacters"]) * 100,
            1,
        )

    return {
        "schemaVersion": "1.0.0",
        "source": {
            "profiles": "src/kicad_mcp/tools/router.py",
            "goldenCases": "evals/tool_selection/cases.yaml",
            "tokenEstimate": "ceil(minified catalog characters / 4)",
        },
        "profiles": profile_data,
    }


def render(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    rendered = render(build_report())
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            print("progressive-disclosure profile snapshot drift detected")
            print("Run: uv run --all-extras python scripts/profile_surface_report.py")
            return 1
        print("progressive-disclosure profile snapshot OK")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    try:
        display_path = args.output.relative_to(ROOT)
    except ValueError:
        display_path = args.output
    print(f"wrote {display_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
