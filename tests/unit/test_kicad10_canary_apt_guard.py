"""Ensure KiCad 10 CI never falls back to stale archive packages on PPA outage."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = (
    ("kicad-live-e2e.yml", "Install KiCad 10.0.x CLI"),
    ("dev-bootstrap.yml", "Install KiCad 10.0.6 CLI"),
)


def _install_prelude(filename: str, step_name: str) -> str:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / filename).read_text())
    steps = [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == step_name
    ]
    assert len(steps) == 1
    script: str = steps[0]["run"]
    assert "APT::Update::Error-Mode=any" in script
    assert 'test "$(kicad-cli version)" = "10.0.6"' in script
    assert "sudo DEBIAN_FRONTEND=noninteractive apt-get" in script
    return script.split("sudo DEBIAN_FRONTEND=noninteractive apt-get", 1)[0]


@pytest.mark.parametrize(("filename", "step_name"), WORKFLOWS)
@pytest.mark.parametrize(
    ("candidate", "fail_update", "should_pass"),
    [
        ("6.0.2+dfsg-1", False, False),
        ("(none)", False, False),
        ("10.0.7-1", False, False),
        ("10.0.6-1", False, True),
        ("10.0.6-1", True, False),
    ],
)
def test_canary_installer_does_not_use_stale_or_unavailable_packages(
    tmp_path: Path,
    filename: str,
    step_name: str,
    candidate: str,
    fail_update: bool,
    should_pass: bool,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sudo = bin_dir / "sudo"
    sudo.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "${FAKE_UPDATE_FAILURE:-0}" == 1 && "$*" == *" update" ]]; '
        "then exit 42; fi\n"
        "exit 0\n"
    )
    sudo.chmod(0o755)
    apt_cache = bin_dir / "apt-cache"
    apt_cache.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'kicad:\\n  Installed: (none)\\n  Candidate: %s\\n' "
        '"${FAKE_KICAD_CANDIDATE}"\n'
    )
    apt_cache.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_KICAD_CANDIDATE"] = candidate
    env["FAKE_UPDATE_FAILURE"] = "1" if fail_update else "0"
    result = subprocess.run(
        ["/usr/bin/bash", "-c", _install_prelude(filename, step_name)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert (result.returncode == 0) is should_pass, result.stderr
    if not should_pass and not fail_update:
        assert "refusing fallback" in result.stderr
