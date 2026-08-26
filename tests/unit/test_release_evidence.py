from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace, TracebackType

import pytest

ROOT = Path(__file__).resolve().parents[2]


class _PypiResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _PypiResponse:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_release_evidence",
        ROOT / "scripts" / "generate_release_evidence.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generate_release_evidence_writes_checksums_and_sbom(tmp_path: Path) -> None:
    module = _load_script()
    pyproject = tmp_path / "pyproject.toml"
    dist = tmp_path / "dist"
    output = tmp_path / "release-evidence"
    dist.mkdir()
    pyproject.write_text(
        """
[project]
name = "kicad-mcp-pro"
version = "1.2.3"
dependencies = ["mcp>=1.27.1,<1.28", "typer>=0.12.0"]
""".strip(),
        encoding="utf-8",
    )
    (dist / "kicad_mcp_pro-1.2.3-py3-none-any.whl").write_bytes(b"wheel")
    (dist / "kicad_mcp_pro-1.2.3.tar.gz").write_bytes(b"sdist")

    module.generate(dist, output, pyproject)

    checksums = (output / "SHA256SUMS.txt").read_text(encoding="utf-8")
    sbom = json.loads((output / "sbom.cdx.json").read_text(encoding="utf-8"))
    evidence = json.loads((output / "release-evidence.json").read_text(encoding="utf-8"))
    assert "kicad_mcp_pro-1.2.3-py3-none-any.whl" in checksums
    assert sbom["bomFormat"] == "CycloneDX"
    assert {component["name"] for component in sbom["components"]} == {"mcp", "typer"}
    assert evidence["surface"] == "python"


def test_verify_local_rejects_checksum_mismatch(tmp_path: Path) -> None:
    module = _load_script()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "artifact.whl").write_text("changed", encoding="utf-8")
    checksums = tmp_path / "SHA256SUMS.txt"
    checksums.write_text(f"{'0' * 64}  artifact.whl\n", encoding="utf-8")

    try:
        module.verify_local(checksums, artifacts)
    except SystemExit as exc:
        assert "sha256 mismatch" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("verify_local should reject mismatched checksums")


def test_verify_local_rejects_checksum_path_traversal(tmp_path: Path) -> None:
    module = _load_script()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    outside = tmp_path / "outside.whl"
    outside.write_bytes(b"outside artifact")
    digest = hashlib.sha256(outside.read_bytes()).hexdigest()
    checksums = tmp_path / "SHA256SUMS.txt"
    checksums.write_text(f"{digest}  ../outside.whl\n", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact filename"):
        module.verify_local(checksums, artifacts)


def test_verify_local_rejects_checksum_windows_path_escape(tmp_path: Path) -> None:
    module = _load_script()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    checksums = tmp_path / "SHA256SUMS.txt"
    checksums.write_text(f"{'0' * 64}  ..\\outside.whl\n", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact filename"):
        module.verify_local(checksums, artifacts)


def test_verify_pypi_accepts_matching_published_digests(tmp_path: Path, monkeypatch) -> None:
    module = _load_script()
    checksums = tmp_path / "SHA256SUMS.txt"
    checksums.write_text(f"{'a' * 64}  artifact.whl\n", encoding="utf-8")

    payload = b'{"urls":[{"filename":"artifact.whl","digests":{"sha256":"' + b"a" * 64 + b'"}}]}'
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _PypiResponse(payload),
    )

    module.verify_pypi("pypi", "kicad-mcp-pro", "1.0.0", checksums, retries=1, retry_delay=0)


def test_verify_pypi_rejects_digest_mismatch(tmp_path: Path, monkeypatch) -> None:
    module = _load_script()
    checksums = tmp_path / "SHA256SUMS.txt"
    checksums.write_text(f"{'0' * 64}  artifact.whl\n", encoding="utf-8")

    payload = b'{"urls":[{"filename":"artifact.whl","digests":{"sha256":"' + b"1" * 64 + b'"}}]}'
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _PypiResponse(payload),
    )

    try:
        module.verify_pypi("pypi", "kicad-mcp-pro", "1.0.0", checksums, retries=1, retry_delay=0)
    except SystemExit as exc:
        assert "Published PyPI digest verification failed" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("verify_pypi should reject mismatched checksums")


def test_verify_pypi_default_retries_cover_registry_propagation(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    checksums = tmp_path / "SHA256SUMS.txt"
    checksums.write_text(f"{'a' * 64}  artifact.whl\n", encoding="utf-8")
    payload = b'{"urls":[{"filename":"artifact.whl","digests":{"sha256":"' + b"a" * 64 + b'"}}]}'
    attempts = 0

    def delayed_metadata(*_args: object, **_kwargs: object) -> _PypiResponse:
        nonlocal attempts
        attempts += 1
        if attempts <= 6:
            raise module.urllib.error.HTTPError("https://pypi.example", 404, "missing", {}, None)
        return _PypiResponse(payload)

    monkeypatch.setattr(module.urllib.request, "urlopen", delayed_metadata)
    monkeypatch.setattr(module.time, "sleep", lambda _delay: None)

    module.verify_pypi("pypi", "kicad-mcp-pro", "1.0.0", checksums)

    assert attempts == 7


def test_verify_pypi_retries_when_sdist_appears_after_wheel(tmp_path: Path, monkeypatch) -> None:
    module = _load_script()
    wheel_digest = "a" * 64
    sdist_digest = "b" * 64
    checksums = tmp_path / "SHA256SUMS.txt"
    checksums.write_text(
        f"{wheel_digest}  artifact.whl\n{sdist_digest}  artifact.tar.gz\n",
        encoding="utf-8",
    )
    attempts = 0

    def partially_visible_metadata(*_args: object, **_kwargs: object) -> _PypiResponse:
        nonlocal attempts
        attempts += 1
        urls = [
            {"filename": "artifact.whl", "digests": {"sha256": wheel_digest}},
        ]
        if attempts >= 3:
            urls.append({"filename": "artifact.tar.gz", "digests": {"sha256": sdist_digest}})
        return _PypiResponse(json.dumps({"urls": urls}).encode("utf-8"))

    monkeypatch.setattr(module.urllib.request, "urlopen", partially_visible_metadata)
    monkeypatch.setattr(module.time, "sleep", lambda _delay: None)

    module.verify_pypi(
        "pypi",
        "kicad-mcp-pro",
        "1.0.0",
        checksums,
        retries=3,
        retry_delay=0,
    )

    assert attempts == 3


def _provenance_payload(
    *, repository: str, environment: str | None, filename: str, digest: str
) -> bytes:
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": filename, "digest": {"sha256": digest}}],
        "predicateType": "https://docs.pypi.org/attestations/publish/v1",
        "predicate": None,
    }
    encoded = base64.b64encode(json.dumps(statement).encode("utf-8")).decode("ascii")
    return json.dumps(
        {
            "version": 1,
            "attestation_bundles": [
                {
                    "publisher": {
                        "kind": "GitHub",
                        "repository": repository,
                        "workflow": "publish-python.yml",
                        "environment": environment,
                    },
                    "attestations": [{"envelope": {"statement": encoded, "signature": "sig"}}],
                }
            ],
        }
    ).encode("utf-8")


def test_verify_pypi_provenance_accepts_expected_trusted_publisher(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    digest = "a" * 64
    checksums = tmp_path / "SHA256SUMS.txt"
    checksums.write_text(f"{digest}  artifact.whl\n", encoding="utf-8")
    payload = _provenance_payload(
        repository="oaslananka/kicad-mcp-pro",
        environment="pypi",
        filename="artifact.whl",
        digest=digest,
    )
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _PypiResponse(payload),
    )

    module.verify_pypi_provenance(
        "pypi",
        "kicad-mcp-pro",
        "1.0.0",
        checksums,
        "oaslananka/kicad-mcp-pro",
        "publish-python.yml",
        "pypi",
        retries=1,
        retry_delay=0,
    )


def test_verify_pypi_provenance_rejects_legacy_repository_identity(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    digest = "a" * 64
    checksums = tmp_path / "SHA256SUMS.txt"
    checksums.write_text(f"{digest}  artifact.whl\n", encoding="utf-8")
    payload = _provenance_payload(
        repository="oaslananka/kicad-mcp",
        environment=None,
        filename="artifact.whl",
        digest=digest,
    )
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _PypiResponse(payload),
    )

    try:
        module.verify_pypi_provenance(
            "pypi",
            "kicad-mcp-pro",
            "1.0.0",
            checksums,
            "oaslananka/kicad-mcp-pro",
            "publish-python.yml",
            "pypi",
            retries=1,
            retry_delay=0,
        )
    except SystemExit as exc:
        assert "no publish attestation matched" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("legacy Trusted Publisher identity must be rejected")


def test_verify_pypi_provenance_cryptographically_verifies_local_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    digest = "a" * 64
    artifact_dir = tmp_path / "dist"
    artifact_dir.mkdir()
    artifact = artifact_dir / "artifact.whl"
    artifact.write_bytes(b"artifact")
    checksums = tmp_path / "SHA256SUMS.txt"
    checksums.write_text(f"{digest}  {artifact.name}\n", encoding="utf-8")
    payload = _provenance_payload(
        repository="oaslananka/kicad-mcp-pro",
        environment="testpypi",
        filename=artifact.name,
        digest=digest,
    )
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _PypiResponse(payload),
    )

    verified: list[Path] = []

    class FakePublisher:
        def __init__(self, *, repository: str, workflow: str, environment: str) -> None:
            self.identity = (repository, workflow, environment)

        def __eq__(self, other: object) -> bool:
            return isinstance(other, FakePublisher) and self.identity == other.identity

    class FakeDistribution:
        @classmethod
        def from_file(cls, path: Path) -> Path:
            return path

    class FakeAttestation:
        def verify(self, publisher: FakePublisher, distribution: Path):
            assert publisher.identity == (
                "oaslananka/kicad-mcp-pro",
                "publish-python.yml",
                "testpypi",
            )
            verified.append(distribution)
            return module.PYPI_PUBLISH_ATTESTATION, None

    class FakeProvenance:
        @classmethod
        def model_validate(cls, _payload: object) -> SimpleNamespace:
            return SimpleNamespace(
                attestation_bundles=[
                    SimpleNamespace(
                        publisher=FakePublisher(
                            repository="oaslananka/kicad-mcp-pro",
                            workflow="publish-python.yml",
                            environment="testpypi",
                        ),
                        attestations=[FakeAttestation()],
                    )
                ]
            )

    fake_module = ModuleType("pypi_attestations")
    fake_module.Distribution = FakeDistribution
    fake_module.GitHubPublisher = FakePublisher
    fake_module.Provenance = FakeProvenance
    monkeypatch.setitem(sys.modules, "pypi_attestations", fake_module)

    module.verify_pypi_provenance(
        "testpypi",
        "kicad-mcp-pro",
        "1.0.0",
        checksums,
        "oaslananka/kicad-mcp-pro",
        "publish-python.yml",
        "testpypi",
        artifact_dir=artifact_dir,
        retries=1,
        retry_delay=0,
    )

    assert verified == [artifact]
