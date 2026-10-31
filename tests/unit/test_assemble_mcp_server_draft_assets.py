"""Offline, fail-closed assembly of GitHub Actions producer artifacts (#1179)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.assemble_mcp_server_draft_assets import assemble
from scripts.check_release_family_inventory import verify_family

TAG = "mcp-server-v4.5.0"
SOURCE = "a" * 40
VERSION = "4.5.0"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixture(tmp_path: Path) -> dict[str, object]:
    dirs = {key: tmp_path / key for key in ("python_dist", "python_evidence", "mcpb", "pcm")}
    for folder in dirs.values():
        folder.mkdir()
    py_artifacts = {
        f"kicad_mcp_pro-{VERSION}-py3-none-any.whl": b"wheel test bytes",
        f"kicad_mcp_pro-{VERSION}.tar.gz": b"sdist test bytes",
    }
    for name, data in py_artifacts.items():
        (dirs["python_dist"] / name).write_bytes(data)
    (dirs["python_evidence"] / "SHA256SUMS.txt").write_text(
        "".join(f"{_sha(data)}  {name}\n" for name, data in py_artifacts.items())
    )
    (dirs["python_evidence"] / "sbom.cdx.json").write_text('{"bomFormat":"CycloneDX"}')
    (dirs["python_evidence"] / "release-evidence.json").write_text(
        json.dumps(
            {
                "product": "kicad-mcp-pro",
                "surface": "python",
                "package": "kicad-mcp-pro",
                "version": VERSION,
                "checksums": "SHA256SUMS.txt",
                "sbom": "sbom.cdx.json",
                "artifacts": [
                    {"name": name, "sha256": _sha(data), "size": len(data)}
                    for name, data in sorted(py_artifacts.items())
                ],
            }
        )
    )
    for kind in ("mcpb", "pcm"):
        name = (
            f"kicad-mcp-pro-{VERSION}.mcpb"
            if kind == "mcpb"
            else f"kicad-mcp-pro-pcm-{VERSION}.zip"
        )
        payload = f"{kind} test bytes".encode()
        (dirs[kind] / name).write_bytes(payload)
        (dirs[kind] / f"kicad-mcp-pro-{kind}-SHA256SUMS.txt").write_text(
            f"{_sha(payload)}  {name}\n"
        )
        evidence = {
            "version": VERSION,
            "artifact": name,
            "sha256": _sha(payload),
        }
        if kind == "mcpb":
            evidence.update({"schemaVersion": 1, "sourceTag": TAG, "sourceCommit": SOURCE})
        else:
            evidence.update(
                {
                    "schema_version": "kicad-pcm-release-evidence.v1",
                    "package_identifier": "com.github.oaslananka.kicad-mcp-pro",
                    "download_size": len(payload),
                    "install_size": 100,
                    "runtime": "ipc",
                    "minimum_kicad_version": "10.0",
                }
            )
        (dirs[kind] / f"kicad-mcp-pro-{kind}-release-evidence.json").write_text(
            json.dumps(evidence)
        )
    return {"tag": TAG, "source_commit": SOURCE, **dirs, "output": tmp_path / "out"}


def test_assembles_all_eleven_roles_and_independently_rechecks_manifest(tmp_path: Path) -> None:
    kwargs = _fixture(tmp_path)
    result = assemble(**kwargs)
    assert result["assetCount"] == 11
    assert result["publicationAuthorized"] is False
    assert result["producerProvenanceVerified"] is False
    assert result["registriesVerified"] is False
    output = kwargs["output"]
    assert isinstance(output, Path)
    assert len(list((output / "assets").iterdir())) == 11
    manifest = output / "manifest.json"
    verified = verify_family(manifest, result["manifestSha256"], TAG, SOURCE)
    assert verified["family"] == "mcp-server"
    assert "kicad-mcp-pro-python-release-evidence.json" in verified["assetNames"]


@pytest.mark.parametrize(
    ("folder", "name"),
    [
        ("python_dist", f"kicad_mcp_pro-{VERSION}.tar.gz"),
        ("python_evidence", "SHA256SUMS.txt"),
        ("mcpb", f"kicad-mcp-pro-{VERSION}.mcpb"),
        ("pcm", f"kicad-mcp-pro-pcm-{VERSION}.zip"),
    ],
)
def test_missing_input_is_rejected_without_output(tmp_path: Path, folder: str, name: str) -> None:
    kwargs = _fixture(tmp_path)
    (kwargs[folder] / name).unlink()
    with pytest.raises(ValueError, match="missing or unexpected"):
        assemble(**kwargs)
    assert not kwargs["output"].exists()


def test_modified_payload_is_rejected_before_assembly(tmp_path: Path) -> None:
    kwargs = _fixture(tmp_path)
    (kwargs["mcpb"] / f"kicad-mcp-pro-{VERSION}.mcpb").write_bytes(b"altered")
    with pytest.raises(ValueError, match="checksum mismatch"):
        assemble(**kwargs)
    assert not kwargs["output"].exists()


def test_forged_source_identity_is_rejected(tmp_path: Path) -> None:
    kwargs = _fixture(tmp_path)
    kwargs["source_commit"] = "b" * 40
    with pytest.raises(ValueError, match="evidence source identity"):
        assemble(**kwargs)


def test_duplicate_or_extra_file_is_rejected(tmp_path: Path) -> None:
    kwargs = _fixture(tmp_path)
    (kwargs["pcm"] / "unapproved-extra.exe").write_bytes(b"extra")
    with pytest.raises(ValueError, match="unexpected"):
        assemble(**kwargs)


def test_foreign_version_is_rejected(tmp_path: Path) -> None:
    kwargs = _fixture(tmp_path)
    kwargs["tag"] = "mcp-server-v4.6.0"
    with pytest.raises(ValueError, match="missing or unexpected"):
        assemble(**kwargs)


def test_symlink_source_asset_is_rejected(tmp_path: Path) -> None:
    kwargs = _fixture(tmp_path)
    archive = kwargs["pcm"] / f"kicad-mcp-pro-pcm-{VERSION}.zip"
    other = tmp_path / "outside"
    other.write_bytes(archive.read_bytes())
    archive.unlink()
    archive.symlink_to(other)
    with pytest.raises(ValueError, match="unsafe or empty"):
        assemble(**kwargs)


def test_output_will_not_overwrite_existing_inventory(tmp_path: Path) -> None:
    kwargs = _fixture(tmp_path)
    kwargs["output"].mkdir()
    with pytest.raises(ValueError, match="must not exist"):
        assemble(**kwargs)
    assert not list(kwargs["output"].iterdir())


def test_wrong_evidence_digest_is_rejected(tmp_path: Path) -> None:
    kwargs = _fixture(tmp_path)
    path = kwargs["pcm"] / "kicad-mcp-pro-pcm-release-evidence.json"
    value = json.loads(path.read_text())
    value["sha256"] = "0" * 64
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="digest mismatch"):
        assemble(**kwargs)


def test_bad_or_duplicate_checksum_targets_are_rejected(tmp_path: Path) -> None:
    kwargs = _fixture(tmp_path)
    path = kwargs["python_evidence"] / "SHA256SUMS.txt"
    path.write_text(path.read_text() + path.read_text().splitlines()[0] + "\n")
    with pytest.raises(ValueError, match="duplicate checksum"):
        assemble(**kwargs)


def test_source_evidence_race_cannot_accept_invalid_staged_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = _fixture(tmp_path)
    import scripts.assemble_mcp_server_draft_assets as module

    original_copy = module.shutil.copyfile
    corrupted = False

    def race_copy(source: Path, destination: Path, **options: object) -> str:
        nonlocal corrupted
        if source.name == "kicad-mcp-pro-mcpb-release-evidence.json" and not corrupted:
            corrupted = True
            value = json.loads(source.read_text())
            value["sourceCommit"] = "b" * 40
            source.write_text(json.dumps(value))
        return str(original_copy(source, destination, **options))

    monkeypatch.setattr(module.shutil, "copyfile", race_copy)
    with pytest.raises(ValueError, match="evidence source identity mismatch"):
        assemble(**kwargs)
    assert corrupted
    assert not kwargs["output"].exists()


@pytest.mark.parametrize("folder", ["python_dist", "python_evidence", "mcpb", "pcm"])
def test_output_inside_input_does_not_create_new_directory(tmp_path: Path, folder: str) -> None:
    kwargs = _fixture(tmp_path)
    source = kwargs[folder]
    nested = source / "unwanted-output-parent"
    kwargs["output"] = nested / "release"
    with pytest.raises(ValueError, match="outside source artifact directories"):
        assemble(**kwargs)
    # Even a rejected invocation must not poison future validated source inventories.
    assert not nested.exists()
    assert not kwargs["output"].exists()
    kwargs["output"] = tmp_path / "out"
    result = assemble(**kwargs)
    assert result["publicationAuthorized"] is False


@pytest.mark.parametrize(
    ("folder", "filename", "key", "value"),
    [
        ("python_evidence", "release-evidence.json", "version", "0.0.0"),
        ("python_evidence", "release-evidence.json", "package", "different-project"),
        ("python_evidence", "release-evidence.json", "surface", "mcpb"),
        ("python_evidence", "release-evidence.json", "artifacts", []),
        (
            "pcm",
            "kicad-mcp-pro-pcm-release-evidence.json",
            "package_identifier",
            "com.attacker.plugin",
        ),
        ("pcm", "kicad-mcp-pro-pcm-release-evidence.json", "download_size", -1),
        ("pcm", "kicad-mcp-pro-pcm-release-evidence.json", "runtime", "swig"),
    ],
)
def test_forged_family_evidence_is_rejected_before_staging(
    tmp_path: Path, folder: str, filename: str, key: str, value: object
) -> None:
    kwargs = _fixture(tmp_path)
    evidence = kwargs[folder] / filename
    current = json.loads(evidence.read_text(encoding="utf-8"))
    current[key] = value
    evidence.write_text(json.dumps(current), encoding="utf-8")
    with pytest.raises(ValueError, match="evidence"):
        assemble(**kwargs)
    assert not kwargs["output"].exists()


def test_python_evidence_asset_digest_must_match_assembled_distribution(tmp_path: Path) -> None:
    kwargs = _fixture(tmp_path)
    evidence = kwargs["python_evidence"] / "release-evidence.json"
    current = json.loads(evidence.read_text(encoding="utf-8"))
    current["artifacts"][0]["sha256"] = "f" * 64
    evidence.write_text(json.dumps(current), encoding="utf-8")
    with pytest.raises(ValueError, match="evidence"):
        assemble(**kwargs)
    assert not kwargs["output"].exists()


def test_python_evidence_race_cannot_accept_invalid_staged_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = _fixture(tmp_path)
    import scripts.assemble_mcp_server_draft_assets as module

    original_copy = module.shutil.copyfile
    corrupted = False

    def race_copy(source: Path, destination: Path, **options: object) -> str:
        nonlocal corrupted
        if source.name == "release-evidence.json" and not corrupted:
            corrupted = True
            value = json.loads(source.read_text(encoding="utf-8"))
            value["version"] = "0.0.0"
            source.write_text(json.dumps(value), encoding="utf-8")
        return str(original_copy(source, destination, **options))

    monkeypatch.setattr(module.shutil, "copyfile", race_copy)
    with pytest.raises(ValueError, match="Python evidence"):
        assemble(**kwargs)
    assert corrupted
    assert not kwargs["output"].exists()
