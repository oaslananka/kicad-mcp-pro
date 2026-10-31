"""Manual, one-shot Cloud project-presence connector; never auto-started.

The owner must explicitly choose a project and an already enrolled device key.
No pairing, OAuth authorization, device registration, filesystem discovery,
KiCad execution or background service is created by this command. The Cloud
server independently verifies its live OAuth client/project grant.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import secrets
import sys
import time
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

from kicad_mcp.cloud_outbound_handshake import (
    HandshakeReceipt,
    execute_single_approved_read,
)
from kicad_mcp.cloud_pair_keys import (
    LocalApprovalDeniedError,
    _load_owner_key,
    _read_owner_binding,
)
from kicad_mcp.cloud_pair_keys import (
    _open_owner_private_dir as _open_owner_private_dir,
)
from kicad_mcp.cloud_pair_keys import (
    _save_owner_binding as _save_owner_binding,
)
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch
from kicad_mcp.cloud_readonly_boundary import (
    OperatorProject,
    VerifiedLocalBinding,
)

_LOCAL_APPROVAL_DENIED = "local approval denied"


def _load_bound_owner_key(filename: Path, origin: str, device_id: str) -> Ed25519PrivateKey:
    """Reject a different Cloud or device before using an enrolled owner key."""
    record = _read_owner_binding(filename)
    if record["origin"] != origin or record["deviceId"] != device_id:
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    key = _load_owner_key(filename)
    der = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    if hashlib.sha256(der).hexdigest() != record["fingerprint"]:
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    return key


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="One approved KiCad Cloud metadata read")
    parser.add_argument("--cloud-origin", required=True, help="Trusted HTTPS origin chosen locally")
    parser.add_argument("--owner-sub", required=True, help="Enrolled account subject")
    parser.add_argument("--device-id", required=True, help="Already enrolled device UUID")
    parser.add_argument("--project-id", required=True, help="Explicitly allowed project UUID")
    # No LLM/CLI-supplied filesystem paths. The already-registered device
    # and project UUIDs select fixed local owner-private records instead.
    parser.add_argument(
        "--allow-once",
        action="store_true",
        required=True,
        help="Explicit local consent; one presence-only read, no native operation",
    )
    return parser


def _confirm_local_read(options: argparse.Namespace) -> tuple[int, int]:
    """Require a deliberate foreground terminal acknowledgement before key use.

    This blocks unattended shell redirection, not a malicious process with its
    own PTY or the same OS account. Real user identity still needs trusted UI.
    """
    if (
        not sys.stdin.isatty()
        or not sys.stdout.isatty()
        or not isinstance(options.project_directory, Path)
        or not options.project_directory.is_absolute()
    ):
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    challenge = secrets.token_hex(4).upper()
    print("One-time metadata-only KiCad Cloud read (no project contents).")
    print(f"Cloud origin: {options.cloud_origin!r}")
    print(f"Owner account: {options.owner_sub!r}")
    print(f"Device UUID: {options.device_id!r}")
    print(f"Project UUID: {options.project_id!r}")
    print(f"Local directory: {str(options.project_directory)!r}")
    print(f"Local project stem: {options.filename_stem!r}")
    print(f"Owner key file: {str(options.private_key_file)!r}")
    answer = input(f"Type APPROVE {challenge} to authorize exactly one read: ")
    if answer != f"APPROVE {challenge}":
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    # Start both deadlines at the actual foreground approval, never after
    # a potentially slow remote device/session handshake.
    return time.time_ns() // 1_000_000 + 30_000, time.monotonic_ns() + 30_000_000_000


async def _connect(
    options: argparse.Namespace, authorization_window: tuple[int, int]
) -> HandshakeReceipt:
    wall_cutoff_ms, monotonic_cutoff_ns = authorization_window
    if (
        not options.allow_once
        or not options.project_directory.is_absolute()
        or time.monotonic_ns() >= monotonic_cutoff_ns
    ):
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
    signing_key = _load_bound_owner_key(
        options.private_key_file, options.cloud_origin, options.device_id
    )

    def approved_local_project(receipt: HandshakeReceipt) -> LocalReadDispatch:
        # This is an independent, local, time-limited operator grant, never a
        # Cloud-supplied authorization flag or a synthetic always-true grant.
        # Even a valid device handshake must not renew expired local consent.
        if time.monotonic_ns() >= monotonic_cutoff_ns:
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        return LocalReadDispatch(
            verified=VerifiedLocalBinding(
                device_id=receipt.device_id,
                project_id=options.project_id,
                operations=frozenset({"project_summary"}),
                session_id=receipt.session_id,
                session_expires_unix_ms=wall_cutoff_ms,
            ),
            operator_project=OperatorProject(
                device_id=options.device_id,
                project_id=options.project_id,
                directory=options.project_directory,
                filename_stem=options.filename_stem,
            ),
            current_authorization=lambda: time.monotonic_ns() < monotonic_cutoff_ns,
            max_reads=1,
        )

    return await execute_single_approved_read(
        origin=options.cloud_origin,
        trusted_origin=options.cloud_origin,
        owner_sub=options.owner_sub,
        device_id=options.device_id,
        signing_key=signing_key,
        dispatcher_factory=approved_local_project,
    )


def main(argv: list[str] | None = None) -> int:
    options = _parser().parse_args(argv)
    try:
        from kicad_mcp.cloud_local_registry import resolve_registered_read

        selected = resolve_registered_read(
            owner_sub=options.owner_sub,
            origin=options.cloud_origin,
            device_id=options.device_id,
            project_id=options.project_id,
        )
        options.project_directory = selected.project_directory
        options.filename_stem = selected.filename_stem
        options.private_key_file = selected.key_file
        approval_window = _confirm_local_read(options)
        asyncio.run(_connect(options, approval_window))
    except (ValueError, OSError, EOFError, KeyboardInterrupt):
        print("Local Cloud connection denied", file=sys.stderr)
        return 1
    print("One authorized project-presence request completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
