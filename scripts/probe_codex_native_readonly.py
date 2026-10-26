#!/usr/bin/env python3
"""Opt-in, model-free Codex MCP smoke in a temporary, isolated config home.

Run only against an explicitly reviewed local Python environment and exact
source revision. No package installation, agent turn or production KiCad IPC.
The sanitized result is NOT an independent compatibility attestation.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import selectors
import shutil
import signal
import subprocess  # nosec B404 -- SHA-256-pinned local binaries; shell never used.
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Any

EXPECTED_SKILLS = frozenset(
    {
        "drc-check",
        "fabrication-output",
        "kicad-design-review",
        "pcb-design",
        "schematic-review",
        "visual-excellence",
        "wired-subcircuit-design",
    }
)
EXPECTED_HOST = "0.163.0"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
BINARY_SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def _sha256_executable(path: Path) -> str:
    """Fingerprint the resolved local executable before starting the host."""
    digest = hashlib.sha256()
    with path.resolve(strict=True).open("rb") as binary:
        for chunk in iter(lambda: binary.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 12) -> str:
    # Only fixed argv sequences: git read, hash-verified Codex/Python;
    # the opt-in probe never uses a shell or user-controlled command text.
    result = subprocess.run(  # nosec B603  # nosemgrep
        argv,  # nosemgrep -- only pre-reviewed executable argv; never a shell.
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return result.stdout.strip()


def _repo_skills(payload: dict[str, Any], root: Path) -> dict[str, str]:
    """Accept only all seven Skills physically inside the pinned checkout."""
    groups = payload.get("data")
    if not isinstance(groups, list):
        raise ValueError("invalid Skill response")
    found: dict[str, str] = {}
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("skills"), list):
            raise ValueError("invalid Skill group")
        for row in group["skills"]:
            if not isinstance(row, dict):
                raise ValueError("invalid Skill entry")
            name = row.get("name", "")
            if not isinstance(name, str) or not name.startswith("kicad-pro:"):
                continue
            short = name.removeprefix("kicad-pro:")
            if short not in EXPECTED_SKILLS:
                continue
            raw = row.get("path")
            if not isinstance(raw, str):
                raise ValueError("invalid project Skill path")
            resolved = Path(raw).resolve()
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise ValueError("project Skill origin is outside the pinned checkout")
            if short in found:
                raise ValueError("duplicate project Skill identity")
            found[short] = resolved.relative_to(root).as_posix()
    if set(found) != EXPECTED_SKILLS:
        raise ValueError("incomplete project Skill discovery")
    return dict(sorted(found.items()))


class _AppServer:
    """Bounded newline JSON-RPC with no raw transcript retention."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process
        self.reader = selectors.DefaultSelector()
        if process.stdout is None or process.stdin is None:
            raise RuntimeError("host pipes unavailable")
        self.stdout = process.stdout
        self.stdin = process.stdin
        self.reader.register(self.stdout, selectors.EVENT_READ)
        self.pending = b""

    def request(self, ident: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
        msg = {"jsonrpc": "2.0", "id": ident, "method": method, "params": params}
        self.stdin.write((json.dumps(msg) + "\n").encode())
        self.stdin.flush()
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            while b"\n" in self.pending:
                line, self.pending = self.pending.split(b"\n", 1)
                try:
                    response = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if response.get("id") == ident:
                    if not isinstance(response, dict):
                        raise RuntimeError(f"{method}: malformed host RPC response")
                    if "error" in response:
                        raise RuntimeError(f"{method}: host RPC failed")
                    result = response.get("result")
                    if not isinstance(result, dict):
                        raise RuntimeError(f"{method}: unexpected host RPC result")
                    return result
            for _, _ in self.reader.select(timeout=0.25):
                fragment = os.read(self.stdout.fileno(), 65_536)
                if not fragment:
                    raise RuntimeError(f"{method}: host closed output")
                self.pending += fragment
                if len(self.pending) > 4_000_000:
                    raise RuntimeError("host RPC output exceeded limit")
            if self.process.poll() is not None:
                raise RuntimeError(f"{method}: host process ended")
        raise TimeoutError(f"{method}: bounded timeout")


def _check_source_policy(root: Path, python: Path, names: list[str], env: dict[str, str]) -> None:
    code = (
        "import json,sys; "
        "from kicad_mcp.operating_modes import OperatingMode,tool_required_mode; "
        "from kicad_mcp.capabilities import get; "
        "names=json.loads(sys.stdin.read()); "
        "bad=[n for n in names if get(n) is None "
        "or tool_required_mode(n) != OperatingMode.READONLY]; "
        "print(json.dumps(bad))"
    )
    # Explicit interpreter SHA-256 is validated before this argv-only call.
    checked = subprocess.run(  # nosec B603  # nosemgrep
        [str(python), "-c", code],  # nosemgrep -- SHA-256-pinned Python, fixed -c body.
        input=json.dumps(names),
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=12,
        check=True,
    )
    if json.loads(checked.stdout) != []:
        raise RuntimeError("host exposes non-readonly tools")


def _execute(
    root: Path,
    python: Path,
    codex: Path,
    revision: str,
    *,
    codex_digest: str,
    python_digest: str,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="codex-kicad-readonly-smoke-") as temp:
        home = Path(temp)
        unbound = home / "not-attached-kicad-ipc.sock"
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": temp,
            "CODEX_HOME": temp,
            "XDG_CONFIG_HOME": temp,
            "XDG_DATA_HOME": temp,
            "XDG_CACHE_HOME": temp,
            "XDG_STATE_HOME": temp,
            "XDG_RUNTIME_DIR": temp,
            "LANG": "C.UTF-8",
        }
        host_version = _run([str(codex), "--version"], cwd=root, env=env).split()[-1]
        if host_version != EXPECTED_HOST:
            raise RuntimeError("unexpected Codex host version")
        pyenv = {
            **env,
            "PYTHONPATH": str(root / "src"),
            "KICAD_MCP_OPERATING_MODE": "readonly",
            "KICAD_MCP_PROFILE": "default",
            "KICAD_API_SOCKET": str(unbound),
        }
        source = json.loads(
            _run(
                [
                    str(python),
                    "-c",
                    "import json,pathlib,kicad_mcp; "
                    "print(json.dumps({'bound':pathlib.Path(kicad_mcp.__file__).resolve()"
                    ".is_relative_to(pathlib.Path.cwd()),'version':kicad_mcp.__version__}))",
                ],
                cwd=root,
                env=pyenv,
            )
        )
        if source["bound"] is not True:
            raise RuntimeError("server source import is not checkout-bound")
        toml_quote = json.dumps
        (home / "config.toml").write_text(
            "[mcp_servers.kicad]\n"
            f"command = {toml_quote(str(python))}\n"
            'args = ["-m", "kicad_mcp.server", "--transport", "stdio", '
            '"--profile", "default", "--mode", "readonly"]\n'
            "startup_timeout_sec = 20\ntool_timeout_sec = 20\n"
            "[mcp_servers.kicad.env]\n"
            f"PYTHONPATH = {toml_quote(str(root / 'src'))}\n"
            'KICAD_MCP_PROFILE = "default"\n'
            'KICAD_MCP_OPERATING_MODE = "readonly"\n'
            f"KICAD_API_SOCKET = {toml_quote(str(unbound))}\n"
            f"HOME = {toml_quote(temp)}\nXDG_RUNTIME_DIR = {toml_quote(temp)}\n",
            encoding="utf-8",
        )
        # Running a reviewed native host is the purpose of this opt-in probe:
        # verify executable digest, version and temporary HOME before start.
        process = subprocess.Popen(  # nosec B603  # nosemgrep
            [str(codex), "app-server", "--stdio"],
            cwd=root,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            bufsize=0,
        )
        try:
            rpc = _AppServer(process)
            rpc.request(
                1,
                "initialize",
                {"clientInfo": {"name": "safe-smoke", "version": "1"}, "capabilities": {}},
            )
            skills = _repo_skills(
                rpc.request(2, "skills/list", {"cwds": [str(root)], "forceReload": True}), root
            )
            thread = rpc.request(3, "thread/start", {"cwd": str(root), "ephemeral": True})
            thread_id = thread["thread"]["id"]
            status = rpc.request(
                4,
                "mcpServerStatus/list",
                {"serverName": "kicad", "detail": "full", "threadId": thread_id},
            )
            entry = next(
                (item for item in status.get("data", []) if item.get("name") == "kicad"),
                None,
            )
            if not entry or entry.get("runtimeStatus") != "connected" or entry.get("toolsError"):
                raise RuntimeError("Codex MCP connection or tool inventory unavailable")
            tools = entry.get("tools", {})
            names = sorted(tools)
            if not names or "kicad_get_server_info" not in names:
                raise RuntimeError("readonly diagnostic not advertised")
            _check_source_policy(root, python, names, pyenv)
            response = rpc.request(
                5,
                "mcpServer/tool/call",
                {
                    "threadId": thread_id,
                    "server": "kicad",
                    "tool": "kicad_get_server_info",
                    "arguments": {},
                },
            )
            if response.get("isError") is not False or not response.get("content"):
                raise RuntimeError("host-originated readonly diagnostic failed")
            if unbound.exists():
                raise RuntimeError("unexpected GUI IPC socket bound")
            return {
                "schema_version": "codex-native-host-sanitized-log.v1",
                "observed_on": date.today().isoformat(),
                "host_id": "codex",
                "host_version": host_version,
                "host_binary_sha256": codex_digest,
                "python_binary_sha256": python_digest,
                "os": "linux",
                "source_revision": revision,
                "source_module_loaded_from_exact_checkout": True,
                "server_version": source["version"],
                "transport": "stdio",
                "profile": "default",
                "mode": "readonly",
                "host_initialized": True,
                "ephemeral_thread_created": True,
                "project_skills_verified": skills,
                "server_status": "connected",
                "native_host_tool_names": names,
                "native_tool_count": len(names),
                "all_native_exposed_tools_readonly_per_source_policy": True,
                "native_tool_call_method": "mcpServer/tool/call",
                "native_tool_called": "kicad_get_server_info",
                "native_tool_call_successful": True,
                "native_tool_call_content_present": True,
                "explicit_unbound_ipc_configured": True,
                "ipc_socket_materialized": False,
                "model_or_agent_turn_started": False,
                "raw_tool_response_retained": False,
                "full_native_host_smoke_independently_attested": False,
            }
        finally:
            # The parent may have exited while its MCP subprocess survives.
            # Always signal the isolated process group, not only the parent.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--expected-codex-sha256", required=True)
    parser.add_argument("--expected-python-sha256", required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        if (
            sys.platform != "linux"
            or not SHA_PATTERN.fullmatch(args.expected_source_sha)
            or not BINARY_SHA_PATTERN.fullmatch(args.expected_codex_sha256)
            or not BINARY_SHA_PATTERN.fullmatch(args.expected_python_sha256)
        ):
            raise RuntimeError("unsupported platform or invalid expected digest")
        # Preserve the venv executable path: resolving its symlink can discard
        # the installed Python environment and its pinned dependencies.
        python = args.python.absolute()
        if not python.is_file():
            raise RuntimeError("reviewed Python executable unavailable")
        codex_binary = shutil.which("codex")
        if not codex_binary:
            raise RuntimeError("Codex CLI unavailable")
        codex = Path(codex_binary).resolve(strict=True)
        codex_digest = _sha256_executable(codex)
        python_digest = _sha256_executable(python)
        if (
            codex_digest != args.expected_codex_sha256
            or python_digest != args.expected_python_sha256
        ):
            raise RuntimeError("reviewed executable SHA-256 mismatch")
        current_head = _run(["git", "rev-parse", "HEAD"], cwd=root, env=os.environ.copy())
        if current_head != args.expected_source_sha:
            # Permit a test-only descendant with identical committed server source.
            _run(
                ["git", "merge-base", "--is-ancestor", args.expected_source_sha, current_head],
                cwd=root,
                env=os.environ.copy(),
            )
            expected_tree = _run(
                ["git", "rev-parse", f"{args.expected_source_sha}:src"],
                cwd=root,
                env=os.environ.copy(),
            )
            current_tree = _run(
                ["git", "rev-parse", "HEAD:src"],
                cwd=root,
                env=os.environ.copy(),
            )
            if expected_tree != current_tree:
                raise RuntimeError("server source tree differs from pinned source")
        revision = args.expected_source_sha
        source_diff = _run(
            ["git", "status", "--porcelain", "--", "src"], cwd=root, env=os.environ.copy()
        )
        if source_diff:
            raise RuntimeError("server source working tree is not clean")
        log = _execute(
            root,
            python,
            codex,
            revision,
            codex_digest=codex_digest,
            python_digest=python_digest,
        )
        raw = (json.dumps(log, indent=2, sort_keys=True) + "\n").encode()
        report = {
            "schema_version": "native-agent-host-smoke.v1",
            "host_id": "codex",
            "host_version": log["host_version"],
            "os": "linux",
            "source_revision": revision,
            "server_version": log["server_version"],
            "transport": "stdio",
            "mode": "readonly",
            "mcp_server_discovered": True,
            "skills_discovered": sorted(log["project_skills_verified"]),
            "tool_called": "kicad_get_server_info",
            "tool_call_successful": True,
            "write_tools_absent": True,
            "observed_on": log["observed_on"],
            "sanitized_log_sha256": hashlib.sha256(raw).hexdigest(),
        }
        if not args.output_dir.is_dir() or args.output_dir.is_symlink():
            raise RuntimeError("output directory must exist and not be a symlink")
        for basename, payload in (
            ("codex-native-sanitized-log.json", raw),
            (
                "codex-native-smoke.json",
                (json.dumps(report, indent=2, sort_keys=True) + "\n").encode(),
            ),
        ):
            with (args.output_dir / basename).open("xb") as f:
                f.write(payload)
        print(
            json.dumps(
                {
                    "status": "structurally_complete_not_attested",
                    "host": "codex",
                    "source_revision": revision,
                }
            )
        )
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        TimeoutError,
        subprocess.SubprocessError,
        RuntimeError,
    ):
        print(json.dumps({"status": "rejected", "reason": "probe_incomplete_or_unsafe"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
