from __future__ import annotations

import json
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


def test_unsigned_build_rejects_update_checks() -> None:
    config = json.loads((TAURI_DIR / "tauri.conf.json").read_text(encoding="utf-8"))
    runtime = (TAURI_DIR / "src" / "lib.rs").read_text(encoding="utf-8")

    assert config["plugins"]["updater"]["pubkey"] == ""
    assert '"Update signing is not configured' in runtime
    assert "Duration::from_secs(24 * 60 * 60)" in runtime


def test_generated_acl_schemas_expose_safe_updater_permissions() -> None:
    manifest_schema = SCHEMA_DIR / "acl-manifests.json"
    if manifest_schema.exists():
        payload = json.loads(manifest_schema.read_text(encoding="utf-8"))
        assert _contains_key(payload, "updater")


def test_desktop_manual_upgrade_and_rollback_are_documented() -> None:
    installation = (ROOT / "docs" / "installation.md").read_text(encoding="utf-8").lower()

    assert "## desktop app" in installation
    assert "automatic updates are not enabled" in installation
    assert "### upgrade" in installation
    assert "### rollback" in installation
