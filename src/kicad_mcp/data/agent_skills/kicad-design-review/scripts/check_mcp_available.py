#!/usr/bin/env python3
"""Check for the KiCad MCP CLI without executing discovered binaries.

This preflight only verifies PATH discovery, not MCP connectivity or KiCad
runtime readiness. Use `kicad-mcp-pro doctor` and a read-only client smoke
separately to validate a live connection in a trusted environment.
"""

import shutil
import sys


def main() -> int:
    """Return failure when the launcher cannot be found on PATH."""
    if shutil.which("kicad-mcp-pro") is None:
        print("KiCad MCP Pro CLI not found. Install: pipx install kicad-mcp-pro")
        return 1
    print("KiCad MCP Pro CLI located on PATH (runtime not yet verified).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
