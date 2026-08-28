"""Build and verify the deterministic KiCad PCM companion package."""

from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
import zipfile
from pathlib import Path
from typing import Any, NamedTuple, cast

PACKAGE_IDENTIFIER = "com.github.oaslananka.kicad-mcp-pro"
PCM_SCHEMA = "https://go.kicad.org/pcm/schemas/v2"
MINIMUM_KICAD_VERSION = "10.0"
PLUGIN_RUNTIME = "swig"
COMPATIBILITY_SCHEMA = "kicad-mcp-companion-compat.v1"
EVIDENCE_SCHEMA = "kicad-pcm-release-evidence.v1"
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_REGULAR_FILE_MODE = 0o100644


class BuildResult(NamedTuple):
    artifact: Path
    checksums: Path
    evidence: Path
    install_size: int


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return cast(dict[str, Any], payload)


def _project_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle).get("project", {})
    version = project.get("version")
    if not isinstance(version, str):
        raise ValueError("pyproject.toml project.version must be a string")
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"PCM packaging requires a numeric major.minor.patch version: {version!r}")
    return version


def _compatibility(version: str) -> dict[str, object]:
    major, minor, _patch = (int(part) for part in version.split("."))
    return {
        "schema_version": COMPATIBILITY_SCHEMA,
        "plugin_version": version,
        "backend": {
            "minimum": f"{major}.{minor}.0",
            "maximum_exclusive": f"{major}.{minor + 1}.0",
        },
        "kicad": {"minimum": MINIMUM_KICAD_VERSION, "runtime": PLUGIN_RUNTIME},
    }


def _metadata(root: Path, version: str) -> dict[str, Any]:
    base = _read_json(root / "packaging" / "kicad-pcm" / "metadata-base.json")
    if base.get("$schema") != PCM_SCHEMA:
        raise ValueError("PCM metadata base must use the KiCad v2 schema")
    if base.get("identifier") != PACKAGE_IDENTIFIER:
        raise ValueError("PCM package identifier does not match the reviewed identifier")
    if "versions" in base:
        raise ValueError(
            "PCM metadata base must be versionless; versions are generated from pyproject.toml"
        )
    metadata = dict(base)
    metadata["versions"] = [
        {
            "version": version,
            "status": "stable",
            "kicad_version": MINIMUM_KICAD_VERSION,
            "runtime": PLUGIN_RUNTIME,
        }
    ]
    return metadata


def _validate_icon(icon: bytes) -> None:
    if not icon.startswith(b"\x89PNG\r\n\x1a\n") or len(icon) < 24:
        raise ValueError("PCM icon must be a PNG")
    width = int.from_bytes(icon[16:20], "big")
    height = int.from_bytes(icon[20:24], "big")
    if (width, height) != (64, 64):
        raise ValueError(f"PCM icon must be 64x64 pixels, got {width}x{height}")


def _package_members(root: Path, version: str) -> dict[str, bytes]:
    plugin_root = root / "packages" / "kicad-plugin"
    members = {
        "metadata.json": (json.dumps(_metadata(root, version), indent=2) + "\n").encode(),
        "plugins/__init__.py": (plugin_root / "__init__.py").read_bytes(),
        "plugins/compatibility.json": (
            json.dumps(_compatibility(version), indent=2) + "\n"
        ).encode(),
        "plugins/context.py": (plugin_root / "context.py").read_bytes(),
        "plugins/kicad_mcp_companion.py": (plugin_root / "kicad_mcp_companion.py").read_bytes(),
        "resources/icon.png": (root / "docs" / "assets" / "icon-64.png").read_bytes(),
    }
    _validate_icon(members["resources/icon.png"])
    return members


def _write_deterministic_zip(path: Path, members: dict[str, bytes]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    install_size = 0
    with zipfile.ZipFile(
        path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for name in sorted(members):
            if name.startswith(("/", "\\")) or ".." in Path(name).parts:
                raise ValueError(f"Unsafe PCM archive member: {name!r}")
            content = members[name]
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = _REGULAR_FILE_MODE << 16
            archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
            install_size += len(content)
    return install_size


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_pcm(root: Path, output_dir: Path) -> BuildResult:
    """Build a deterministic PCM ZIP and local release evidence from repository source."""
    root = root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    version = _project_version(root)
    artifact = output_dir / f"kicad-mcp-pro-pcm-{version}.zip"
    install_size = _write_deterministic_zip(artifact, _package_members(root, version))
    digest = _sha256(artifact)
    checksums = output_dir / "kicad-mcp-pro-pcm-SHA256SUMS.txt"
    checksums.write_text(f"{digest}  {artifact.name}\n", encoding="utf-8")
    evidence = output_dir / "kicad-mcp-pro-pcm-release-evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "schema_version": EVIDENCE_SCHEMA,
                "package_identifier": PACKAGE_IDENTIFIER,
                "version": version,
                "artifact": artifact.name,
                "sha256": digest,
                "download_size": artifact.stat().st_size,
                "install_size": install_size,
                "runtime": PLUGIN_RUNTIME,
                "minimum_kicad_version": MINIMUM_KICAD_VERSION,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return BuildResult(artifact, checksums, evidence, install_size)


def verify_pcm(artifact: Path, checksums: Path) -> None:
    """Verify one local PCM artifact against its checksum manifest and package contract."""
    line = checksums.read_text(encoding="utf-8").strip()
    expected, filename = line.split(maxsplit=1)
    if filename != artifact.name or expected != _sha256(artifact):
        raise ValueError("PCM checksum verification failed")
    with zipfile.ZipFile(artifact) as archive:
        names = archive.namelist()
        expected_names = sorted(
            {
                "metadata.json",
                "plugins/__init__.py",
                "plugins/compatibility.json",
                "plugins/context.py",
                "plugins/kicad_mcp_companion.py",
                "resources/icon.png",
            }
        )
        if names != expected_names:
            raise ValueError(f"Unexpected PCM archive members: {names!r}")
        metadata = json.loads(archive.read("metadata.json"))
        if metadata.get("identifier") != PACKAGE_IDENTIFIER:
            raise ValueError("Unexpected PCM package identifier")
        versions = metadata.get("versions")
        if not isinstance(versions, list) or len(versions) != 1:
            raise ValueError("Internal PCM metadata must contain exactly one version")
        if any(str(key).startswith("download_") for key in versions[0]):
            raise ValueError("Internal PCM metadata must not contain download_* fields")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--verify", action="store_true", help="Verify the artifact after building it."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = build_pcm(args.root, args.output_dir)
    if args.verify:
        verify_pcm(result.artifact, result.checksums)
    print(result.artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
