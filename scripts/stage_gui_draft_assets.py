"""Stage the exact six GUI installers for a future draft Release (no publication).

Input is downloaded Actions bundles from three trusted named matrix jobs.
Reject missing, unexpected, cross-platform, stale-version and linked files
*before* creating the output directory. This does not authorize publication,
validate GitHub producer identity or replace signed provenance verification.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

_TAG = re.compile(r"kicad-mcp-gui-v([0-9]+\.[0-9]+\.[0-9]+)", re.ASCII)
_PLATFORM_FILES = {
    "linux": (
        "KiCad-MCP-Pro_{v}_amd64.deb",
        "KiCad-MCP-Pro-{v}-1.x86_64.rpm",
        "KiCad-MCP-Pro_{v}_amd64.AppImage",
    ),
    "macos": ("KiCad-MCP-Pro_{v}_aarch64.dmg",),
    "windows": (
        "KiCad-MCP-Pro_{v}_x64_en-US.msi",
        "KiCad-MCP-Pro_{v}_x64-setup.exe",
    ),
}


def stage_gui_draft_assets(artifacts_dir: Path, output_dir: Path, release_tag: str) -> list[str]:
    """Copy only complete, source-versioned platform installers to empty staging.

    No GitHub Release/registry/network operation is performed. Stage paths are
    caller-local, never selected from a GitHub API or an untrusted archive.
    """
    match = _TAG.fullmatch(release_tag)
    if match is None:
        raise ValueError("unsupported stable GUI release tag")
    version = match.group(1)
    root = artifacts_dir.resolve()
    output = output_dir.resolve()
    if root == output or root in output.parents or output in root.parents:
        raise ValueError("installer input/output paths overlap")
    if not artifacts_dir.is_dir() or artifacts_dir.is_symlink():
        raise ValueError("missing or linked Actions artifact directory")
    if output_dir.is_symlink() or (
        output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir()))
    ):
        raise ValueError("staging destination must be empty and not a symlink")

    expected = {
        f"gui-{platform}-tauri": {name.format(v=version) for name in names}
        for platform, names in _PLATFORM_FILES.items()
    }
    seen: dict[str, Path] = {}
    roles = {path.name for path in artifacts_dir.iterdir()}
    if roles != set(expected):
        raise ValueError(f"unexpected or missing GUI platform bundles: {sorted(roles)}")

    for role, names in sorted(expected.items()):
        source = artifacts_dir / role
        if not source.is_dir() or source.is_symlink():
            raise ValueError(f"untrusted GUI bundle directory: {role}")
        found: set[str] = set()
        for path in source.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"linked GUI installer input: {path.name}")
            if path.is_dir():
                continue
            if not path.is_file() or path.name not in names or path.stat().st_size <= 0:
                raise ValueError(f"unapproved GUI installer input: {path.name}")
            if path.name in found:
                raise ValueError(f"duplicate GUI installer: {path.name}")
            found.add(path.name)
            platform = role.removeprefix("gui-").removesuffix("-tauri")
            seen[f"{platform}_{path.name}"] = path
        if found != names:
            raise ValueError(f"missing required GUI installers for {role}: {sorted(names - found)}")

    # No output directory/file is written until the complete inventory passes.
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, source in sorted(seen.items()):
        with source.open("rb") as inp, (output_dir / filename).open("xb") as dst:
            shutil.copyfileobj(inp, dst)
    return sorted(seen)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-tag", required=True)
    args = parser.parse_args()
    try:
        names = stage_gui_draft_assets(args.artifacts_dir, args.output_dir, args.release_tag)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"GUI draft preparation: FAIL: {exc}\n")
    print(json.dumps({"preparedAssets": names, "published": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
