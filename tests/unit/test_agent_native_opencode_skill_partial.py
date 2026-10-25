"""Reject accidental promotion of model-free OpenCode native Skill discovery."""

from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.check_agent_native_smoke_evidence import validate_report

ROOT = Path(__file__).resolve().parents[2]
PARTIAL = (
    ROOT / "docs" / "evidence" / "agent-host" / "2026-10-25-windows-opencode-skills-partial.json"
)
CATALOG = ROOT / "integrations/common/agent-host-evidence.json"
EXPECTED_SKILLS = {
    "drc-check",
    "fabrication-output",
    "kicad-design-review",
    "pcb-design",
    "schematic-review",
    "visual-excellence",
    "wired-subcircuit-design",
}


def _record() -> dict:
    return json.loads(PARTIAL.read_text(encoding="utf-8"))


def test_native_host_skills_are_bounded_to_actual_public_project_files() -> None:
    report = _record()
    assert report["schemaVersion"] == "agent-native-skill-discovery-partial.v1"
    assert report["observedOn"] == "2026-10-25"
    assert re.fullmatch(r"[0-9a-f]{40}", report["sourceRevision"])
    assert report["platform"] == "windows"
    assert report["host"] == {
        "id": "opencode",
        "version": "1.18.31",
        "command": "opencode debug skill --pure",
        "exitCode": 0,
    }
    discovery = report["skillDiscovery"]
    assert discovery["hostReportedSkillCount"] >= 7
    assert discovery["allSevenDiscovered"] is True
    assert discovery["allProjectSkillOriginsInsideSourceCheckout"] is True
    assert set(discovery["expectedProjectSkills"]) == EXPECTED_SKILLS
    for name, relative in discovery["expectedProjectSkills"].items():
        assert relative in {
            f".opencode/skills/{name}/SKILL.md",
            f".agents/skills/{name}/SKILL.md",
        }
        source = ROOT / relative
        assert source.is_file() and not source.is_symlink()
    assert re.fullmatch(r"[0-9a-f]{64}", discovery["stdoutSha256"])
    assert discovery["stderrBytes"] == 0
    assert discovery["rawOutputRetained"] is False


def test_native_skill_discovery_never_claims_mcp_or_release_attestation() -> None:
    report = _record()
    assert report["hostMcpServerDiscovery"] == "not-run"
    assert report["nativeHostMcpToolCall"] == "not-run"
    assert report["readonlyWriteToolAbsence"] == "not-run"
    assert report["modelInferenceExecuted"] is False
    assert report["catalogPromotionAuthorized"] is False
    assert report["fullNativeHostSmokeAttested"] is False

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert catalog["evidenceScope"] == "repository-static"
    assert all(row["smokeStatus"] == "not-run" for row in catalog["hosts"])
    assert validate_report(report, known_hosts={row["id"] for row in catalog["hosts"]}) == [
        "invalid_schema_fields"
    ]


def test_partial_file_has_no_host_paths_or_raw_credentials() -> None:
    text = PARTIAL.read_text(encoding="utf-8")
    assert not re.search(r"[/\\](?:home|Users|Admin)[/\\]", text, re.IGNORECASE)
    assert not re.search(r"(?i)(api[_-]?key|bearer|access[_-]?token|password|authorization)", text)
