"""Review a dated native-host observation without granting compatibility acceptance."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_agent_host_evidence import check

ROOT = Path(__file__).resolve().parents[2]
CATALOG = Path("integrations/common/agent-host-evidence.json")
EVIDENCE = Path("docs/evidence/agent-host")
REPORT = "2026-10-31-linux-codex-native-smoke.json"
LOG = "2026-10-31-linux-codex-native-sanitized-log.json"


def _fixture(tmp_path: Path) -> Path:
    catalog = json.loads((ROOT / CATALOG).read_text(encoding="utf-8"))
    paths = [
        CATALOG,
        Path("integrations/gemini-cli/kicad-mcp-pro/gemini-extension.json"),
        Path("packages/mcp-npm/package.json"),
        EVIDENCE / REPORT,
        EVIDENCE / LOG,
    ]
    for row in catalog["hosts"]:
        paths.extend([Path(row["configuration"]), Path(row["guide"])])
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, target)
    return tmp_path


def _change(tmp_path: Path, path: Path, key: str, value: object) -> None:
    target = tmp_path / path
    content = json.loads(target.read_text(encoding="utf-8"))
    content[key] = value
    target.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")


def test_reviewed_codex_observation_remains_not_attested() -> None:
    catalog = json.loads((ROOT / CATALOG).read_text(encoding="utf-8"))
    record = catalog["reviewedNativeObservations"]
    assert len(record) == 1
    assert record[0]["host"] == "codex"
    assert record[0]["os"] == "linux"
    assert record[0]["transport"] == "stdio"
    assert record[0]["report"] == REPORT
    assert record[0]["verification"] == "structurally-complete-not-independently-attested"
    assert catalog["evidenceScope"] == "repository-static"
    assert all(host["smokeStatus"] == "not-run" for host in catalog["hosts"])
    assert check(ROOT) == []


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("report", "reviewed native observation"),
        ("log", "reviewed native observation"),
        ("missing", "reviewed native observation"),
        ("symlink", "reviewed native observation"),
    ],
)
def test_changed_missing_or_linked_evidence_rejected(
    tmp_path: Path,
    target: str,
    expected: str,
) -> None:
    repo = _fixture(tmp_path)
    report = repo / EVIDENCE / REPORT
    log = repo / EVIDENCE / LOG
    if target == "report":
        _change(repo, EVIDENCE / REPORT, "server_version", "4.6.0")
    elif target == "log":
        _change(repo, EVIDENCE / LOG, "server_version", "4.6.0")
    elif target == "missing":
        log.unlink()
    else:
        log.unlink()
        log.symlink_to(report)
    assert any(expected in message for message in check(repo))


@pytest.mark.parametrize(
    "mutation",
    [
        {"host": "gemini-cli"},
        {"verification": "passed"},
        {"transport": "streamable-http"},
        {"os": "windows"},
        {"report": "../unreviewed-smoke.json"},
    ],
)
def test_unreviewed_or_promoted_claim_rejected(tmp_path: Path, mutation: dict) -> None:
    repo = _fixture(tmp_path)
    path = repo / CATALOG
    catalog = json.loads(path.read_text(encoding="utf-8"))
    catalog["reviewedNativeObservations"][0].update(mutation)
    path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    assert any("reviewed native observation" in issue for issue in check(repo))


def test_unchanged_native_archive_is_accepted_by_static_ci(tmp_path: Path) -> None:
    assert check(_fixture(tmp_path)) == []


def test_real_ci_script_entrypoint_accepts_reviewed_archive() -> None:
    # The required CI policy job invokes the script by path, not with -m.
    cmd = [sys.executable, str(ROOT / "scripts/check_agent_host_evidence.py")]
    run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    assert "static only" in run.stdout
