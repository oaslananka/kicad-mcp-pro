from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAURI_DIR = ROOT / "src-tauri"
SCHEMA_DIR = TAURI_DIR / "gen" / "schemas"


def _contains_key(value: object, target: str) -> bool:
    if isinstance(value, dict):
        return target in value or any(_contains_key(item, target) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, target) for item in value)
    return False


def test_updater_is_absent_from_runtime_and_shipped_configuration() -> None:
    manifest = tomllib.loads((TAURI_DIR / "Cargo.toml").read_text(encoding="utf-8"))
    lockfile = tomllib.loads((TAURI_DIR / "Cargo.lock").read_text(encoding="utf-8"))
    config_text = (TAURI_DIR / "tauri.conf.json").read_text(encoding="utf-8")
    config = json.loads(config_text)
    capability = json.loads(
        (TAURI_DIR / "capabilities" / "default.json").read_text(encoding="utf-8")
    )
    runtime = (TAURI_DIR / "src" / "lib.rs").read_text(encoding="utf-8")

    assert "tauri-plugin-updater" not in manifest["dependencies"]
    assert all(package.get("name") != "tauri-plugin-updater" for package in lockfile["package"])
    assert "tauri_plugin_updater" not in runtime
    assert "updater" not in config.get("plugins", {})
    assert "TAURI_SIGNING_PUBLIC_KEY_PLACEHOLDER" not in config_text
    assert "latest.json" not in config_text
    assert "createUpdaterArtifacts" not in config["bundle"]
    assert all(not permission.startswith("updater:") for permission in capability["permissions"])


def test_generated_acl_schemas_do_not_expose_updater_permissions() -> None:
    for path in sorted(SCHEMA_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert not _contains_key(payload, "updater"), path
        assert "updater:" not in path.read_text(encoding="utf-8"), path


def test_desktop_manual_upgrade_and_rollback_are_documented() -> None:
    installation = (ROOT / "docs" / "installation.md").read_text(encoding="utf-8").lower()

    assert "## desktop app" in installation
    assert "automatic updates are not enabled" in installation
    assert "### upgrade" in installation
    assert "### rollback" in installation
