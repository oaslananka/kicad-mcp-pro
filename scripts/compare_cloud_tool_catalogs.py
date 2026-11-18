"""Inspect offline MCP tool contract changes before publishing a Cloud update."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kicad_mcp.tool_contract_evolution import compare_tool_catalogs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare generated tool catalogs for additions and compatibility hazards."
    )
    parser.add_argument("before", type=Path, help="Previously published catalog JSON")
    parser.add_argument("after", type=Path, help="Candidate catalog JSON")
    parser.add_argument(
        "--fail-on-breaking",
        action="store_true",
        help="Return nonzero for tool removals or potentially breaking contract changes.",
    )
    args = parser.parse_args(argv)
    try:
        old = json.loads(args.before.read_text(encoding="utf-8"))
        new = json.loads(args.after.read_text(encoding="utf-8"))
        report = compare_tool_catalogs(old, new)
    except (OSError, ValueError, TypeError) as exc:
        print(f"Tool contract comparison failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 1 if args.fail_on_breaking and report["breaking"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
