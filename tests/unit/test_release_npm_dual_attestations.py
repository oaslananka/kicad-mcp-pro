"""Registry tarballs need independent SLSA and SBOM attestations (#1179)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTION_PIN = "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6"

WORKFLOWS = [
    (
        "publish-npm.yml",
        "Attest npm SLSA build provenance",
        "Attest npm launcher tarball",
        "Pack npm launcher and generate evidence",
        "Store npm release evidence",
        "release-assets/mcp-npm",
        "mcp-npm-v",
    ),
    (
        "publish-protocol-schemas.yml",
        "Attest Protocol Schemas SLSA build provenance",
        "Attest tarball",
        "Pack and generate evidence",
        "Store release evidence",
        "release-assets/protocol-schemas",
        "protocol-schemas-v",
    ),
]


@pytest.mark.parametrize(
    ("filename", "provenance_name", "sbom_name", "pack_name", "upload_name", "directory", "prefix"),
    WORKFLOWS,
)
def test_independent_signed_provenance_precedes_sbom_and_artifact_upload(
    filename: str,
    provenance_name: str,
    sbom_name: str,
    pack_name: str,
    upload_name: str,
    directory: str,
    prefix: str,
) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text(encoding="utf-8"))
    job = workflow["jobs"]["publish"]
    steps = job["steps"]
    labels = [item.get("name") for item in steps]
    assert labels.count(provenance_name) == 1
    assert labels.count(sbom_name) == 1
    assert labels.count(pack_name) == 1
    assert labels.count(upload_name) == 1
    assert labels.index(pack_name) < labels.index(provenance_name)
    assert labels.index(provenance_name) < labels.index(sbom_name)
    assert labels.index(sbom_name) < labels.index(upload_name)

    provenance = steps[labels.index(provenance_name)]
    sbom = steps[labels.index(sbom_name)]
    assert provenance["uses"] == sbom["uses"] == ACTION_PIN
    assert provenance["with"] == {"subject-checksums": f"{directory}/SHA256SUMS.txt"}
    assert sbom["with"] == {
        "subject-checksums": f"{directory}/SHA256SUMS.txt",
        "sbom-path": f"{directory}/sbom.cdx.json",
    }
    assert job["permissions"]["attestations"] == "write"
    assert job["permissions"]["id-token"] == "write"
    assert job["permissions"]["artifact-metadata"] == "write"
    assert workflow[True]["release"]["types"] == ["published"]
    assert workflow[True]["workflow_dispatch"]["inputs"]["release_tag"]["required"] is True
    assert f"startsWith(inputs.release_tag, '{prefix}')" in job["if"]
    assert f"startsWith(github.event.release.tag_name, '{prefix}')" in job["if"]


@pytest.mark.parametrize("case", WORKFLOWS)
def test_existing_legacy_publisher_and_registry_writes_remain_unchanged(
    case: tuple[str, ...],
) -> None:
    filename = case[0]
    data = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text(encoding="utf-8"))
    steps = data["jobs"]["publish"]["steps"]
    assert any("npm publish" in str(item.get("run", "")) for item in steps)
    assert any("gh release upload" in str(item.get("run", "")) for item in steps)
    assert sum(1 for item in steps if item.get("uses", "").startswith("actions/attest@")) == 2
