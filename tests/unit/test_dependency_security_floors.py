from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import yaml
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "integrations" / "chatgpt-app" / "apps-sdk"


def _assert_all_locked_versions_patched(packages: list[dict], name: str, minimum: str) -> None:
    versions = [
        package["version"] for package in packages if package["name"].lower() == name.lower()
    ]
    assert versions, f"{name} must exist in the resolved lock"
    assert all(Version(version) >= Version(minimum) for version in versions), name


def test_gitpython_security_floor_is_patched() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    uv_lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

    vcs_dependencies = pyproject["project"]["optional-dependencies"]["vcs"]
    assert any("gitpython>=3.2.1" in dependency.lower() for dependency in vcs_dependencies)

    _assert_all_locked_versions_patched(uv_lock["package"], "gitpython", "3.2.1")


def test_opentelemetry_api_security_floor_uses_patched_family() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

    dependencies = pyproject["project"]["dependencies"]
    for package in ("opentelemetry-sdk", "opentelemetry-exporter-otlp"):
        assert any(f"{package}>=1.45.1" in item.lower() for item in dependencies)
    for package in ("opentelemetry-api", "opentelemetry-sdk", "opentelemetry-exporter-otlp"):
        _assert_all_locked_versions_patched(lock["package"], package, "1.45.1")


def test_pypdf_security_floor_blocks_known_dependabot_regressions() -> None:
    """PDF resource-exhaustion advisories require >=6.21.2 as of 2026-10-24.

    GHSA-6vvc-x485-93v7, GHSA-f54x-cmq8-qg57, GHSA-cgf9-327m-v77c,
    GHSA-5hx5-vpf9-5wcv, GHSA-qfv9-64jg-mh7p, GHSA-9mx8-4j7g-633p.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    uv_lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

    dev_dependencies = pyproject["project"]["optional-dependencies"]["dev"]
    assert "pypdf==6.21.2" in dev_dependencies
    _assert_all_locked_versions_patched(uv_lock["package"], "pypdf", "6.21.2")


def test_opentelemetry_otlp_exporters_share_patched_runtime_floor() -> None:
    """No exporter subpackage may pull vulnerable opentelemetry-api back in."""
    uv_lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    for name in (
        "opentelemetry-api",
        "opentelemetry-sdk",
        "opentelemetry-exporter-otlp",
        "opentelemetry-exporter-otlp-proto-common",
        "opentelemetry-exporter-otlp-proto-grpc",
        "opentelemetry-exporter-otlp-proto-http",
    ):
        _assert_all_locked_versions_patched(uv_lock["package"], name, "1.45.1")


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

    assert workspace["overrides"]["fast-uri"] == "3.1.9"  # nosec B101
    assert versions
    assert min(versions) >= Version("3.1.9")  # nosec B101


def test_chatgpt_app_transitive_security_overrides_are_patched() -> None:
    package = json.loads((APP / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((APP / "package-lock.json").read_text(encoding="utf-8"))

    assert package["overrides"]["@hono/node-server"] == "2.1.5"
    assert package["overrides"]["hono"] == "4.13.13"
    assert package["overrides"]["fast-uri"] == "3.1.9"  # nosec B101
    assert package["overrides"]["qs"] == "6.16.1"

    patched = {
        "node_modules/@hono/node-server": "2.1.5",
        "node_modules/hono": "4.13.13",
        "node_modules/fast-uri": "3.1.9",
        "node_modules/qs": "6.16.1",
        "node_modules/ip-address": "10.7.4",
    }
    for path, minimum in patched.items():
        assert Version(lock["packages"][path]["version"]) >= Version(minimum)


def test_fastmcp_runtime_locked_to_patched_security_floor() -> None:
    """Both reported fastmcp advisories require 4.1.2 or newer.

    GHSA-7xgj-8392-5q4r and GHSA-vqqp-x5qm-5qp4 affect the slim
    implementation and its public fastmcp wrapper.
    """
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    for name in ("fastmcp", "fastmcp-slim"):
        _assert_all_locked_versions_patched(lock["package"], name, "4.1.2")
