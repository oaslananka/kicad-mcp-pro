"""Stage immutable mcp-server draft assets from four downloaded Actions artifacts.

Offline, preparation-only. Does not fetch workflows, trust the producer,
verify attestations/registries, create drafts, upload, or publish Releases.
Inputs must be separately downloaded from independently approved producer runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from scripts.check_draft_release_inventory import digest, manifest_for
from scripts.check_release_family_inventory import verify_family
from scripts.runtime_path_safety import approved_runtime_path

_VERSION = re.compile(r"^mcp-server-v(\d+\.\d+\.\d+)$", re.ASCII)
_SHA = re.compile(r"^[0-9a-f]{40}$")
_PYTHON_SUMS = "SHA256SUMS.txt"


def _expected(version: str) -> dict[str, set[str]]:
    return {
        "python_dist": {
            f"kicad_mcp_pro-{version}-py3-none-any.whl",
            f"kicad_mcp_pro-{version}.tar.gz",
        },
        "python_evidence": {
            _PYTHON_SUMS,
            "sbom.cdx.json",
            "release-evidence.json",
        },
        "mcpb": {
            f"kicad-mcp-pro-{version}.mcpb",
            "kicad-mcp-pro-mcpb-SHA256SUMS.txt",
            "kicad-mcp-pro-mcpb-release-evidence.json",
        },
        "pcm": {
            f"kicad-mcp-pro-pcm-{version}.zip",
            "kicad-mcp-pro-pcm-SHA256SUMS.txt",
            "kicad-mcp-pro-pcm-release-evidence.json",
        },
    }


def _source_files(folder: Path, names: set[str]) -> dict[str, Path]:
    if folder.is_symlink():
        raise ValueError("artifact folder must not be a symlink")
    folder = approved_runtime_path(folder)
    if not folder.is_dir():
        raise ValueError("missing downloaded Actions artifact directory")
    items = {p.name: p for p in folder.iterdir()}
    if set(items) != names:
        raise ValueError(f"missing or unexpected downloaded files: {sorted(names ^ set(items))}")
    for file in items.values():
        if file.is_symlink() or not file.is_file() or not file.stat().st_size:
            raise ValueError(f"unsafe or empty downloaded asset: {file.name}")
    return items


def _check_hashes(path: Path, values: dict[str, Path]) -> None:
    names = set(values)
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) [ *]([^/\\\r\n]+)", line)
        if match is None:
            raise ValueError("invalid or untrusted checksum file line")
        hash_value, name = match.groups()
        if name not in names or name in seen:
            raise ValueError("unapproved or duplicate checksum target")
        seen.add(name)
        if digest(values[name]) != hash_value:
            raise ValueError(f"downloaded artifact checksum mismatch: {name}")
    if seen != names:
        raise ValueError("incomplete artifact checksum file")


def _check_evidence(
    path: Path, artifact: Path, *, version: str, tag: str, source_commit: str, kind: str
) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid package evidence")
    if (
        value.get("version") != version
        or value.get("artifact") != artifact.name
        or value.get("sha256") != digest(artifact)
    ):
        raise ValueError(f"{kind} evidence version, artifact or digest mismatch")
    if kind == "mcpb" and (
        value.get("schemaVersion") != 1
        or value.get("sourceTag") != tag
        or value.get("sourceCommit") != source_commit
    ):
        raise ValueError("MCPB evidence source identity mismatch")
    if kind == "pcm" and value.get("schema_version") != "kicad-pcm-release-evidence.v1":
        raise ValueError("PCM evidence format mismatch")


def _check_source_evidence(
    source: dict[str, dict[str, Path]], *, version: str, tag: str, source_commit: str
) -> None:
    """Check all source family checksums and identity-bearing sidecars."""
    _check_hashes(source["python_evidence"][_PYTHON_SUMS], source["python_dist"])
    for kind in ("mcpb", "pcm"):
        archive = next(p for p in source[kind].values() if p.suffix in (".mcpb", ".zip"))
        checksums = source[kind][f"kicad-mcp-pro-{kind}-SHA256SUMS.txt"]
        evidence = source[kind][f"kicad-mcp-pro-{kind}-release-evidence.json"]
        _check_hashes(checksums, {archive.name: archive})
        _check_evidence(
            evidence, archive, version=version, tag=tag, source_commit=source_commit, kind=kind
        )


def assemble(
    *,
    tag: str,
    source_commit: str,
    python_dist: Path,
    python_evidence: Path,
    mcpb: Path,
    pcm: Path,
    output: Path,
) -> dict[str, object]:
    version_match = _VERSION.fullmatch(tag)
    if version_match is None or _SHA.fullmatch(source_commit) is None:
        raise ValueError("invalid stable mcp-server tag or source commit")
    version = version_match.group(1)
    folders = {
        "python_dist": python_dist,
        "python_evidence": python_evidence,
        "mcpb": mcpb,
        "pcm": pcm,
    }
    expected = _expected(version)
    source = {name: _source_files(folders[name], names) for name, names in expected.items()}
    inputs = [p.resolve() for p in folders.values()]
    if len(set(inputs)) != len(inputs):
        raise ValueError("artifact source directories must be distinct")

    _check_source_evidence(source, version=version, tag=tag, source_commit=source_commit)

    output = Path(output).expanduser()
    if output.is_symlink() or output.exists():
        raise ValueError("output must not exist: no overwrite of approved release inventory")
    parent = approved_runtime_path(output.parent)
    # Reject nested output paths before creating directories inside validated inputs.
    target = parent / output.name
    if any(target.is_relative_to(p) for p in inputs):
        raise ValueError("output directory must be outside source artifact directories")
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".kicad-draft-assembly-", dir=parent) as temp:
        staged = Path(temp)
        assets = staged / "assets"
        assets.mkdir()
        rename = {
            _PYTHON_SUMS: "kicad-mcp-pro-python-SHA256SUMS.txt",
            "sbom.cdx.json": "kicad-mcp-pro-python-sbom.cdx.json",
            "release-evidence.json": "kicad-mcp-pro-python-release-evidence.json",
        }
        for group in source.values():
            for name, path in group.items():
                dest = assets / rename.get(name, name)
                if dest.exists():
                    raise ValueError(f"duplicate asset name across producer artifacts: {dest.name}")
                shutil.copyfile(path, dest, follow_symlinks=False)
                if digest(path) != digest(dest):
                    raise ValueError("asset changed while copying")
        # Validate assembled sidecars again; the copy is the actual approved payload.
        _check_hashes(
            assets / "kicad-mcp-pro-python-SHA256SUMS.txt",
            {name: assets / name for name in expected["python_dist"]},
        )
        for kind in ("mcpb", "pcm"):
            archive = next(
                assets / name for name in expected[kind] if name.endswith((".mcpb", ".zip"))
            )
            _check_hashes(assets / f"kicad-mcp-pro-{kind}-SHA256SUMS.txt", {archive.name: archive})
            _check_evidence(
                assets / f"kicad-mcp-pro-{kind}-release-evidence.json",
                archive,
                version=version,
                tag=tag,
                source_commit=source_commit,
                kind=kind,
            )
        manifest_path = staged / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest_for(assets, tag, source_commit), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        pin = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        result = verify_family(manifest_path, pin, tag, source_commit)
        os.rename(staged, output)
    return {
        "tag": tag,
        "sourceCommit": source_commit,
        "assetCount": len(result["assetNames"]),
        "manifestSha256": pin,
        "familyAssetNamesVerified": True,
        "producerProvenanceVerified": False,
        "attestationsVerified": False,
        "registriesVerified": False,
        "draftAssetsVerified": False,
        "exclusiveWriterVerified": False,
        "publicationAuthorized": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tag", required=True)
    p.add_argument("--source-commit", required=True)
    for name in ("python-dist", "python-evidence", "mcpb", "pcm"):
        p.add_argument(f"--{name}", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    try:
        result = assemble(
            tag=args.tag,
            source_commit=args.source_commit,
            python_dist=args.python_dist,
            python_evidence=args.python_evidence,
            mcpb=args.mcpb,
            pcm=args.pcm,
            output=args.output,
        )
    except (OSError, ValueError) as exc:
        p.exit(2, f"draft mcp-server assembly: FAIL: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
