# Gemini CLI package provenance review — 2026-10-28 (#1219)

**Scope:** published KiCad MCP Pro 4.4.0 package identity, not a real-host
smoke or independent cryptographic attestation. No agent/model invocation,
KiCad project operation, release or persistent extension installation occurred.

## Observed public release and independently checked bytes

The [PyPI 4.4.0 release](https://pypi.org/project/kicad-mcp-pro/4.4.0/)
publishes exactly one universal wheel and one source distribution. An isolated,
read-only HTTPS check retrieved `https://pypi.org/pypi/kicad-mcp-pro/4.4.0/json`
and streamed each distribution from the returned HTTPS
`files.pythonhosted.org` address, without executing or retaining either file.
The locally calculated SHA-256 hashes matched both the official PyPI JSON
metadata and its published release page:

| File | Bytes checked | Verified SHA-256 |
| --- | ---: | --- |
| `kicad_mcp_pro-4.4.0-py3-none-any.whl` | 1,157,695 | `3717a59c083925179d14fe2721b32c237702d8e5825786fb6310bcc2896c7240` |
| `kicad_mcp_pro-4.4.0.tar.gz` | 956,495 | `de13429f6baeb3fda6b17fe909b7796b891b25dab92c569e8586c0faea5e0862` |

For each artifact, PyPI's release page reports a verified **publish
attestation** under GitHub Actions for
`oaslananka/kicad-mcp-pro@285be423edd2d16c799f4cb20b60858a4a729010`,
using `.github/workflows/publish-python.yml`. The referenced source commit
was independently confirmed to exist in the canonical repository and to be
its `4.4.0` release commit. The publisher's attestation was **not**
independently cryptographically verified in this check; the claim here is
limited to what PyPI reports plus separately downloaded artifact bytes.

## Runtime binding and remaining acceptance limits

The extension manifest now asks `uvx` for the exact package *version* with
`--from kicad-mcp-pro==4.4.0`. Release metadata synchronization updates that
argument whenever the checked-in extension version changes. Static checks
reject unversioned, ranged, mismatched and unexpected launch arguments.

This is **not** a wheel-byte pin or complete dependency lock: the actual
installed artifact, package index and transitive dependencies still require
independent review at host-test time. Nor does the published 4.4.0 release
commit equal the later repository `main` commit being tested.

A bounded `uvx --offline --from 'kicad-mcp-pro==4.4.0' kicad-mcp-pro --help`
probe reported that the pinned package was absent from the local uv cache;
no command or server started. This was an **offline cache miss**, not evidence
of either failed online installation or a working native host connection.
Do not promote the six static host-catalog entries: Gemini-native diagnostic
`tools/call`, readonly mutation-tool inventory, independent attestation and
actual source-bound runtime acceptance are still outstanding.

Follow-up: verify the package's PyPI attestation signature with a reviewed
verifier, reproduce a *source-bound* isolated runtime, and collect genuine
host-native readonly diagnostics before changing compatibility claims.
