from __future__ import annotations

import json
import platform
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from scripts import check_docker_metadata

ROOT = Path(__file__).resolve().parents[2]


def test_docker_metadata_action_pin_contract_accepts_sha_rotation() -> None:
    action = "docker/setup-qemu-action"
    workflow = f"uses: {action}@{'a' * 40}"

    assert check_docker_metadata._has_sha_pinned_action(workflow, action)
    assert not check_docker_metadata._has_sha_pinned_action(f"uses: {action}@v3", action)
    assert not check_docker_metadata._has_sha_pinned_action(workflow, "docker/setup-buildx-action")


def _docker() -> str:
    if platform.system() == "Windows":
        pytest.skip("Docker image smoke test is covered on Linux runners")

    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is not available")
    try:
        info = subprocess.run(
            [docker, "info"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        if info.returncode != 0:
            pytest.skip(
                f"Docker daemon is not available: {info.stderr.strip() or info.stdout.strip()}"
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"Docker cannot be executed: {exc}")
    return docker


def test_docker_image_builds_and_exposes_stdio_cli_smoke() -> None:
    docker = _docker()
    tag = f"kicad-mcp-pro:test-{uuid.uuid4().hex[:12]}"
    try:
        build = subprocess.run(
            [docker, "build", "-t", tag, "."],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        assert build.returncode == 0, build.stdout + build.stderr

        inspect = subprocess.run(
            [docker, "image", "inspect", tag],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        assert inspect.returncode == 0, inspect.stdout + inspect.stderr
        config = json.loads(inspect.stdout)[0]["Config"]
        assert config["User"] == "kicadmcp"
        assert config["Entrypoint"] == ["kicad-mcp-pro-entrypoint"]
        assert config["Cmd"] == ["--transport", "streamable-http"]
        assert "3334/tcp" in config["ExposedPorts"]
        assert "KICAD_MCP_HOST=0.0.0.0" in config["Env"]
        assert "KICAD_MCP_TRANSPORT=streamable-http" in config["Env"]

        help_result = subprocess.run(
            [docker, "run", "--rm", tag, "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        assert help_result.returncode == 0, help_result.stdout + help_result.stderr
        assert "KiCad MCP Pro server" in help_result.stdout

        explicit_help = subprocess.run(
            [docker, "run", "--rm", tag, "kicad-mcp-pro", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        assert explicit_help.returncode == 0, explicit_help.stdout + explicit_help.stderr
        assert "KiCad MCP Pro server" in explicit_help.stdout

        health = subprocess.run(
            [
                docker,
                "run",
                "--rm",
                "-e",
                "KICAD_MCP_AUTH_TOKEN=test-token-with-at-least-32-characters",
                tag,
                "health",
                "--json",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        assert health.returncode == 0, health.stdout + health.stderr
        payload = json.loads(health.stdout)
        assert payload["ok"] is True
        assert payload["kicad"]["ipc_reachable"] is False
    finally:
        subprocess.run(
            [docker, "image", "rm", "-f", tag],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )


def test_docker_healthcheck_uses_machine_readable_health_endpoint() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    health_path = "/api" + "/health"

    assert "HEALTHCHECK" in dockerfile
    assert health_path in dockerfile
    assert "127.0.0.1:3334/').status" not in dockerfile
