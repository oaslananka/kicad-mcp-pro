from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import jsonschema
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT
IGNORED_SCAN_PARTS = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "dist",
    "htmlcov",
    "node_modules",
    "site",
}
ICON_SIZES = (16, 32, 48, 64, 128, 256, 512, 1024)
SUBMISSION_DOCS = (
    "README.md",
    "anthropic-directory.md",
    "chatgpt-apps.md",
    "openai-mcp-registry.md",
    "reviewer-test-prompts.md",
    "safety-and-permissions.md",
)
SCREENSHOTS = (
    "01-claude-desktop-quality-gate.png",
    "02-cursor-schematic-build.png",
    "03-vscode-pcb-inspection.png",
    "04-tools-reference.png",
    "05-export-manufacturing.png",
    "06-chatgpt-app-dashboard.png",
)
FORBIDDEN_NAMESPACE = tuple(
    "".join(parts)
    for parts in (
        ("oaslananka", "-", "lab"),
        ("oaslananka", "_", "lab"),
        ("oaslananka", "/", "lab"),
        ("lab", "/", "oaslananka"),
        ("kicad-mcp-pro", "-", "lab"),
    )
)
ORG_CI_RUNNER = "ubuntu-24.04"
OBSOLETE_SELF_HOSTED_WORKFLOWS = {
    "docker-publish.yml",
    "homebrew-publish.yml",
    "mcp-registry.yml",
    "scoop-publish.yml",
}
SELF_HOSTED_RUNNER = ("self-hosted", "Linux", "X64")

# Keep report labels and metadata filenames stable across success/error paths.
PYPROJECT_FILENAME = "pyproject.toml"
SERVER_MANIFEST_FILENAME = "server.json"
PRIVACY_POLICY_CHECK = "privacy policy"
DEMO_CAST_CHECK = "demo cast"
REVIEWER_PROMPTS_CHECK = "reviewer prompts"
CHATGPT_APP_CONTRACT_CHECK = "ChatGPT App contract"
SERVER_SCHEMA_CHECK = "server schema"


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def _tool(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        msg = f"{name} not found on PATH"
        raise RuntimeError(msg)
    return executable


def _git_files() -> list[Path]:
    result = subprocess.run(
        [_tool("git"), "ls-files"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return [
            path
            for path in ROOT.rglob("*")
            if path.is_file() and not (IGNORED_SCAN_PARTS & set(path.parts))
        ]
    return [ROOT / line for line in result.stdout.splitlines() if line.strip()]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _tracked_text_files() -> list[Path]:
    return [path for path in _git_files() if path.is_file()]


def _contains_any(path: Path, needles: tuple[str, ...]) -> list[str]:
    text = _read_text(path)
    return [needle for needle in needles if needle in text]


def _namespace_check() -> CheckResult:
    hits: list[str] = []
    for path in _tracked_text_files():
        found = _contains_any(path, FORBIDDEN_NAMESPACE)
        if found:
            hits.append(f"{path.relative_to(ROOT)}: {', '.join(found)}")
    if hits:
        return CheckResult("namespace regression", "FAIL", "; ".join(hits[:10]))
    return CheckResult("namespace regression", "PASS", "no forbidden owner strings")


def _runner_check() -> CheckResult:
    hits: list[str] = []
    workflow_dir = REPO_ROOT / ".github" / "workflows"
    for path in [*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")]:
        if path.name in OBSOLETE_SELF_HOSTED_WORKFLOWS:
            hits.append(f"{path.relative_to(REPO_ROOT)} is an obsolete pre-monorepo workflow")
            continue
        payload = yaml.safe_load(_read_text(path)) or {}
        jobs = payload.get("jobs", {}) if isinstance(payload, dict) else {}
        for job_name, job in jobs.items():
            if not isinstance(job, dict) or "runs-on" not in job:
                continue
            runs_on = job["runs-on"]
            values = runs_on if isinstance(runs_on, list) else [runs_on]
            normalized = tuple(str(value).strip().strip("'\"") for value in values)
            if "self-hosted" in normalized:
                hits.append(
                    f"{path.relative_to(REPO_ROOT)} job {job_name}: "
                    "self-hosted runner is not allowed"
                )
    if hits:
        return CheckResult("runner regression", "FAIL", "; ".join(hits))
    return CheckResult(
        "runner regression",
        "PASS",
        "monorepo workflows use GitHub-hosted runners only",
    )


def _version_check() -> CheckResult:
    try:
        pyproject = tomllib.loads((ROOT / PYPROJECT_FILENAME).read_text(encoding="utf-8"))
        tauri_cargo = tomllib.loads((ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8"))
        tauri_config = json.loads(
            (ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
        )
        release_manifest = json.loads(
            (ROOT / ".release-please-manifest.json").read_text(encoding="utf-8")
        )
        versions = {
            PYPROJECT_FILENAME: pyproject["project"]["version"],
            SERVER_MANIFEST_FILENAME: json.loads(
                (ROOT / SERVER_MANIFEST_FILENAME).read_text(encoding="utf-8")
            )["version"],
            "src-tauri/Cargo.toml": tauri_cargo["package"]["version"],
            "src-tauri/tauri.conf.json": tauri_config["version"],
            ".release-please-manifest.json src-tauri": release_manifest["src-tauri"],
        }
        init_text = (ROOT / "src" / "kicad_mcp" / "__init__.py").read_text(encoding="utf-8")
        match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
        versions["src/kicad_mcp/__init__.py"] = match.group(1) if match else ""
    except (OSError, tomllib.TOMLDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        return CheckResult("version metadata sync", "FAIL", f"unreadable version metadata: {exc}")
    if len(set(versions.values())) != 1:
        return CheckResult("version metadata sync", "FAIL", json.dumps(versions, sort_keys=True))
    return CheckResult("version metadata sync", "PASS", next(iter(versions.values())))


def _pypi_check() -> CheckResult:
    try:
        pyproject = tomllib.loads((ROOT / PYPROJECT_FILENAME).read_text(encoding="utf-8"))
        version = pyproject["project"]["version"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        return CheckResult("pypi reachability", "FAIL", f"unreadable package metadata: {exc}")
    try:
        with urlopen("https://pypi.org/pypi/kicad-mcp-pro/json", timeout=10) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError) as exc:
        return CheckResult("pypi reachability", "WARN", f"offline or unavailable: {exc}")
    releases = payload.get("releases", {})
    if version not in releases:
        return CheckResult(
            "pypi current version",
            "WARN",
            f"{version} is not published yet; expected for in-flight release branches",
        )
    return CheckResult("pypi current version", "PASS", f"{version} is published")


def _privacy_check() -> CheckResult:
    path = ROOT / "docs" / "privacy.md"
    if not path.is_file():
        return CheckResult(PRIVACY_POLICY_CHECK, "FAIL", "docs/privacy.md missing")
    text = _read_text(path).lower()
    if "data" not in text or "telemetry" not in text:
        return CheckResult(PRIVACY_POLICY_CHECK, "FAIL", "missing data or telemetry language")
    return CheckResult(PRIVACY_POLICY_CHECK, "PASS", "privacy.md covers data and telemetry")


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def _icon_check() -> CheckResult:
    errors: list[str] = []
    for size in ICON_SIZES:
        path = ROOT / "docs" / "assets" / f"icon-{size}.png"
        if not path.is_file():
            errors.append(f"missing {path.relative_to(ROOT)}")
        elif _image_size(path) != (size, size):
            errors.append(f"{path.relative_to(ROOT)} has {_image_size(path)}")
    if errors:
        return CheckResult("icon assets", "FAIL", "; ".join(errors))
    return CheckResult("icon assets", "PASS", "all icon sizes present")


def _screenshot_check() -> CheckResult:
    errors: list[str] = []
    hash_path = ROOT / "scripts" / "_placeholder_hashes.json"
    placeholders = json.loads(hash_path.read_text(encoding="utf-8")) if hash_path.is_file() else {}
    submission_mode = os.environ.get("SUBMISSION_MODE") == "1"
    for filename in SCREENSHOTS:
        path = ROOT / "docs" / "assets" / "screenshots" / filename
        if not path.is_file():
            errors.append(f"missing {path.relative_to(ROOT)}")
            continue
        if _image_size(path) != (1920, 1080):
            errors.append(f"{path.relative_to(ROOT)} has {_image_size(path)}")
            continue
        if submission_mode:
            import hashlib

            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if placeholders.get(filename) == digest:
                errors.append(f"{filename} is still the placeholder")
    if errors:
        return CheckResult("screenshot assets", "FAIL", "; ".join(errors))
    return CheckResult("screenshot assets", "PASS", "all screenshot slots valid")


def _demo_cast_check() -> CheckResult:
    path = ROOT / "docs" / "assets" / "demo.cast"
    gif_path = ROOT / "docs" / "assets" / "demo.gif"
    if not path.is_file():
        return CheckResult(DEMO_CAST_CHECK, "FAIL", "docs/assets/demo.cast missing")
    if not gif_path.is_file():
        return CheckResult(DEMO_CAST_CHECK, "FAIL", "docs/assets/demo.gif missing")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
        frames = [json.loads(line) for line in lines[1:] if line.strip()]
    except (IndexError, json.JSONDecodeError) as exc:
        return CheckResult(DEMO_CAST_CHECK, "FAIL", str(exc))
    if header.get("version") != 2 or not all(isinstance(frame, list) for frame in frames):
        return CheckResult(DEMO_CAST_CHECK, "FAIL", "invalid asciinema v2 structure")
    return CheckResult(DEMO_CAST_CHECK, "PASS", f"{len(frames)} frames and demo.gif present")


def _submission_docs_check() -> CheckResult:
    errors: list[str] = []
    for filename in SUBMISSION_DOCS:
        path = ROOT / "docs" / "submission" / filename
        if not path.is_file():
            errors.append(f"missing {filename}")
            continue
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count < 150:
            errors.append(f"{filename} has {line_count} lines")
    if errors:
        return CheckResult("submission docs", "FAIL", "; ".join(errors))
    return CheckResult("submission docs", "PASS", "six files at >=150 lines")


def _reviewer_prompts_check() -> CheckResult:
    path = ROOT / "tests" / "reviewer" / "prompts.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return CheckResult(REVIEWER_PROMPTS_CHECK, "FAIL", str(exc))
    prompts = payload.get("prompts")
    if not isinstance(prompts, list) or len(prompts) != 5:
        return CheckResult(REVIEWER_PROMPTS_CHECK, "FAIL", "expected exactly five prompts")
    return CheckResult(REVIEWER_PROMPTS_CHECK, "PASS", "five prompts")


def _readme_check() -> CheckResult:
    try:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        pyproject = tomllib.loads((ROOT / PYPROJECT_FILENAME).read_text(encoding="utf-8"))
        version = pyproject["project"]["version"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        return CheckResult(
            "README listing references", "FAIL", f"unreadable listing metadata: {exc}"
        )
    required = {
        "canonical repository": "https://github.com/oaslananka/kicad-mcp-pro",
        "PyPI package": "kicad-mcp-pro",
        "npm wrapper": "kicad-mcp-pro",
        "MCP Registry name": "io.github.oaslananka/kicad-mcp-pro",
        "version": f"| Version | `{version}` |",
    }
    missing = [label for label, marker in required.items() if marker not in text]
    if missing:
        return CheckResult("README listing references", "FAIL", ", ".join(missing))
    return CheckResult("README listing references", "PASS", "monorepo package identity linked")


def _chatgpt_app_check() -> CheckResult:
    app_root = ROOT / "integrations" / "chatgpt-app" / "apps-sdk"
    try:
        package = json.loads((app_root / "package.json").read_text(encoding="utf-8"))
        manifest = (app_root / "app-manifest.md").read_text(encoding="utf-8")
        source = (app_root / "src" / "server.ts").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        return CheckResult(CHATGPT_APP_CONTRACT_CHECK, "FAIL", str(exc))

    version = package.get("version")
    scripts = package.get("scripts", {})
    required = {
        "package identity": package.get("name") == "kicad-mcp-chatgpt-app",
        "private package": package.get("private") is True,
        "manifest version": isinstance(version, str) and f"Version: `{version}`" in manifest,
        "smoke script": scripts.get("test:smoke") == "node --test test/app-smoke.test.mjs",
        "runtime version source": "APP_VERSION = APP_PACKAGE.version" in source,
        "read-only annotations": "LOCAL_READ_ONLY_ANNOTATIONS" in source,
        "open-world annotation": "OPEN_WORLD_READ_ONLY_ANNOTATIONS" in source,
        "required CI job": "  chatgpt-app:" in workflow and "npm run test:smoke" in workflow,
        "smoke test file": (app_root / "test" / "app-smoke.test.mjs").is_file(),
    }
    failed = [name for name, passed in required.items() if not passed]
    if failed:
        return CheckResult(CHATGPT_APP_CONTRACT_CHECK, "FAIL", ", ".join(failed))
    return CheckResult(
        CHATGPT_APP_CONTRACT_CHECK,
        "PASS",
        f"{version}: package, manifest, read-only metadata, E2E, and required CI aligned",
    )


def _server_schema_check() -> CheckResult:
    schema_path = ROOT / "scripts" / "schemas" / "server.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        server = json.loads((ROOT / SERVER_MANIFEST_FILENAME).read_text(encoding="utf-8"))
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)
        errors = sorted(
            validator_cls(schema).iter_errors(server),
            key=lambda error: list(error.path),
        )
    except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
        return CheckResult(SERVER_SCHEMA_CHECK, "FAIL", str(exc))
    if errors:
        return CheckResult(SERVER_SCHEMA_CHECK, "FAIL", errors[0].message)
    return CheckResult(SERVER_SCHEMA_CHECK, "PASS", f"{SERVER_MANIFEST_FILENAME} validates")


def run_checks() -> list[CheckResult]:
    first_namespace = _namespace_check()
    first_runner = _runner_check()
    final_namespace = _namespace_check()
    final_runner = _runner_check()
    final_namespace = CheckResult(
        "namespace regression final pass",
        final_namespace.status,
        final_namespace.detail,
    )
    final_runner = CheckResult(
        "runner regression final pass", final_runner.status, final_runner.detail
    )
    return [
        first_namespace,
        first_runner,
        _version_check(),
        _pypi_check(),
        _privacy_check(),
        _chatgpt_app_check(),
        _icon_check(),
        _screenshot_check(),
        _demo_cast_check(),
        _submission_docs_check(),
        _reviewer_prompts_check(),
        _readme_check(),
        _server_schema_check(),
        final_namespace,
        final_runner,
    ]


def main() -> int:
    results = run_checks()
    print("| Check | Result | Detail |")
    print("|---|---|---|")
    for result in results:
        detail = result.detail.replace("|", "\\|")
        print(f"| {result.name} | {result.status} | {detail} |")
    return 1 if any(result.status == "FAIL" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
