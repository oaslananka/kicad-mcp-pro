"""Generate and verify release evidence for Python distribution artifacts."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import time
import tomllib
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

PYPI_ENDPOINTS = {
    "pypi": "https://pypi.org/pypi/{name}/{version}/json",
    "testpypi": "https://test.pypi.org/pypi/{name}/{version}/json",
}
PYPI_INTEGRITY_ENDPOINTS = {
    "pypi": "https://pypi.org/integrity/{name}/{version}/{filename}/provenance",
    "testpypi": "https://test.pypi.org/integrity/{name}/{version}/{filename}/provenance",
}
PYPI_PUBLISH_ATTESTATION = "https://docs.pypi.org/attestations/publish/v1"
DEFAULT_PYPI_RETRIES = 18
DEFAULT_PYPI_RETRY_DELAY = 10.0


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest for one artifact."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_project(pyproject_path: Path) -> dict[str, Any]:
    """Load project metadata from pyproject.toml."""
    with pyproject_path.open("rb") as handle:
        project = tomllib.load(handle)["project"]
    return cast(dict[str, Any], project)


def _artifact_paths(dist_dir: Path, project: dict[str, Any]) -> list[Path]:
    """Find the wheel and source distribution for the project version."""
    prefix = str(project["name"]).replace("-", "_")
    version = str(project["version"])
    artifacts = sorted(
        path
        for path in dist_dir.iterdir()
        if path.name.startswith(f"{prefix}-{version}")
        and (path.suffix == ".whl" or path.suffixes[-2:] == [".tar", ".gz"])
    )
    kinds = {"wheel" if path.suffix == ".whl" else "sdist" for path in artifacts}
    if kinds != {"wheel", "sdist"}:
        raise SystemExit(f"Expected wheel and sdist in {dist_dir} for {project['name']} {version}.")
    return artifacts


def _dependency_name(requirement: str) -> str:
    """Extract a package name from a PEP 508 dependency string."""
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
    if match is None:
        raise ValueError(f"Could not parse dependency name from {requirement!r}.")
    return match.group(1).replace("_", "-")


def _bom_ref(name: str, version: str) -> str:
    """Create a deterministic CycloneDX component reference."""
    return f"pkg:pypi/{name}@{version}"


def _cyclonedx_sbom(project: dict[str, Any], artifacts: list[Path]) -> dict[str, Any]:
    """Build a minimal CycloneDX SBOM from pyproject metadata."""
    name = str(project["name"])
    version = str(project["version"])
    dependency_components = [
        {
            "type": "library",
            "name": _dependency_name(dependency),
            "purl": f"pkg:pypi/{_dependency_name(dependency)}",
        }
        for dependency in project.get("dependencies", [])
    ]
    subject = "|".join(f"{path.name}:{_sha256(path)}" for path in artifacts)
    serial = uuid.uuid5(uuid.NAMESPACE_URL, f"{name}:{version}:{subject}")
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": name,
                "version": version,
                "bom-ref": _bom_ref(name, version),
            }
        },
        "components": dependency_components,
    }


def _write_checksum_file(artifacts: list[Path], output_dir: Path) -> Path:
    """Write SHA256SUMS.txt for release artifacts."""
    checksum_path = output_dir / "SHA256SUMS.txt"
    lines = [f"{_sha256(path)}  {path.name}" for path in artifacts]
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return checksum_path


def _read_checksums(checksum_file: Path) -> dict[str, str]:
    """Read a SHA256SUMS file into a filename-to-digest mapping."""
    checksums: dict[str, str] = {}
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, filename = line.split(maxsplit=1)
        checksums[filename.strip()] = digest.strip()
    return checksums


def _write_evidence(
    project: dict[str, Any], artifacts: list[Path], output_dir: Path, checksum_path: Path
) -> None:
    """Write machine-readable release evidence metadata."""
    evidence = {
        "product": "kicad-mcp-pro",
        "surface": "python",
        "package": project["name"],
        "version": project["version"],
        "checksums": checksum_path.name,
        "sbom": "sbom.cdx.json",
        "artifacts": [
            {"name": path.name, "sha256": _sha256(path), "size": path.stat().st_size}
            for path in artifacts
        ],
    }
    (output_dir / "release-evidence.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )


def generate(dist_dir: Path, output_dir: Path, pyproject_path: Path) -> None:
    """Generate checksums, SBOM, and evidence JSON."""
    project = _read_project(pyproject_path)
    artifacts = _artifact_paths(dist_dir, project)
    output_dir.mkdir(parents=True, exist_ok=True)
    checksum_path = _write_checksum_file(artifacts, output_dir)
    sbom = _cyclonedx_sbom(project, artifacts)
    (output_dir / "sbom.cdx.json").write_text(json.dumps(sbom, indent=2) + "\n", encoding="utf-8")
    _write_evidence(project, artifacts, output_dir, checksum_path)


def verify_local(checksum_file: Path, artifact_dir: Path) -> None:
    """Verify local artifacts against SHA256SUMS.txt."""
    failures = []
    for filename, expected in _read_checksums(checksum_file).items():
        artifact = artifact_dir / filename
        if not artifact.exists():
            failures.append(f"missing artifact: {artifact}")
        elif _sha256(artifact) != expected:
            failures.append(f"sha256 mismatch: {artifact}")
    if failures:
        raise SystemExit("Release evidence verification failed:\n- " + "\n- ".join(failures))


def _published_pypi_digests(repository: str, package: str, version: str) -> dict[str, str]:
    """Read published artifact digests from PyPI or TestPyPI."""
    url = PYPI_ENDPOINTS[repository].format(name=package, version=version)
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    return {
        str(item["filename"]): str(item["digests"]["sha256"])
        for item in payload.get("urls", [])
        if "digests" in item and "sha256" in item["digests"]
    }


def _pypi_digest_failures(expected: dict[str, str], published: dict[str, str]) -> list[str]:
    """Describe release artifacts that do not match published PyPI digests."""
    return [
        f"{filename}: expected {digest}, published {published.get(filename, '<missing>')}"
        for filename, digest in expected.items()
        if published.get(filename) != digest
    ]


def verify_pypi(
    repository: str,
    package: str,
    version: str,
    checksum_file: Path,
    retries: int = DEFAULT_PYPI_RETRIES,
    retry_delay: float = DEFAULT_PYPI_RETRY_DELAY,
) -> None:
    """Verify PyPI or TestPyPI published artifact digests."""
    expected = _read_checksums(checksum_file)
    last_error = "published metadata did not match release checksums"
    for attempt in range(1, retries + 1):
        try:
            failures = _pypi_digest_failures(
                expected, _published_pypi_digests(repository, package, version)
            )
            if not failures:
                return
            last_error = "\n- ".join(failures)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        if attempt < retries:
            time.sleep(retry_delay)
    raise SystemExit("Published PyPI digest verification failed:\n- " + last_error)


def _published_pypi_provenance(
    repository: str, package: str, version: str, filename: str
) -> dict[str, Any]:
    """Read one artifact's PEP 740 provenance from the PyPI Integrity API."""
    url = PYPI_INTEGRITY_ENDPOINTS[repository].format(
        name=quote(package, safe=""),
        version=quote(version, safe=""),
        filename=quote(filename, safe=""),
    )
    request = urllib.request.Request(  # noqa: S310
        url,
        headers={"Accept": "application/vnd.pypi.integrity.v1+json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected PyPI provenance payload for {filename}.")
    return payload


def _decode_attestation_statement(attestation: dict[str, Any]) -> dict[str, Any] | None:
    """Decode an in-toto statement embedded in a PyPI attestation envelope."""
    envelope = attestation.get("envelope")
    if not isinstance(envelope, dict) or not isinstance(envelope.get("statement"), str):
        return None
    decoded = base64.b64decode(envelope["statement"], validate=True)
    statement = json.loads(decoded.decode("utf-8"))
    return statement if isinstance(statement, dict) else None


def _provenance_failure(
    provenance: dict[str, Any],
    *,
    filename: str,
    digest: str,
    publisher_repository: str,
    publisher_workflow: str,
    publisher_environment: str,
) -> str | None:
    """Return why provenance does not match the required Trusted Publisher identity."""
    bundles = provenance.get("attestation_bundles")
    if not isinstance(bundles, list) or not bundles:
        return f"{filename}: no attestation bundles"
    for bundle in bundles:
        if not isinstance(bundle, dict):
            continue
        publisher = bundle.get("publisher")
        if not isinstance(publisher, dict):
            continue
        if (
            publisher.get("kind") != "GitHub"
            or publisher.get("repository") != publisher_repository
            or publisher.get("workflow") != publisher_workflow
            or publisher.get("environment") != publisher_environment
        ):
            continue
        attestations = bundle.get("attestations")
        if not isinstance(attestations, list):
            continue
        for attestation in attestations:
            if not isinstance(attestation, dict):
                continue
            statement = _decode_attestation_statement(attestation)
            if statement is None or statement.get("predicateType") != PYPI_PUBLISH_ATTESTATION:
                continue
            subjects = statement.get("subject")
            if not isinstance(subjects, list):
                continue
            for subject in subjects:
                if not isinstance(subject, dict) or subject.get("name") != filename:
                    continue
                subject_digest = subject.get("digest")
                if isinstance(subject_digest, dict) and subject_digest.get("sha256") == digest:
                    return None
    return (
        f"{filename}: no publish attestation matched GitHub publisher "
        f"{publisher_repository}/{publisher_workflow} environment={publisher_environment}"
    )


def _cryptographic_provenance_failure(
    provenance_payload: dict[str, Any],
    *,
    artifact_path: Path,
    publisher_repository: str,
    publisher_workflow: str,
    publisher_environment: str,
) -> str | None:
    """Cryptographically verify a local artifact against PyPI provenance."""
    try:
        from pypi_attestations import Distribution, GitHubPublisher, Provenance
    except ImportError:
        return "pypi-attestations is required for cryptographic provenance verification"

    publisher = GitHubPublisher(
        repository=publisher_repository,
        workflow=publisher_workflow,
        environment=publisher_environment,
    )
    try:
        provenance = Provenance.model_validate(provenance_payload)
        distribution = Distribution.from_file(artifact_path)
    except Exception as exc:
        return f"{artifact_path.name}: invalid provenance or artifact: {exc}"

    matching_bundles = [
        bundle for bundle in provenance.attestation_bundles if bundle.publisher == publisher
    ]
    if not matching_bundles:
        return f"{artifact_path.name}: no cryptographic bundle matched the expected publisher"

    failures: list[str] = []
    for bundle in matching_bundles:
        for attestation in bundle.attestations:
            try:
                predicate_type, _predicate = attestation.verify(publisher, distribution)
            except Exception as exc:
                failures.append(str(exc))
                continue
            if predicate_type == PYPI_PUBLISH_ATTESTATION:
                return None
    detail = "; ".join(failures) if failures else "no PyPI publish attestation was present"
    return f"{artifact_path.name}: cryptographic provenance verification failed: {detail}"


def verify_pypi_provenance(
    repository: str,
    package: str,
    version: str,
    checksum_file: Path,
    publisher_repository: str,
    publisher_workflow: str,
    publisher_environment: str,
    artifact_dir: Path | None = None,
    retries: int = DEFAULT_PYPI_RETRIES,
    retry_delay: float = DEFAULT_PYPI_RETRY_DELAY,
) -> None:
    """Verify PEP 740 metadata, identity, and optional cryptographic provenance."""
    expected = _read_checksums(checksum_file)
    last_errors = ["PyPI provenance was not available"]
    for attempt in range(1, retries + 1):
        errors: list[str] = []
        try:
            for filename, digest in expected.items():
                provenance_payload = _published_pypi_provenance(
                    repository, package, version, filename
                )
                failure = _provenance_failure(
                    provenance_payload,
                    filename=filename,
                    digest=digest,
                    publisher_repository=publisher_repository,
                    publisher_workflow=publisher_workflow,
                    publisher_environment=publisher_environment,
                )
                if failure:
                    errors.append(failure)
                    continue
                if artifact_dir is not None:
                    artifact_path = artifact_dir / filename
                    if not artifact_path.is_file():
                        errors.append(f"{filename}: local artifact is missing from {artifact_dir}")
                        continue
                    crypto_failure = _cryptographic_provenance_failure(
                        provenance_payload,
                        artifact_path=artifact_path,
                        publisher_repository=publisher_repository,
                        publisher_workflow=publisher_workflow,
                        publisher_environment=publisher_environment,
                    )
                    if crypto_failure:
                        errors.append(crypto_failure)
        except (
            OSError,
            ValueError,
            urllib.error.URLError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            binascii.Error,
        ) as exc:
            errors = [str(exc)]
        if not errors:
            return
        last_errors = errors
        if attempt < retries:
            time.sleep(retry_delay)
    raise SystemExit(
        "Published PyPI provenance verification failed:\n- " + "\n- ".join(last_errors)
    )


def main() -> int:
    """Run the release evidence CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    generate_parser.add_argument("--output", type=Path, default=Path("release-evidence"))
    generate_parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))

    local_parser = subparsers.add_parser("verify-local")
    local_parser.add_argument("--checksums", type=Path, required=True)
    local_parser.add_argument("--artifacts", type=Path, required=True)

    pypi_parser = subparsers.add_parser("verify-pypi")
    pypi_parser.add_argument("--repository", choices=sorted(PYPI_ENDPOINTS), required=True)
    pypi_parser.add_argument("--package", required=True)
    pypi_parser.add_argument("--version", required=True)
    pypi_parser.add_argument("--checksums", type=Path, required=True)
    pypi_parser.add_argument("--retries", type=int, default=DEFAULT_PYPI_RETRIES)
    pypi_parser.add_argument("--retry-delay", type=float, default=DEFAULT_PYPI_RETRY_DELAY)

    provenance_parser = subparsers.add_parser("verify-pypi-provenance")
    provenance_parser.add_argument("--repository", choices=sorted(PYPI_ENDPOINTS), required=True)
    provenance_parser.add_argument("--package", required=True)
    provenance_parser.add_argument("--version", required=True)
    provenance_parser.add_argument("--checksums", type=Path, required=True)
    provenance_parser.add_argument("--publisher-repository", required=True)
    provenance_parser.add_argument("--publisher-workflow", required=True)
    provenance_parser.add_argument("--publisher-environment", required=True)
    provenance_parser.add_argument("--artifacts", type=Path)
    provenance_parser.add_argument("--retries", type=int, default=DEFAULT_PYPI_RETRIES)
    provenance_parser.add_argument("--retry-delay", type=float, default=DEFAULT_PYPI_RETRY_DELAY)

    args = parser.parse_args()
    if args.command == "generate":
        generate(args.dist_dir, args.output, args.pyproject)
    elif args.command == "verify-local":
        verify_local(args.checksums, args.artifacts)
    elif args.command == "verify-pypi":
        verify_pypi(
            args.repository,
            args.package,
            args.version,
            args.checksums,
            retries=args.retries,
            retry_delay=args.retry_delay,
        )
    elif args.command == "verify-pypi-provenance":
        verify_pypi_provenance(
            args.repository,
            args.package,
            args.version,
            args.checksums,
            args.publisher_repository,
            args.publisher_workflow,
            args.publisher_environment,
            artifact_dir=args.artifacts,
            retries=args.retries,
            retry_delay=args.retry_delay,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
