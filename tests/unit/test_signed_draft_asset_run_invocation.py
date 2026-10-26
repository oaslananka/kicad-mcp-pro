"""Cryptographically verified SLSA statement and certificate bind the package to the exact run."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_signed_draft_asset import verify_signed_asset
from tests.unit.test_signed_draft_asset import SHA, TAG, StubVerifier

RUN_ID = 40050705072
ATTEMPT = 1
URI = f"https://github.com/oaslananka/kicad-mcp-pro/actions/runs/{RUN_ID}/attempts/{ATTEMPT}"


def _fixture(tmp_path: Path) -> tuple[Path, StubVerifier]:
    package = tmp_path / "kicad-mcp-pro-4.5.0.mcpb"
    package.write_bytes(b"exact run bound signed artifact")
    verifier = StubVerifier(package)
    proof = verifier.output[0]["verificationResult"]
    proof["statement"]["predicate"] = {
        "runDetails": {"metadata": {"invocationId": URI}},
    }
    proof["signature"] = {"certificate": {"runInvocationURI": URI}}
    return package, verifier


def _verify(package: Path, verifier: StubVerifier, **overrides: object) -> dict[str, object]:
    params = {
        "package": package,
        "tag": TAG,
        "source_commit": SHA,
        "kind": "mcpb",
        "producer_run_id": RUN_ID,
        "producer_run_attempt": ATTEMPT,
    }
    params.update(overrides)
    return verify_signed_asset(verifier, **params)


def test_exact_run_attempt_bound_in_both_signed_provenance_and_certificate(tmp_path: Path) -> None:
    package, verifier = _fixture(tmp_path)
    result = _verify(package, verifier)
    assert result["signedAttestationVerified"] is True
    assert result["producerRunInvocationVerified"] is True
    assert result["producerRunId"] == RUN_ID
    assert result["producerRunAttempt"] == ATTEMPT
    assert result["producerJobBindingVerified"] is False
    assert result["registryReceiptVerified"] is False
    assert result["publicationAuthorized"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("statement", "https://github.com/foreign/repo/actions/runs/40050705072/attempts/1"),
        ("certificate", "https://github.com/foreign/repo/actions/runs/40050705072/attempts/1"),
        ("statement", "https://github.com/oaslananka/kicad-mcp-pro/actions/runs/11/attempts/1"),
        ("certificate", "https://github.com/oaslananka/kicad-mcp-pro/actions/runs/11/attempts/1"),
        ("statement", None),
        ("certificate", None),
    ],
)
def test_signed_run_or_attempt_substitution_rejected(
    tmp_path: Path,
    field: str,
    value: str | None,
) -> None:
    package, verifier = _fixture(tmp_path)
    result = verifier.output[0]["verificationResult"]
    if field == "statement":
        result["statement"]["predicate"]["runDetails"]["metadata"]["invocationId"] = value
    else:
        result["signature"]["certificate"]["runInvocationURI"] = value
    with pytest.raises(ValueError, match="signed SLSA invocation"):
        _verify(package, verifier)


@pytest.mark.parametrize(
    ("run_id", "attempt"),
    [
        (RUN_ID + 1, ATTEMPT),
        (RUN_ID, ATTEMPT + 1),
    ],
)
def test_other_approved_run_or_attempt_cannot_reuse_existing_signature(
    tmp_path: Path, run_id: int, attempt: int
) -> None:
    package, verifier = _fixture(tmp_path)
    with pytest.raises(ValueError, match="signed SLSA invocation"):
        _verify(
            package,
            verifier,
            producer_run_id=run_id,
            producer_run_attempt=attempt,
        )


@pytest.mark.parametrize(
    ("run_id", "attempt"),
    [
        (0, 1),
        (-1, 1),
        (True, 1),
        (RUN_ID, 0),
        (RUN_ID, None),
        (None, 1),
    ],
)
def test_invalid_or_incomplete_run_parameters_rejected_before_crypto(
    tmp_path: Path,
    run_id: int | bool | None,
    attempt: int | None,
) -> None:
    package, verifier = _fixture(tmp_path)
    with pytest.raises(ValueError, match="run ID|run ID and attempt"):
        _verify(
            package,
            verifier,
            producer_run_id=run_id,
            producer_run_attempt=attempt,
        )
    assert verifier.calls == []


def test_absent_run_binding_never_claims_run_identity(tmp_path: Path) -> None:
    package, verifier = _fixture(tmp_path)
    result = verify_signed_asset(verifier, package=package, tag=TAG, source_commit=SHA, kind="mcpb")
    assert result["signedAttestationVerified"] is True
    assert result["producerRunInvocationVerified"] is False
    assert result["producerRunId"] is None


def test_matching_second_signature_is_accepted_even_if_first_invocation_differs(
    tmp_path: Path,
) -> None:
    package, verifier = _fixture(tmp_path)
    import copy

    other = copy.deepcopy(verifier.output[0])
    other["verificationResult"]["signature"]["certificate"]["runInvocationURI"] = "different"
    verifier.output.insert(0, other)
    result = _verify(package, verifier)
    assert result["verifiedMatchingAttestationCount"] == 2
    assert result["producerRunInvocationVerified"] is True
