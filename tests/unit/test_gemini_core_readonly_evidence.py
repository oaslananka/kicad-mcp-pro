"""Same-source readonly review and bounded model-free Gemini-core probe tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 -- test-only fixed argv to local Node, never shell
from pathlib import Path

import pytest

from scripts import check_gemini_core_readonly_evidence as checker

ROOT = Path(__file__).resolve().parents[2]


def _observed() -> dict:
    return json.loads(checker.EVIDENCE.read_text(encoding="utf-8"))


def test_checked_in_gemini_core_observation_matches_readonly_source_policy() -> None:
    assert checker.check(_observed()) == []


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("hostVersion", "0.61.0"),
        ("reviewedSourceRevision", "0" * 40),
        ("calledOnly", "pcb_add_track"),
        ("responseError", True),
        ("rawResponseRetained", True),
        ("modelTurnStarted", True),
        ("hostCliInteractiveSession", True),
        ("independentProcessAttestation", True),
        ("fullHostAcceptance", True),
        ("kiCadIpcSocketCreated", True),
        ("temporaryEnvironmentRemoved", False),
        ("hostCoreSha256", "unverified"),
        ("launchArgs", ["kicad-mcp-pro"]),
    ],
)
def test_unsafe_or_overstated_gemini_core_observation_fails_closed(
    field: str, invalid: object
) -> None:
    observed = _observed()
    observed[field] = invalid
    assert checker.check(observed)


def test_write_or_unknown_tools_cannot_be_silently_accepted() -> None:
    for injected in ("pcb_add_track", "not_a_registered_tool"):
        observed = _observed()
        observed["discoveredTools"] = sorted([*observed["discoveredTools"], injected])
        assert checker.check(observed)


def test_tool_inventory_and_annotation_mismatch_rejected() -> None:
    observed = _observed()
    observed["discoveredTools"].append(observed["discoveredTools"][0])
    assert checker.check(observed)

    observed = _observed()
    observed["missingReadOnlyAnnotations"] = ["invented_mutation_tool"]
    assert checker.check(observed)


def test_gemini_probe_uses_verified_regular_file_handles_not_scanner_exemptions() -> None:
    script = (ROOT / "scripts/probe_gemini_core_readonly.mjs").read_text(encoding="utf-8")
    assert "nosemgrep" not in script
    assert "O_NOFOLLOW" in script
    assert "after.dev !== before.dev || after.ino !== before.ino" in script
    assert "after.size > MAX_FILE_BYTES" in script
    assert "const bytes = await readVerifiedFile(corePath)" in script
    assert "discoveredTools: [...names].sort(compareToolNames)" in script
    assert ".map((t) => t.serverToolName).sort(compareToolNames)" in script
    assert "function compareToolNames(a, b)" in script
    assert script.index("const bytes = await readVerifiedFile(corePath)") < script.index(
        "const core = await import(pathToFileURL(corePath))"
    )


def test_no_duplicate_json_keys_in_observation(tmp_path: Path) -> None:
    file = tmp_path / "bad.json"
    file.write_text('{"hostVersion":"0.60.0","hostVersion":"0.61.0"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        checker._read(file)


def test_bound_on_observation_size(tmp_path: Path) -> None:
    file = tmp_path / "huge.json"
    file.write_bytes(b"x" * (checker.MAX_EVIDENCE_BYTES + 1))
    with pytest.raises(ValueError, match="too large"):
        checker._read(file)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_model_free_probe_uses_only_whitelisted_tool_and_no_user_config(tmp_path: Path) -> None:
    # Deliberately fake local core; no network or GUI. A malicious/unpinned
    # core MUST be rejected before its executable module can be imported.
    # Positive integration evidence comes from the independent real CLI run.
    bundle = tmp_path / "installed" / "bundle"
    bundle.mkdir(parents=True)
    (bundle.parent / "package.json").write_text(
        json.dumps({"name": "@google/gemini-cli", "version": "0.60.0", "type": "module"}),
        encoding="utf-8",
    )
    entry = bundle / "gemini.js"
    entry.write_text("", encoding="utf-8")
    (bundle / "core-TEST.js").write_text(
        """
import { writeFileSync } from 'node:fs';
throw Error('UNTRUSTED CORE MODULE WAS EXECUTED');
export class McpClient {
  constructor(name, config) {
    if (name !== 'kicad' || config.trust !== false ||
        config.env.KICAD_MCP_OPERATING_MODE !== 'readonly' ||
        !config.env.KICAD_API_SOCKET.endsWith('unbound-kicad-ipc.sock')) {
      throw Error('unsafe configuration');
    }
  }
  async connect() {}
  getStatus() { return 'connected'; }
  async discoverTools() {
    return [{
      serverToolName: 'kicad_get_server_info',
      toolAnnotations: { readOnlyHint: true },
      createInvocation(params) {
        if (Object.keys(params).length) throw Error('nonempty arguments');
        return {async execute() {return {returnDisplay: 'mock diagnostic only'}}};
      }
    }];
  }
  async disconnect() {}
}
""",
        encoding="utf-8",
    )
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path / "ephemeral-home"),
        "USER": "gemini-test",
    }
    probe = ROOT / "scripts/probe_gemini_core_readonly.mjs"
    command = [shutil.which("node") or "node", str(probe), "--gemini-entry", str(entry)]
    result = subprocess.run(  # nosec B603  # nosemgrep
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert "Installed Gemini core exact SHA-256 mismatch" in result.stderr
    assert "mock diagnostic only" not in result.stdout

    env["GEMINI_API_KEY"] = "deliberate-fake-credential"
    rejected = subprocess.run(  # nosec B603  # nosemgrep
        command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=15, check=False
    )
    assert rejected.returncode != 0
    assert "Refusing inherited provider credential" in rejected.stderr
    assert "deliberate-fake-credential" not in rejected.stderr

    env.pop("GEMINI_API_KEY")
    env["KICAD_MCP_PROJECT_DIR"] = "/absolute/not-a-fixture"
    denied = subprocess.run(  # nosec B603  # nosemgrep
        command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=15, check=False
    )
    assert denied.returncode != 0
    assert "Refusing inherited provider credential or project" in denied.stderr
    assert "/absolute/not-a-fixture" not in denied.stderr
