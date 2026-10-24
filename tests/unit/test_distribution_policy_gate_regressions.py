"""Preserve strict release and workflow security diagnostics after decomposition."""

from pathlib import Path

import pytest

from scripts import check_docker_metadata as docker
from scripts import check_github_actions_policy as actions


def test_dockerfile_runtime_accepts_current_pinned_python_base() -> None:
    dockerfile = (docker.PACKAGE_ROOT / "Dockerfile").read_text(encoding="utf-8")
    errors: list[str] = []

    docker._check_dockerfile_runtime(dockerfile, errors)

    assert errors == []


@pytest.mark.parametrize("replacement", ["3.14.7-slim@sha256:", "3.14.9-slim:"])
def test_dockerfile_runtime_rejects_stale_or_unpinned_python_base(replacement: str) -> None:
    dockerfile = (docker.PACKAGE_ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerfile = dockerfile.replace("3.14.9-slim@sha256:", replacement)
    errors: list[str] = []

    docker._check_dockerfile_runtime(dockerfile, errors)

    assert "Dockerfile must use the pinned Python 3.14.8 slim base for KiCad 10 stages" in errors


def test_dockerfile_guard_accumulates_all_missing_pins(monkeypatch) -> None:
    monkeypatch.setattr(docker, "_read", lambda path: "FROM python:untrusted\n")
    errors: list[str] = []
    docker._check_dockerfile(errors, "0.12.19")
    assert "Dockerfile must pin Docker base images by digest" in errors
    assert "Dockerfile must pin ARG UV_VERSION=0.12.19" in errors
    assert "Dockerfile must install runtime dependencies with hash enforcement" in errors
    assert "Dockerfile must create the non-root runtime user with Alpine tools" in errors


def test_compose_guard_rejects_mutable_tag_and_unpinned_router(monkeypatch) -> None:
    monkeypatch.setattr(docker, "_read", lambda path: "image: ghcr.io/example:latest\n")
    errors: list[str] = []
    docker._check_compose(errors)
    assert "docker-compose.yml must not use :latest images" in errors
    assert "docker-compose.yml must pin the freerouting image by digest" in errors
    assert "docker-compose.yml must declare the loopback-proxy HTTP boundary" in errors


def test_actions_guard_does_not_allow_unpinned_third_party_action() -> None:
    errors: list[str] = []
    repository = actions._check_action_reference(
        "untrusted/action@v3", Path("unsafe.yml"), {"actions"}, set(), set(), errors
    )
    assert repository == "untrusted/action"
    assert errors == [
        "unsafe.yml: action is not pinned to a 40-character SHA: untrusted/action@v3",
        "unsafe.yml: action repository is not allowlisted: untrusted/action",
    ]


def test_actions_guard_preserves_workflow_write_scope_rejection() -> None:
    errors: list[str] = []
    writes = actions._check_workflow_permissions(
        Path("unsafe.yml"),
        {
            "permissions": {"contents": "read", "packages": "write"},
            "jobs": {
                "publish": {
                    "permissions": {"contents": "read", "packages": "write"},
                }
            },
        },
        errors,
    )
    assert writes == {"publish": ["packages"]}
    assert errors == ["unsafe.yml: write permissions must be scoped to a job: ['packages']"]
