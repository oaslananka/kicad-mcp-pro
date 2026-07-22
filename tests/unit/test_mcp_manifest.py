from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_META_KEY = "io.github.oaslananka/kicad-mcp-pro"


def _load_validator() -> object:
    script = ROOT / "scripts" / "validate_mcp_manifest.py"
    spec = importlib.util.spec_from_file_location("validate_mcp_manifest", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checked_mcp_manifest_is_valid() -> None:
    module = _load_validator()
    manifest = module.validate_manifest_file(ROOT / "server.json")

    assert manifest["name"] == "io.github.oaslananka/kicad-mcp-pro"
    assert manifest["repository"]["url"] == "https://github.com/oaslananka/kicad-mcp-pro"
    assert manifest["repository"].get("subfolder") is None
    assert [package["runtimeHint"] for package in manifest["packages"]] == [
        "uvx",
        "npx",
        "docker",
    ]
    assert all(
        package.get("version") == manifest["version"]
        for package in manifest["packages"]
        if package.get("registryType") != "oci" and package.get("registry") != "container"
    )
    assert manifest["packages"][2]["identifier"].endswith(f":{manifest['version']}")


def test_checked_mcp_manifest_has_public_registry_listing_metadata() -> None:
    module = _load_validator()
    manifest = module.validate_manifest_file(ROOT / "server.json")
    registry_meta = manifest["_meta"][REGISTRY_META_KEY]

    assert len(manifest["description"]) <= 100
    assert manifest["icons"] == [
        {
            "src": "https://oaslananka.github.io/kicad-mcp-pro/assets/icon-512.png",
            "mimeType": "image/png",
            "sizes": ["512x512"],
        },
        {
            "src": "https://oaslananka.github.io/kicad-mcp-pro/assets/icon.svg",
            "mimeType": "image/svg+xml",
            "sizes": ["any"],
        },
    ]
    assert registry_meta["categories"] == [
        "developer-tools",
        "electronic-design-automation",
        "manufacturing",
    ]
    assert set(registry_meta["tags"]) >= {
        "kicad",
        "pcb",
        "schematic",
        "drc",
        "erc",
        "bom",
        "gerber",
        "mcp",
    }
    assert "KiCad CLI" in registry_meta["longDescription"]
    assert len(registry_meta["screenshots"]) == 5
    assert registry_meta["prerequisites"] == [
        "KiCad CLI 10.0.x available on PATH for file-backed DRC, ERC, and export tools. "
        "KiCad 8.x is deprecated and limited to file-level read and migration workflows."
    ]
    assert registry_meta["supportedMcpProtocolVersions"] == ["2025-11-25"]
    assert registry_meta["license"] == "MIT"
    assert registry_meta["canonicalRepository"] == ("https://github.com/oaslananka/kicad-mcp-pro")
    assert registry_meta["changelog"] == (
        "https://github.com/oaslananka/kicad-mcp-pro/blob/main/CHANGELOG.md"
    )
    assert registry_meta["releaseNotes"] == registry_meta["changelog"]
    assert registry_meta["maintainer"] == {
        "name": "Osman Aslan",
        "url": "https://github.com/oaslananka",
    }
    assert registry_meta["serverInfo"] == {
        "schemaVersion": "1.1.0",
        "mcpProtocolVersion": "2025-11-25",
        "toolSchemaVersion": "1.0.0",
        "capabilities": [
            "fileBackedDrc",
            "fileBackedErc",
            "fileBackedExports",
            "livePcbRead",
            "livePcbWrite",
            "liveSchematicRead",
            "liveSchematicWrite",
            "chatgptConnectorCompatible",
            "cliExports",
        ],
    }
    assert registry_meta["toolCatalog"] == {
        "summary": (
            "EDA automation tools for KiCad project setup, schematic analysis, PCB "
            "inspection, DRC/ERC validation, BOM/netlist generation, routing review, "
            "simulation, DFM, and manufacturing export."
        ),
        "reference": (
            "https://github.com/oaslananka/kicad-mcp-pro/blob/main/docs/tools-reference.generated.md"
        ),
    }


def test_validator_rejects_missing_public_registry_metadata(tmp_path: Path) -> None:
    module = _load_validator()
    manifest = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    manifest.pop("_meta", None)
    manifest.pop("icons", None)
    path = tmp_path / "server.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    errors = module.validate_manifest(module.load_manifest(path))

    assert "icons must include at least one public registry icon." in errors
    assert f"_meta.{REGISTRY_META_KEY} is required for public registry listing metadata." in errors


def test_validator_lints_against_official_schema() -> None:
    module = _load_validator()
    manifest = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    manifest["icons"][0]["mimeType"] = "text/plain"

    errors = module.validate_manifest(manifest)

    assert any(
        error.startswith("official MCP Registry schema icons.0.mimeType:") and "text/plain" in error
        for error in errors
    )


def test_validator_rejects_invalid_license_and_broken_metadata_link() -> None:
    module = _load_validator()
    manifest = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    manifest["license"] = "MIT License"
    manifest["_meta"][REGISTRY_META_KEY]["changelog"] = (
        "https://github.com/oaslananka/kicad-mcp-pro/blob/main/MISSING.md"
    )

    errors = module.validate_manifest(manifest)

    assert "license must be a valid SPDX license identifier." in errors
    assert any("broken repository link" in error and "MISSING.md" in error for error in errors)


def test_validator_rejects_missing_command(tmp_path: Path) -> None:
    module = _load_validator()
    manifest = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    for package in manifest["packages"]:
        package.pop("command", None)
        package.pop("runtimeHint", None)
    path = tmp_path / "server.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    errors = module.validate_manifest(module.load_manifest(path))

    assert "manifest must define mcp.command or a package command." in errors


def test_validator_rejects_duplicate_packages(tmp_path: Path) -> None:
    module = _load_validator()
    manifest = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    manifest["packages"].append(dict(manifest["packages"][0]))
    path = tmp_path / "server.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    errors = module.validate_manifest(module.load_manifest(path))

    assert any("duplicates package pypi/kicad-mcp-pro" in error for error in errors)


def test_validator_rejects_unsupported_transport() -> None:
    module = _load_validator()
    manifest = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    manifest["packages"][0]["transport"]["type"] = "websocket"

    errors = module.validate_manifest(manifest)

    assert "packages[0] uses unsupported transport 'websocket'." in errors


def test_validator_rejects_oci_registry_base_url() -> None:
    module = _load_validator()
    manifest = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    manifest["packages"][2]["registryBaseUrl"] = "https://ghcr.io"

    errors = module.validate_manifest(manifest)

    assert (
        "packages[1] must not define registryBaseUrl for OCI packages; "
        "use a canonical registry/repository:tag identifier."
    ).replace("packages[1]", "packages[2]") in errors


def test_validator_rejects_missing_package_version() -> None:
    module = _load_validator()
    manifest = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    manifest["packages"][0].pop("version")

    errors = module.validate_manifest(manifest)

    assert "packages[0] must define version." in errors


def test_validator_rejects_oci_package_with_version() -> None:
    module = _load_validator()
    manifest = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    manifest["packages"][2]["version"] = "3.6.0"

    errors = module.validate_manifest(manifest)

    assert any("OCI packages must not define version field" in error for error in errors)


def test_validator_accepts_oci_without_version() -> None:
    module = _load_validator()
    manifest = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    # OCI package (index 2) should not have version — confirm it passes
    assert "version" not in manifest["packages"][2]

    errors = module.validate_manifest(manifest)

    assert not errors


def test_validator_accepts_oci_identifier_with_digest() -> None:
    module = _load_validator()
    manifest = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    digest = "a" * 64
    manifest["packages"][2]["identifier"] = f"ghcr.io/oaslananka/kicad-mcp-pro@sha256:{digest}"

    errors = module.validate_manifest(manifest)

    assert not errors


def test_validator_accepts_oci_identifier_with_single_repository_segment() -> None:
    module = _load_validator()
    manifest = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    manifest["packages"][2]["identifier"] = "ghcr.io/kicad-mcp-pro:3.4.0"

    errors = module.validate_manifest(manifest)

    assert not errors


@pytest.mark.parametrize(
    "identifier",
    [
        "ghcr.io/oaslananka/kicad-mcp-pro",
        "ghcr.io/oaslananka/kicad-mcp-pro:",
        "ghcr.io/oaslananka/kicad-mcp-pro:3.4.0 bad",
        "https://ghcr.io/oaslananka/kicad-mcp-pro:3.4.0",
    ],
)
def test_validator_rejects_malformed_oci_identifier(identifier: str) -> None:
    module = _load_validator()
    manifest = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    manifest["packages"][2]["identifier"] = identifier

    errors = module.validate_manifest(manifest)

    assert (
        "packages[2] OCI identifier must be registry/repository:tag "
        "or registry/repository@algorithm:digest."
    ) in errors


def test_candidate_protocol_is_not_advertised_before_release_gates_pass() -> None:
    module = _load_validator()
    manifest = module.validate_manifest_file(ROOT / "server.json")
    registry_meta = manifest["_meta"][REGISTRY_META_KEY]

    assert registry_meta["supportedMcpProtocolVersions"] == ["2025-11-25"]
    assert "2026-07-28" not in registry_meta["supportedMcpProtocolVersions"]
    assert registry_meta["serverInfo"]["mcpProtocolVersion"] == "2025-11-25"
