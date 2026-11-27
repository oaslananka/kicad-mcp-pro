"""Wait for the Python distribution required by a new npm launcher release."""

from __future__ import annotations

import argparse
import json
import re
import time
from urllib.request import Request, urlopen


def has_matching_wheel(payload: object, version: str) -> bool:
    if not isinstance(payload, dict):
        return False
    info, files = payload.get("info"), payload.get("urls")
    if not isinstance(info, dict) or not isinstance(files, list):
        return False
    if info.get("name") != "kicad-mcp-pro" or info.get("version") != version:
        return False
    expected = f"kicad_mcp_pro-{version}-py3-none-any.whl"
    return any(
        isinstance(item, dict)
        and item.get("packagetype") == "bdist_wheel"
        and item.get("yanked") is False
        and item.get("filename") == expected
        for item in files
    )


def fetch_release(version: str) -> object:
    if not re.fullmatch(r"[0-9]+\\.[0-9]+\\.[0-9]+", version):
        raise ValueError("Expected a stable Python release version.")
    request = Request(
        f"https://pypi.org/pypi/kicad-mcp-pro/{version}/json",
        headers={"User-Agent": "kicad-mcp-pro-release-wheel-gate"},
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310 - fixed HTTPS host/version
        return json.load(response)


def wait_for_wheel(version: str, *, attempts: int = 30, delay: int = 20) -> bool:
    for attempt in range(attempts):
        try:
            if has_matching_wheel(fetch_release(version), version):
                print(f"Matching non-yanked Python wheel is available: {version}")
                return True
        except (OSError, ValueError):
            pass
        print(f"Python wheel {version} not ready (attempt {attempt + 1}/{attempts}).", flush=True)
        if attempt + 1 < attempts:
            time.sleep(delay)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]+\\.[0-9]+\\.[0-9]+", args.version):
        parser.error("Expected a stable release version.")
    return 0 if wait_for_wheel(args.version) else 1


if __name__ == "__main__":
    raise SystemExit(main())
