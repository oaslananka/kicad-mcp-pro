"""Validate Docker and OCI metadata used by release packaging."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT
MCP_SERVER_NAME = "io.github.oaslananka/kicad-mcp-pro"
GHCR_IMAGE = "ghcr.io/oaslananka/kicad-mcp-pro"
OLD_GHCR_IMAGE = "ghcr.io/oaslananka/kicad-mcp-pro/kicad-mcp-pro"


def _read(path: str) -> str:
    return (PACKAGE_ROOT / path).read_text(encoding="utf-8")


def _read_repo(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _uv_required_version() -> str | None:
    try:
        config = tomllib.loads(_read("uv.toml"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return None
    if version := config.get("required-version"):
        return str(version)
    return None


def main() -> int:
    errors: list[str] = []
    uv_version = _uv_required_version()
    if uv_version is None:
        errors.append("uv.toml must define a valid required-version")
    dockerfiles = {"Dockerfile": _read("Dockerfile")}

    for path, content in dockerfiles.items():
        required = [
            f'io.modelcontextprotocol.server.name="{MCP_SERVER_NAME}"',
            'org.opencontainers.image.source="https://github.com/oaslananka/kicad-mcp-pro"',
            "ARG KICAD_MCP_VERSION",
            "ARG VCS_REF",
        ]
        for marker in required:
            if marker not in content:
                errors.append(f"{path} is missing {marker}")
        if "@sha256:" not in content:
            errors.append(f"{path} must pin Docker base images by digest")
        if uv_version is not None and f"ARG UV_VERSION={uv_version}" not in content:
            errors.append(f"{path} must pin ARG UV_VERSION={uv_version}")
        if "EXPOSE 3334" not in content:
            errors.append(f"{path} must expose 3334")
        if 'CMD ["--transport", "streamable-http"]' not in content:
            errors.append(f"{path} must default to streamable HTTP")
        if "ghcr.io/astral-sh/uv:${UV_VERSION}@sha256:" not in content:
            errors.append(f"{path} must install uv from a digest-pinned image")
        if "COPY --from=uv-bin /uv /usr/local/bin/uv" not in content:
            errors.append(f"{path} must copy uv from the pinned uv image")
        if "uv pip install --system --no-cache --require-hashes" not in content:
            errors.append(f"{path} must install runtime dependencies with hash enforcement")

    dockerfile = dockerfiles["Dockerfile"]
    if "python:3.13.12-alpine3.22@sha256:" not in dockerfile:
        errors.append("Dockerfile must use the Trivy-clean pinned Python Alpine base")
    if (
        "ENV PYTHONDONTWRITEBYTECODE=1" not in dockerfile
        or "KICAD_MCP_HOST=0.0.0.0" not in dockerfile
    ):
        errors.append("Dockerfile must bind streamable HTTP to all container interfaces by default")
    if "ARG KICAD_CLI_APK_PACKAGE" not in dockerfile:
        errors.append("Dockerfile must support build-time KiCad CLI package installation via APK")
    if "apk upgrade --no-cache" not in dockerfile:
        errors.append("Dockerfile must upgrade Alpine packages without persisting apk cache")
    if 'apk add --no-cache "${KICAD_CLI_APK_PACKAGE}"' not in dockerfile:
        errors.append("Dockerfile must install the optional KiCad CLI APK package without cache")
    if "addgroup -S kicadmcp" not in dockerfile or "adduser -S -G kicadmcp" not in dockerfile:
        errors.append("Dockerfile must create the non-root runtime user with Alpine tools")
    compose = _read("docker-compose.yml")
    if ":latest" in compose:
        errors.append("docker-compose.yml must not use :latest images")
    if "ghcr.io/freerouting/freerouting:2.1.0@sha256:" not in compose:
        errors.append("docker-compose.yml must pin the freerouting image by digest")

    docker_workflow = _read_repo(".github/workflows/publish-mcp-registry.yml")
    if "type=raw,value=latest" in docker_workflow:
        errors.append("publish-mcp-registry.yml must not publish a mutable latest tag")

    container_workflow = _read_repo(".github/workflows/publish-mcp-container.yml")
    workflow_markers = {
        GHCR_IMAGE: "container workflow must publish the canonical GHCR image",
        "mcp-server-v": "container workflow must only publish tagged MCP server releases",
        f"{GHCR_IMAGE}:latest": "container workflow must publish latest for stable releases",
        "linux/amd64,linux/arm64": "container workflow must build amd64 and arm64 images",
        "outputs: type=cacheonly": "container workflow must verify multi-arch builds on PRs",
        "packages: write": "container workflow must have GHCR package write permission",
        "id-token: write": "container workflow must have OIDC permission for signing",
        "docker/setup-qemu-action@ce360397dd3f832beb865e1373c09c0e9f86d70a": (
            "container workflow must pin setup-qemu-action"
        ),
        "tonistiigi/binfmt:qemu-v10.0.4@sha256:": (
            "container workflow must pin the QEMU binfmt image by digest"
        ),
        "docker/setup-buildx-action@d7f5e7f509e45cec5c76c4d5afdd7de93d0b3df5": (
            "container workflow must pin setup-buildx-action"
        ),
        "moby/buildkit:v0.26.2@sha256:": (
            "container workflow must pin the BuildKit driver image by digest"
        ),
        "docker/login-action@650006c6eb7dba73a995cc03b0b2d7f5ca915bee": (
            "container workflow must pin docker/login-action"
        ),
        "docker/metadata-action@80c7e94dd9b9319bd5eb7a0e0fe9291e23a2a2e9": (
            "container workflow must pin docker/metadata-action"
        ),
        "docker/build-push-action@f9f3042f7e2789586610d6e8b85c8f03e5195baf": (
            "container workflow must pin docker/build-push-action"
        ),
        "aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25": (
            "container workflow must pin trivy-action"
        ),
        "version: v0.70.0": "container workflow must pin Trivy CLI",
        "sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6": (
            "container workflow must pin cosign-installer"
        ),
        "cosign-release: v3.0.6": "container workflow must pin cosign CLI",
        "cosign sign --yes": "container workflow must sign the image digest",
        "sbom: true": "container workflow must attach a BuildKit SBOM",
        "provenance: mode=max": "container workflow must attach provenance",
    }
    for marker, message in workflow_markers.items():
        if marker not in container_workflow:
            errors.append(message)

    docs_to_scan = [
        PACKAGE_ROOT / "docs" / "install" / "docker.md",
        PACKAGE_ROOT / "docs" / "deployment" / "docker.md",
        PACKAGE_ROOT / "docs" / "publishing.md",
        REPO_ROOT / "docs" / "deployment" / "docker.md",
    ]
    for doc_path in docs_to_scan:
        text = doc_path.read_text(encoding="utf-8")
        if OLD_GHCR_IMAGE in text:
            errors.append(f"{doc_path.relative_to(REPO_ROOT)} must not use old GHCR namespace")
    docker_docs = "\n".join(path.read_text(encoding="utf-8") for path in docs_to_scan)
    for marker in (
        "KICAD_MCP_PROJECT_DIR",
        "KICAD_MCP_AUTH_TOKEN",
        "KICAD_MCP_TRANSPORT",
        "ChatGPT connector",
        "https://www.kicad.org/about/licenses/",
    ):
        if marker not in docker_docs:
            errors.append(f"Docker docs must document {marker}")

    compose_example = _read_repo("examples/mcp-docker/docker-compose.yml")
    if f"{GHCR_IMAGE}:latest" not in compose_example:
        errors.append("examples/mcp-docker/docker-compose.yml must use the published image")
    if "read_only: true" not in compose_example:
        errors.append("examples/mcp-docker/docker-compose.yml must mount projects read-only")

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Docker metadata validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
