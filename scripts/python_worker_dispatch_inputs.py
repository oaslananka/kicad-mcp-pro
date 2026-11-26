"""Encode and parse independent Python handoff selectors, never authorization."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scripts.check_signed_python_handoff import HandoffIdentity, _version
from scripts.runtime_path_safety import approved_runtime_path

_ID_FIELDS = (
    "release_id",
    "owner_run_id",
    "owner_attempt",
    "producer_run_id",
    "producer_attempt",
    "producer_artifact_id",
)
_FIELDS = {"tag", "source_commit", "manifest_sha256", *_ID_FIELDS}
_MAX_EVENT_BYTES = 1024 * 1024


def positive_id(value: str) -> int:
    """Accept only canonical positive ASCII decimal IDs (at most 15 digits)."""
    if re.fullmatch(r"[1-9]\d{0,14}", value, flags=re.ASCII) is None:
        raise ValueError("expected canonical positive decimal ID")
    return int(value)


def parse_inputs(inputs: object) -> tuple[HandoffIdentity, str]:
    """Require the exact string input schema; verify live identity separately."""
    if (
        not isinstance(inputs, dict)
        or set(inputs) != _FIELDS
        or any(not isinstance(value, str) for value in inputs.values())
    ):
        raise ValueError("invalid Python worker dispatch input schema")
    handoff = HandoffIdentity(
        inputs["tag"],
        inputs["source_commit"],
        *(positive_id(inputs[field]) for field in _ID_FIELDS),
    )
    _version(handoff)
    pin = inputs["manifest_sha256"]
    if (
        handoff.owner_run_id == handoff.producer_run_id
        or re.fullmatch(r"[0-9a-f]{64}", pin) is None
    ):
        raise ValueError("invalid Python worker dispatch selectors")
    return handoff, pin


def dispatch_payload(identity: HandoffIdentity, pin: str) -> dict[str, Any]:
    """Prepare an API body from independently verified owner inputs; do not dispatch."""
    _version(identity)
    inputs = {key: str(value) for key, value in asdict(identity).items()}
    inputs["manifest_sha256"] = pin
    parse_inputs(inputs)
    return {"ref": identity.tag, "inputs": inputs}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate dispatch event key")
        result[key] = value
    return result


def read_event_inputs(
    event: Path, *, runner_temp: Path | None = None
) -> tuple[HandoffIdentity, str]:
    """Read bounded event JSON from the runner, not from an artifact."""
    if event.is_symlink():
        raise ValueError("linked dispatch event file")
    roots = () if runner_temp is None else (runner_temp,)
    path = approved_runtime_path(event, extra_roots=roots)
    if not path.is_file():
        raise ValueError("missing dispatch event file")
    with path.open("rb") as stream:
        raw = stream.read(_MAX_EVENT_BYTES + 1)
    if len(raw) > _MAX_EVENT_BYTES:
        raise ValueError("dispatch event exceeds size limit")
    try:
        event_data = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as exc:
        raise ValueError("invalid dispatch event JSON") from exc
    if not isinstance(event_data, dict):
        raise ValueError("invalid dispatch event object")
    return parse_inputs(event_data.get("inputs"))
