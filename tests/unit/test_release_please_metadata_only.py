import json
from pathlib import Path

from scripts.check_release_please_metadata_only import (
    allowed_release_metadata_paths,
    is_release_metadata_only,
    unexpected_release_paths,
)

ROOT = Path(__file__).resolve().parents[2]


def _config() -> dict[str, object]:
    return json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_release_metadata_allowlist_covers_generated_version_files() -> None:
    allowed = allowed_release_metadata_paths(_config())

    expected = {
        ".release-please-manifest.json",
        ".claude-plugin/plugin.json",
        "CHANGELOG.md",
        "CITATION.cff",
        "README.md",
        "compatibility.yaml",
        "package.json",
        "packages/mcp-npm/CHANGELOG.md",
        "packages/mcp-npm/package-lock.json",
        "packages/mcp-npm/package.json",
        "packaging/mcpb/manifest.json",
        "pyproject.toml",
        "server.json",
        "sonar-project.properties",
        "src-tauri/CHANGELOG.md",
        "src-tauri/Cargo.lock",
        "src-tauri/Cargo.toml",
        "src-tauri/tauri.conf.json",
        "src/kicad_mcp/__init__.py",
        "uv.lock",
    }
    _require(expected <= allowed, "release metadata allowlist is incomplete")


def test_release_metadata_classifier_rejects_implementation_changes() -> None:
    unexpected = unexpected_release_paths(
        ["pyproject.toml", "CHANGELOG.md", "src/kicad_mcp/tools/schematic.py"],
        _config(),
    )

    _require(
        unexpected == ["src/kicad_mcp/tools/schematic.py"],
        "implementation path must be rejected",
    )


def test_release_metadata_classifier_requires_release_manifest() -> None:
    config = _config()

    _require(
        is_release_metadata_only(
            [".release-please-manifest.json", "pyproject.toml", "CHANGELOG.md"], config
        ),
        "release manifest plus generated metadata should classify as metadata-only",
    )
    _require(
        not is_release_metadata_only(["uv.lock"], config),
        "release manifest is required for metadata-only classification",
    )
