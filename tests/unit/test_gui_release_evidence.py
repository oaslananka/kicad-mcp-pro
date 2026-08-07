from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECKSUM_NAME = "kicad-mcp-pro-gui-SHA256SUMS.txt"
SBOM_NAME = "kicad-mcp-pro-gui-sbom.cdx.json"
EVIDENCE_NAME = "kicad-mcp-pro-gui-release-evidence.json"


def _load_script() -> ModuleType:
    path = ROOT / "scripts" / "generate_gui_release_evidence.py"
    assert path.is_file(), "GUI release evidence script must exist"
    spec = importlib.util.spec_from_file_location("generate_gui_release_evidence", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_cargo_lock(path: Path) -> None:
    path.write_text(
        """
version = 3

[[package]]
name = "kicad-mcp-pro"
version = "1.2.3"
dependencies = [
 "serde 1.0.0",
 "tauri 2.11.5",
]

[[package]]
name = "serde"
version = "1.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

[[package]]
name = "tauri"
version = "2.11.5"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
dependencies = ["serde 1.0.0"]
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_installers(artifact_dir: Path) -> list[Path]:
    artifact_dir.mkdir(parents=True)
    artifacts = [
        artifact_dir / "linux_kicad-mcp-pro_1.2.3_amd64.deb",
        artifact_dir / "windows_kicad-mcp-pro_1.2.3_x64.msi",
        artifact_dir / "macos_kicad-mcp-pro_1.2.3_aarch64.dmg",
    ]
    for index, artifact in enumerate(artifacts, start=1):
        artifact.write_bytes(f"installer-{index}".encode())
    return artifacts


def _generate_fixture(tmp_path: Path):
    module = _load_script()
    artifact_dir = tmp_path / "release-assets"
    output_dir = tmp_path / "release-evidence"
    cargo_lock = tmp_path / "Cargo.lock"
    installers = _write_installers(artifact_dir)
    _write_cargo_lock(cargo_lock)
    module.generate(
        artifact_dir=artifact_dir,
        output_dir=output_dir,
        cargo_lock=cargo_lock,
        source_commit="a" * 40,
        release_tag="kicad-mcp-gui-v1.2.3",
    )
    return module, artifact_dir, output_dir, installers


def test_generate_gui_release_evidence_writes_exact_inventory_checksums_and_cargo_sbom(
    tmp_path: Path,
) -> None:
    _module, _artifact_dir, output_dir, installers = _generate_fixture(tmp_path)

    checksums = (output_dir / CHECKSUM_NAME).read_text(encoding="utf-8").splitlines()
    evidence = json.loads((output_dir / EVIDENCE_NAME).read_text(encoding="utf-8"))
    sbom = json.loads((output_dir / SBOM_NAME).read_text(encoding="utf-8"))

    assert len(checksums) == len(installers)
    assert {line.split(maxsplit=1)[1].strip() for line in checksums} == {
        path.name for path in installers
    }
    assert evidence["schemaVersion"] == 1
    assert evidence["surface"] == "desktop"
    assert evidence["releaseTag"] == "kicad-mcp-gui-v1.2.3"
    assert evidence["sourceCommit"] == "a" * 40
    assert {artifact["platform"] for artifact in evidence["artifacts"]} == {
        "linux",
        "windows",
        "macos",
    }
    assert all(len(artifact["sha256"]) == 64 for artifact in evidence["artifacts"])
    assert evidence["signing"] == {
        "linux": {"packageSigning": "unsigned"},
        "windows": {"authenticode": "unsigned"},
        "macos": {"codeSigning": "unsigned", "notarization": "not-notarized"},
    }
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.6"
    assert sbom["metadata"]["component"]["name"] == "kicad-mcp-pro"
    assert {component["name"] for component in sbom["components"]} == {"serde", "tauri"}
    dependency_graph = {entry["ref"]: set(entry["dependsOn"]) for entry in sbom["dependencies"]}
    assert dependency_graph["pkg:cargo/kicad-mcp-pro@1.2.3"] == {
        "pkg:cargo/serde@1.0.0",
        "pkg:cargo/tauri@2.11.5",
    }
    assert dependency_graph["pkg:cargo/tauri@2.11.5"] == {"pkg:cargo/serde@1.0.0"}


def test_generate_gui_release_evidence_rejects_missing_platform(tmp_path: Path) -> None:
    module = _load_script()
    artifact_dir = tmp_path / "release-assets"
    output_dir = tmp_path / "release-evidence"
    cargo_lock = tmp_path / "Cargo.lock"
    artifact_dir.mkdir()
    (artifact_dir / "linux_app.deb").write_bytes(b"linux")
    (artifact_dir / "windows_app.msi").write_bytes(b"windows")
    _write_cargo_lock(cargo_lock)

    with pytest.raises(SystemExit, match="missing required installer platform: macos"):
        module.generate(
            artifact_dir=artifact_dir,
            output_dir=output_dir,
            cargo_lock=cargo_lock,
            source_commit="b" * 40,
            release_tag="kicad-mcp-gui-v1.2.3",
        )


def test_verify_published_rejects_tampered_installer(tmp_path: Path) -> None:
    module, artifact_dir, output_dir, installers = _generate_fixture(tmp_path)
    published = tmp_path / "published"
    published.mkdir()
    for path in installers:
        shutil.copy2(path, published / path.name)
    for name in (CHECKSUM_NAME, SBOM_NAME, EVIDENCE_NAME):
        shutil.copy2(output_dir / name, published / name)
    (published / installers[0].name).write_bytes(b"tampered")

    with pytest.raises(SystemExit, match="sha256 mismatch"):
        module.verify_published(published, published / EVIDENCE_NAME)


def test_verify_published_rejects_missing_and_extra_assets(tmp_path: Path) -> None:
    module, artifact_dir, output_dir, installers = _generate_fixture(tmp_path)
    published = tmp_path / "published"
    published.mkdir()
    for path in installers:
        shutil.copy2(path, published / path.name)
    for name in (CHECKSUM_NAME, SBOM_NAME, EVIDENCE_NAME):
        shutil.copy2(output_dir / name, published / name)

    module.verify_published(published, published / EVIDENCE_NAME)

    (published / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(SystemExit, match="unexpected published asset"):
        module.verify_published(published, published / EVIDENCE_NAME)
    (published / "unexpected.txt").unlink()

    (published / installers[-1].name).unlink()
    with pytest.raises(SystemExit, match="missing published asset"):
        module.verify_published(published, published / EVIDENCE_NAME)


def test_gui_release_workflow_attests_and_verifies_published_installer_inventory() -> None:
    workflow = (ROOT / ".github" / "workflows" / "gui-release.yml").read_text(encoding="utf-8")
    policy = json.loads((ROOT / ".github" / "actions-policy.json").read_text(encoding="utf-8"))

    assert "scripts/generate_gui_release_evidence.py generate" in workflow
    assert "scripts/generate_gui_release_evidence.py verify-local" in workflow
    assert "scripts/generate_gui_release_evidence.py verify-published" in workflow
    assert "actions/attest@59d89421af93a897026c735860bf21b6eb4f7b26" in workflow
    assert f"subject-checksums: release-evidence/gui/{CHECKSUM_NAME}" in workflow
    assert f"sbom-path: release-evidence/gui/{SBOM_NAME}" in workflow
    assert "attestations: write" in workflow
    assert "artifact-metadata: write" in workflow
    assert "id-token: write" in workflow
    assert 'SOURCE_COMMIT="$(git rev-parse HEAD)"' in workflow
    assert 'gh release download "$TAG"' in workflow
    assert (
        "ref: ${{ github.event_name == 'workflow_dispatch' && inputs.tag || github.ref }}"
        in workflow
    )
    assert policy["workflow_write_permissions"]["gui-release.yml"]["create-release"] == [
        "artifact-metadata",
        "attestations",
        "contents",
        "id-token",
    ]


def test_verify_local_accepts_generated_inventory_and_rejects_tamper(tmp_path: Path) -> None:
    module, artifact_dir, output_dir, installers = _generate_fixture(tmp_path)

    module.verify_local(artifact_dir, output_dir)

    installers[1].write_bytes(b"tampered-after-evidence")
    with pytest.raises(SystemExit, match="sha256 mismatch"):
        module.verify_local(artifact_dir, output_dir)


def test_cli_verify_local_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    module, artifact_dir, output_dir, _installers = _generate_fixture(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_gui_release_evidence.py",
            "verify-local",
            "--artifact-dir",
            str(artifact_dir),
            "--evidence-dir",
            str(output_dir),
        ],
    )

    assert module.main() == 0


def test_cli_verify_published_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    module, artifact_dir, output_dir, installers = _generate_fixture(tmp_path)
    published = tmp_path / "published"
    published.mkdir()
    for path in installers:
        shutil.copy2(path, published / path.name)
    for name in (CHECKSUM_NAME, SBOM_NAME, EVIDENCE_NAME):
        shutil.copy2(output_dir / name, published / name)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_gui_release_evidence.py",
            "verify-published",
            "--published-dir",
            str(published),
            "--evidence",
            str(published / EVIDENCE_NAME),
        ],
    )

    assert module.main() == 0


def test_generate_gui_release_evidence_rejects_empty_installer(tmp_path: Path) -> None:
    module = _load_script()
    artifact_dir = tmp_path / "release-assets"
    output_dir = tmp_path / "release-evidence"
    cargo_lock = tmp_path / "Cargo.lock"
    installers = _write_installers(artifact_dir)
    installers[0].write_bytes(b"")
    _write_cargo_lock(cargo_lock)

    with pytest.raises(SystemExit, match="installer is empty"):
        module.generate(
            artifact_dir=artifact_dir,
            output_dir=output_dir,
            cargo_lock=cargo_lock,
            source_commit="c" * 40,
            release_tag="kicad-mcp-gui-v1.2.3",
        )


def test_generate_gui_release_evidence_rejects_unsupported_artifact(tmp_path: Path) -> None:
    module = _load_script()
    artifact_dir = tmp_path / "release-assets"
    output_dir = tmp_path / "release-evidence"
    cargo_lock = tmp_path / "Cargo.lock"
    _write_installers(artifact_dir)
    (artifact_dir / "internal-bundle.zip").write_bytes(b"not-a-public-installer")
    _write_cargo_lock(cargo_lock)

    with pytest.raises(SystemExit, match="unsupported installer artifact"):
        module.generate(
            artifact_dir=artifact_dir,
            output_dir=output_dir,
            cargo_lock=cargo_lock,
            source_commit="d" * 40,
            release_tag="kicad-mcp-gui-v1.2.3",
        )
