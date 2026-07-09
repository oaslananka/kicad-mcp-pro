from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT
WRAPPER_ROOT = ROOT / "packages" / "mcp-npm"
REGISTRY_SCHEMA = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"


def _load_metadata_sync_module() -> object:
    script = ROOT / "scripts" / "sync_mcp_metadata.py"
    spec = importlib.util.spec_from_file_location("sync_mcp_metadata", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("license_toml", "expected"),
    [
        ('license = "MIT"', "MIT"),
        ('license = { text = "MIT" }', "MIT"),
    ],
)
def test_metadata_sync_accepts_supported_license_forms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    license_toml: str,
    expected: str,
) -> None:
    module = _load_metadata_sync_module()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        f"""
[project]
name = "kicad-mcp-pro"
version = "1.2.3"
description = "Test metadata"
{license_toml}

[project.urls]
Repository = "https://github.com/oaslananka/kicad-mcp-pro"
Documentation = "https://docs.example.test"
""".lstrip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "PYPROJECT", pyproject)

    assert module._project_metadata()["license"] == expected


def test_release_metadata_is_synchronised() -> None:
    def is_oci_package(package: dict[str, object]) -> bool:
        return package.get("registryType") == "oci" or package.get("registry") in {
            "container",
            "oci",
        }

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]
    server_json = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    mcp_json = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    npm_wrapper = json.loads((WRAPPER_ROOT / "package.json").read_text(encoding="utf-8"))
    package_init = (ROOT / "src" / "kicad_mcp" / "__init__.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    mkdocs = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    assert server_json["$schema"] == REGISTRY_SCHEMA
    assert server_json["version"] == version
    assert server_json["icons"][0]["src"].endswith("/assets/icon-512.png")
    assert server_json["_meta"]["io.github.oaslananka/kicad-mcp-pro"]["license"] == "MIT"
    assert server_json["_meta"]["io.github.oaslananka/kicad-mcp-pro"]["toolCatalog"][
        "reference"
    ].endswith("/docs/tools-reference.generated.md")
    assert server_json["packages"][0]["version"] == version
    server_oci = next(
        package for package in server_json["packages"] if package["registryType"] == "oci"
    )
    mcp_oci = next(package for package in mcp_json["packages"] if package["registryType"] == "oci")
    assert all(
        package.get("version") == version
        for package in server_json["packages"]
        if package.get("registryType") != "oci" and package.get("registry") != "container"
    )
    assert all(
        package.get("version") == version
        for package in mcp_json["packages"]
        if package.get("registryType") != "oci" and package.get("registry") != "container"
    )
    assert server_oci["registry"] == "container"
    assert server_oci["image"] == "ghcr.io/oaslananka/kicad-mcp-pro"
    assert server_oci["identifier"] == f"{server_oci['image']}:{version}"
    assert mcp_oci["identifier"] == f"{mcp_oci['image']}:{version}"
    assert mcp_json["version"] == version
    assert server_json["name"] == "io.github.oaslananka/kicad-mcp-pro"
    assert server_json["repository"]["url"] == "https://github.com/oaslananka/kicad-mcp-pro"
    assert mcp_json["repository"]["url"] == "https://github.com/oaslananka/kicad-mcp-pro"
    assert npm_wrapper["version"] == version
    assert npm_wrapper["homepage"] == "https://oaslananka.github.io/kicad-mcp-pro"
    assert npm_wrapper["mcpName"] == "io.github.oaslananka/kicad-mcp-pro"
    assert npm_wrapper["repository"]["url"] == "git+https://github.com/oaslananka/kicad-mcp-pro.git"
    assert f'__version__ = "{version}"  # x-release-please-version' in package_init
    assert "<!-- mcp-name: io.github.oaslananka/kicad-mcp-pro -->" in readme
    assert "development/v2-migration.md" in mkdocs
    assert "https://github.com/oaslananka/kicad-mcp-pro/security/advisories/new" in security
    assert "Do not open public issues for active vulnerabilities." in security


def test_kicad_studio_contract_documents_current_http_bridge() -> None:
    studio_doc = (ROOT / "docs" / "integration" / "kicad-studio.md").read_text(encoding="utf-8")
    mkdocs = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")

    assert "2.8.x" in studio_doc
    assert ">=3.5.2,<4.0.0" in studio_doc
    assert "http://127.0.0.1:27185/mcp" in studio_doc
    assert "KICAD_MCP_LEGACY_SSE=true" in studio_doc
    assert "kicad-mcp-pro/mcp/workflows/manufacturing-export/" in studio_doc
    assert "workflows/manufacturing-export.md" in mkdocs


def test_built_distributions_include_runtime_entrypoint(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required for the packaging smoke test")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]

    dist_dir = tmp_path / "dist"
    result = subprocess.run(
        [uv, "build", "--out-dir", str(dist_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and "Required uv version" in (result.stdout + result.stderr):
        pytest.skip("Host uv version does not match repo-pinned uv required-version")
    assert result.returncode == 0, result.stdout + result.stderr

    wheel = next(dist_dir.glob("*.whl"))
    sdist = next(dist_dir.glob("*.tar.gz"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        entry_points = archive.read(f"kicad_mcp_pro-{version}.dist-info/entry_points.txt").decode()

    assert "kicad_mcp/server.py" in names
    assert "kicad_mcp/tools/export.py" in names
    assert "kicad_mcp/models/export.py" in names
    assert "kicad_mcp/utils/sexpr.py" in names
    assert "kicad_mcp/dfm_profiles/jlcpcb_standard.json" in names
    assert "kicad-mcp-pro = kicad_mcp.server:main" in entry_points

    with tarfile.open(sdist) as archive:
        sdist_names = set(archive.getnames())
    assert any(name.endswith("/src/kicad_mcp/server.py") for name in sdist_names)
    assert any(name.endswith("/src/kicad_mcp/tools/export.py") for name in sdist_names)

    install_dir = tmp_path / "install"
    install = subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            sys.executable,
            "--no-deps",
            "--target",
            str(install_dir),
            str(wheel),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert install.returncode == 0, install.stdout + install.stderr

    env = os.environ.copy()
    env["PYTHONPATH"] = str(install_dir)
    smoke = subprocess.run(
        [
            sys.executable,
            "-c",
            "import kicad_mcp.server; print(kicad_mcp.server.__name__)",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert smoke.returncode == 0, smoke.stdout + smoke.stderr
    assert smoke.stdout.strip() == "kicad_mcp.server"


def test_docs_workflow_uses_properdocs_to_avoid_mkdocs_2_warning() -> None:
    workflow = (ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")

    assert "uv run properdocs build -f mkdocs.yml --strict" in workflow
    assert "python -m mkdocs build" not in workflow


def test_plugin_manifest_version_tracks_package_and_is_release_managed() -> None:
    """The Claude plugin manifest version must match the package and be release-managed.

    It drifted (3.19.0 vs 3.24.0) because release-please did not bump it; this locks
    the version to pyproject and asserts the manifest is listed as a release extra-file
    so future releases keep it in sync automatically.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert plugin["version"] == version

    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    extra_files = config["packages"]["."]["extra-files"]
    tracked = {(entry["path"], entry.get("jsonpath")) for entry in extra_files}
    assert (".claude-plugin/plugin.json", "$.version") in tracked
