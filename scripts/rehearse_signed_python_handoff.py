"""Exercise real attestation verification with a distinct non-production trust root."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.assemble_mcp_server_draft_assets import _expected
from scripts.check_signed_draft_asset import AttestationVerifier, GitHubAttestationCLI
from scripts.check_signed_python_handoff import (
    HandoffIdentity,
    _read_manifest,
    _verify_signature,
    _version,
    manifest_bytes,
)
from scripts.runtime_path_safety import approved_runtime_path

_NAME = "python-worker-rehearsal.json"
_SIGNER = ".github/workflows/signed-python-handoff-rehearsal.yml"


def _identity(source: str, run_id: int, attempt: int) -> HandoffIdentity:
    # The nested production-shaped request uses deliberately synthetic IDs.
    # No tag, draft, producer artifact or registry operation is performed.
    return HandoffIdentity("mcp-server-v0.0.0", source, 1, run_id, attempt, run_id, attempt, 1)


def _envelope(bundle: Path, identity: HandoffIdentity) -> bytes:
    request = json.loads(manifest_bytes(identity, bundle / "dist"))
    return (
        json.dumps(
            {
                "schemaVersion": 1,
                "rehearsal": True,
                "syntheticPackages": True,
                "syntheticReleaseAndProducerIdentity": True,
                "request": request,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def generate(bundle: Path, source: str, run_id: int, attempt: int) -> str:
    """Create a fresh synthetic bundle and return its independent manifest pin."""
    if bundle.is_symlink():
        raise ValueError("linked rehearsal bundle")
    bundle = approved_runtime_path(bundle)
    identity = _identity(source, run_id, attempt)
    _version(identity)
    bundle.mkdir()
    dist = bundle / "dist"
    dist.mkdir()
    for name in sorted(_expected("0.0.0")["python_dist"]):
        (dist / name).write_text(
            f"NON-PUBLISHABLE REHEARSAL FIXTURE\n{source}\n{run_id}/{attempt}\n{name}\n",
            encoding="utf-8",
        )
    payload = _envelope(bundle, identity)
    (bundle / _NAME).write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def verify(
    verifier: AttestationVerifier,
    bundle: Path,
    source: str,
    run_id: int,
    attempt: int,
    pin: str,
) -> dict[str, object]:
    """Verify the synthetic manifest with only the rehearsal workflow signer."""
    if bundle.is_symlink():
        raise ValueError("linked rehearsal bundle")
    bundle = approved_runtime_path(bundle)
    manifest = bundle / _NAME
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("missing or linked rehearsal manifest")
    if {path.name for path in bundle.iterdir()} != {_NAME, "dist"}:
        raise ValueError("unexpected rehearsal bundle inventory")
    identity = _identity(source, run_id, attempt)
    expected = _envelope(bundle, identity)
    if hashlib.sha256(expected).hexdigest() != pin or _read_manifest(manifest) != expected:
        raise ValueError("rehearsal manifest or independent digest pin mismatch")
    _verify_signature(verifier, manifest, identity, pin, signer=_SIGNER)
    if _read_manifest(manifest) != expected or _envelope(bundle, identity) != expected:
        raise ValueError("rehearsal bytes changed during verification")
    return {
        "rehearsal": True,
        "syntheticPackages": True,
        "sourceCommit": source,
        "ownerRunId": run_id,
        "ownerRunAttempt": attempt,
        "manifestSha256": pin,
        "rehearsalSignatureVerified": True,
        "rehearsalPackageBytesVerified": True,
        "signedOwnerManifestVerified": False,
        "workerRunVerified": False,
        "protectedTagVerified": False,
        "registryReceiptVerified": False,
        "exclusiveWriterVerified": False,
        "publicationAuthorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("generate", "verify"))
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--pin")
    args = parser.parse_args()
    try:
        if args.operation == "generate":
            if args.pin is not None:
                raise ValueError("generate does not accept a pin")
            print(generate(args.bundle, args.source, args.run_id, args.attempt))
        else:
            if args.pin is None:
                raise ValueError("verify requires the independent pin")
            result = verify(
                GitHubAttestationCLI(),
                args.bundle,
                args.source,
                args.run_id,
                args.attempt,
                args.pin,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"signed handoff rehearsal: FAIL: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
