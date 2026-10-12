"""Protect partial real-host observations from accidental compatibility promotion."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

from scripts.check_agent_native_smoke_evidence import validate_report

ROOT = Path(__file__).resolve().parents[2]
OBSERVATION = ROOT / "docs/evidence/agent-host/2026-10-12-windows-readonly-stdio-partial.json"
CATALOG = ROOT / "integrations/common/agent-host-evidence.json"
_SHA = re.compile(r"[0-9a-f]{40}\Z")


def _observation() -> dict[str, object]:
    data = json.loads(OBSERVATION.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return cast(dict[str, object], data)


def test_observation_is_sanitized_exact_source_and_not_an_attestation() -> None:
    report = _observation()
    assert set(report) == {
        "schemaVersion",
        "observedOn",
        "sourceRevision",
        "serverVersion",
        "kicadCliVersion",
        "platform",
        "transport",
        "operatingMode",
        "profile",
        "environment",
        "hosts",
        "independentSdkProbe",
        "catalogPromotionAuthorized",
        "realHostToolInvocationEstablished",
        "fullNativeHostSmokeAttested",
    }
    assert report["schemaVersion"] == "agent-native-host-partial.v1"
    assert report["observedOn"] == "2026-10-12"
    assert isinstance(report["sourceRevision"], str)
    assert _SHA.fullmatch(report["sourceRevision"])
    assert report["platform"] == "windows"
    assert report["transport"] == "stdio"
    assert report["operatingMode"] == "readonly"
    assert report["profile"] == "default"
    assert report["environment"] == "isolated-user-config"
    assert all(
        report[key] is False
        for key in (
            "catalogPromotionAuthorized",
            "realHostToolInvocationEstablished",
            "fullNativeHostSmokeAttested",
        )
    )
    text = OBSERVATION.read_text(encoding="utf-8")
    assert not re.search(r"[/\\](?:home|Users|Admin)[/\\]", text, re.IGNORECASE)
    assert not re.search(r"(?i)(api[_-]?key|bearer|access[_-]?token|password|authorization)", text)


def test_native_host_statuses_are_not_mixed_with_generic_sdk_tool_calls() -> None:
    report = _observation()
    rows = report["hosts"]
    assert isinstance(rows, list)
    assert len(rows) == 2
    by_host = {row["id"]: row for row in rows}
    assert set(by_host) == {"claude-code", "codex"}
    assert by_host["claude-code"]["version"] == "2.1.296"
    assert by_host["claude-code"]["connectionObserved"] == "connected"
    assert by_host["codex"]["version"] == "0.151.0"
    assert by_host["codex"]["connectionObserved"] == "not-verified"
    for row in rows:
        assert row["configurationListed"] is True
        assert row["skillDiscovery"] == "not-run"
        assert row["nativeToolCall"] == "not-run"
    sdk = report["independentSdkProbe"]
    assert sdk == {
        "sdkVersion": "2.2.0",
        "initializeSucceeded": True,
        "discoveredToolCount": 24,
        "readonlyTool": "kicad_get_server_info",
        "readonlyCallSucceeded": True,
        "designMutationToolsExposed": False,
        "sessionProjectSelectorDiscovered": True,
    }


def test_partial_observation_cannot_be_reported_as_native_host_attestation() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert catalog["evidenceScope"] == "repository-static"
    assert all(row["smokeStatus"] == "not-run" for row in catalog["hosts"])
    assert validate_report(
        _observation(),
        known_hosts={row["id"] for row in catalog["hosts"]},
    ) == ["invalid_schema_fields"]
