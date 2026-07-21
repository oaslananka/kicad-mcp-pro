"""Health and doctor diagnostics for CLI and integrations."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, ClassVar, Literal
from zipfile import ZIP_DEFLATED, ZipFile

from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .capabilities import AccessTier, RuntimeRequirement, all_records
from .config import get_config
from .connection import KiCadConnectionError, get_board
from .discovery import find_kicad_version

CheckStatus = Literal["ok", "warn", "error", "skipped"]
OverallStatus = Literal["ok", "degraded", "error"]
DevelopmentClassification = Literal["required", "optional", "live-kicad"]
DevelopmentToolStatus = Literal["ok", "missing", "version-mismatch"]
DevelopmentCapabilityMode = Literal["core-only", "headless-kicad", "gui-connected"]
DIAGNOSTIC_SCHEMA_VERSION = "1.0.0"
_PRIVATE_KEY_MARKER = "PRIVATE" + " KEY"
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(token|access_token|refresh_token|client_secret|password)=([^\s,;]+)"),
    re.compile(r"(?i)\b(authorization:\s*bearer\s+)([^\s,;]+)"),
    re.compile(
        rf"-----BEGIN {_PRIVATE_KEY_MARKER}-----.*?-----END {_PRIVATE_KEY_MARKER}-----",
        re.DOTALL,
    ),
)


class CheckResult(BaseModel):
    """One diagnostics check result."""

    name: str
    status: CheckStatus
    message: str
    hint: str = ""


class PackageDiagnostics(BaseModel):
    """Installed package information."""

    name: str = "kicad-mcp-pro"
    version: str = __version__
    location: str | None = None
    install_source: str = "installed_package"
    repo_path: str | None = None
    repo_version: str | None = None
    git_branch: str | None = None
    git_commit: str | None = None
    version_drift: bool = False


class PythonDiagnostics(BaseModel):
    """Python runtime information."""

    version: str = Field(default_factory=platform.python_version)
    executable: str | None = None


class McpDiagnostics(BaseModel):
    """MCP server runtime settings."""

    transport_default: str
    profile: str
    host: str | None = None
    port: int | None = None
    mount_path: str | None = None
    stateful_http: bool = False


class KiCadDiagnostics(BaseModel):
    """KiCad CLI and IPC availability."""

    cli_path: str | None
    cli_found: bool
    version: str | None = None
    ipc_reachable: bool = False
    headless: bool = False


class ConfigDiagnostics(BaseModel):
    """Sanitized server configuration fields."""

    workspace_root: str | None = None
    project_dir: str | None = None
    project_file: str | None = None
    pcb_file: str | None = None
    sch_file: str | None = None
    output_dir: str | None = None
    timeout_ms: int
    retries: int
    headless: bool
    log_level: str
    log_format: str
    transport: str
    host: str | None = None
    port: int | None = None
    mount_path: str | None = None
    stateful_http: bool = False
    auth_token: dict[str, bool]
    kicad_token: dict[str, bool]


class ToolCatalogDiagnostics(BaseModel):
    """Summary of the tool registry available to the configured profile."""

    tool_count: int = 0
    category_count: int = 0
    categories: list[str] = Field(default_factory=list)
    capability_summary: dict[str, dict[str, int]] = Field(default_factory=dict)


class LiveContextDiagnostics(BaseModel):
    """Live KiCad GUI and IPC context availability."""

    available: bool = False
    ipc_reachable: bool = False
    live_pcb_context: bool = False
    live_schematic_context: bool = False
    diagnostics: list[str] = Field(default_factory=list)


class DevelopmentToolDiagnostics(BaseModel):
    """One source-checkout development capability."""

    name: str
    classification: DevelopmentClassification
    expected_version: str | None = None
    actual_version: str | None = None
    executable: str | None = None
    status: DevelopmentToolStatus
    remediation: str


class DevelopmentRootDiagnostics(BaseModel):
    """One repository-scoped development state root."""

    name: str
    path: str
    exists: bool
    writable: bool


class DevelopmentDiagnostics(BaseModel):
    """Source-checkout toolchain and live KiCad capability report."""

    available: bool = True
    capability_mode: DevelopmentCapabilityMode
    prepared: bool
    frozen_python_ready: bool = False
    frozen_node_ready: bool = False
    tools: list[DevelopmentToolDiagnostics] = Field(default_factory=list)
    roots: list[DevelopmentRootDiagnostics] = Field(default_factory=list)


class DiagnosticReport(BaseModel):
    """Machine-readable health/doctor report."""

    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)

    schema_version: str = Field(default=DIAGNOSTIC_SCHEMA_VERSION, alias="schemaVersion")
    ok: bool
    status: OverallStatus
    package: PackageDiagnostics = Field(default_factory=PackageDiagnostics)
    python: PythonDiagnostics = Field(default_factory=PythonDiagnostics)
    mcp: McpDiagnostics
    kicad: KiCadDiagnostics
    config: ConfigDiagnostics
    tools: ToolCatalogDiagnostics = Field(default_factory=ToolCatalogDiagnostics)
    live_context: LiveContextDiagnostics = Field(default_factory=LiveContextDiagnostics)
    development: DevelopmentDiagnostics | None = None
    recent_errors: list[str] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)


def _redact_sensitive(value: str) -> str:
    redacted = value
    redacted = _SECRET_PATTERNS[0].sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    redacted = _SECRET_PATTERNS[1].sub(lambda match: f"{match.group(1)}[REDACTED]", redacted)
    redacted = _SECRET_PATTERNS[2].sub(
        f"-----BEGIN {_PRIVATE_KEY_MARKER}-----[REDACTED]-----END {_PRIVATE_KEY_MARKER}-----",
        redacted,
    )
    return redacted


def _redact_check(check: CheckResult) -> CheckResult:
    return CheckResult(
        name=check.name,
        status=check.status,
        message=_redact_sensitive(check.message),
        hint=_redact_sensitive(check.hint),
    )


def _status(checks: list[CheckResult]) -> tuple[bool, OverallStatus]:
    if any(check.status == "error" for check in checks):
        return False, "error"
    if any(check.status == "warn" for check in checks):
        return True, "degraded"
    return True, "ok"


def _cli_found(path: Path) -> bool:
    return path.exists()


def _capability_summary() -> dict[str, dict[str, int]]:
    tiers = {tier.value: 0 for tier in AccessTier}
    runtimes = {runtime.value: 0 for runtime in RuntimeRequirement}
    for record in all_records().values():
        tiers[record.tier.value] += 1
        runtimes[record.runtime.value] += 1
    return {"tiers": tiers, "runtimes": runtimes}


def _tool_catalog_diagnostics(profile: str) -> ToolCatalogDiagnostics:
    from .tools.router import categories_for_profile

    categories = list(categories_for_profile(profile))
    return ToolCatalogDiagnostics(
        tool_count=len(all_records()),
        category_count=len(categories),
        categories=categories,
        capability_summary=_capability_summary(),
    )


def _recent_errors(checks: list[CheckResult]) -> list[str]:
    return [
        f"{check.name}: {check.message}" for check in checks if check.status in {"warn", "error"}
    ]


def _pyproject_metadata(path: Path) -> tuple[str, str] | None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    project = data.get("project")
    if not isinstance(project, dict):
        return None
    name = project.get("name")
    version = project.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        return None
    return name, version


def _find_checkout_root(start: Path) -> Path | None:
    try:
        current = start.expanduser().resolve()
    except OSError:
        return None
    for candidate in (current, *current.parents):
        pyproject = candidate / "pyproject.toml"
        metadata = _pyproject_metadata(pyproject)
        if metadata is None:
            continue
        name, _version = metadata
        if name == "kicad-mcp-pro":
            return candidate
    return None


def _git_value(repo: Path, *args: str) -> str | None:
    git_executable = shutil.which("git")
    if git_executable is None:
        return None
    try:
        result = subprocess.run(
            [git_executable, "-C", str(repo), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _checkout_candidates() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("KICAD_MCP_REPO_PATH", "KICAD_MCP_CHECKOUT_PATH"):
        value = os.environ.get(env_name, "").strip()
        if value:
            candidates.append(Path(value))
    candidates.append(Path.cwd())
    candidates.append(Path(__file__).resolve())
    return candidates


def _development_contract(checkout: Path) -> dict[str, str] | None:
    path = checkout / "scripts" / "dev-toolchain.env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    required = {
        "KICAD_CLI_VERSION",
        "NODE_VERSION",
        "PNPM_VERSION",
        "PYTHON_VERSION",
        "RUST_TOOLCHAIN",
        "TASK_VERSION",
        "UV_VERSION",
    }
    return values if required <= values.keys() else None


def _writable_path(path: Path) -> bool:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.exists() and os.access(candidate, os.W_OK)


def _development_tool_version(name: str, path: Path | None, arguments: list[str]) -> str | None:
    executable: str | None
    if path is not None and path.is_file():
        executable = str(path)
    else:
        executable = shutil.which(name)
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0] if output else None


def build_development_diagnostics(
    checkout: Path,
    *,
    cli_found: bool,
    ipc_reachable: bool,
    cli_path: Path | None = None,
) -> DevelopmentDiagnostics:
    """Build source-checkout development tool and capability diagnostics."""

    root = checkout.resolve()
    contract = _development_contract(root)
    if contract is None:
        return DevelopmentDiagnostics(
            available=False,
            capability_mode="gui-connected"
            if ipc_reachable
            else "headless-kicad"
            if cli_found
            else "core-only",
            prepared=False,
        )

    tool_root = root / ".dev-tools"
    cache_root = root / ".dev-cache"
    venv_root = root / ".venv"
    candidates: list[tuple[str, DevelopmentClassification, str | None, Path | None, list[str]]] = [
        (
            "python",
            "required",
            contract["PYTHON_VERSION"],
            venv_root / "bin" / "python",
            ["--version"],
        ),
        (
            "uv",
            "required",
            contract["UV_VERSION"],
            tool_root / "uv" / contract["UV_VERSION"] / "bin" / "uv",
            ["--version"],
        ),
        (
            "uvx",
            "required",
            contract["UV_VERSION"],
            tool_root / "uv" / contract["UV_VERSION"] / "bin" / "uvx",
            ["--version"],
        ),
        (
            "node",
            "required",
            contract["NODE_VERSION"],
            tool_root / "node" / contract["NODE_VERSION"] / "bin" / "node",
            ["--version"],
        ),
        (
            "pnpm",
            "required",
            contract["PNPM_VERSION"],
            tool_root / "pnpm" / contract["PNPM_VERSION"] / "bin" / "pnpm",
            ["--version"],
        ),
        (
            "task",
            "optional",
            contract["TASK_VERSION"],
            tool_root / "task" / contract["TASK_VERSION"] / "bin" / "task",
            ["--version"],
        ),
        (
            "rustc",
            "optional",
            contract["RUST_TOOLCHAIN"],
            tool_root / "cargo" / "bin" / "rustc",
            ["--version"],
        ),
        (
            "cargo",
            "optional",
            contract["RUST_TOOLCHAIN"],
            tool_root / "cargo" / "bin" / "cargo",
            ["--version"],
        ),
        ("kicad-cli", "live-kicad", contract["KICAD_CLI_VERSION"], cli_path, ["--version"]),
    ]
    tools: list[DevelopmentToolDiagnostics] = []
    for name, classification, expected, executable, arguments in candidates:
        actual = _development_tool_version(name, executable, arguments)
        status: DevelopmentToolStatus
        if actual is None:
            status = "missing"
        elif expected is not None and expected not in actual.lstrip("v"):
            status = "version-mismatch"
        else:
            status = "ok"
        if classification == "live-kicad":
            remediation = "Install the supported KiCad CLI or set KICAD_MCP_KICAD_CLI."
        elif classification == "optional":
            remediation = "Run ./scripts/bootstrap-dev.sh to install the optional development tool."
        else:
            remediation = "Run ./scripts/bootstrap-dev.sh to restore the exact required tool."
        resolved_executable = (
            executable if executable is not None and executable.is_file() else None
        )
        tools.append(
            DevelopmentToolDiagnostics(
                name=name,
                classification=classification,
                expected_version=expected,
                actual_version=actual,
                executable=str(resolved_executable) if resolved_executable is not None else None,
                status=status,
                remediation=remediation,
            )
        )

    roots = [
        DevelopmentRootDiagnostics(
            name=name,
            path=str(path),
            exists=path.exists(),
            writable=_writable_path(path),
        )
        for name, path in (
            ("tools", tool_root),
            ("cache", cache_root),
            ("venv", venv_root),
        )
    ]
    capability_mode: DevelopmentCapabilityMode = (
        "gui-connected" if ipc_reachable else "headless-kicad" if cli_found else "core-only"
    )
    return DevelopmentDiagnostics(
        capability_mode=capability_mode,
        prepared=(root / ".dev-env.sh").is_file(),
        frozen_python_ready=(venv_root / "pyvenv.cfg").is_file(),
        frozen_node_ready=(root / "node_modules" / ".modules.yaml").is_file(),
        tools=tools,
        roots=roots,
    )


def _package_diagnostics() -> tuple[PackageDiagnostics, list[CheckResult]]:
    package_path = Path(__file__).resolve().parent
    package_repo = _find_checkout_root(package_path)
    checkout = next(
        (
            root
            for candidate in _checkout_candidates()
            if (root := _find_checkout_root(candidate)) is not None
        ),
        None,
    )

    install_source = "source_checkout" if package_repo is not None else "installed_package"
    repo_version: str | None = None
    git_branch: str | None = None
    git_commit: str | None = None
    checks: list[CheckResult] = []
    if checkout is not None:
        metadata = _pyproject_metadata(checkout / "pyproject.toml")
        if metadata is not None:
            _name, repo_version = metadata
        git_branch = _git_value(checkout, "branch", "--show-current")
        git_commit = _git_value(checkout, "rev-parse", "--short=12", "HEAD")

    version_drift = bool(repo_version and repo_version != __version__)
    diagnostics = PackageDiagnostics(
        version=__version__,
        location=str(package_path),
        install_source=install_source,
        repo_path=str(checkout) if checkout is not None else None,
        repo_version=repo_version,
        git_branch=git_branch,
        git_commit=git_commit,
        version_drift=version_drift,
    )
    if version_drift and checkout is not None:
        checks.append(
            CheckResult(
                name="package_version_drift",
                status="warn",
                message=(
                    f"Active server version {__version__} differs from checkout "
                    f"{checkout} version {repo_version}."
                ),
                hint=(
                    "Restart the MCP server from the checkout, reinstall the package in "
                    "editable mode, or update the client MCP config to the intended entrypoint."
                ),
            )
        )
    return diagnostics, checks


def _toml_data(path: Path) -> dict[str, Any] | None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _required_uv_version_from_uv_toml(checkout: Path) -> str | None:
    data = _toml_data(checkout / "uv.toml")
    if data is None:
        return None
    value = data.get("required-version")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _required_uv_version_from_pyproject(checkout: Path) -> str | None:
    data = _toml_data(checkout / "pyproject.toml")
    if data is None:
        return None
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return None
    uv = tool.get("uv")
    if not isinstance(uv, dict):
        return None
    value = uv.get("required-version")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _required_uv_version(checkout: Path | None) -> str | None:
    if checkout is None:
        return None
    return _required_uv_version_from_uv_toml(checkout) or _required_uv_version_from_pyproject(
        checkout
    )


def _uv_requirement_specifier(required: str) -> str:
    requirement = required.strip()
    if re.match(r"^(===|~=|==|!=|<=|>=|<|>)", requirement):
        return requirement
    return f"=={requirement}"


def _uv_requirement_satisfied(current: str, required: str) -> bool:
    try:
        from packaging.specifiers import InvalidSpecifier, SpecifierSet
        from packaging.version import InvalidVersion, Version
    except ImportError:
        return current == required.strip().removeprefix("==")
    try:
        return Version(current) in SpecifierSet(_uv_requirement_specifier(required))
    except (InvalidSpecifier, InvalidVersion):
        return current == required.strip().removeprefix("==")


def _uv_version_hint(required: str) -> str:
    exact = required.strip().removeprefix("==")
    if re.fullmatch(r"[0-9][A-Za-z0-9.!+_-]*", exact):
        return (
            f"Use the repo-compatible uv version, for example: uv self update {exact}. "
            "Then rerun uv sync --all-extras --frozen."
        )
    return f"Use a uv version satisfying {required}. Then rerun uv sync --all-extras --frozen."


def _detect_uv_version() -> tuple[str | None, str | None]:
    uv_executable = shutil.which("uv")
    if uv_executable is None:
        return None, None
    try:
        result = subprocess.run(
            [uv_executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None, uv_executable
    match = re.search(r"\buv\s+([^\s]+)", result.stdout.strip())
    return (match.group(1) if match else None), uv_executable


def _uv_version_check(checkout: Path | None) -> CheckResult | None:
    required = _required_uv_version(checkout)
    if required is None:
        return None
    current, executable = _detect_uv_version()
    if current is None:
        return CheckResult(
            name="uv_version",
            status="warn",
            message=f"Checkout requires uv {required}, but uv was not found on PATH.",
            hint=f"Install uv {required} before running repository commands such as uv run.",
        )
    if not _uv_requirement_satisfied(current, required):
        return CheckResult(
            name="uv_version",
            status="warn",
            message=(
                f"Checkout requires uv {required}, but PATH resolves uv {current} "
                f"at {executable}. uv run will fail before tests or tools start."
            ),
            hint=_uv_version_hint(required),
        )
    return CheckResult(
        name="uv_version",
        status="ok",
        message=f"uv {current} satisfies checkout requirement {required}.",
    )


def _diagnostic_payload(report: DiagnosticReport) -> dict[str, Any]:
    payload = report.model_dump(mode="json", by_alias=True)
    DiagnosticReport.model_validate(payload)
    return payload


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def write_diagnostic_bundle(report: DiagnosticReport, bundle_path: Path) -> None:
    """Write a redacted support bundle for setup diagnostics."""
    payload = _diagnostic_payload(report)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    config = payload["config"]
    if not isinstance(config, dict):
        config = {}
    environment = {
        "schemaVersion": DIAGNOSTIC_SCHEMA_VERSION,
        "platform": platform.platform(),
        "python": payload["python"],
        "package": payload["package"],
        "config": config,
        "environment": {
            "KICAD_MCP_AUTH_TOKEN": config.get("auth_token", {"configured": False}),
            "KICAD_API_TOKEN": config.get("kicad_token", {"configured": False}),
            "KICAD_MCP_KICAD_TOKEN": config.get("kicad_token", {"configured": False}),
            "OTEL_EXPORTER_OTLP_HEADERS": {"configured": bool(config.get("otel_headers"))},
        },
    }
    readme = (
        "KiCad MCP Pro diagnostic bundle\n\n"
        "This bundle contains redacted setup diagnostics only. Secret values, tokens, "
        "and plaintext credentials are not included.\n"
    )
    with ZipFile(bundle_path, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", readme)
        archive.writestr("doctor.json", _json_dumps(payload))
        archive.writestr(
            "diagnostic-schema.json",
            _json_dumps(DiagnosticReport.model_json_schema(by_alias=True)),
        )
        archive.writestr("environment.json", _json_dumps(environment))


def diagnostic_report_json(report: DiagnosticReport, *, indent: int = 2) -> str:
    """Return schema-validated JSON for a diagnostic report."""
    payload = _diagnostic_payload(report)
    return json.dumps(payload, indent=indent)


def _agent_config_checks() -> list[CheckResult]:
    """Check agent configuration files for kicad-mcp presence."""
    checks: list[CheckResult] = []
    try:
        from .setup import check_all_agent_configs

        for result in check_all_agent_configs():
            key = str(result.get("key", "?"))
            configs = result.get("configs", {})
            if not configs:
                continue
            for scope, entry in configs.items():  # type: ignore[attr-defined]
                if not isinstance(entry, dict):
                    continue
                path = entry.get("path", "")
                exists = entry.get("exists", False)
                valid = entry.get("valid", False)
                issues = entry.get("issues", [])

                if exists:
                    if valid:
                        checks.append(
                            CheckResult(
                                name=f"agent_config_{key}_{scope}",
                                status="ok",
                                message=f"{key} ({scope}) config found at {path}",
                            )
                        )
                    else:
                        checks.append(
                            CheckResult(
                                name=f"agent_config_{key}_{scope}",
                                status="warn",
                                message=f"{key} ({scope}) config at {path} has issues",
                                hint="; ".join(str(i) for i in issues[:3]),
                            )
                        )
                else:
                    checks.append(
                        CheckResult(
                            name=f"agent_config_{key}_{scope}",
                            status="skipped",
                            message=f"{key} ({scope}) config not found at {path}",
                            hint=f"Run: kicad-mcp-pro setup {key} --write",
                        )
                    )
    except Exception as exc:
        checks.append(
            CheckResult(
                name="agent_config_check",
                status="warn",
                message=f"Agent config check failed: {exc}",
            )
        )
    return checks


def build_diagnostic_report(*, probe_cli: bool, probe_ipc: bool) -> DiagnosticReport:
    """Build a diagnostics report without raising for non-fatal KiCad unavailability."""
    cfg = get_config()
    checks: list[CheckResult] = []
    package_diagnostics, package_checks = _package_diagnostics()

    cli_found = _cli_found(cfg.kicad_cli)
    kicad_version: str | None = None
    if cli_found:
        checks.append(
            CheckResult(
                name="kicad_cli",
                status="ok",
                message=f"kicad-cli found at {cfg.kicad_cli}",
            )
        )
        if probe_cli:
            kicad_version = find_kicad_version(cfg.kicad_cli)
            checks.append(
                CheckResult(
                    name="kicad_cli_version",
                    status="ok" if kicad_version else "warn",
                    message=kicad_version or "Could not read KiCad CLI version.",
                    hint="" if kicad_version else "Verify that kicad-cli runs on this machine.",
                )
            )
    else:
        checks.append(
            CheckResult(
                name="kicad_cli",
                status="warn",
                message=f"kicad-cli was not found at {cfg.kicad_cli}",
                hint="Install KiCad or set KICAD_CLI_PATH/KICAD_MCP_KICAD_CLI.",
            )
        )

    ipc_reachable = False
    if probe_ipc:
        try:
            get_board()
            ipc_reachable = True
            checks.append(
                CheckResult(
                    name="kicad_ipc",
                    status="ok",
                    message="KiCad IPC is reachable and a board is open.",
                )
            )
        except KiCadConnectionError as exc:
            checks.append(
                CheckResult(
                    name="kicad_ipc",
                    status="warn",
                    message=str(exc).splitlines()[0],
                    hint="Start KiCad, enable the IPC API server, and open a board.",
                )
            )
    else:
        checks.append(
            CheckResult(
                name="kicad_ipc",
                status="skipped",
                message="KiCad IPC probe deferred for fast health check.",
                hint="Run doctor --json for a deeper probe.",
            )
        )

    if probe_cli:
        checks.extend(package_checks)
        checkout = (
            Path(package_diagnostics.repo_path)
            if package_diagnostics.repo_path is not None
            else None
        )
        uv_check = _uv_version_check(checkout)
        if uv_check is not None:
            checks.append(uv_check)

    checks = [_redact_check(check) for check in checks]

    # Agent config checks (only in doctor mode, not health)
    if probe_cli:
        checks.extend(_agent_config_checks())

    ok, status = _status(checks)
    config_payload = cfg.safe_diagnostics()
    checkout = (
        Path(package_diagnostics.repo_path) if package_diagnostics.repo_path is not None else None
    )
    development = (
        build_development_diagnostics(
            checkout,
            cli_found=cli_found,
            ipc_reachable=ipc_reachable,
            cli_path=Path(cfg.kicad_cli) if cfg.kicad_cli else None,
        )
        if checkout is not None
        else None
    )
    return DiagnosticReport(
        ok=ok,
        status=status,
        package=package_diagnostics,
        python=PythonDiagnostics(executable=sys.executable),
        mcp=McpDiagnostics(
            transport_default=cfg.transport,
            profile=cfg.profile,
            host=cfg.host,
            port=cfg.port,
            mount_path=cfg.mount_path,
            stateful_http=cfg.stateful_http,
        ),
        kicad=KiCadDiagnostics(
            cli_path=str(cfg.kicad_cli) if cfg.kicad_cli else None,
            cli_found=cli_found,
            version=kicad_version,
            ipc_reachable=ipc_reachable,
            headless=cfg.headless,
        ),
        config=ConfigDiagnostics.model_validate(config_payload),
        tools=_tool_catalog_diagnostics(cfg.profile),
        development=development,
        live_context=LiveContextDiagnostics(
            available=ipc_reachable,
            ipc_reachable=ipc_reachable,
            live_pcb_context=ipc_reachable,
            live_schematic_context=False,
            diagnostics=_recent_errors(checks),
        ),
        recent_errors=_recent_errors(checks),
        checks=checks,
    )


def build_health_report() -> DiagnosticReport:
    """Build a fast health report that never requires KiCad IPC."""
    return build_diagnostic_report(probe_cli=False, probe_ipc=False)


def build_doctor_report() -> DiagnosticReport:
    """Build a deeper doctor report with non-fatal KiCad probes."""
    return build_diagnostic_report(probe_cli=True, probe_ipc=True)
