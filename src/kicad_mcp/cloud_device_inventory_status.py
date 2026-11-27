"""Read-only, device-signed inventory diagnosis over the existing verified TLS path."""

from __future__ import annotations

import base64
import secrets
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kicad_mcp import cloud_pair

_STATES = frozenset(
    {
        "unverified",
        "active",
        "device_disabled",
        "device_revoked",
        "project_missing",
        "project_disabled",
    }
)


def inspect_inventory(
    origin: str,
    owner_sub: str,
    device_id: str,
    project_id: str | None,
    signing_key: Ed25519PrivateKey,
) -> str:
    """Distinguish authorized inventory states; never infer deletion from network failure."""
    if (
        not isinstance(owner_sub, str)
        or not 1 <= len(owner_sub) <= 256
        or any(ord(char) < 32 or ord(char) == 127 for char in owner_sub)
        or not isinstance(device_id, str)
        or not cloud_pair._UUID.fullmatch(device_id)
        or (
            project_id is not None
            and (not isinstance(project_id, str) or not cloud_pair._UUID.fullmatch(project_id))
        )
    ):
        return "unavailable"
    nonce = secrets.token_urlsafe(32)
    issued = time.time_ns() // 1_000_000
    proof = "\0".join(
        (
            "kicad-cloud-device-inventory-v1",
            device_id,
            owner_sub,
            project_id or "",
            nonce,
            str(issued),
        )
    ).encode()
    signature = base64.urlsafe_b64encode(signing_key.sign(proof)).decode("ascii").rstrip("=")
    try:
        response = cloud_pair._post(
            cloud_pair._origin(origin),
            "/api/v1/pairing/device/inventory",
            {
                "deviceId": device_id,
                "ownerSub": owner_sub,
                "projectId": project_id,
                "nonce": nonce,
                "issuedAtMs": issued,
                "signature": signature,
            },
            200,
        )
    except cloud_pair.CloudPairingError:
        return "unavailable"
    state = response.get("state")
    if set(response) != {"nonce", "state"} or response["nonce"] != nonce:
        return "unavailable"
    return state if isinstance(state, str) and state in _STATES else "unavailable"
