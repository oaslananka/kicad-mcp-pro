from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "release-please-config.json"
DEFAULT_MANIFEST = ".release-please-manifest.json"


def _repo_path(package_path: str, relative_path: str) -> str:
    if package_path in {"", "."}:
        return Path(relative_path).as_posix()
    return (Path(package_path) / relative_path).as_posix()


def allowed_release_metadata_paths(config: dict[str, Any]) -> set[str]:
    allowed = {DEFAULT_MANIFEST}
    for package_path, package in config.get("packages", {}).items():
        changelog = str(package.get("changelog-path", "CHANGELOG.md"))
        allowed.add(_repo_path(package_path, changelog))

        release_type = package.get("release-type")
        if release_type == "python":
            allowed.update({_repo_path(package_path, "pyproject.toml"), "uv.lock"})
        elif release_type == "node":
            allowed.update(
                {
                    _repo_path(package_path, "package.json"),
                    _repo_path(package_path, "package-lock.json"),
                }
            )
        elif release_type == "rust":
            allowed.update(
                {
                    _repo_path(package_path, "Cargo.toml"),
                    _repo_path(package_path, "Cargo.lock"),
                }
            )

        for extra in package.get("extra-files", []):
            path = extra.get("path") if isinstance(extra, dict) else extra
            if path:
                allowed.add(_repo_path(package_path, str(path)))
    return allowed


def unexpected_release_paths(paths: list[str], config: dict[str, Any]) -> list[str]:
    allowed = allowed_release_metadata_paths(config)
    return sorted(path for path in paths if path and Path(path).as_posix() not in allowed)


def is_release_metadata_only(paths: list[str], config: dict[str, Any]) -> bool:
    normalized = {Path(path).as_posix() for path in paths if path}
    return DEFAULT_MANIFEST in normalized and not unexpected_release_paths(
        sorted(normalized), config
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths-file", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    paths = [line.strip() for line in args.paths_file.read_text(encoding="utf-8").splitlines()]
    unexpected = unexpected_release_paths(paths, config)
    if unexpected:
        print("Change set contains non-release-metadata paths:")
        for path in unexpected:
            print(f"- {path}")
        return 1
    if DEFAULT_MANIFEST not in {Path(path).as_posix() for path in paths if path}:
        print(f"Change set does not include {DEFAULT_MANIFEST}; treating it as normal CI.")
        return 1
    print(f"Release change set is metadata-only ({len([p for p in paths if p])} paths).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
