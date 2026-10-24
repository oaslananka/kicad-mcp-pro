"""Fail-closed, offline coverage tests for GitHub Release asset families."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from scripts.check_release_family_inventory import main, verify_family

SHA = "a" * 40
ASSETS = {
    "mcp-server-v4.4.0": [
        "kicad_mcp_pro-4.4.0-py3-none-any.whl",
        "kicad_mcp_pro-4.4.0.tar.gz",
        "kicad-mcp-pro-python-SHA256SUMS.txt",
        "kicad-mcp-pro-python-sbom.cdx.json",
        "kicad-mcp-pro-python-release-evidence.json",
        "kicad-mcp-pro-4.4.0.mcpb",
        "kicad-mcp-pro-mcpb-SHA256SUMS.txt",
        "kicad-mcp-pro-mcpb-release-evidence.json",
        "kicad-mcp-pro-pcm-4.4.0.zip",
        "kicad-mcp-pro-pcm-SHA256SUMS.txt",
        "kicad-mcp-pro-pcm-release-evidence.json",
    ],
    "mcp-npm-v4.4.0": [
        "kicad-mcp-pro-4.4.0.tgz",
        "mcp-npm-SHA256SUMS.txt",
        "mcp-npm-sbom.cdx.json",
        "npm-published-digest.json",
    ],
    "protocol-schemas-v2.0.0": [
        "oaslananka-kicad-protocol-schemas-2.0.0.tgz",
        "protocol-schemas-SHA256SUMS.txt",
        "protocol-schemas-sbom.cdx.json",
    ],
    "kicad-mcp-gui-v4.4.0": [
        "linux_KiCad-MCP-Pro-4.4.0-1.x86_64.rpm",
        "linux_KiCad-MCP-Pro_4.4.0_amd64.AppImage",
        "linux_KiCad-MCP-Pro_4.4.0_amd64.deb",
        "macos_KiCad-MCP-Pro_4.4.0_aarch64.dmg",
        "windows_KiCad-MCP-Pro_4.4.0_x64-setup.exe",
        "windows_KiCad-MCP-Pro_4.4.0_x64_en-US.msi",
        "kicad-mcp-pro-gui-SHA256SUMS.txt",
        "kicad-mcp-pro-gui-sbom.cdx.json",
        "kicad-mcp-pro-gui-release-evidence.json",
    ],
}


def _case(tmp_path: Path, tag: str) -> dict[str, Any]:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "releaseTag": tag,
                "sourceCommit": SHA,
                "assets": [
                    {"name": name, "size": 5, "sha256": hashlib.sha256(name.encode()).hexdigest()}
                    for name in ASSETS[tag]
                ],
            }
        )
    )
    return {
        "manifest_path": path,
        "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "tag": tag,
        "source_commit": SHA,
    }


def _change(case: dict[str, Any], update: Callable[[dict[str, Any]], object]) -> None:
    path = case["manifest_path"]
    payload = json.loads(path.read_text())
    update(payload)
    path.write_text(json.dumps(payload))
    case["manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("tag", list(ASSETS))
def test_all_roles_present_but_publication_not_authorized(tmp_path: Path, tag: str) -> None:
    result = verify_family(**_case(tmp_path, tag))
    assert result["familyAssetNamesVerified"] is True
    assert result["publicationAuthorized"] is False
    assert result["draftAssetsVerified"] is False
    assert result["attestationsVerified"] is False
    assert result["registriesVerified"] is False
    assert result["exclusiveWriterVerified"] is False


@pytest.mark.parametrize("tag", list(ASSETS))
def test_every_missing_role_rejected(tmp_path: Path, tag: str) -> None:
    for index in range(len(ASSETS[tag])):
        case = _case(tmp_path, tag)
        _change(case, lambda data, index=index: data["assets"].pop(index))
        with pytest.raises(ValueError, match="incomplete release family inventory"):
            verify_family(**case)


@pytest.mark.parametrize("tag", list(ASSETS))
def test_unexpected_asset_rejected(tmp_path: Path, tag: str) -> None:
    case = _case(tmp_path, tag)
    extra = {"name": "unreviewed-installer.exe", "size": 3, "sha256": "0" * 64}
    _change(case, lambda data: data["assets"].append(extra))
    with pytest.raises(ValueError, match="unexpected"):
        verify_family(**case)


@pytest.mark.parametrize("tag", list(ASSETS))
def test_duplicate_name_rejected(tmp_path: Path, tag: str) -> None:
    case = _case(tmp_path, tag)
    _change(case, lambda data: data["assets"].append(data["assets"][0].copy()))
    with pytest.raises(ValueError, match="duplicate"):
        verify_family(**case)


@pytest.mark.parametrize("tag", list(ASSETS))
def test_cross_version_package_rejected(tmp_path: Path, tag: str) -> None:
    case = _case(tmp_path, tag)
    old_version = tag.rsplit("-v", maxsplit=1)[-1]
    _change(
        case,
        lambda data: data["assets"][0].__setitem__(
            "name", data["assets"][0]["name"].replace(old_version, "9.9.9")
        ),
    )
    with pytest.raises(ValueError, match="unexpected"):
        verify_family(**case)


@pytest.mark.parametrize("tag", list(ASSETS))
def test_source_commit_mismatch_rejected(tmp_path: Path, tag: str) -> None:
    case = _case(tmp_path, tag)
    case["source_commit"] = "b" * 40
    with pytest.raises(ValueError, match="tag or source"):
        verify_family(**case)


@pytest.mark.parametrize(
    ("field", "value"),
    [("size", 0), ("size", True), ("size", "5"), ("sha256", "bad"), ("sha256", None)],
)
def test_invalid_size_and_digest_rejected(tmp_path: Path, field: str, value: object) -> None:
    case = _case(tmp_path, "mcp-server-v4.4.0")
    _change(case, lambda data: data["assets"][0].__setitem__(field, value))
    with pytest.raises(ValueError, match="invalid pinned"):
        verify_family(**case)


@pytest.mark.parametrize(
    "tag", ["mcp-server-v4.4.0-alpha.1", "mcp-server-v4.4.0/escape", "unknown-v4.4.0"]
)
def test_unknown_or_prerelease_tag_fails_closed(tmp_path: Path, tag: str) -> None:
    case = _case(tmp_path, "mcp-server-v4.4.0")
    case["tag"] = tag
    with pytest.raises(ValueError, match="unsupported"):
        verify_family(**case)


def test_protocol_schemas_must_have_reviewed_package_name(tmp_path: Path) -> None:
    case = _case(tmp_path, "protocol-schemas-v2.0.0")
    _change(
        case,
        lambda data: data["assets"][0].__setitem__("name", "unrelated-package-2.0.0.tgz"),
    )
    with pytest.raises(ValueError, match="unexpected"):
        verify_family(**case)


@pytest.mark.parametrize(
    "installer",
    [
        "linux_KiCad-MCP-Pro-4.4.0-1.x86_64.rpm",
        "linux_KiCad-MCP-Pro_4.4.0_amd64.AppImage",
        "linux_KiCad-MCP-Pro_4.4.0_amd64.deb",
        "macos_KiCad-MCP-Pro_4.4.0_aarch64.dmg",
        "windows_KiCad-MCP-Pro_4.4.0_x64-setup.exe",
        "windows_KiCad-MCP-Pro_4.4.0_x64_en-US.msi",
    ],
)
@pytest.mark.parametrize("foreign_version", ["14.4.0", "4.4.01", "4.4.0a"])
def test_gui_installer_foreign_version_near_miss_rejected(
    tmp_path: Path, installer: str, foreign_version: str
) -> None:
    case = _case(tmp_path, "kicad-mcp-gui-v4.4.0")
    wrong = installer.replace("4.4.0", foreign_version)

    def replace_installer(document: dict[str, Any]) -> None:
        for item in document["assets"]:
            if item["name"] == installer:
                item["name"] = wrong
                return
        raise AssertionError("fixture installer missing")

    _change(case, replace_installer)
    with pytest.raises(ValueError, match="unexpected"):
        verify_family(**case)


@pytest.mark.parametrize(
    "unreviewed",
    [
        "linux_KiCad-MCP-Foreign_4.4.0_amd64.deb",
        "linux_KiCad-MCP-Pro_4.4.0_arm64.deb",
        "linux_KiCad-MCP-Foreign-4.4.0-1.x86_64.rpm",
        "linux_KiCad-MCP-Pro-4.4.0-2.x86_64.rpm",
        "linux_KiCad-MCP-Pro_4.4.0_arm64.AppImage",
        "macos_KiCad-MCP-Foreign_4.4.0_aarch64.dmg",
        "macos_KiCad-MCP-Pro_4.4.0_x64.dmg",
        "windows_KiCad-MCP-Pro_4.4.0_arm64_en-US.msi",
        "windows_KiCad-MCP-Pro_4.4.0_x64-setup-fake.exe",
        "windows_KiCad-MCP-Foreign_4.4.0_x64-setup.exe",
    ],
)
def test_unreviewed_gui_product_architecture_or_format_fails_closed(
    tmp_path: Path, unreviewed: str
) -> None:
    case = _case(tmp_path, "kicad-mcp-gui-v4.4.0")

    def foreign(document: dict[str, Any]) -> None:
        suffix = unreviewed.rsplit(".", maxsplit=1)[-1]
        for asset in document["assets"]:
            if asset["name"].endswith("." + suffix):
                asset["name"] = unreviewed
                return
        raise AssertionError("fixture asset missing")

    _change(case, foreign)
    with pytest.raises(ValueError, match="unexpected"):
        verify_family(**case)


def test_manifest_pin_must_be_external(tmp_path: Path) -> None:
    case = _case(tmp_path, "mcp-server-v4.4.0")
    case["manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="trusted manifest SHA"):
        verify_family(**case)


def test_cli_fails_closed_on_incomplete_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, "mcp-server-v4.4.0")
    _change(case, lambda data: data["assets"].pop())
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_release_family_inventory",
            "--manifest",
            str(case["manifest_path"]),
            "--manifest-sha256",
            case["manifest_sha256"],
            "--tag",
            case["tag"],
            "--source-commit",
            case["source_commit"],
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
