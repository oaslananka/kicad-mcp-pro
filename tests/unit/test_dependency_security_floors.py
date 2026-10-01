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
    assert any("gitpython>=3.1.62" in dependency.lower() for dependency in vcs_dependencies)

    locked = next(
        package["version"]
        for package in uv_lock["package"]
        if package["name"].lower() == "gitpython"
    )
    assert Version(locked) >= Version("3.1.62")


def test_cryptography_security_floor_is_patched() -> None:
    uv_lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

    locked = next(
        package["version"]
        for package in uv_lock["package"]
        if package["name"].lower() == "cryptography"
    )
    assert Version(locked) >= Version("50.0.0")


def test_pyjwt_security_floor_is_patched() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    uv_lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

    dependencies = pyproject["project"]["dependencies"]
    has_pyjwt_floor = any("pyjwt>=2.15.0" in dependency.lower() for dependency in dependencies)
    assert has_pyjwt_floor  # nosec B101

    locked = next(
        package["version"] for package in uv_lock["package"] if package["name"].lower() == "pyjwt"
    )
    assert Version(locked) >= Version("2.15.0")  # nosec B101


def test_urllib3_security_floor_is_patched() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    uv_lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

    dependencies = pyproject["project"]["dependencies"]
    has_urllib3_floor = any("urllib3>=2.8.0" in dependency.lower() for dependency in dependencies)
    assert has_urllib3_floor  # nosec B101

    locked = next(
        package["version"] for package in uv_lock["package"] if package["name"].lower() == "urllib3"
    )
    assert Version(locked) >= Version("2.8.0")  # nosec B101


def test_root_pnpm_lock_uses_current_js_yaml_security_floor() -> None:
    workspace = yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8"))
    lock = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    versions = {Version(value) for value in re.findall(r"js-yaml@(\d+\.\d+\.\d+)", lock)}

    assert Version(workspace["overrides"]["js-yaml"]) >= Version("4.3.2")
    assert versions
    assert min(versions) >= Version("4.3.2")


def test_root_pnpm_lock_uses_patched_fast_uri() -> None:
    workspace = yaml.safe_load((ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8"))
    lock = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    versions = {Version(value) for value in re.findall(r"fast-uri@(\d+\.\d+\.\d+)", lock)}

    assert workspace["overrides"]["fast-uri"] == "3.1.8"  # nosec B101
    assert versions
    assert min(versions) >= Version("3.1.8")  # nosec B101


def test_chatgpt_app_transitive_security_overrides_are_patched() -> None:
    package = json.loads((APP / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((APP / "package-lock.json").read_text(encoding="utf-8"))

    assert package["overrides"]["@hono/node-server"] == "2.0.11"
    assert package["overrides"]["hono"] == "4.13.5"
    assert package["overrides"]["fast-uri"] == "3.1.8"  # nosec B101
    assert package["overrides"]["qs"] == "6.16.0"

    patched = {
        "node_modules/@hono/node-server": "2.0.5",
        "node_modules/hono": "4.13.5",
        "node_modules/fast-uri": "3.1.8",
        "node_modules/qs": "6.16.0",
        "node_modules/ip-address": "10.4.0",
    }
    for path, minimum in patched.items():
        assert Version(lock["packages"][path]["version"]) >= Version(minimum)
