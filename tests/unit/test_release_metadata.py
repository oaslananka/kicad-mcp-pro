from __future__ import annotations

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
REGISTRY_SCHEMA = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"


def test_release_metadata_is_synchronised() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]
    server_json = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    mcp_json = json.loads((ROOT / "mcp.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    mkdocs = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    assert server_json["$schema"] == REGISTRY_SCHEMA
    assert server_json["version"] == version
    assert server_json["packages"][0]["version"] == version
    assert mcp_json["version"] == version
    assert "<!-- mcp-name: io.github.oaslananka/kicad-mcp-pro -->" in readme
    assert "development/v2-migration.md" in mkdocs
    assert "| `2.x`   | Yes" in security
    assert "CVE-2025-69872" in security


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
            sys.executable,
            "-m",
            "pip",
            "install",
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
