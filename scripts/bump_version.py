"""Update release version metadata across the repository."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bump KiCad MCP Pro release metadata.")
    parser.add_argument("version", help="Target release version, for example 1.0.4.")
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Release date for CHANGELOG.md, default: today.",
    )
    parser.add_argument(
        "--skip-lock",
        action="store_true",
        help="Do not run `uv lock` after updating metadata.",
    )
    return parser.parse_args(argv)


def validate_version(version: str) -> None:
    if not VERSION_PATTERN.fullmatch(version):
        raise SystemExit(f"Expected a stable x.y.z version, got: {version}")


def replace_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"Could not update version in {path.relative_to(ROOT)}")
    path.write_text(updated, encoding="utf-8")


def update_json(path: Path, version: str) -> None:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version

    for package in data.get("packages", []):
        if isinstance(package, dict) and "version" in package:
            package["version"] = version

    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def update_changelog(path: Path, version: str, release_date: str) -> None:
    text = path.read_text(encoding="utf-8")
    if f"## [{version}]" in text:
        return

    entry = (
        f"## [{version}] - {release_date}\n\n"
        "### Changed\n\n"
        f"- Bumped project release version to {version} across package/runtime/registry "
        "metadata.\n\n"
    )
    first_release = re.search(r"\n## \[", text)
    if first_release is None:
        updated = f"{text.rstrip()}\n\n{entry}"
    else:
        insert_at = first_release.start() + 1
        updated = f"{text[:insert_at]}{entry}{text[insert_at:]}"

    path.write_text(updated, encoding="utf-8")


def run_uv_lock() -> None:
    uv_path = shutil.which("uv")
    if uv_path is None:
        raise SystemExit("Could not find `uv` on PATH; run `uv lock` manually.")
    subprocess.run([uv_path, "lock"], cwd=ROOT, check=True)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    version = args.version
    validate_version(version)

    replace_once(ROOT / "pyproject.toml", r'^version = "[^"]+"', f'version = "{version}"')
    replace_once(
        ROOT / "src" / "kicad_mcp" / "__init__.py",
        r'^__version__ = "[^"]+"',
        f'__version__ = "{version}"',
    )
    update_json(ROOT / "server.json", version)
    update_json(ROOT / "mcp.json", version)
    update_changelog(ROOT / "CHANGELOG.md", version, args.date)

    if not args.skip_lock:
        run_uv_lock()

    print(f"Bumped KiCad MCP Pro to {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
