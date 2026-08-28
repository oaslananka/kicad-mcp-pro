"""Deterministic KiCad Plugin and Content Manager packaging contract."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tomllib
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_kicad_pcm.py"
EXPECTED_MEMBERS = {
    "metadata.json",
    "plugins/__init__.py",
    "plugins/compatibility.json",
    "plugins/context.py",
    "plugins/kicad_mcp_companion.py",
    "resources/icon.png",
}


def _load_builder() -> ModuleType:
    assert SCRIPT.is_file(), "issue #731 requires scripts/build_kicad_pcm.py"
    spec = importlib.util.spec_from_file_location("build_kicad_pcm", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def test_pcm_builder_exists() -> None:
    assert SCRIPT.is_file()


def test_pcm_archive_has_exact_reviewed_structure_and_metadata(tmp_path: Path) -> None:
    builder = _load_builder()
    result = builder.build_pcm(ROOT, tmp_path)

    with zipfile.ZipFile(result.artifact) as archive:
        assert set(archive.namelist()) == EXPECTED_MEMBERS
        metadata = json.loads(archive.read("metadata.json"))
        compatibility = json.loads(archive.read("plugins/compatibility.json"))
        icon = archive.read("resources/icon.png")
        for info in archive.infolist():
            assert not info.filename.startswith(("/", "\\"))
            assert ".." not in Path(info.filename).parts
            assert (info.external_attr >> 16) & 0o170000 != 0o120000

    assert metadata["$schema"] == "https://go.kicad.org/pcm/schemas/v2"
    assert metadata["identifier"] == "com.github.oaslananka.kicad-mcp-pro"
    assert metadata["type"] == "plugin"
    assert metadata["license"] == "MIT"
    assert metadata["author"]["name"] == "Osman Aslan"
    assert metadata["resources"]["homepage"] == "https://github.com/oaslananka/kicad-mcp-pro"
    assert len(metadata["versions"]) == 1
    version = metadata["versions"][0]
    assert version == {
        "version": _project_version(),
        "status": "stable",
        "kicad_version": "10.0",
        "runtime": "swig",
    }
    assert not any(key.startswith("download_") for key in version)
    assert compatibility["schema_version"] == "kicad-mcp-companion-compat.v1"
    assert compatibility["plugin_version"] == _project_version()
    major, minor, _patch = map(int, _project_version().split("."))
    assert compatibility["backend"] == {
        "minimum": f"{major}.{minor}.0",
        "maximum_exclusive": f"{major}.{minor + 1}.0",
    }
    assert compatibility["kicad"] == {"minimum": "10.0", "runtime": "swig"}
    assert icon == (ROOT / "docs" / "assets" / "icon-64.png").read_bytes()


def test_pcm_build_is_byte_reproducible_and_evidence_matches(tmp_path: Path) -> None:
    builder = _load_builder()
    first = builder.build_pcm(ROOT, tmp_path / "first")
    second = builder.build_pcm(ROOT, tmp_path / "second")

    assert first.artifact.name == second.artifact.name
    assert first.artifact.read_bytes() == second.artifact.read_bytes()
    digest = hashlib.sha256(first.artifact.read_bytes()).hexdigest()
    evidence = json.loads(first.evidence.read_text(encoding="utf-8"))
    assert evidence == {
        "schema_version": "kicad-pcm-release-evidence.v1",
        "package_identifier": "com.github.oaslananka.kicad-mcp-pro",
        "version": _project_version(),
        "artifact": first.artifact.name,
        "sha256": digest,
        "download_size": first.artifact.stat().st_size,
        "install_size": first.install_size,
        "runtime": "swig",
        "minimum_kicad_version": "10.0",
    }
    assert first.checksums.read_text(encoding="utf-8") == f"{digest}  {first.artifact.name}\n"


def test_pcm_metadata_base_is_versionless_and_release_owned() -> None:
    base = json.loads((ROOT / "packaging" / "kicad-pcm" / "metadata-base.json").read_text())
    assert base["identifier"] == "com.github.oaslananka.kicad-mcp-pro"
    assert "versions" not in base
    assert base["resources"]["documentation"].startswith("https://oaslananka.github.io/")


def test_companion_context_vendored_copy_matches_canonical_source() -> None:
    canonical = ROOT / "src" / "kicad_mcp" / "companion" / "context.py"
    vendored = ROOT / "packages" / "kicad-plugin" / "context.py"

    assert vendored.read_bytes() == canonical.read_bytes()


def test_pcm_builder_rejects_external_output_before_filesystem_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = _load_builder()
    external_output = ROOT.parent / "kicad-mcp-pro-unsafe-output"

    def fail_if_mkdir_is_reached(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("output directory write was reached before path validation")

    monkeypatch.setattr(Path, "mkdir", fail_if_mkdir_is_reached)

    with pytest.raises(ValueError, match="approved output roots"):
        builder.build_pcm(ROOT, external_output)
