from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT
WRAPPER_ROOT = ROOT / "packages" / "mcp-npm"


def test_npm_wrapper_package_is_separate_from_private_root_package() -> None:
    root_package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    wrapper_package = json.loads((WRAPPER_ROOT / "package.json").read_text(encoding="utf-8"))

    assert root_package["private"] is True
    assert wrapper_package["name"] == "kicad-mcp-pro"
    assert wrapper_package["bin"]["kicad-mcp-pro"] == "bin/kicad-mcp-pro.js"
    assert "scripts/" in wrapper_package["files"]
    assert wrapper_package["mcpName"] == "io.github.oaslananka/kicad-mcp-pro"


def test_npm_wrapper_fails_clearly_when_uvx_is_missing() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")

    env = os.environ.copy()
    env["PATH"] = ""
    result = subprocess.run(
        [node, str(WRAPPER_ROOT / "bin" / "kicad-mcp-pro.js"), "--help"],
        cwd=WRAPPER_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 127
    assert "uvx was not found on PATH." in result.stderr
    assert "does not install the Python package" in result.stderr


def test_npm_wrapper_build_smoke_is_cross_platform() -> None:
    wrapper_package = json.loads((WRAPPER_ROOT / "package.json").read_text(encoding="utf-8"))

    assert wrapper_package["scripts"]["build"] == "node scripts/build-smoke.js"
    assert "|| true" not in wrapper_package["scripts"]["build"]


def test_npm_wrapper_build_smoke_tolerates_unpublished_python_package() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")

    env = os.environ.copy()
    env["PATH"] = ""
    result = subprocess.run(
        [node, str(WRAPPER_ROOT / "scripts" / "build-smoke.js")],
        cwd=WRAPPER_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0
    assert "npm launcher smoke skipped: uvx is not available on PATH." in result.stderr
    assert "wrapper itself still exits non-zero for users" in result.stderr


def test_windows_launcher_uses_executable_not_batch_or_directory() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")
    script = """
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path').win32;
const source = fs.readFileSync(process.argv[1], 'utf8');
let selected;
const mockFs = {
  existsSync: () => true,
  statSync: candidate => ({isFile: () => candidate.startsWith('second')}),
};
vm.runInNewContext(source, {
  require: name => ({
    'node:fs': mockFs, 'node:path': path,
    'node:child_process': {spawn: candidate => {
      selected = candidate; return {on() {}};
    }},
    '../package.json': {version: '1.0.0'},
  })[name],
  process: {platform: 'win32', env: {PATH: 'first;second'}, argv: []},
  console,
});
if (selected !== path.join('second', 'uvx.exe')) throw Error(selected);
"""
    result = subprocess.run(
        [node, "-e", script, str(WRAPPER_ROOT / "bin" / "kicad-mcp-pro.js")],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
