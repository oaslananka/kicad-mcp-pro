# Device pairing only — no remote access

This is the isolated client-side enrollment stage of the original Cloud PR #1513.

- The client generates an owner-private Ed25519 key in a mode-0700 directory
  with a mode-0600 key and binding sidecar, anchored through POSIX no-follow
  directory descriptors.
- A new HTTPS Cloud challenge is checked with a distinct signed, read-only
  status preflight *before* any browser approval page opens.
  A missing endpoint or an already-approved new challenge fails closed.
- After the owner verifies the displayed code and manually approves in the
  authenticated browser, the client polls no faster than every eight seconds
  (within the five-minute deadline), then makes exactly one separate signed
  redeem request. The terminal needs no Enter.
- Cloud saves the device in the **disabled** state. Pairing grants neither
  remote command execution nor project-presence reading, WebSocket access,
  project permissions, or an OAuth token.
- The production Cloud owner-only pilot on 31 October 2026 verified one
  consumed challenge, one *disabled* device and one credential matching the
  client key/fingerprint. The pilot was restored with all features OFF and
  temporary WAF removed.

**Non-goal:** The cloud_once remote-read CLI, project registry/dispatch,
one-shot project_summary and remote project-file presence. These remain in
Draft PR #1513 because independent user-verifying per-read authorization,
restricted automation identity, server-side grant enforcement and real
one-shot read acceptance have not been completed.

To test without connecting to Cloud:
    python scripts/run_pytest.py cloud-pairing
    ruff check src/kicad_mcp/cloud_pair.py src/kicad_mcp/cloud_pair_keys.py tests/cloud/test_cloud_pair.py

This helper is not auto-started and must not activate any production
feature flag. Enrollment requires a real owner browser click; automation
must never approve it.
