"""Fail-closed review of a partial Gemini CLI core model-free MCP observation.

This checks structure and same-source readonly policy; it does NOT attest the
native binary, run a host GUI session, or promote any host compatibility claim.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kicad_mcp.operating_modes import OperatingMode, known_tool_names, tool_required_mode

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/agent-host/2026-10-28-linux-gemini-core-readonly.json"
EXTENSION = ROOT / "integrations/gemini-cli/kicad-mcp-pro/gemini-extension.json"
CATALOG = ROOT / "integrations/common/agent-host-evidence.json"

GEMINI_VERSION = "0.60.0"
REVIEWED_CORE_SHA256 = "82bbf0bd5c3c0040b6b454d7977a0c03c4fee6ae7b8891f282c7e7c896567ab5"
SOURCE_SHA = "7c18dfa071b74e12e4d09027b86fe799ed7bd6c9"
DIAGNOSTIC = "kicad_get_server_info"
MAX_EVIDENCE_BYTES = 20_000


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_EVIDENCE_BYTES:
        raise ValueError("Evidence too large")
    item = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
    if not isinstance(item, dict):
        raise ValueError("Evidence must be a JSON object")
    return item


def check(report: dict[str, Any]) -> list[str]:
    """Reject false acceptance, source/pin drift, unknown or non-readonly tools."""

    errors: list[str] = []
    manifest = _read(EXTENSION)
    catalog = _read(CATALOG)
    server = manifest["mcpServers"]["kicad"]

    def ensure(condition: bool, what: str) -> None:
        if not condition:
            errors.append(what)

    ensure(report.get("schemaVersion") == "gemini-core-readonly-diagnostic.v1", "schema")
    ensure(report.get("observedOn") == "2026-10-28", "date")
    ensure(report.get("reviewedSourceRevision") == SOURCE_SHA, "reviewed source SHA")
    ensure(report.get("hostPackage") == "@google/gemini-cli", "host identity")
    ensure(report.get("hostVersion") == GEMINI_VERSION, "Gemini build")
    ensure(report.get("hostCoreSha256") == REVIEWED_CORE_SHA256, "reviewed core digest")
    ensure(
        report.get("actualInvocationPath")
        == "McpClient.discoverTools/DiscoveredMCPToolInvocation.execute",
        "core native invocation path",
    )
    ensure(
        report.get("launchArgs")
        == server.get("args")
        == ["--from", "kicad-mcp-pro==4.4.0", "kicad-mcp-pro", "--transport", "stdio"],
        "published-version launch pin",
    )
    ensure(manifest["version"] == "4.4.0" and server.get("command") == "uvx", "extension version")
    ensure(
        report.get("operatingMode")
        == server.get("env", {}).get("KICAD_MCP_OPERATING_MODE")
        == "readonly",
        "readonly mode",
    )
    ensure(
        report.get("profile") == server.get("env", {}).get("KICAD_MCP_PROFILE") == "default",
        "profile",
    )
    ensure(report.get("transport") == "stdio", "transport")
    ensure(server.get("trust") is not True, "extension tool trust")
    ensure(report.get("connected") is True, "connection")

    names = report.get("discoveredTools")
    if (
        not isinstance(names, list)
        or not (1 <= len(names) <= 256)
        or not all(isinstance(x, str) for x in names)
    ):
        errors.append("tool inventory structure")
    else:
        ensure(names == sorted(set(names)), "tool inventory ordered/unique")
        known = set(known_tool_names())
        ensure(all(name in known for name in names), "unknown tool in inventory")
        ensure(
            all(tool_required_mode(name) is OperatingMode.READONLY for name in names),
            "write/manufacturing/experimental tool in readonly inventory",
        )
        ensure(DIAGNOSTIC in names, "diagnostic missing")

    missing = report.get("missingReadOnlyAnnotations")
    if not isinstance(missing, list) or not all(isinstance(x, str) for x in missing):
        errors.append("annotation list")
    elif isinstance(names, list):
        ensure(
            missing == sorted(set(missing)) and set(missing) <= set(names), "annotation inventory"
        )

    ensure(report.get("calledOnly") == DIAGNOSTIC, "only diagnostic may be called")
    for key in (
        "responseError",
        "rawResponseRetained",
        "modelTurnStarted",
        "hostCliInteractiveSession",
        "independentProcessAttestation",
        "fullHostAcceptance",
        "kiCadIpcSocketCreated",
    ):
        ensure(report.get(key) is False, f"unsupported/unsafe evidence claim: {key}")
    for key in ("responsePresent", "temporaryEnvironmentRemoved"):
        ensure(report.get(key) is True, f"required observed property: {key}")

    # A Gemini core library invocation is NOT an interactive CLI-host smoke.
    ensure(
        all(row["smokeStatus"] == "not-run" for row in catalog["hosts"]),
        "unreviewed promotion of six-host catalog",
    )
    return errors


def main() -> int:
    try:
        errors = check(_read(EVIDENCE))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Gemini core evidence invalid: {exc}")
        return 1
    if errors:
        for error in errors:
            print(f"Gemini core evidence invalid: {error}")
        return 1
    print("Gemini CLI core diagnostic: source-bound, readonly, partial-only evidence valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
