from __future__ import annotations

import yaml

from kicad_mcp.compatibility import COMPATIBILITY_MATRIX, MCP_PROTOCOL_VERSION
from scripts.check_compatibility_matrix import (
    KICAD10_FEATURE_STATUSES,
    PCBNEW_POLICY,
    REPO_ROOT,
    REQUIRED_IPC_AREAS,
    validate_compatibility_matrix,
)


def test_embedded_compatibility_metadata_declares_current_contract() -> None:
    assert COMPATIBILITY_MATRIX["mcp"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert COMPATIBILITY_MATRIX["kicad"]["primary"] == "10.0.x"
    assert (
        COMPATIBILITY_MATRIX["products"]["kicad-studio"]["compatibleMcpPro"]["required"]
        == ">=3.5.2 <4.0.0"
    )


def test_repository_compatibility_matrix_has_no_drift() -> None:
    assert validate_compatibility_matrix() == []


def test_kicad_9_upstream_eol_policy_is_dropped() -> None:
    matrix = yaml.safe_load((REPO_ROOT / "compatibility.yaml").read_text(encoding="utf-8"))
    kicad_9 = next(entry for entry in matrix["kicad"]["dropped"] if entry["range"] == "9.x")

    assert "Upstream KiCad 9.x reached end of life" in kicad_9["reason"]
    assert kicad_9["ci"] == "none"
    assert kicad_9["removalVersion"] == "3.9.0"
    assert "9.x" not in [e["range"] for e in matrix["kicad"]["supported"]]
    assert COMPATIBILITY_MATRIX["kicad"]["deprecated"] == ["8.x"]


def test_kicad_ipc_readiness_contract_covers_pcbnew_and_parity() -> None:
    matrix = yaml.safe_load((REPO_ROOT / "compatibility.yaml").read_text(encoding="utf-8"))
    readiness = matrix["kicadIpcReadiness"]
    direct_imports = readiness["directPcbnewImports"]
    required_for = readiness["ipcApi"]["requiredFor"]

    assert direct_imports["policy"] == PCBNEW_POLICY
    assert direct_imports["allowedPaths"] == [
        "scripts/check_no_pcbnew.py",
        "tests/**",
    ]
    assert set(REQUIRED_IPC_AREAS).issubset(required_for)
    assert readiness["manualCanary"]["currentNightlyRange"] == "10.99.x"
    assert readiness["manualCanary"]["releaseCandidateRange"] == "11.0.x"


def test_kicad10_feature_parity_matrix_tracks_gaps_and_evidence() -> None:
    matrix = yaml.safe_load((REPO_ROOT / "compatibility.yaml").read_text(encoding="utf-8"))
    parity = matrix["kicad10FeatureParity"]
    surfaces = parity["surfaces"]

    assert matrix["kicad"]["latestVerified"] == "10.0.5"
    assert parity["baseline"] == matrix["kicad"]["latestVerified"]
    assert parity["primaryIssue"].endswith("/issues/191")
    assert parity["documentation"] == "docs/compatibility/kicad-10-0-5-feature-parity.md"
    assert set(parity["allowedStatuses"]) == KICAD10_FEATURE_STATUSES
    assert surfaces["importers"]["allegro"]["status"] == "blocked"
    assert surfaces["exports"]["stepz"]["status"] == "supported"
    assert "stpz" in surfaces["exports"]["stepz"]["nativeSurface"]
    assert surfaces["exports"]["xao"]["status"] == "supported"
    assert surfaces["gui_editor"]["time_domain_tuning"]["status"] == "supported"
    assert surfaces["gui_editor"]["graphical_drc_rule_editor"]["status"] == "not-applicable"
    assert surfaces["mcp_server"]["empty_project_read_tools"]["issue"].endswith("/issues/228")
    assert parity["kicad11Readiness"]["protocol_upgrade"]["issue"].endswith("/issues/197")

    supported_items = [
        feature
        for group in surfaces.values()
        for feature in group.values()
        if feature["status"] == "supported"
    ]
    assert supported_items
    assert all(
        any(
            item.startswith(("path:", "fixture:", "command:", "smoke:"))
            for item in feature["evidence"]
        )
        for feature in supported_items
    )


def test_kicad_adapter_matrix_contract_is_generated_and_release_gated() -> None:
    matrix = yaml.safe_load((REPO_ROOT / "compatibility.yaml").read_text(encoding="utf-8"))
    adapter = matrix["kicadAdapterMatrix"]

    assert adapter["stableBaseline"] == matrix["kicad"]["primary"]
    assert adapter["previewBaseline"] == "11.x"
    assert set(adapter["surfaces"]) == {"read", "write", "export"}
    assert adapter["noSwigGuard"] == "scripts/check_no_pcbnew.py"
    assert adapter["generatedJson"] == "integrations/common/kicad-adapter-matrix.json"
    assert adapter["decisionRecord"].endswith("0007-kicad-adapter-selection-and-swig-retirement.md")
    assert set(adapter["mutationEvidence"]) == {
        "schematicRoundTrip",
        "schematicWriter",
        "transactionGuard",
        "adapterContract",
    }
