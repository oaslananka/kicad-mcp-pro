#!/usr/bin/env python3
"""Validate the repository compatibility matrix against product metadata."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

MCP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MCP_ROOT
HAS_VSCODE_EXTENSION = (REPO_ROOT / "apps" / "vscode-extension").is_dir()
PCBNEW_POLICY = "forbidden-in-production"
REQUIRED_IPC_AREAS = (
    "projectDiscovery",
    "pcbRead",
    "schematicRead",
    "drc",
    "erc",
    "export",
    "diagnostics",
)
KICAD_SUPPORT_STATES = {"primary", "supported", "deprecated"}
KICAD_CI_MODES = {"required", "scheduled", "manual"}
KICAD10_FEATURE_STATUSES = {"supported", "not-applicable", "partial", "blocked", "future"}
PRODUCT_EVIDENCE_PREFIXES = ("path:", "fixture:", "command:", "smoke:")
ISSUE_URL_RE = re.compile(r"^https://github.com/oaslananka/kicad-mcp-pro/issues/\d+$")
URL_RE = re.compile(r"^https://[^\s]+$")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path} must contain a YAML mapping")
    return data


def _pyproject() -> dict[str, Any]:
    return tomllib.loads((MCP_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _mcp_compat_from_ts() -> dict[str, str]:
    text = (REPO_ROOT / "apps/vscode-extension/src/mcp/compatibilityMatrix.ts").read_text(
        encoding="utf-8"
    )
    values: dict[str, str] = {}
    for key in ("required", "recommended", "testedAgainst"):
        match = re.search(rf"{key}:\s*'([^']+)'", text)
        if match is None:
            raise ValueError(f"compatibilityMatrix.ts missing {key}")
        values[key] = match.group(1)
    return values


def _extension_protocol_from_ts() -> str:
    text = (REPO_ROOT / "apps/vscode-extension/src/mcp/compatibilityMatrix.ts").read_text(
        encoding="utf-8"
    )
    match = re.search(r"protocolVersion:\s*'([^']+)'", text)
    if match is None:
        raise ValueError("compatibilityMatrix.ts missing protocolVersion")
    return match.group(1)


def _tool_names() -> set[str]:
    text = (MCP_ROOT / "docs/tools-reference.generated.md").read_text(encoding="utf-8")
    return set(re.findall(r"^\| `([^`]+)` \|", text, flags=re.MULTILINE))


def _validate_repo_relative_path(value: object, label: str) -> list[str]:
    if not isinstance(value, str) or not value:
        return [f"{label} must be a non-empty relative path"]
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return [f"{label} must stay inside the repository: {value!r}"]
    return []


def _repo_path_exists(relative_path: str) -> bool:
    if "*" in relative_path:
        return any(REPO_ROOT.glob(relative_path))
    return (REPO_ROOT / relative_path).exists()


def _validate_issue_url(value: object, label: str) -> list[str]:
    if not isinstance(value, str) or ISSUE_URL_RE.fullmatch(value) is None:
        return [f"{label} must link to a GitHub issue in this repository"]
    return []


def _validate_evidence_entry(value: object, label: str) -> list[str]:
    if not isinstance(value, str) or ":" not in value:
        return [f"{label} must be prefixed evidence such as path:, fixture:, command:, smoke:"]
    prefix, payload = value.split(":", 1)
    if not payload:
        return [f"{label} must include evidence detail after {prefix!r}"]
    if prefix == "path":
        errors = _validate_repo_relative_path(payload, label)
        if not errors and not _repo_path_exists(payload):
            # In standalone repo, skip paths under apps/vscode-extension/
            if not HAS_VSCODE_EXTENSION and payload.startswith("apps/vscode-extension/"):
                return errors
            errors.append(f"{label} path does not exist: {payload!r}")
        return errors
    if prefix == "fixture":
        fixture_path = REPO_ROOT / "packages" / "kicad-fixtures" / "fixtures" / payload
        return [] if fixture_path.exists() else [f"{label} fixture does not exist: {payload!r}"]
    if prefix == "source":
        return [] if URL_RE.fullmatch(payload) else [f"{label} source must be an HTTPS URL"]
    if prefix in {"command", "smoke"}:
        return []
    return [f"{label} uses unknown evidence prefix {prefix!r}"]


def _has_product_evidence(evidence: list[object]) -> bool:
    return any(
        isinstance(item, str) and item.startswith(PRODUCT_EVIDENCE_PREFIXES) for item in evidence
    )


def _validate_feature_evidence(
    detail: dict[str, Any],
    label: str,
    *,
    require_product_evidence: bool,
) -> list[str]:
    evidence = detail.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return [f"{label}.evidence must be a non-empty list"]
    errors: list[str] = []
    for index, item in enumerate(evidence):
        errors.extend(_validate_evidence_entry(item, f"{label}.evidence[{index}]"))
    if require_product_evidence and not _has_product_evidence(evidence):
        errors.append(f"{label}.evidence must include path:, fixture:, command:, or smoke:")
    return errors


def _validate_kicad10_feature(
    group: str,
    feature: str,
    detail: object,
    docs_text: str,
    *,
    label_root: str = "kicad10FeatureParity.surfaces",
) -> list[str]:
    label = f"{label_root}.{group}.{feature}"
    if not isinstance(detail, dict):
        return [f"{label} must be a mapping"]
    errors: list[str] = []
    status = detail.get("status")
    if status not in KICAD10_FEATURE_STATUSES:
        errors.append(f"{label}.status must be one of {sorted(KICAD10_FEATURE_STATUSES)!r}")
    for key in ("nativeSurface", "productSurface", "notes"):
        if not isinstance(detail.get(key), str) or not detail[key]:
            errors.append(f"{label}.{key} must be a non-empty string")
    errors.extend(
        _validate_feature_evidence(
            detail,
            label,
            require_product_evidence=status == "supported",
        )
    )
    if status in {"partial", "blocked"}:
        errors.extend(_validate_issue_url(detail.get("issue"), f"{label}.issue"))
    elif "issue" in detail:
        errors.extend(_validate_issue_url(detail.get("issue"), f"{label}.issue"))
    if docs_text and feature not in docs_text:
        errors.append(f"{label} is not documented in the parity docs page")
    return errors


def _validate_kicad10_group(
    group: str,
    features: object,
    docs_text: str,
    *,
    label_root: str,
) -> list[str]:
    if not isinstance(features, dict) or not features:
        return [f"{label_root}.{group} must be a non-empty mapping"]
    errors: list[str] = []
    for feature, detail in features.items():
        if not isinstance(feature, str) or not feature:
            errors.append(f"{label_root}.{group} feature keys must be non-empty strings")
            continue
        errors.extend(
            _validate_kicad10_feature(
                group,
                feature,
                detail,
                docs_text,
                label_root=label_root,
            )
        )
    return errors


def _validate_kicad10_sources(parity: dict[str, Any]) -> list[str]:
    sources = parity.get("sources")
    if not isinstance(sources, dict) or not sources:
        return ["kicad10FeatureParity.sources must be a non-empty mapping"]
    errors: list[str] = []
    for key, value in sources.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or URL_RE.fullmatch(value) is None
        ):
            errors.append(f"kicad10FeatureParity.sources.{key} must be an HTTPS URL")
    return errors


def _kicad10_docs_text(parity: dict[str, Any]) -> tuple[str, list[str]]:
    docs_path = parity.get("documentation")
    label = "kicad10FeatureParity.documentation"
    errors = _validate_repo_relative_path(docs_path, label)
    if not isinstance(docs_path, str) or errors:
        return "", errors
    full_docs_path = REPO_ROOT / docs_path
    if not full_docs_path.exists():
        return "", [f"{label} does not exist: {docs_path!r}"]
    return full_docs_path.read_text(encoding="utf-8"), []


def _validate_kicad10_surface_groups(
    surfaces: object,
    docs_text: str,
) -> list[str]:
    required_groups = {
        "importers",
        "exports",
        "gui_editor",
        "ipc",
        "mcp_server",
        "release",
    }
    if HAS_VSCODE_EXTENSION:
        required_groups.add("vscode_extension")
    if not isinstance(surfaces, dict):
        return ["kicad10FeatureParity.surfaces must be a mapping"]
    errors: list[str] = []
    missing = required_groups - set(surfaces)
    if missing:
        errors.append(f"kicad10FeatureParity.surfaces missing groups: {sorted(missing)!r}")
    for group, features in surfaces.items():
        errors.extend(
            _validate_kicad10_group(
                group,
                features,
                docs_text,
                label_root="kicad10FeatureParity.surfaces",
            )
        )
    return errors


def _validate_kicad10_feature_parity(matrix: dict[str, Any]) -> list[str]:
    parity = matrix.get("kicad10FeatureParity")
    if not isinstance(parity, dict):
        return ["compatibility.yaml missing top-level 'kicad10FeatureParity'"]
    errors = _validate_kicad10_sources(parity)
    if parity.get("baseline") != matrix.get("kicad", {}).get("latestVerified"):
        errors.append("kicad10FeatureParity.baseline must match kicad.latestVerified")
    if set(parity.get("allowedStatuses", [])) != KICAD10_FEATURE_STATUSES:
        errors.append("kicad10FeatureParity.allowedStatuses must match the validator vocabulary")

    docs_text, docs_errors = _kicad10_docs_text(parity)
    errors.extend(docs_errors)
    errors.extend(_validate_kicad10_surface_groups(parity.get("surfaces"), docs_text))
    errors.extend(
        _validate_kicad10_group(
            "kicad11Readiness",
            parity.get("kicad11Readiness"),
            docs_text,
            label_root="kicad10FeatureParity",
        )
    )
    return errors


def _validate_pcbnew_policy(readiness: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    direct = readiness.get("directPcbnewImports")
    if not isinstance(direct, dict):
        return ["kicadIpcReadiness.directPcbnewImports must be a mapping"]
    if direct.get("policy") != PCBNEW_POLICY:
        errors.append(f"kicadIpcReadiness.directPcbnewImports.policy must be {PCBNEW_POLICY!r}")
    allowed = direct.get("allowedPaths")
    if not isinstance(allowed, list) or not allowed:
        return [*errors, "kicadIpcReadiness.directPcbnewImports.allowedPaths must be a list"]
    for index, value in enumerate(allowed):
        errors.extend(
            _validate_repo_relative_path(value, f"directPcbnewImports.allowedPaths[{index}]")
        )
    if "tests/**" not in allowed:
        errors.append("direct pcbnew allowlist must document test-only compatibility paths")
    return errors


def _validate_manual_canary(readiness: dict[str, Any]) -> list[str]:
    manual = readiness.get("manualCanary")
    if not isinstance(manual, dict):
        return ["kicadIpcReadiness.manualCanary must be a mapping"]
    errors: list[str] = []
    for key in ("currentNightlyRange", "releaseCandidateRange"):
        value = manual.get(key)
        if not isinstance(value, str) or re.fullmatch(r"\d+(?:\.\d+)?\.x", value) is None:
            errors.append(f"kicadIpcReadiness.manualCanary.{key} must be a KiCad range")
    for key in ("currentNightlyCommand", "releaseCandidateCommand"):
        if not isinstance(manual.get(key), str) or not manual[key]:
            errors.append(f"kicadIpcReadiness.manualCanary.{key} must be a non-empty command")
    return errors


def _validate_ipc_area(
    area: str,
    detail: object,
    available_tools: set[str],
) -> list[str]:
    if not isinstance(detail, dict):
        return [f"kicadIpcReadiness.ipcApi.requiredFor.{area} must be a mapping"]
    errors: list[str] = []
    for key in ("tools", "canaryProbes", "evidence"):
        if not isinstance(detail.get(key), list) or not detail[key]:
            errors.append(f"kicadIpcReadiness.ipcApi.requiredFor.{area}.{key} must be a list")
    for tool_name in detail.get("tools", []):
        if isinstance(tool_name, str) and tool_name not in available_tools:
            errors.append(f"kicadIpcReadiness {area} references unknown tool {tool_name!r}")
    for index, evidence in enumerate(detail.get("evidence", [])):
        label = f"kicadIpcReadiness.ipcApi.requiredFor.{area}.evidence[{index}]"
        errors.extend(_validate_repo_relative_path(evidence, label))
        if isinstance(evidence, str) and not (REPO_ROOT / evidence).exists():
            errors.append(f"{label} does not exist: {evidence!r}")
    return errors


def _validate_ipc_readiness(
    matrix: dict[str, Any],
    available_tools: set[str],
) -> list[str]:
    readiness = matrix.get("kicadIpcReadiness")
    if not isinstance(readiness, dict):
        return ["compatibility.yaml missing top-level 'kicadIpcReadiness'"]
    errors = [*_validate_pcbnew_policy(readiness), *_validate_manual_canary(readiness)]
    ipc_api = readiness.get("ipcApi")
    required_for = ipc_api.get("requiredFor") if isinstance(ipc_api, dict) else None
    if not isinstance(required_for, dict):
        return [*errors, "kicadIpcReadiness.ipcApi.requiredFor must be a mapping"]
    for area in REQUIRED_IPC_AREAS:
        if area not in required_for:
            errors.append(f"kicadIpcReadiness.ipcApi.requiredFor missing {area!r}")
            continue
        errors.extend(_validate_ipc_area(area, required_for[area], available_tools))
    return errors


def _validate_required_shape(matrix: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_top = {"schemaVersion", "kicad", "vscode", "node", "pnpm", "python", "mcp", "products"}
    for key in required_top:
        if key not in matrix:
            errors.append(f"compatibility.yaml missing top-level {key!r}")
    if errors:
        return errors
    products = matrix["products"]
    if not isinstance(products, dict):
        return ["compatibility.yaml products must be a mapping"]
    required_products = {"kicad-mcp-pro"}
    if HAS_VSCODE_EXTENSION:
        required_products.add("kicad-studio")
    for key in required_products:
        if key not in products:
            errors.append(f"compatibility.yaml products missing {key!r}")
    return errors


def _validate_kicad_support_policy(matrix: dict[str, Any]) -> list[str]:
    kicad = matrix.get("kicad")
    if not isinstance(kicad, dict):
        return ["compatibility.yaml kicad must be a mapping"]
    primary = kicad.get("primary")
    if not isinstance(primary, str) or not primary:
        return ["compatibility.yaml kicad.primary must be a non-empty string"]
    entries = kicad.get("supported")
    if not isinstance(entries, list) or not entries:
        return ["compatibility.yaml kicad.supported must be a non-empty list"]

    errors: list[str] = []
    primary_entries = 0
    for index, entry in enumerate(entries):
        label = f"kicad.supported[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be a mapping")
            continue
        kicad_range = entry.get("range")
        state = entry.get("state")
        ci_mode = entry.get("ci")
        if not isinstance(kicad_range, str) or not kicad_range:
            errors.append(f"{label}.range must be a non-empty string")
        if state not in KICAD_SUPPORT_STATES:
            errors.append(f"{label}.state must be one of {sorted(KICAD_SUPPORT_STATES)!r}")
        if ci_mode not in KICAD_CI_MODES:
            errors.append(f"{label}.ci must be one of {sorted(KICAD_CI_MODES)!r}")
        if not isinstance(entry.get("notes"), str) or not entry["notes"]:
            errors.append(f"{label}.notes must be a non-empty string")
        if entry.get("upstreamEol") is True and state != "deprecated":
            errors.append(f"{label} marks upstreamEol but is not deprecated")
        if kicad_range == primary:
            primary_entries += 1
            if state != "primary" or ci_mode != "required":
                errors.append(f"{label} must be primary and required for {primary!r}")
    if primary_entries != 1:
        errors.append(f"kicad.supported must contain exactly one primary entry for {primary!r}")
    return errors


def validate_compatibility_matrix() -> list[str]:
    """Return compatibility drift errors without exiting."""
    matrix = _read_yaml(REPO_ROOT / "compatibility.yaml")
    errors = _validate_required_shape(matrix)
    errors.extend(_validate_kicad_support_policy(matrix))
    errors.extend(_validate_kicad10_feature_parity(matrix))

    # Standalone repo: tolerate evidence paths for Studio-owned files that are
    # intentionally absent because the VS Code extension is not part of the
    # kicad-mcp standalone repository.
    if not HAS_VSCODE_EXTENSION:
        allowed_missing_paths = frozenset(
            {
                ".github/workflows/publish-extension.yml",  # VS Code extension workflow
            }
        )
        errors = [e for e in errors if not any(f"'{p}'" in e for p in allowed_missing_paths)]

    if errors:
        return errors

    root_pkg = _read_json(REPO_ROOT / "package.json")
    pyproject = _pyproject()
    server_json = _read_json(MCP_ROOT / "server.json")

    mcp_product = matrix["products"]["kicad-mcp-pro"]

    expected_pairs = [
        ("root Node range", matrix["node"]["range"], root_pkg["engines"]["node"]),
        ("root pnpm range", matrix["pnpm"]["range"], root_pkg["engines"]["pnpm"]),
        ("kicad-mcp-pro version", mcp_product["version"], pyproject["project"]["version"]),
        ("kicad-mcp-pro server.json version", mcp_product["version"], server_json["version"]),
        ("Python range", matrix["python"]["range"], pyproject["project"]["requires-python"]),
    ]
    for label, expected, actual in expected_pairs:
        if expected != actual:
            errors.append(f"{label} drift: compatibility.yaml={expected!r}, metadata={actual!r}")

    if HAS_VSCODE_EXTENSION:
        extension_pkg = _read_json(REPO_ROOT / "apps/vscode-extension/package.json")
        studio = matrix["products"]["kicad-studio"]
        expected_pairs_vscode = [
            ("kicad-studio version", studio["version"], extension_pkg["version"]),
            (
                "kicad-studio VS Code engines range",
                matrix["vscode"]["enginesRange"],
                extension_pkg["engines"]["vscode"],
            ),
            (
                "kicad-studio Node runtime",
                matrix["vscode"]["nodeRuntime"],
                extension_pkg["engines"]["node"],
            ),
        ]
        for label, expected, actual in expected_pairs_vscode:
            if expected != actual:
                errors.append(
                    f"{label} drift: compatibility.yaml={expected!r}, metadata={actual!r}"
                )

        ts_compat = _mcp_compat_from_ts()
        for key, expected in studio["compatibleMcpPro"].items():
            if ts_compat.get(key) != expected:
                errors.append(
                    f"extension MCP compatibility {key} drift: "
                    f"compatibility.yaml={expected!r}, TS={ts_compat.get(key)!r}"
                )

        extension_protocol = _extension_protocol_from_ts()
        if extension_protocol != matrix["mcp"]["protocolVersion"]:
            errors.append(
                "extension MCP protocol version drift: "
                "compatibility.yaml="
                f"{matrix['mcp']['protocolVersion']!r}, TS={extension_protocol!r}"
            )
        mcp_client_source = (REPO_ROOT / "apps/vscode-extension/src/mcp/mcpClient.ts").read_text(
            encoding="utf-8"
        )
        if "protocolVersion: MCP_PROTOCOL_VERSION" not in mcp_client_source:
            errors.append("extension MCP client must initialize with MCP_PROTOCOL_VERSION")

    sys.path.insert(0, str(MCP_ROOT / "src"))
    from kicad_mcp.compatibility import COMPATIBILITY_MATRIX as PY_COMPATIBILITY_MATRIX

    embedded = PY_COMPATIBILITY_MATRIX
    if embedded["mcp"]["protocolVersion"] != matrix["mcp"]["protocolVersion"]:
        errors.append("Python compatibility protocol version drift")
    if embedded["mcp"]["toolSchema"] != matrix["mcp"]["toolSchema"]:
        errors.append("Python compatibility tool schema drift")
    if embedded["kicad"]["primary"] != matrix["kicad"]["primary"]:
        errors.append("Python compatibility primary KiCad version drift")
    if embedded["products"]["kicad-mcp-pro"]["version"] != mcp_product["version"]:
        errors.append("Python compatibility MCP package version drift")

    wellknown_source = (MCP_ROOT / "src/kicad_mcp/wellknown.py").read_text(encoding="utf-8")
    if "MCP_PROTOCOL_VERSION" not in wellknown_source:
        errors.append("well-known server card must use MCP_PROTOCOL_VERSION")
    if "compatibility_summary()" not in wellknown_source:
        errors.append("well-known server card must embed compatibility_summary()")

    available_tools = _tool_names()
    errors.extend(_validate_ipc_readiness(matrix, available_tools))
    for group in ("required", "optional"):
        for tool_name in matrix["mcpTools"][group]:
            if tool_name not in available_tools:
                errors.append(
                    f"compatibility.yaml mcpTools.{group} references unknown tool {tool_name!r}"
                )
    for feature, detail in matrix["featureGates"].items():
        for tool_name in detail.get("tools", []):
            if tool_name not in available_tools:
                errors.append(f"featureGates.{feature} references unknown tool {tool_name!r}")

    return errors


def main() -> int:
    errors = validate_compatibility_matrix()
    if errors:
        print("Compatibility matrix validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Compatibility matrix validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
