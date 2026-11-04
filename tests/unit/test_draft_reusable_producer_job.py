"""Offline, read-only reusable producer job metadata gate (#1179)."""

from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.check_draft_producer_job import (
    _REUSABLE_JOB_NAMES,
    verify_producer_job,
)
from tests.unit.test_draft_producer_job import Fake, _params


def _fixture(role: str) -> tuple[Fake, dict]:
    base_role = (
        role
        if role
        in {
            "python-dist",
            "python-release-evidence",
            "mcpb-release-evidence",
            "kicad-pcm-release-evidence",
        }
        else "mcpb-release-evidence"
    )
    fake = Fake(base_role)
    names = _REUSABLE_JOB_NAMES[role]
    fake.run["path"] = ".github/workflows/draft-producer-preflight.yml"
    fake.jobs["jobs"][0]["workflow_name"] = names[0]
    fake.jobs["jobs"][0]["name"] = names[1]
    steps = [
        {"name": names[2], "status": "completed", "conclusion": "success", "number": 7},
        {"name": names[3], "status": "completed", "conclusion": "success", "number": 8},
    ]
    if role.startswith("python-"):
        steps.insert(
            0,
            {
                "name": "Attest Python SLSA build provenance",
                "status": "completed",
                "conclusion": "success",
                "number": 6,
            },
        )
        steps.append(
            {
                "name": names[3] + "another",
                "status": "completed",
                "conclusion": "success",
                "number": 9,
            },
        )
    if role == "protocol-schemas-release-evidence":
        steps.insert(
            0,
            {
                "name": "Attest Protocol Schemas SLSA build provenance",
                "status": "completed",
                "conclusion": "success",
                "number": 6,
            },
        )
    if role == "npm-draft-release-evidence":
        steps.insert(
            0,
            {
                "name": "Attest npm SLSA build provenance",
                "status": "completed",
                "conclusion": "success",
                "number": 6,
            },
        )
    if role in ("gui-draft-installers", "gui-draft-evidence"):
        steps.insert(
            0,
            {
                "name": "Attest GUI SLSA build provenance",
                "status": "completed",
                "conclusion": "success",
                "number": 6,
            },
        )
        companion = (
            "Store GUI draft checksums and attestable evidence"
            if role == "gui-draft-installers"
            else "Store GUI draft installers"
        )
        steps.append(
            {"name": companion, "status": "completed", "conclusion": "success", "number": 9}
        )
    fake.jobs["jobs"][0]["steps"] = steps
    args = {**_params(base_role), "role": role, "producer_profile": "reusable"}
    return fake, args


@pytest.mark.parametrize("role", list(_REUSABLE_JOB_NAMES))
def test_strict_reusable_job_and_required_steps_offline(role: str) -> None:
    fake, args = _fixture(role)
    result = verify_producer_job(fake, **args)
    assert result["producerProfile"] == "reusable"
    assert result["approvedJobCompleted"] is True
    assert result["requiredAttestationStepCompleted"] is True
    assert result["requiredUploadStepCompleted"] is True
    assert result["artifactProducedByThisJobVerified"] is False
    assert result["signedAttestationVerified"] is False
    assert result["publicationAuthorized"] is False
    assert fake.calls == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "mcpb / attacker"),
        ("name", "prepare"),
        ("workflow_name", "Prepare MCPB (non-publishing)"),
        ("run_id", 999),
        ("run_attempt", 0),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("check_run_url", "https://hostile.invalid/job"),
    ],
)
def test_wrong_reusable_job_is_rejected(field: str, value: object) -> None:
    fake, args = _fixture("mcpb-release-evidence")
    fake.jobs["jobs"][0][field] = value
    with pytest.raises(ValueError, match="producer job ID"):
        verify_producer_job(fake, **args)


@pytest.mark.parametrize("profile", ["all", "", "legacy,reusable", False, None])
def test_unknown_profile_rejected_before_api(profile: object) -> None:
    fake, args = _fixture("mcpb-release-evidence")
    args["producer_profile"] = profile
    with pytest.raises(ValueError, match="unapproved producer profile"):
        verify_producer_job(fake, **args)
    assert fake.calls == 0


@pytest.mark.parametrize("role", list(_REUSABLE_JOB_NAMES))
def test_legacy_workflow_can_never_impersonate_reusable_job(role: str) -> None:
    fake, args = _fixture(role)
    fake.run["path"] = ".github/workflows/publish-mcpb.yml"
    with pytest.raises(ValueError, match="approved completed main producer"):
        verify_producer_job(fake, **args)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda steps: steps.pop(0),
        lambda steps: steps[0].update(conclusion="skipped"),
        lambda steps: steps[0].update(number=9),
    ],
)
def test_schema_slsa_provenance_is_required_before_sbom(mutator) -> None:
    fake, args = _fixture("protocol-schemas-release-evidence")
    mutator(fake.jobs["jobs"][0]["steps"])
    with pytest.raises(ValueError, match="schema SLSA|required producer step"):
        verify_producer_job(fake, **args)


def test_reusable_run_must_not_pass_legacy_default() -> None:
    fake, args = _fixture("mcpb-release-evidence")
    args.pop("producer_profile")
    with pytest.raises(ValueError, match="approved completed main producer"):
        verify_producer_job(fake, **args)


def test_incomplete_or_duplicated_job_listing_fails_closed() -> None:
    fake, args = _fixture("mcpb-release-evidence")
    fake.jobs["total_count"] = 101
    with pytest.raises(ValueError, match="incomplete"):
        verify_producer_job(fake, **args)
    fake.jobs["total_count"] = 2
    fake.jobs["jobs"].append(deepcopy(fake.jobs["jobs"][0]))
    with pytest.raises(ValueError, match="not found uniquely"):
        verify_producer_job(fake, **args)


_NEW_ROLES = (
    "npm-draft-release-evidence",
    "gui-draft-installers",
    "gui-draft-evidence",
    "container-build-source-evidence",
    "mcp-registry-draft-evidence",
)


@pytest.mark.parametrize("role", _NEW_ROLES)
def test_new_reusable_job_does_not_infer_signed_or_release_authority(role: str) -> None:
    fake, args = _fixture(role)
    result = verify_producer_job(fake, **args)
    assert result["producerProfile"] == "reusable"
    assert result["approvedJobCompleted"] is True
    assert result["requiredAttestationStepCompleted"] is True
    assert result["requiredUploadStepCompleted"] is True
    assert result["artifactProducedByThisJobVerified"] is False
    assert result["signedAttestationVerified"] is False
    assert result["publicationAuthorized"] is False


@pytest.mark.parametrize("role", _NEW_ROLES)
@pytest.mark.parametrize("mutation", ["missing", "skipped", "duplicated", "too-early"])
def test_new_reusable_role_requires_exact_completed_attest_and_upload(
    role: str, mutation: str
) -> None:
    fake, args = _fixture(role)
    steps = fake.jobs["jobs"][0]["steps"]
    _, _, attest, upload = _REUSABLE_JOB_NAMES[role]
    chosen = next(step for step in steps if step["name"] == upload)
    if mutation == "missing":
        steps.remove(chosen)
    elif mutation == "skipped":
        chosen["conclusion"] = "skipped"
    elif mutation == "duplicated":
        steps.append({**chosen, "number": 15})
    else:
        chosen["number"] = 1
    with pytest.raises(ValueError):
        verify_producer_job(fake, **args)


@pytest.mark.parametrize(
    "role",
    (
        "npm-draft-release-evidence",
        "gui-draft-installers",
        "gui-draft-evidence",
    ),
)
@pytest.mark.parametrize("mutation", ["missing", "skipped", "out-of-order", "duplicated"])
def test_new_signed_package_provenance_step_precedes_attestation(role: str, mutation: str) -> None:
    fake, args = _fixture(role)
    steps = fake.jobs["jobs"][0]["steps"]
    provenance = next(s for s in steps if "SLSA build provenance" in s["name"])
    if mutation == "missing":
        steps.remove(provenance)
    elif mutation == "skipped":
        provenance["conclusion"] = "skipped"
    elif mutation == "out-of-order":
        provenance["number"] = 9
    else:
        steps.append({**provenance, "number": 10})
    with pytest.raises(ValueError, match="SLSA provenance|required producer step"):
        verify_producer_job(fake, **args)


@pytest.mark.parametrize("role", ("gui-draft-installers", "gui-draft-evidence"))
@pytest.mark.parametrize("mutation", ["missing", "skipped", "out-of-order", "duplicated"])
def test_gui_reusable_job_requires_both_final_artifact_uploads(role: str, mutation: str) -> None:
    fake, args = _fixture(role)
    steps = fake.jobs["jobs"][0]["steps"]
    primary = _REUSABLE_JOB_NAMES[role][3]
    companion = next(s for s in steps if s["name"].startswith("Store GUI") and s["name"] != primary)
    if mutation == "missing":
        steps.remove(companion)
    elif mutation == "skipped":
        companion["conclusion"] = "skipped"
    elif mutation == "out-of-order":
        companion["number"] = 1
    else:
        steps.append({**companion, "number": 12})
    with pytest.raises(ValueError, match="companion artifact|required producer step"):
        verify_producer_job(fake, **args)


def test_readonly_job_profile_matches_reviewed_workflow_step_names() -> None:
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[2]
    expected = {
        "npm-draft-release-evidence": ("prepare-npm.yml", "prepare", "npm / prepare"),
        "gui-draft-installers": (
            "prepare-gui.yml",
            "attest-and-store",
            "gui / attest-and-store",
        ),
        "gui-draft-evidence": ("prepare-gui.yml", "attest-and-store", "gui / attest-and-store"),
        "container-build-source-evidence": (
            "prepare-mcp-container.yml",
            "prepare",
            "container / prepare",
        ),
        "mcp-registry-draft-evidence": (
            "prepare-mcp-registry.yml",
            "prepare",
            "registry / prepare",
        ),
    }
    for role, (workflow, job, expected_job_name) in expected.items():
        cfg = yaml.safe_load((root / ".github/workflows" / workflow).read_text())
        steps = cfg["jobs"][job]["steps"]
        names = [step.get("name") for step in steps]
        mapping = _REUSABLE_JOB_NAMES[role]
        assert mapping[1] == expected_job_name
        assert names.count(mapping[2]) == 1
        assert names.count(mapping[3]) == 1
        assert names.index(mapping[2]) < names.index(mapping[3])
        assert cfg["permissions"] == {"contents": "read"}
