from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import yaml
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "integrations" / "chatgpt-app" / "apps-sdk"


def test_gitpython_security_floor_is_patched() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    uv_lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

    vcs_dependencies = pyproject["project"]["optional-dependencies"]["vcs"]
    assert any("gitpython>=3.1.57" in dependency.lower() for dependency in vcs_dependencies)

    locked = next(
        package["version"]
        for package in uv_lock["package"]
        if package["name"].lower() == "gitpython"
    )
    assert Version(locked) >= Version("3.1.57")


def test_cryptography_security_floor_is_patched() -> None:
    uv_lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

    locked = next(
        package["version"]
        for package in uv_lock["package"]
        if package["name"].lower() == "cryptography"
    )
    assert Version(locked) >= Version("50.0.0")


def test_root_pnpm_lock_uses_current_js_yaml_security_floor() -> None:
    workspace = yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8"))
    lock = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    versions = {Version(value) for value in re.findall(r"js-yaml@(\d+\.\d+\.\d+)", lock)}

    assert Version(workspace["overrides"]["js-yaml"]) >= Version("4.3.1")
    assert versions
    assert min(versions) >= Version("4.3.1")


def test_root_pnpm_lock_uses_patched_fast_uri() -> None:
    workspace = yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8"))
    lock = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    versions = {Version(value) for value in re.findall(r"fast-uri@(\d+\.\d+\.\d+)", lock)}

    assert workspace["overrides"]["fast-uri"] == "3.1.5"
    assert versions
    assert min(versions) >= Version("3.1.5")


def test_chatgpt_app_transitive_security_overrides_are_patched() -> None:
    package = json.loads((APP / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((APP / "package-lock.json").read_text(encoding="utf-8"))

    assert package["overrides"]["@hono/node-server"] == "2.0.11"
    assert package["overrides"]["hono"] == "4.12.34"
    assert package["overrides"]["fast-uri"] == "3.1.5"

    patched = {
        "node_modules/@hono/node-server": "2.0.5",
        "node_modules/hono": "4.12.34",
        "node_modules/fast-uri": "3.1.5",
        "node_modules/ip-address": "10.4.0",
    }
    for path, minimum in patched.items():
        assert Version(lock["packages"][path]["version"]) >= Version(minimum)
