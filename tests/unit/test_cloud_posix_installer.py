"""Exercise the real Bash installer through a local owner pseudo-terminal."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("script") is None,
    reason="Linux util-linux pseudo-terminal acceptance",
)

_INSTALLER = Path(__file__).resolve().parents[2] / "scripts" / "install-cloud.sh"


@pytest.mark.parametrize("scenario", ["install", "repeat", "offline", "running"])
def test_posix_one_command_installer(tmp_path: Path, scenario: str) -> None:
    bin_dir = tmp_path / "mock-bin"
    bin_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    data = home / "data"
    app = data / "KiCadMCPPro"
    cli = app / "bin" / "kicad-mcp-pro"
    cli.parent.mkdir(parents=True)
    log = tmp_path / "events"
    cli_content = """#!/bin/bash
if [[ "$1" == --version ]]; then exit 0; fi
[[ "$*" == cloud && -t 0 ]] || exit 97
echo connected >> "$TEST_LOG"
"""
    uv = bin_dir / "uv"
    uv.write_text(
        """#!/bin/bash
if [[ "$1" == --version ]]; then exit 0; fi
echo "$*" >> "$TEST_LOG"
if [[ "$TEST_SCENARIO" == offline ]]; then exit 1; fi
mkdir -p "$UV_TOOL_BIN_DIR"
cp "$TEST_CLI_TEMPLATE" "$UV_TOOL_BIN_DIR/kicad-mcp-pro"
chmod 700 "$UV_TOOL_BIN_DIR/kicad-mcp-pro"
"""
    )
    uv.chmod(0o700)
    template = tmp_path / "cli"
    template.write_text(cli_content)
    if scenario != "install":
        cli.write_text(cli_content)
        cli.chmod(0o700)
    if scenario == "running":
        (app / "installer.lock").mkdir()
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_DATA_HOME": str(data),
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "TEST_LOG": str(log),
        "TEST_SCENARIO": scenario,
        "TEST_CLI_TEMPLATE": str(template),
    }
    # Match the actual documented curl | bash shape without internet or a real install.
    command = f"cat {shlex.quote(str(_INSTALLER))} | bash"
    result = subprocess.run(
        [str(shutil.which("script")), "-qec", command, "/dev/null"],
        env=env,
        capture_output=True,
        timeout=20,
        check=False,
    )
    if scenario == "running":
        assert result.returncode != 0
        assert not log.exists()
        assert (app / "installer.lock").is_dir()
    else:
        assert result.returncode == 0, result.stdout.decode(errors="replace")
        assert log.read_text().splitlines() == ["tool install --upgrade kicad-mcp-pro", "connected"]
        assert not (app / "installer.lock").exists()
