#!/usr/bin/env python3
"""Quick check that kicad-mcp-pro is installed and the server is available."""

import shutil
import subprocess
import sys


def main() -> int:
    """Run a quick availability check."""
    executable = shutil.which("kicad-mcp-pro")
    if executable is None:
        print("✗ kicad-mcp-pro not found. Install: pipx install kicad-mcp-pro")
        return 1
    try:
        result = subprocess.run(
            [executable, "health", "--json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            print("✓ kicad-mcp-pro server is available")
            return 0
        print(f"✗ Server returned exit code {result.returncode}")
        return 1
    except subprocess.TimeoutExpired:
        print("✗ Server startup timed out")
        return 1


if __name__ == "__main__":
    sys.exit(main())
