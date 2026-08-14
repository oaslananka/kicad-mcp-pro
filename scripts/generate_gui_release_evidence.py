"""Generate and verify integrity evidence for Tauri GUI release installers."""

from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
import uuid
from pathlib import Path
from typing import Any, cast

CHECKSUM_NAME = "kicad-mcp-pro-gui-SHA256SUMS.txt"
SBOM_NAME = "kicad-mcp-pro-gui-sbom.cdx.json"
EVIDENCE_NAME = "kicad-mcp-pro-gui-release-evidence.json"
REQUIRED_PLATFORMS = ("linux", "windows", "macos")
PLATFORM_SIGNING: dict[str, dict[str, str]] = {
    "linux": {"packageSigning": "unsigned"},
    "windows": {"authenticode": "unsigned"},
    "macos": {"codeSigning": "unsigned", "notarization": "not-notarized"},
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _platform_for(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in {".deb", ".rpm", ".appimage"}:
        return "linux"
    if suffix in {".msi", ".exe"}:
        return "windows"
    if suffix == ".dmg":
        return "macos"
    return None


def _installer_inventory(artifact_dir: Path) -> list[tuple[Path, str]]:
    files = sorted(
        (path for path in artifact_dir.iterdir() if path.is_file()),
        key=lambda item: item.name.lower(),
    )
    inventory: list[tuple[Path, str]] = []
    for path in files:
        platform = _platform_for(path)
        if platform is None:
            raise SystemExit(f"unsupported installer artifact: {path.name}")
        inventory.append((path, platform))
    if not inventory:
        raise SystemExit(f"No supported GUI installers found in {artifact_dir}.")
    for artifact, _platform in inventory:
        if artifact.stat().st_size == 0:
            raise SystemExit(f"installer is empty: {artifact.name}")
    present = {platform for _path, platform in inventory}
    for platform in REQUIRED_PLATFORMS:
        if platform not in present:
            raise SystemExit(f"missing required installer platform: {platform}")
    return inventory


def _read_cargo_lock(cargo_lock: Path) -> dict[str, Any]:
    with cargo_lock.open("rb") as handle:
        return cast(dict[str, Any], tomllib.load(handle))


def _bom_ref(package: dict[str, Any]) -> str:
    return f"pkg:cargo/{package['name']}@{package['version']}"


def _dependency_ref(
    dependency: str,
    packages_by_name: dict[str, list[dict[str, Any]]],
) -> str:
    parts = dependency.split()
    name = parts[0]
    candidates = packages_by_name.get(name, [])
    if len(parts) >= 2:
        version = parts[1]
        candidates = [package for package in candidates if str(package.get("version")) == version]
    if len(candidates) != 1:
        raise SystemExit(f"Could not resolve Cargo.lock dependency entry: {dependency}")
    return _bom_ref(candidates[0])


def _cargo_dependency_graph(packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    packages_by_name: dict[str, list[dict[str, Any]]] = {}
    for package in packages:
        packages_by_name.setdefault(str(package["name"]), []).append(package)

    graph: list[dict[str, Any]] = []
    for package in sorted(packages, key=lambda item: _bom_ref(item)):
        dependencies = package.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise SystemExit(f"Invalid Cargo.lock dependency list for {_bom_ref(package)}")
        graph.append(
            {
                "ref": _bom_ref(package),
                "dependsOn": sorted(
                    {
                        _dependency_ref(str(dependency), packages_by_name)
                        for dependency in dependencies
                    }
                ),
            }
        )
    return graph


def _cargo_sbom(cargo_lock: Path, inventory: list[tuple[Path, str]]) -> dict[str, Any]:
    payload = _read_cargo_lock(cargo_lock)
    packages = [package for package in payload.get("package", []) if isinstance(package, dict)]
    root = next(
        (
            package
            for package in packages
            if package.get("name") == "kicad-mcp-pro" and package.get("source") is None
        ),
        None,
    )
    if root is None:
        raise SystemExit(f"Cargo.lock has no kicad-mcp-pro root package: {cargo_lock}")

    components: list[dict[str, Any]] = []
    for package in sorted(
        (package for package in packages if package is not root),
        key=lambda item: (str(item.get("name", "")), str(item.get("version", ""))),
    ):
        name = str(package["name"])
        version = str(package["version"])
        component: dict[str, Any] = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": _bom_ref(package),
            "bom-ref": _bom_ref(package),
        }
        checksum = package.get("checksum")
        if isinstance(checksum, str) and checksum:
            component["hashes"] = [{"alg": "SHA-256", "content": checksum}]
        components.append(component)

    artifact_subject = "|".join(f"{path.name}:{_sha256(path)}" for path, _ in inventory)
    lock_digest = _sha256(cargo_lock)
    serial = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"kicad-mcp-pro-gui:{root['version']}:{lock_digest}:{artifact_subject}",
    )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": str(root["name"]),
                "version": str(root["version"]),
                "bom-ref": _bom_ref(root),
            }
        },
        "components": components,
        "dependencies": _cargo_dependency_graph(packages),
    }


def _write_checksums(inventory: list[tuple[Path, str]], output_dir: Path) -> Path:
    path = output_dir / CHECKSUM_NAME
    lines = [f"{_sha256(artifact)}  {artifact.name}" for artifact, _platform in inventory]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def generate(
    *,
    artifact_dir: Path,
    output_dir: Path,
    cargo_lock: Path,
    source_commit: str,
    release_tag: str,
) -> None:
    """Generate checksums, Cargo SBOM, and machine-readable GUI release evidence."""
    inventory = _installer_inventory(artifact_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_checksums(inventory, output_dir)
    sbom = _cargo_sbom(cargo_lock, inventory)
    (output_dir / SBOM_NAME).write_text(json.dumps(sbom, indent=2) + "\n", encoding="utf-8")
    evidence = {
        "schemaVersion": 1,
        "product": "kicad-mcp-pro",
        "surface": "desktop",
        "releaseTag": release_tag,
        "sourceCommit": source_commit,
        "checksums": CHECKSUM_NAME,
        "sbom": SBOM_NAME,
        "signing": PLATFORM_SIGNING,
        "artifacts": [
            {
                "name": path.name,
                "platform": platform,
                "sha256": _sha256(path),
                "size": path.stat().st_size,
            }
            for path, platform in inventory
        ],
    }
    (output_dir / EVIDENCE_NAME).write_text(
        json.dumps(evidence, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected JSON object: {path}")
    return cast(dict[str, Any], payload)


def _artifact_digests(evidence: dict[str, Any]) -> dict[str, str]:
    artifacts = evidence.get("artifacts")
    if not isinstance(artifacts, list):
        raise SystemExit("GUI release evidence has no artifact inventory.")
    digests: dict[str, str] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise SystemExit("GUI release evidence contains an invalid artifact entry.")
        name = artifact.get("name")
        digest = artifact.get("sha256")
        if not isinstance(name, str) or not isinstance(digest, str):
            raise SystemExit("GUI release evidence artifact is missing name or sha256.")
        digests[name] = digest
    return digests


def _read_checksums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, filename = line.split(maxsplit=1)
        checksums[filename.strip()] = digest.strip()
    return checksums


def verify_local(artifact_dir: Path, evidence_dir: Path) -> None:
    """Verify generated GUI evidence still matches the local installer inventory."""
    evidence_path = evidence_dir / EVIDENCE_NAME
    evidence = _read_json_object(evidence_path)
    digests = _artifact_digests(evidence)
    checksum_name = evidence.get("checksums")
    sbom_name = evidence.get("sbom")
    if not isinstance(checksum_name, str) or not isinstance(sbom_name, str):
        raise SystemExit("GUI release evidence is missing checksum or SBOM filenames.")

    actual_assets = {
        path.name
        for path in artifact_dir.iterdir()
        if path.is_file() and _platform_for(path) is not None
    }
    expected_assets = set(digests)
    missing = sorted(expected_assets - actual_assets)
    if missing:
        raise SystemExit(
            "GUI local inventory verification failed:\n- missing local asset: " + missing[0]
        )
    unexpected = sorted(actual_assets - expected_assets)
    if unexpected:
        raise SystemExit(
            "GUI local inventory verification failed:\n- unexpected local asset: " + unexpected[0]
        )

    checksums = _read_checksums(evidence_dir / checksum_name)
    if checksums != digests:
        raise SystemExit("GUI local checksum manifest does not match release evidence.")

    for filename, expected in digests.items():
        actual = _sha256(artifact_dir / filename)
        if actual != expected:
            raise SystemExit(
                f"GUI local inventory verification failed:\n- sha256 mismatch: {filename}"
            )

    _read_json_object(evidence_dir / sbom_name)


def verify_published(published_dir: Path, evidence_path: Path) -> None:
    """Verify the exact GitHub Release asset inventory and installer digests."""
    evidence = _read_json_object(evidence_path)
    digests = _artifact_digests(evidence)
    checksum_name = evidence.get("checksums")
    sbom_name = evidence.get("sbom")
    if not isinstance(checksum_name, str) or not isinstance(sbom_name, str):
        raise SystemExit("GUI release evidence is missing checksum or SBOM filenames.")

    expected_assets = set(digests) | {checksum_name, sbom_name, evidence_path.name}
    actual_assets = {path.name for path in published_dir.iterdir() if path.is_file()}
    missing = sorted(expected_assets - actual_assets)
    if missing:
        raise SystemExit(
            "GUI published inventory verification failed:\n- missing published asset: " + missing[0]
        )
    unexpected = sorted(actual_assets - expected_assets)
    if unexpected:
        raise SystemExit(
            "GUI published inventory verification failed:\n- unexpected published asset: "
            + unexpected[0]
        )

    checksums = _read_checksums(published_dir / checksum_name)
    if checksums != digests:
        raise SystemExit("GUI published checksum manifest does not match release evidence.")

    for filename, expected in digests.items():
        actual = _sha256(published_dir / filename)
        if actual != expected:
            raise SystemExit(
                f"GUI published inventory verification failed:\n- sha256 mismatch: {filename}"
            )

    _read_json_object(published_dir / sbom_name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--artifact-dir", type=Path, required=True)
    generate_parser.add_argument("--output-dir", type=Path, required=True)
    generate_parser.add_argument("--cargo-lock", type=Path, required=True)
    generate_parser.add_argument("--source-commit", required=True)
    generate_parser.add_argument("--release-tag", required=True)

    verify_local_parser = subparsers.add_parser("verify-local")
    verify_local_parser.add_argument("--artifact-dir", type=Path, required=True)
    verify_local_parser.add_argument("--evidence-dir", type=Path, required=True)

    verify_published_parser = subparsers.add_parser("verify-published")
    verify_published_parser.add_argument("--published-dir", type=Path, required=True)
    verify_published_parser.add_argument("--evidence", type=Path, required=True)

    args = parser.parse_args()

    if args.command == "generate":
        generate(
            artifact_dir=args.artifact_dir,
            output_dir=args.output_dir,
            cargo_lock=args.cargo_lock,
            source_commit=args.source_commit,
            release_tag=args.release_tag,
        )
    elif args.command == "verify-local":
        verify_local(args.artifact_dir, args.evidence_dir)
    elif args.command == "verify-published":
        verify_published(args.published_dir, args.evidence)
    else:
        raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    main()
