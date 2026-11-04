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

try:
    from scripts.runtime_path_safety import approved_runtime_path
except ModuleNotFoundError:  # Direct python scripts/foo.py execution.
    from runtime_path_safety import approved_runtime_path

_TAG = re.compile(r"kicad-mcp-gui-v(\d+\.\d+\.\d+)", re.ASCII)
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


def _approved_staging_paths(artifacts_dir: Path, output_dir: Path) -> tuple[Path, Path]:
    """Bound CLI-selected paths before touching any file or creating directories."""
    if ".." in artifacts_dir.parts or ".." in output_dir.parts:
        raise ValueError("parent traversal in GUI draft filesystem path")
    root = approved_runtime_path(artifacts_dir)
    output = approved_runtime_path(output_dir)
    if root == output or root in output.parents or output in root.parents:
        raise ValueError("installer input/output paths overlap")
    if not artifacts_dir.is_dir() or artifacts_dir.is_symlink():
        raise ValueError("missing or linked Actions artifact directory")
    if output_dir.is_symlink() or (
        output.exists() and (not output.is_dir() or any(output.iterdir()))
    ):
        raise ValueError("staging destination must be empty and not a symlink")
    return root, output


def _expected_platform_roles(version: str) -> dict[str, set[str]]:
    return {
        f"gui-{platform}-tauri": {name.format(v=version) for name in names}
        for platform, names in _PLATFORM_FILES.items()
    }


def _validated_role_files(root: Path, role: str, names: set[str]) -> dict[str, Path]:
    """Refuse malformed individual artifact bundles before any staging write."""
    source = root / role
    if not source.is_dir() or source.is_symlink():
        raise ValueError(f"untrusted GUI bundle directory: {role}")
    found: dict[str, Path] = {}
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"linked GUI installer input: {path.name}")
        if path.is_dir():
            continue
        if not path.is_file() or path.name not in names or path.stat().st_size <= 0:
            raise ValueError(f"unapproved GUI installer input: {path.name}")
        if path.name in found:
            raise ValueError(f"duplicate GUI installer: {path.name}")
        found[path.name] = path
    if set(found) != names:
        raise ValueError(
            f"missing required GUI installers for {role}: {sorted(names - set(found))}"
        )
    platform = role.removeprefix("gui-").removesuffix("-tauri")
    return {f"{platform}_{name}": path for name, path in found.items()}


def _validated_installers(root: Path, version: str) -> dict[str, Path]:
    expected = _expected_platform_roles(version)
    roles = {path.name for path in root.iterdir()}
    if roles != set(expected):
        raise ValueError(f"unexpected or missing GUI platform bundles: {sorted(roles)}")
    seen: dict[str, Path] = {}
    for role, names in sorted(expected.items()):
        seen.update(_validated_role_files(root, role, names))
    return seen


def stage_gui_draft_assets(artifacts_dir: Path, output_dir: Path, release_tag: str) -> list[str]:
    """Stage six versioned installers under the repo/temp filesystem boundary.

    No GitHub Release/registry/network operation is performed. CLI-supplied
    locations are confined to canonical automation roots, with explicit
    parent-traversal rejection; staging begins only after full validation.
    """
    match = _TAG.fullmatch(release_tag)
    if match is None:
        raise ValueError("unsupported stable GUI release tag")
    root, output = _approved_staging_paths(artifacts_dir, output_dir)
    seen = _validated_installers(root, match.group(1))

    # Never stage to an unbounded raw path taken from CLI arguments.
    output.mkdir(parents=True, exist_ok=True)
    for filename, source in sorted(seen.items()):
        with source.open("rb") as inp, (output / filename).open("xb") as dst:
            shutil.copyfileobj(inp, dst)
    return sorted(seen)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-tag", required=True)
    args = parser.parse_args()
    try:
        # GitHub Actions controls its working directory. Caller-provided paths
        # are deliberately not CLI parameters (no arbitrary filesystem targets).
        workspace = approved_runtime_path(Path.cwd())
        names = stage_gui_draft_assets(
            workspace / "artifacts", workspace / "release-assets", args.release_tag
        )
    except (ValueError, OSError) as exc:
        parser.exit(2, f"GUI draft preparation: FAIL: {exc}\n")
    print(json.dumps({"preparedAssets": names, "published": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
