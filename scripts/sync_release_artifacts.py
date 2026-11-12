#!/usr/bin/env python3
"""Synchronize generated release artifacts derived from package metadata."""

from __future__ import annotations

import argparse

if __package__:
    # Module entry point: python -m scripts.sync_release_artifacts.
    from . import build_capability_catalog, build_tool_effect_manifest, sync_mcp_metadata
else:
    # Script entry point: python scripts/sync_release_artifacts.py.
    # Avoid importing an unrelated third-party "scripts" namespace on Windows.
    import build_tool_effect_manifest
    import sync_mcp_metadata


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Fail if release artifacts drift.")
    mode.add_argument("--write", action="store_true", help="Regenerate release artifacts.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    metadata_args = ["--write"] if args.write else ["--check"]
    manifest_args = [] if args.write else ["--check"]

    metadata_status = sync_mcp_metadata.main(metadata_args)
    if metadata_status != 0:
        return metadata_status
    manifest_status = build_tool_effect_manifest.main(manifest_args)
    if manifest_status != 0:
        return manifest_status
    # The local capability catalog embeds the release packageVersion.
    # A version bump must update it before CI tests assert exact parity.
    return build_capability_catalog.main(manifest_args)


if __name__ == "__main__":
    raise SystemExit(main())
