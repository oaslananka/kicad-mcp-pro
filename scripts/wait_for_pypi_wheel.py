"""Wait for the Python distribution required by a new npm launcher release."""

from __future__ import annotations

import argparse
import json
import re
import time

from urllib3 import PoolManager
from urllib3.exceptions import HTTPError

MAX_JSON_BYTES = 4 * 1024 * 1024
_STABLE_VERSION = re.compile(r"\d+\.\d+\.\d+", re.ASCII)


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
    if not _STABLE_VERSION.fullmatch(version):
        raise ValueError("Expected a stable Python release version.")
    pool = PoolManager(cert_reqs="CERT_REQUIRED", timeout=10.0)
    try:
        with pool.request(
            "GET",
            f"https://pypi.org/pypi/kicad-mcp-pro/{version}/json",
            headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            preload_content=False,
            redirect=False,
            retries=False,
            decode_content=False,
        ) as response:
            if response.status != 200:
                raise OSError(f"PyPI returned HTTP {response.status}")
            raw = response.read(MAX_JSON_BYTES + 1)
    finally:
        pool.clear()
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("PyPI JSON exceeds size limit.")
    return json.loads(raw)


def wait_for_wheel(version: str, *, attempts: int = 30, delay: int = 20) -> bool:
    for attempt in range(attempts):
        try:
            if has_matching_wheel(fetch_release(version), version):
                print(f"Matching non-yanked Python wheel is available: {version}")
                return True
        except (OSError, ValueError, HTTPError):
            pass
        print(f"Python wheel {version} not ready (attempt {attempt + 1}/{attempts}).", flush=True)
        if attempt + 1 < attempts:
            time.sleep(delay)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    args = parser.parse_args()
    if not _STABLE_VERSION.fullmatch(args.version):
        parser.error("Expected a stable release version.")
    return 0 if wait_for_wheel(args.version) else 1


if __name__ == "__main__":
    raise SystemExit(main())
