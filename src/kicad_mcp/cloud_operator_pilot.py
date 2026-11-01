"""Explicit owner-operated presence or bounded native DRC count pilot.

This lower-assurance, manual foreground path is separate from the independent
owner WebAuthn release gate in cloud_once. A same-UID process can spoof a
terminal prompt, so this cannot authorize unattended/public native execution.
No file contents, arbitrary commands or writes are sent to Cloud.
"""

from __future__ import annotations

import asyncio
import sys
import time
from argparse import Namespace

from kicad_mcp import cloud_once
from kicad_mcp.cloud_local_registry import resolve_registered_read
from kicad_mcp.cloud_outbound_handshake import (
    HandshakeReceipt,
    execute_operator_native_drc_once,
    execute_operator_presence_once,
)
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding

_LOCAL_APPROVAL_DENIED = "local approval denied"


async def _single_presence(options: Namespace, lease: tuple[int, int]) -> HandshakeReceipt:
    wall_cutoff_ms, monotonic_cutoff_ns = lease
    if (
        not options.allow_once
        or not options.project_directory.is_absolute()
        or time.monotonic_ns() >= monotonic_cutoff_ns
    ):
        raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)

    native_drc = bool(getattr(options, "native_drc_once", False))
    key = cloud_once._load_bound_owner_key(
        options.private_key_file, options.cloud_origin, options.device_id
    )

    def dispatch(receipt: HandshakeReceipt) -> LocalReadDispatch:
        if time.monotonic_ns() >= monotonic_cutoff_ns:
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        return LocalReadDispatch(
            verified=VerifiedLocalBinding(
                device_id=receipt.device_id,
                project_id=options.project_id,
                operations=frozenset({"run_drc" if native_drc else "project_summary"}),
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
            native_drc=native_drc,
        )

    transport = execute_operator_native_drc_once if native_drc else execute_operator_presence_once
    return await transport(
        origin=options.cloud_origin,
        trusted_origin=options.cloud_origin,
        owner_sub=options.owner_sub,
        device_id=options.device_id,
        signing_key=key,
        dispatcher_factory=dispatch,
    )


def main(argv: list[str] | None = None) -> int:
    parser = cloud_once._parser()
    parser.add_argument(
        "--native-drc-once",
        action="store_true",
        help="Explicit foreground one-shot DRC counts, requires separate Cloud opt-in",
    )
    options = parser.parse_args(argv)
    try:
        # Headless callers are denied before owner registry/key access.
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise LocalApprovalDeniedError(_LOCAL_APPROVAL_DENIED)
        selected = resolve_registered_read(
            owner_sub=options.owner_sub,
            origin=options.cloud_origin,
            device_id=options.device_id,
            project_id=options.project_id,
        )
        options.project_directory = selected.project_directory
        options.filename_stem = selected.filename_stem
        options.private_key_file = selected.key_file
        lease = cloud_once._confirm_local_read(options)
        asyncio.run(_single_presence(options, lease))
    except (ValueError, OSError, EOFError, KeyboardInterrupt):
        print("Local Cloud pilot denied", file=sys.stderr)
        return 1
    if options.native_drc_once:
        print("One owner-operated native DRC count completed")
    else:
        print("One owner-operated project-presence read completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
