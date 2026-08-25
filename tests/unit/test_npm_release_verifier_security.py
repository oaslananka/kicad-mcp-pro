from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_npm_release_verifier_security_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for npm release verifier security tests")

    subprocess.run(
        [node, "--test", "tests/js/verify-npm-release-security.test.mjs"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
