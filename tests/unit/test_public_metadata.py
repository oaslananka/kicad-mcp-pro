from __future__ import annotations

import importlib.util
import json
import re
import tomllib
from pathlib import Path

import yaml
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]


def _load_metadata_sync_module() -> object:
    script = ROOT / "scripts" / "sync_mcp_metadata.py"
    spec = importlib.util.spec_from_file_location("sync_mcp_metadata_public", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repository_identity_is_loaded_from_pyproject() -> None:
    module = _load_metadata_sync_module()

    metadata = module._project_metadata()

    assert metadata["repository_url"] == "https://github.com/oaslananka/kicad-mcp-pro"
    assert metadata["repository_id"] == "R_kgDOStXTag"


def test_server_manifest_uses_canonical_repository_identity() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))

    assert server["repository"]["url"] == pyproject["project"]["urls"]["Repository"]
    assert (
        server["repository"]["id"]
        == pyproject["tool"]["kicad-mcp"]["public-metadata"]["repository-id"]
    )


def test_public_support_docs_match_compatibility_policy() -> None:
    matrix = yaml.safe_load((ROOT / "compatibility.yaml").read_text(encoding="utf-8"))
    faq = (ROOT / "docs" / "faq.md").read_text(encoding="utf-8")

    dropped_ranges = {entry["range"] for entry in matrix["kicad"]["dropped"]}
    assert "9.x" in dropped_ranges
    assert "KiCad 9 is supported" not in faq
    assert "KiCad 9.x has been dropped and is not supported." in faq
    assert f"KiCad {matrix['kicad']['primary']} is the primary supported target." in faq


def test_upcoming_roadmap_does_not_list_published_versions() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    current = Version(pyproject["project"]["version"])
    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    upcoming = roadmap.split("## Upcoming", maxsplit=1)[1].split("\n## ", maxsplit=1)[0]
    versions = [
        Version(match) for match in re.findall(r"^###\s+(\d+\.\d+(?:\.\d+)?)\b", upcoming, re.M)
    ]

    assert versions
    assert all(version > current for version in versions)


def test_roadmap_validator_rejects_published_version_in_upcoming_section() -> None:
    module = _load_metadata_sync_module()
    roadmap = """# Roadmap

## Upcoming

### 3.18 (Target: July 2026)
- stale

### 4.0 (Target: TBD)
- future

## Ownership
"""

    errors = module._roadmap_version_errors(roadmap, "3.27.0")

    assert errors == [
        "ROADMAP.md upcoming section lists already-published version 3.18 "
        "while the current package version is 3.27.0"
    ]


def test_faq_support_block_is_rendered_from_compatibility_policy() -> None:
    module = _load_metadata_sync_module()
    matrix = {
        "kicad": {
            "primary": "10.0.x",
            "supported": [
                {"range": "10.0.x", "state": "primary"},
                {"range": "8.x", "state": "deprecated"},
            ],
            "dropped": [{"range": "9.x"}],
            "preview": [{"range": "11.x"}],
        }
    }

    rendered = module._render_faq_support_block(matrix)

    assert "KiCad 10.0.x is the primary supported target." in rendered
    assert "KiCad 8.x remains deprecated" in rendered
    assert "KiCad 9.x has been dropped and is not supported." in rendered
    assert "KiCad 11.x is preview-only." in rendered


def test_registry_prerequisite_excludes_dropped_kicad_lines() -> None:
    module = _load_metadata_sync_module()
    matrix = {
        "kicad": {
            "primary": "10.0.x",
            "supported": [
                {"range": "10.0.x", "state": "primary"},
                {"range": "8.x", "state": "deprecated"},
            ],
            "dropped": [{"range": "9.x"}],
        }
    }

    prerequisite = module._registry_prerequisite(matrix)

    assert "10.0.x" in prerequisite
    assert "8.x" in prerequisite
    assert "deprecated" in prerequisite
    assert "9.x" not in prerequisite


def test_registry_metadata_uses_compatibility_protocol_contract() -> None:
    module = _load_metadata_sync_module()
    metadata = module._project_metadata()
    matrix = module._compatibility_metadata()
    matrix["mcp"]["protocolVersion"] = "2099-01-01"

    registry = module._registry_metadata(metadata, matrix)
    registry_meta = registry["_meta"]["io.github.oaslananka/kicad-mcp-pro"]

    assert registry_meta["supportedMcpProtocolVersions"] == ["2099-01-01"]
    assert registry_meta["serverInfo"]["mcpProtocolVersion"] == "2099-01-01"


def test_release_validation_runs_public_metadata_gate() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert '      - "compatibility.yaml"' in workflow
    assert '      - "ROADMAP.md"' in workflow
    assert '      - "docs/faq.md"' in workflow
    assert '      - "scripts/sync_mcp_metadata.py"' in workflow
    assert "- run: corepack pnpm run metadata:check" in workflow


def test_current_policy_docs_do_not_advertise_dropped_kicad_lines() -> None:
    runtime_matrix = (ROOT / "docs" / "status" / "runtime-policy-matrix.md").read_text(
        encoding="utf-8"
    )
    capability_levels = (ROOT / "docs" / "status" / "capability-levels.md").read_text(
        encoding="utf-8"
    )
    high_speed = (ROOT / "docs" / "workflows" / "high-speed-review.md").read_text(encoding="utf-8")
    time_domain = (ROOT / "docs" / "kicad10" / "time-domain.md").read_text(encoding="utf-8")

    normalized_runtime_matrix = " ".join(runtime_matrix.split())
    assert "KiCad 9.x is dropped and excluded from runtime coverage." in normalized_runtime_matrix
    assert "| KiCad 9.x" not in runtime_matrix
    assert "On KiCad 9.x" not in runtime_matrix
    assert "Requires KiCad 9+" not in capability_levels
    assert "KiCad 9 keeps" not in high_speed
    assert "mixed KiCad 9/10" not in time_domain


def test_public_docs_distinguish_canonical_inputs_from_registry_payload() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    registry = (ROOT / "docs" / "registry.md").read_text(encoding="utf-8")
    submission = (ROOT / "docs" / "submission" / "openai-mcp-registry.md").read_text(
        encoding="utf-8"
    )

    assert "canonical metadata source of truth is `server.json`" not in readme
    assert "generated registry manifest" in readme
    assert "generated registry payload" in registry
    assert "generated registry payload" in submission
