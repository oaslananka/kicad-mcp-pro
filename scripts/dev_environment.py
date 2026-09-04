"""Repository-scoped development toolchain contract and bootstrap helpers."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARCHITECTURES = ("aarch64", "x86_64")
_DOWNLOAD_TOOLS = ("node", "rustup", "task", "uv")


@dataclass(frozen=True)
class DownloadSpec:
    """One checksum-pinned native tool download."""

    url: str
    sha256: str

    @property
    def archive_name(self) -> str:
        return Path(urlparse(self.url).path).name


@dataclass(frozen=True)
class DevToolchainContract:
    """Exact repository development toolchain contract."""

    python_version: str
    uv_version: str
    node_version: str
    pnpm_version: str
    task_version: str
    rustup_version: str
    rust_toolchain: str
    kicad_cli_version: str
    supported_architectures: tuple[str, ...]
    downloads: dict[str, dict[str, DownloadSpec]]


@dataclass(frozen=True)
class BootstrapPlan:
    """Repository-scoped destinations and exact versions used by bootstrap."""

    root: Path
    tool_root: Path
    cache_root: Path
    venv_root: Path
    environment_file: Path
    install_optional: bool
    required_tools: tuple[str, ...]
    optional_tools: tuple[str, ...]
    versions: dict[str, str]
    contract: DevToolchainContract

    def as_json(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "toolRoot": str(self.tool_root),
            "cacheRoot": str(self.cache_root),
            "venvRoot": str(self.venv_root),
            "environmentFile": str(self.environment_file),
            "installOptional": self.install_optional,
            "requiredTools": list(self.required_tools),
            "optionalTools": list(self.optional_tools),
            "versions": self.versions,
        }


def _parse_contract_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid toolchain contract line {line_number}: {raw_line!r}")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not value:
            raise ValueError(f"Invalid toolchain contract line {line_number}: {raw_line!r}")
        if key in values:
            raise ValueError(f"Duplicate toolchain contract key: {key}")
        values[key] = value
    return values


def _required(values: dict[str, str], key: str) -> str:
    try:
        return values[key]
    except KeyError as exc:
        raise ValueError(f"Missing toolchain contract key: {key}") from exc


def load_toolchain_contract(root: Path) -> DevToolchainContract:
    """Load and validate the exact repository development toolchain contract."""

    values = _parse_contract_file(root / "scripts" / "dev-toolchain.env")
    if _required(values, "KICAD_MCP_DEV_TOOLCHAIN_SCHEMA") != "1":
        raise ValueError("Unsupported development toolchain schema")

    versions = {
        "python_version": _required(values, "PYTHON_VERSION"),
        "uv_version": _required(values, "UV_VERSION"),
        "node_version": _required(values, "NODE_VERSION"),
        "pnpm_version": _required(values, "PNPM_VERSION"),
        "task_version": _required(values, "TASK_VERSION"),
        "rustup_version": _required(values, "RUSTUP_VERSION"),
        "rust_toolchain": _required(values, "RUST_TOOLCHAIN"),
        "kicad_cli_version": _required(values, "KICAD_CLI_VERSION"),
    }
    for name, version in versions.items():
        if not _VERSION.fullmatch(version):
            raise ValueError(f"Invalid exact version for {name}: {version}")

    architectures = tuple(sorted(_required(values, "SUPPORTED_ARCHITECTURES").split(",")))
    if architectures != _ARCHITECTURES:
        raise ValueError(f"Unsupported architecture contract: {architectures}")

    downloads: dict[str, dict[str, DownloadSpec]] = {}
    for architecture in architectures:
        architecture_downloads: dict[str, DownloadSpec] = {}
        suffix = architecture.upper()
        for tool in _DOWNLOAD_TOOLS:
            prefix = f"{tool.upper()}_{suffix}"
            url = _required(values, f"{prefix}_URL")
            sha256 = _required(values, f"{prefix}_SHA256")
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError(f"Invalid HTTPS URL for {tool}/{architecture}: {url}")
            if not _SHA256.fullmatch(sha256):
                raise ValueError(f"Invalid SHA-256 for {tool}/{architecture}: {sha256}")
            architecture_downloads[tool] = DownloadSpec(url=url, sha256=sha256)
        downloads[architecture] = architecture_downloads

    return DevToolchainContract(
        supported_architectures=architectures,
        downloads=downloads,
        **versions,
    )


def build_bootstrap_plan(
    root: Path,
    *,
    core_only: bool,
    contract_root: Path | None = None,
) -> BootstrapPlan:
    """Build an immutable root-contained bootstrap plan."""

    resolved = root.resolve()
    contract = load_toolchain_contract((contract_root or resolved).resolve())
    return BootstrapPlan(
        root=resolved,
        tool_root=resolved / ".dev-tools",
        cache_root=resolved / ".dev-cache",
        venv_root=resolved / ".venv",
        environment_file=resolved / ".dev-env.sh",
        install_optional=not core_only,
        required_tools=("node", "pnpm", "python", "uv"),
        optional_tools=("cargo", "rustc", "task"),
        versions={
            "node": contract.node_version,
            "pnpm": contract.pnpm_version,
            "python": contract.python_version,
            "rust": contract.rust_toolchain,
            "rustup": contract.rustup_version,
            "task": contract.task_version,
            "uv": contract.uv_version,
        },
        contract=contract,
    )


def download_verified(url: str, destination: Path, expected_sha256: str) -> Path:
    """Download to a temporary sibling and publish only after SHA-256 verification."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    parsed = urlparse(url)
    if parsed.scheme not in {"file", "https"}:
        raise ValueError(f"Unsupported download URL scheme: {parsed.scheme}")
    try:
        digest = hashlib.sha256()
        with (
            urllib.request.urlopen(url, timeout=120) as response,  # noqa: S310
            temporary.open("wb") as output,
        ):
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
        actual = digest.hexdigest()
        if actual != expected_sha256:
            raise ValueError(
                f"SHA-256 mismatch for {url}: expected {expected_sha256}, got {actual}"
            )
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
    return destination


def _path_within(root: Path, candidate: Path) -> bool:
    return candidate == root or root in candidate.parents


def _safe_tar_filter(member: tarfile.TarInfo, destination: str) -> tarfile.TarInfo:
    """Apply a Python-version-independent safe extraction policy."""

    destination_root = Path(destination).resolve()
    target = (destination_root / member.name).resolve()
    if not _path_within(destination_root, target):
        raise ValueError(f"Archive member resolves outside destination: {member.name}")

    if not (member.isreg() or member.isdir() or member.issym() or member.islnk()):
        raise ValueError(f"Unsupported archive member type: {member.name}")

    if member.issym():
        link_target = (target.parent / member.linkname).resolve()
    elif member.islnk():
        link_target = (destination_root / member.linkname).resolve()
    else:
        link_target = None
    if link_target is not None and not _path_within(destination_root, link_target):
        raise ValueError(f"Archive link resolves outside destination: {member.name}")

    member.uid = None
    member.gid = None
    member.uname = None
    member.gname = None
    if member.isdir() or member.issym():
        member.mode = None
    elif member.mode is not None:
        mode = member.mode & 0o755
        if not mode & 0o100:
            mode &= ~0o111
        member.mode = mode | 0o600
    return member


def safe_extract_tar(archive: Path, destination: Path) -> None:
    """Extract a native tool archive without allowing unsafe members or paths."""

    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as bundle:
        bundle.extractall(destination, filter=_safe_tar_filter)  # noqa: S202


def _host_architecture() -> str:
    machine = platform.machine().lower()
    architecture = {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    if platform.system() != "Linux":
        raise RuntimeError("The repository bootstrap currently supports Linux only")
    if architecture not in _ARCHITECTURES:
        raise RuntimeError(
            "Unsupported bootstrap architecture "
            f"{machine!r}; supported: {', '.join(_ARCHITECTURES)}"
        )
    return architecture


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=capture,
        check=True,
    )


def _install_archive_binary(
    plan: BootstrapPlan,
    *,
    architecture: str,
    tool: str,
    version: str,
    binary_name: str,
) -> Path:
    destination = plan.tool_root / tool / version / "bin" / binary_name
    if destination.is_file():
        return destination
    spec = plan.contract.downloads[architecture][tool]
    download = plan.cache_root / "downloads" / spec.archive_name
    download_verified(spec.url, download, spec.sha256)
    with tempfile.TemporaryDirectory(prefix=f"kicad-mcp-{tool}-") as temporary:
        extracted = Path(temporary)
        safe_extract_tar(download, extracted)
        candidates = [path for path in extracted.rglob(binary_name) if path.is_file()]
        if len(candidates) != 1:
            raise RuntimeError(f"Expected one {binary_name} in {download}, found {len(candidates)}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidates[0], destination)
        destination.chmod(destination.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return destination


def _install_node(plan: BootstrapPlan, architecture: str) -> Path:
    destination = plan.tool_root / "node" / plan.contract.node_version
    binary = destination / "bin" / "node"
    npm = destination / "bin" / "npm"
    if binary.is_file() and npm.exists():
        return destination
    if destination.exists():
        shutil.rmtree(destination)
    spec = plan.contract.downloads[architecture]["node"]
    download = plan.cache_root / "downloads" / spec.archive_name
    download_verified(spec.url, download, spec.sha256)
    with tempfile.TemporaryDirectory(prefix="kicad-mcp-node-") as temporary:
        extracted = Path(temporary)
        safe_extract_tar(download, extracted)
        roots = [path for path in extracted.iterdir() if path.is_dir()]
        if len(roots) != 1 or not (roots[0] / "bin" / "node").is_file():
            raise RuntimeError(f"Unexpected Node.js archive layout: {download}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(roots[0], destination, symlinks=True)
    return destination


def _environment(plan: BootstrapPlan) -> dict[str, str]:
    bins = [
        plan.venv_root / "bin",
        plan.tool_root / "uv" / plan.contract.uv_version / "bin",
        plan.tool_root / "node" / plan.contract.node_version / "bin",
        plan.tool_root / "pnpm" / plan.contract.pnpm_version / "bin",
        plan.tool_root / "task" / plan.contract.task_version / "bin",
        plan.tool_root / "cargo" / "bin",
    ]
    env = dict(os.environ)
    env.update(
        {
            "CARGO_HOME": str(plan.tool_root / "cargo"),
            "COREPACK_HOME": str(plan.cache_root / "corepack"),
            "NPM_CONFIG_CACHE": str(plan.cache_root / "npm"),
            "PATH": os.pathsep.join([*(str(path) for path in bins), env.get("PATH", "")]),
            "PNPM_HOME": str(plan.tool_root / "pnpm" / plan.contract.pnpm_version / "bin"),
            "RUSTUP_HOME": str(plan.tool_root / "rustup-home"),
            "UV_CACHE_DIR": str(plan.cache_root / "uv"),
            "UV_PYTHON_INSTALL_DIR": str(plan.tool_root / "python"),
        }
    )
    return env


def _install_pnpm(plan: BootstrapPlan, env: dict[str, str], *, capture: bool = False) -> Path:
    prefix = plan.tool_root / "pnpm" / plan.contract.pnpm_version
    binary = prefix / "bin" / "pnpm"
    if binary.is_file():
        return binary
    npm = plan.tool_root / "node" / plan.contract.node_version / "bin" / "npm"
    prefix.mkdir(parents=True, exist_ok=True)
    _run(
        [
            str(npm),
            "install",
            "--global",
            "--prefix",
            str(prefix),
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            f"pnpm@{plan.contract.pnpm_version}",
        ],
        cwd=plan.root,
        env=env,
        capture=capture,
    )
    if not binary.is_file():
        raise RuntimeError("pnpm installation did not create the expected binary")
    return binary


def _install_rust(
    plan: BootstrapPlan,
    architecture: str,
    env: dict[str, str],
    *,
    capture: bool = False,
) -> None:
    rustc = plan.tool_root / "cargo" / "bin" / "rustc"
    rust_ready = False
    if rustc.is_file():
        completed = _run([str(rustc), "--version"], cwd=plan.root, env=env, capture=True)
        rust_ready = plan.contract.rust_toolchain in completed.stdout
    if not rust_ready:
        spec = plan.contract.downloads[architecture]["rustup"]
        installer = plan.tool_root / "rustup" / plan.contract.rustup_version / "bin" / "rustup-init"
        if not installer.is_file():
            download_verified(spec.url, installer, spec.sha256)
            installer.chmod(installer.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
        _run(
            [
                str(installer),
                "-y",
                "--no-modify-path",
                "--profile",
                "minimal",
                "--default-toolchain",
                plan.contract.rust_toolchain,
            ],
            cwd=plan.root,
            env=env,
            capture=capture,
        )
    rustup = plan.tool_root / "cargo" / "bin" / "rustup"
    _run(
        [str(rustup), "component", "add", "rustfmt", "--toolchain", plan.contract.rust_toolchain],
        cwd=plan.root,
        env=env,
        capture=capture,
    )


def _write_environment_file(plan: BootstrapPlan) -> None:
    content = f"""#!/usr/bin/env bash
# Generated by scripts/bootstrap-dev.sh. Re-run bootstrap instead of editing.
_KICAD_MCP_DEV_ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd -P)"
export UV_CACHE_DIR="${{_KICAD_MCP_DEV_ROOT}}/.dev-cache/uv"
export UV_PYTHON_INSTALL_DIR="${{_KICAD_MCP_DEV_ROOT}}/.dev-tools/python"
export NPM_CONFIG_CACHE="${{_KICAD_MCP_DEV_ROOT}}/.dev-cache/npm"
export COREPACK_HOME="${{_KICAD_MCP_DEV_ROOT}}/.dev-cache/corepack"
export CARGO_HOME="${{_KICAD_MCP_DEV_ROOT}}/.dev-tools/cargo"
export RUSTUP_HOME="${{_KICAD_MCP_DEV_ROOT}}/.dev-tools/rustup-home"
export PNPM_HOME="${{_KICAD_MCP_DEV_ROOT}}/.dev-tools/pnpm/{plan.contract.pnpm_version}/bin"
export PATH="${{_KICAD_MCP_DEV_ROOT}}/.venv/bin:${{PATH}}"
export PATH="${{_KICAD_MCP_DEV_ROOT}}/.dev-tools/uv/{plan.contract.uv_version}/bin:${{PATH}}"
export PATH="${{_KICAD_MCP_DEV_ROOT}}/.dev-tools/node/{plan.contract.node_version}/bin:${{PATH}}"
export PATH="${{PNPM_HOME}}:${{PATH}}"
export PATH="${{_KICAD_MCP_DEV_ROOT}}/.dev-tools/task/{plan.contract.task_version}/bin:${{PATH}}"
export PATH="${{CARGO_HOME}}/bin:${{PATH}}"
unset _KICAD_MCP_DEV_ROOT
"""
    plan.environment_file.write_text(content, encoding="utf-8")
    plan.environment_file.chmod(0o755)


def prepare_environment(plan: BootstrapPlan, *, capture: bool = False) -> dict[str, Any]:
    """Install the exact repository toolchain and frozen dependencies."""

    architecture = _host_architecture()
    plan.tool_root.mkdir(parents=True, exist_ok=True)
    plan.cache_root.mkdir(parents=True, exist_ok=True)
    uv = _install_archive_binary(
        plan,
        architecture=architecture,
        tool="uv",
        version=plan.contract.uv_version,
        binary_name="uv",
    )
    _install_archive_binary(
        plan,
        architecture=architecture,
        tool="uv",
        version=plan.contract.uv_version,
        binary_name="uvx",
    )
    _install_node(plan, architecture)
    env = _environment(plan)
    _install_pnpm(plan, env, capture=capture)
    if plan.install_optional:
        _install_archive_binary(
            plan,
            architecture=architecture,
            tool="task",
            version=plan.contract.task_version,
            binary_name="task",
        )
        _install_rust(plan, architecture, env, capture=capture)
        env = _environment(plan)

    _run(
        [str(uv), "python", "install", plan.contract.python_version],
        cwd=plan.root,
        env=env,
        capture=capture,
    )
    _run(
        [str(uv), "sync", "--all-extras", "--frozen", "--python", plan.contract.python_version],
        cwd=plan.root,
        env=env,
        capture=capture,
    )
    pnpm = plan.tool_root / "pnpm" / plan.contract.pnpm_version / "bin" / "pnpm"
    _run(
        [
            str(pnpm),
            "install",
            "--frozen-lockfile",
            "--store-dir",
            str(plan.cache_root / "pnpm-store"),
        ],
        cwd=plan.root,
        env=env,
        capture=capture,
    )
    _write_environment_file(plan)
    return check_prepared_environment(plan)


def _command_version(command: Path, arguments: list[str], env: dict[str, str]) -> str | None:
    if not command.is_file():
        return None
    try:
        completed = _run([str(command), *arguments], cwd=command.parent, env=env, capture=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return (completed.stdout or completed.stderr).strip().splitlines()[0]


def check_prepared_environment(plan: BootstrapPlan) -> dict[str, Any]:
    """Verify prepared tool versions without downloading or mutating."""

    if not plan.environment_file.is_file():
        return {
            "ok": False,
            "status": "not-prepared",
            "message": "Run ./scripts/bootstrap-dev.sh before --check.",
            "tools": {},
        }
    env = _environment(plan)
    commands: dict[str, tuple[Path, list[str], str]] = {
        "node": (
            plan.tool_root / "node" / plan.contract.node_version / "bin" / "node",
            ["--version"],
            plan.contract.node_version,
        ),
        "pnpm": (
            plan.tool_root / "pnpm" / plan.contract.pnpm_version / "bin" / "pnpm",
            ["--version"],
            plan.contract.pnpm_version,
        ),
        "python": (plan.venv_root / "bin" / "python", ["--version"], plan.contract.python_version),
        "uv": (
            plan.tool_root / "uv" / plan.contract.uv_version / "bin" / "uv",
            ["--version"],
            plan.contract.uv_version,
        ),
        "uvx": (
            plan.tool_root / "uv" / plan.contract.uv_version / "bin" / "uvx",
            ["--version"],
            plan.contract.uv_version,
        ),
    }
    if plan.install_optional:
        commands.update(
            {
                "cargo": (
                    plan.tool_root / "cargo" / "bin" / "cargo",
                    ["--version"],
                    plan.contract.rust_toolchain,
                ),
                "rustc": (
                    plan.tool_root / "cargo" / "bin" / "rustc",
                    ["--version"],
                    plan.contract.rust_toolchain,
                ),
                "task": (
                    plan.tool_root / "task" / plan.contract.task_version / "bin" / "task",
                    ["--version"],
                    plan.contract.task_version,
                ),
            }
        )
    tools: dict[str, Any] = {}
    ok = True
    for name, (command, arguments, expected) in commands.items():
        actual = _command_version(command, arguments, env)
        matched = actual is not None and expected in actual.lstrip("v")
        tools[name] = {"path": str(command), "expected": expected, "actual": actual, "ok": matched}
        ok = ok and matched
    return {
        "ok": ok,
        "status": "ready" if ok else "version-mismatch",
        "tools": tools,
        "root": str(plan.root),
    }


def evaluate_development_policy(development: dict[str, Any] | None) -> dict[str, Any]:
    """Evaluate source-development readiness without blocking optional/live limitations."""

    blocking: list[dict[str, str]] = []
    limitations: list[dict[str, str]] = []
    if not development or not development.get("available"):
        blocking.append({"name": "development", "reason": "source toolchain contract unavailable"})
        return {"ready": False, "blocking": blocking, "limitations": limitations}

    if not development.get("prepared"):
        blocking.append({"name": "bootstrap", "reason": "environment is not prepared"})
    if not development.get("frozen_python_ready"):
        blocking.append({"name": "python-lock", "reason": "frozen Python environment is not ready"})
    if not development.get("frozen_node_ready"):
        blocking.append({"name": "node-lock", "reason": "frozen pnpm environment is not ready"})
    for root in development.get("roots") or []:
        if not root.get("writable"):
            blocking.append(
                {
                    "name": str(root.get("name", "root")),
                    "reason": "development root is not writable",
                }
            )
    for tool in development.get("tools") or []:
        status = str(tool.get("status", "missing"))
        classification = tool.get("classification")
        item = {"name": str(tool.get("name", "tool")), "reason": f"tool status is {status}"}
        if classification == "required" and status != "ok":
            item["reason"] = f"required tool status is {status}"
            blocking.append(item)
        elif classification in {"optional", "live-kicad"} and status != "ok":
            limitations.append(item)
    return {"ready": not blocking, "blocking": blocking, "limitations": limitations}


def ci_quality_gate_commands(plan: BootstrapPlan) -> list[list[str]]:
    """Return acceptance-criteria quality gates using the prepared pnpm binary."""

    pnpm = plan.tool_root / "pnpm" / plan.contract.pnpm_version / "bin" / "pnpm"
    return [
        [str(pnpm), "run", script]
        for script in (
            "metadata:check",
            "format:check",
            "lint",
            "typecheck",
            "test:unit",
            "package:check",
        )
    ]


def _doctor_payload(plan: BootstrapPlan) -> dict[str, Any]:
    previous = os.environ.get("KICAD_MCP_REPO_PATH")
    os.environ["KICAD_MCP_REPO_PATH"] = str(plan.root)
    try:
        from kicad_mcp.diagnostics import build_doctor_report

        with contextlib.redirect_stdout(io.StringIO()):
            payload = build_doctor_report().model_dump(mode="json", by_alias=True)
    finally:
        if previous is None:
            os.environ.pop("KICAD_MCP_REPO_PATH", None)
        else:
            os.environ["KICAD_MCP_REPO_PATH"] = previous
    payload["developmentPolicy"] = evaluate_development_policy(payload.get("development"))
    return payload


def run_prepared_doctor(plan: BootstrapPlan) -> dict[str, Any]:
    """Run doctor inside the managed virtual environment created by bootstrap."""

    python = plan.venv_root / "bin" / "python"
    command = [
        str(python),
        str(plan.root / "scripts" / "dev_environment.py"),
        "--doctor",
        "--json",
        "--ci",
        "--root",
        str(plan.root),
    ]
    completed = _run(command, cwd=plan.root, env=_environment(plan), capture=True)
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise ValueError("Prepared doctor did not return a JSON object")
    return payload


def run_ci_quality_gates(plan: BootstrapPlan) -> list[dict[str, Any]]:
    """Run the agreed clean-host quality gates and return concise evidence."""

    env = _environment(plan)
    evidence: list[dict[str, Any]] = []
    for command in ci_quality_gate_commands(plan):
        completed = _run(command, cwd=plan.root, env=env, capture=True)
        evidence.append(
            {
                "command": command[2],
                "ok": True,
                "stdoutTail": completed.stdout.strip().splitlines()[-10:],
            }
        )
    kicad_cli = shutil.which("kicad-cli", path=env.get("PATH"))
    if kicad_cli is None:
        evidence.append(
            {
                "command": "test:kicad-cli-contract",
                "ok": True,
                "skipped": True,
                "reason": "kicad-cli is not installed; live capability is limited",
            }
        )
    else:
        pnpm = plan.tool_root / "pnpm" / plan.contract.pnpm_version / "bin" / "pnpm"
        completed = _run(
            [str(pnpm), "run", "test:kicad-cli-contract"],
            cwd=plan.root,
            env=env,
            capture=True,
        )
        evidence.append(
            {
                "command": "test:kicad-cli-contract",
                "ok": True,
                "stdoutTail": completed.stdout.strip().splitlines()[-10:],
            }
        )
    return evidence


def _render(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if payload.get("ok") is False:
        print(f"Development environment: {payload.get('status', 'error')}")
        if payload.get("message"):
            print(payload["message"])
        return
    if "versions" in payload and "tools" not in payload:
        print("Development bootstrap plan:")
        for name, version in sorted(payload["versions"].items()):
            print(f"- {name}: {version}")
        return
    if "developmentPolicy" in payload:
        policy = payload.get("developmentPolicy") or {}
        print(f"Development doctor: {payload.get('status', 'unknown')}")
        print(f"- development ready: {'yes' if policy.get('ready') else 'no'}")
        tools = payload.get("tools")
        if isinstance(tools, dict) and isinstance(tools.get("tool_count"), int):
            print(f"- tool count: {tools['tool_count']}")
        for item in policy.get("blocking") or []:
            print(f"- blocking: {item.get('name')}: {item.get('reason')}")
        for item in policy.get("limitations") or []:
            print(f"- limitation: {item.get('name')}: {item.get('reason')}")
        return
    print("Development environment ready.")
    for name, details in sorted((payload.get("tools") or {}).items()):
        print(f"- {name}: {details.get('actual')}")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    arguments = [argument for argument in arguments if argument != "--"]
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="Print the immutable bootstrap plan.")
    mode.add_argument(
        "--check", action="store_true", help="Verify an existing prepared environment."
    )
    mode.add_argument("--doctor", action="store_true", help="Report development capabilities.")
    parser.add_argument("--ci", action="store_true", help="Run CI verification after bootstrap.")
    parser.add_argument(
        "--core-only", action="store_true", help="Skip Task and Rust/Cargo installation."
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--root", type=Path, help="Override the prepared checkout root (tests/recovery)."
    )
    args = parser.parse_args(arguments)

    source_root = Path(__file__).resolve().parents[1]
    target_root = (args.root or source_root).resolve()
    plan = build_bootstrap_plan(target_root, core_only=args.core_only, contract_root=source_root)
    if args.plan:
        _render(plan.as_json(), json_output=args.json)
        return 0
    if args.check:
        payload = check_prepared_environment(plan)
        _render(payload, json_output=args.json)
        return 0 if payload["ok"] else 2
    if args.doctor:
        payload = _doctor_payload(plan)
        _render(payload, json_output=args.json)
        policy = payload["developmentPolicy"]
        return 0 if not args.ci or policy["ready"] else 2

    payload = prepare_environment(plan, capture=args.json)
    if not payload["ok"]:
        _render(payload, json_output=args.json)
        return 2
    if args.ci:
        doctor = run_prepared_doctor(plan)
        payload["doctor"] = doctor
        if not doctor["developmentPolicy"]["ready"]:
            _render(payload, json_output=args.json)
            return 2
        payload["qualityGates"] = run_ci_quality_gates(plan)
    _render(payload, json_output=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
