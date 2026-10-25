"""Python wheel/sdist need both signed SLSA and signed CycloneDX predicates (#1179)."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/publish-python.yml"
PIN = "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6"


def _job() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data[True]["workflow_dispatch"] is None
    assert data[True]["push"]["tags"] == ["mcp-server-v*"]
    return data["jobs"]["build"]


def test_slsa_and_cyclonedx_are_independent_signed_steps_before_upload() -> None:
    job = _job()
    steps = job["steps"]
    provenance = next(
        i
        for i, item in enumerate(steps)
        if item.get("name") == "Attest Python SLSA build provenance"
    )
    sbom = next(
        i for i, item in enumerate(steps) if item.get("name") == "Attest Python distributions"
    )
    uploader = [
        i
        for i, item in enumerate(steps)
        if item.get("uses", "").startswith("actions/upload-artifact@")
    ]
    assert len(uploader) == 2
    assert provenance < sbom < min(uploader)
    assert steps[provenance]["uses"] == PIN
    assert steps[sbom]["uses"] == PIN
    assert steps[provenance]["with"] == {"subject-checksums": "release-evidence/SHA256SUMS.txt"}
    assert steps[sbom]["with"] == {
        "subject-checksums": "release-evidence/SHA256SUMS.txt",
        "sbom-path": "release-evidence/sbom.cdx.json",
    }
    assert job["permissions"]["attestations"] == "write"
    assert job["permissions"]["id-token"] == "write"
    assert job["permissions"]["artifact-metadata"] == "write"


def test_existing_publishing_and_backfill_paths_unchanged() -> None:
    job = _job()
    steps = job["steps"]
    names = [s.get("name") for s in steps]
    assert names.index("Generate Python release evidence") < names.index(
        "Attest Python SLSA build provenance"
    )
    assert any(
        s.get("name") == "Attach Python evidence to GitHub Release"
        and s["if"] == "inputs.source_commit == '' && github.event_name == 'push'"
        for s in steps
    )
    assert any(s.get("name") == "Attest Python distributions" for s in steps)
    assert set(job.keys()) >= {"if", "runs-on", "permissions", "steps"}
