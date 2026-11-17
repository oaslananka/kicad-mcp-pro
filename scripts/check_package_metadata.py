"""Validate built package metadata for PyPI compatibility."""

from __future__ import annotations

import argparse
import tarfile
import tomllib
import zipfile
from pathlib import Path


def _metadata_from_wheel(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        return archive.read(metadata_name).decode("utf-8")


def _metadata_from_sdist(path: Path) -> str:
    with tarfile.open(path, mode="r:gz") as archive:
        member = next(member for member in archive.getmembers() if member.name.endswith("PKG-INFO"))
        extracted = archive.extractfile(member)
        if extracted is None:
            raise ValueError(f"Could not read PKG-INFO from {path}.")
        return extracted.read().decode("utf-8")


def _metadata_for(path: Path) -> str:
    if path.suffix == ".whl":
        return _metadata_from_wheel(path)
    if path.suffixes[-2:] == [".tar", ".gz"]:
        return _metadata_from_sdist(path)
    raise ValueError(f"Unsupported distribution artifact: {path}")


def _validate_metadata(path: Path, metadata: str, expected_license: str) -> None:
    if "License-Expression:" in metadata:
        raise ValueError(
            f"{path.name} uses License-Expression metadata, which PyPI rejected for this project. "
            "Use legacy License metadata until the release workflow is migrated."
        )
    if f"License: {expected_license}" not in metadata:
        raise ValueError(
            f"{path.name} is missing the expected License: {expected_license} metadata field."
        )
    if "License-File: LICENSE" not in metadata:
        raise ValueError(
            f"{path.name} is missing the expected License-File: LICENSE metadata field."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dist_dir",
        nargs="?",
        type=Path,
        default=Path("dist"),
        help="Directory containing built wheel and source distribution artifacts.",
    )
    args = parser.parse_args()
    with Path("pyproject.toml").open("rb") as pyproject_file:
        project = tomllib.load(pyproject_file)["project"]
    if project.get("license-files") != ["LICENSE"]:
        raise SystemExit('pyproject.toml must include license-files = ["LICENSE"].')
    distribution_prefix = str(project["name"]).replace("-", "_")
    version = str(project["version"])

    artifacts = sorted(
        path
        for path in args.dist_dir.iterdir()
        if (
            path.name.startswith(f"{distribution_prefix}-{version}")
            and (path.suffix == ".whl" or path.suffixes[-2:] == [".tar", ".gz"])
        )
    )
    if not artifacts:
        raise SystemExit(
            f"No package artifacts for {project['name']} {version} found in {args.dist_dir}. "
            "Run uv build first."
        )
    artifact_kinds = {"wheel" if path.suffix == ".whl" else "sdist" for path in artifacts}
    if artifact_kinds != {"wheel", "sdist"}:
        raise SystemExit(
            f"Expected both wheel and sdist artifacts for {project['name']} {version}; "
            f"found {', '.join(sorted(artifact_kinds))}."
        )

    for artifact in artifacts:
        _validate_metadata(artifact, _metadata_for(artifact), project["license"]["text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
