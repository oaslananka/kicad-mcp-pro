"""Read-only per-family draft asset completeness gate for #1179.

A SHA-pinned manifest can be internally consistent while missing entire
artifact roles. This gate checks required names independently of its contents.
It never asserts trusted registry state, signed provenance, or publish authority.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from scripts.check_draft_release_inventory import _asset_inventory, _trusted_manifest

_TAG = re.compile(
    r"^(mcp-server|mcp-npm|protocol-schemas|kicad-mcp-gui)-v(\d+\.\d+\.\d+)$", re.ASCII
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _roles(family: str, version: str) -> dict[str, str]:
    v = re.escape(version)
    if family == "mcp-server":
        return {
            "wheel": rf"kicad_mcp_pro-{v}-py3-none-any\.whl",
            "sdist": rf"kicad_mcp_pro-{v}\.tar\.gz",
            "python-hashes": r"kicad-mcp-pro-python-SHA256SUMS\.txt",
            "python-sbom": r"kicad-mcp-pro-python-sbom\.cdx\.json",
            "python-evidence": r"kicad-mcp-pro-python-release-evidence\.json",
            "mcpb": rf"kicad-mcp-pro-{v}\.mcpb",
            "mcpb-hashes": r"kicad-mcp-pro-mcpb-SHA256SUMS\.txt",
            "mcpb-evidence": r"kicad-mcp-pro-mcpb-release-evidence\.json",
            "pcm": rf"kicad-mcp-pro-pcm-{v}\.zip",
            "pcm-hashes": r"kicad-mcp-pro-pcm-SHA256SUMS\.txt",
            "pcm-evidence": r"kicad-mcp-pro-pcm-release-evidence\.json",
        }
    if family == "mcp-npm":
        return {
            "package": rf"kicad-mcp-pro-{v}\.tgz",
            "hashes": r"mcp-npm-SHA256SUMS\.txt",
            "sbom": r"mcp-npm-sbom\.cdx\.json",
            "published-digest": r"npm-published-digest\.json",
        }
    if family == "protocol-schemas":
        return {
            "package": rf"oaslananka-kicad-protocol-schemas-{v}\.tgz",
            "hashes": r"protocol-schemas-SHA256SUMS\.txt",
            "sbom": r"protocol-schemas-sbom\.cdx\.json",
        }
    if family == "kicad-mcp-gui":
        return {
            "deb": rf"linux_KiCad-MCP-Pro_{v}_amd64\.deb",
            "rpm": rf"linux_KiCad-MCP-Pro-{v}-1\.x86_64\.rpm",
            "appimage": rf"linux_KiCad-MCP-Pro_{v}_amd64\.AppImage",
            "dmg": rf"macos_KiCad-MCP-Pro_{v}_aarch64\.dmg",
            "msi": rf"windows_KiCad-MCP-Pro_{v}_x64_en-US\.msi",
            "exe": rf"windows_KiCad-MCP-Pro_{v}_x64-setup\.exe",
            "hashes": r"kicad-mcp-pro-gui-SHA256SUMS\.txt",
            "sbom": r"kicad-mcp-pro-gui-sbom\.cdx\.json",
            "evidence": r"kicad-mcp-pro-gui-release-evidence\.json",
        }
    raise ValueError("unsupported release family")


def verify_family(
    manifest_path: Path, manifest_sha256: str, tag: str, source_commit: str
) -> dict[str, Any]:
    """Validate exact artifact roles using a trusted external manifest SHA-256."""
    match = _TAG.fullmatch(tag)
    if match is None or _COMMIT.fullmatch(source_commit) is None:
        raise ValueError("unsupported stable release tag or source commit")
    family, version = match.groups()
    manifest = _trusted_manifest(manifest_path, manifest_sha256)
    if manifest.get("releaseTag") != tag or manifest.get("sourceCommit") != source_commit:
        raise ValueError("pinned manifest tag or source commit mismatch")
    assets = _asset_inventory(manifest.get("assets"))
    roles = _roles(family, version)
    found: dict[str, str] = {}
    for name, asset in assets.items():
        if (
            type(asset.get("size")) is not int
            or asset["size"] <= 0
            or not isinstance(asset.get("sha256"), str)
            or _SHA256.fullmatch(asset["sha256"]) is None
        ):
            raise ValueError(f"invalid pinned asset size or digest: {name}")
        matched = [
            role for role, pattern in roles.items() if re.fullmatch(pattern, name, flags=re.ASCII)
        ]
        if len(matched) != 1 or matched[0] in found:
            raise ValueError(f"unexpected or duplicate release family asset: {name}")
        found[matched[0]] = name
    if set(found) != set(roles):
        raise ValueError(f"incomplete release family inventory: {sorted(set(roles) - set(found))}")
    return {
        "releaseTag": tag,
        "sourceCommit": source_commit,
        "family": family,
        "assetNames": sorted(assets),
        "familyAssetNamesVerified": True,
        "draftAssetsVerified": False,
        "registriesVerified": False,
        "attestationsVerified": False,
        "exclusiveWriterVerified": False,
        "publicationAuthorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    try:
        result = verify_family(args.manifest, args.manifest_sha256, args.tag, args.source_commit)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"release family inventory: FAIL: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
