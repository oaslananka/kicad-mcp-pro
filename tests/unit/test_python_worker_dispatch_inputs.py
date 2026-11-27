"""Independent dispatch selectors must never become publication authority."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from tests.unit.test_signed_python_dispatch_binding import DISPATCH

FIELDS = {
    "tag": DISPATCH.handoff.tag,
    "source_commit": DISPATCH.handoff.source_commit,
    "release_id": str(DISPATCH.handoff.release_id),
    "owner_run_id": str(DISPATCH.handoff.owner_run_id),
    "owner_attempt": str(DISPATCH.handoff.owner_attempt),
    "producer_run_id": str(DISPATCH.handoff.producer_run_id),
    "producer_attempt": str(DISPATCH.handoff.producer_attempt),
    "producer_artifact_id": str(DISPATCH.handoff.producer_artifact_id),
    "manifest_sha256": DISPATCH.manifest_sha256,
}


def test_owner_payload_exact_contract() -> None:
    from scripts import python_worker_dispatch_inputs as contract

    payload = contract.dispatch_payload(DISPATCH.handoff, DISPATCH.manifest_sha256)
    assert payload == {"ref": DISPATCH.handoff.tag, "inputs": FIELDS}
    assert contract.parse_inputs(payload["inputs"]) == (DISPATCH.handoff, DISPATCH.manifest_sha256)


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "missing",
        "int",
        "bool",
        "unicode",
        "zero",
        "leading",
        "plus",
        "large",
        "pin",
        "tag",
        "source",
        "same-run",
    ],
)
def test_reject_invalid_selectors(change) -> None:
    from scripts import python_worker_dispatch_inputs as contract

    inputs = FIELDS.copy()
    if change == "extra":
        inputs["worker_run_id"] = "901"
    elif change == "missing":
        del inputs["manifest_sha256"]
    elif change == "same-run":
        inputs["producer_run_id"] = inputs["owner_run_id"]
    else:
        key, value = {
            "int": ("release_id", 42),
            "bool": ("release_id", True),
            "unicode": ("release_id", "1９"),
            "zero": ("release_id", "0"),
            "leading": ("release_id", "01"),
            "plus": ("release_id", "+1"),
            "large": ("release_id", "1" * 16),
            "pin": ("manifest_sha256", "A" * 64),
            "tag": ("tag", "main"),
            "source": ("source_commit", "bad"),
        }[change]
        inputs[key] = value
    with pytest.raises(ValueError):
        contract.parse_inputs(inputs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_run_id", True),
        ("producer_artifact_id", -1),
        ("release_id", 10**15),
        ("producer_run_id", DISPATCH.handoff.owner_run_id),
    ],
)
def test_owner_encoder_rejects_invalid_identity(field, value) -> None:
    from scripts import python_worker_dispatch_inputs as contract

    identity = replace(DISPATCH.handoff, **{field: value})
    with pytest.raises(ValueError):
        contract.dispatch_payload(identity, DISPATCH.manifest_sha256)


@pytest.mark.parametrize(
    "change", ["duplicate", "oversize", "bad-json", "link", "missing", "wrong-type"]
)
def test_event_file_rejects_unsafe_inputs(tmp_path, change) -> None:
    from scripts import python_worker_dispatch_inputs as contract

    path = tmp_path / "event.json"
    raw = json.dumps({"inputs": FIELDS}).encode()
    if change == "duplicate":
        raw = raw.replace(b'"release_id":', b'"release_id":"42","release_id":')
    elif change == "oversize":
        raw += b" " * (1024 * 1024)
    elif change == "bad-json":
        raw = b"{"
    elif change == "wrong-type":
        raw = b'{"inputs":[]}'
    if change != "missing":
        path.write_bytes(raw)
    if change == "link":
        link = tmp_path / "link.json"
        link.symlink_to(path)
        path = link
    with pytest.raises((ValueError, OSError)):
        contract.read_event_inputs(path)
