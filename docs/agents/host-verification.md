# Agent host verification: evidence levels

Agent compatibility has three distinct evidence levels. Do **not** equate them:

1. **Static**: the repository's JSON/TOML/YAML files parse, metadata is
   consistent, and host-specific starter configuration exists. Checked by
   `python scripts/check_agent_host_evidence.py` in the required CI policy job.
2. **Protocol smoke**: a generic MCP SDK client performs discovery and a safe
   tool call against the project server. This validates the transport, **not**
   that Claude, Codex, Gemini, Cursor, OpenCode or Copilot installed the server.
3. **Real host smoke**: the exact named host, build/version and OS installed
   the package, discovered the intended portable skill and MCP server, called
   one read-only diagnostic tool on a trusted fixture, and refused an attempted
   write in `readonly` mode. Record the host versions and sanitized outcomes.

The source catalog, `integrations/common/agent-host-evidence.json`, reports
**static-only** for every host until separately reproducible evidence exists.
CI never silently downloads agent binaries, registers plugins, acquires auth
tokens, enables shell permissions, or accesses private KiCad projects.

## Manual smoke checklist (trusted sandbox only)

1. Record host + version, OS, Python/uvx/KiCad versions, repository SHA and
   local package version, without home paths or credentials.
2. In an isolated fixture, install the host-native config or extension.
3. Confirm the host explicitly lists the `kicad` MCP server and the relevant
   `pcb-design` / `kicad-design-review` skill; capture sanitized results.
4. Ask it to call the actual `kicad_get_server_info` or project summary tool
   in **readonly** mode, and record the observed tool response, not a screenshot
   of a static config or an SDK-only test.
5. Verify the host does **not** expose mutation operations in readonly mode;
   never execute destructive calls solely to prove they're disabled.
6. Repeat for supported stdio/HTTP transports only when the host supports them;
   distinguish platform/host limitations from KiCad server failures.
7. Add dated evidence and review it before changing a catalog `smokeStatus`.

See also [the common compatibility matrix](compatibility.md) and
[Agent Skills ownership](progressive-disclosure.md). Local installation of the
Gemini pilot is documented under
`integrations/gemini-cli/kicad-mcp-pro/README.md`.


## Sanitize and review native-host evidence (#1219)

A manually captured, **sanitized** JSON observation should contain the host
identity/version, platform, source SHA, server version, stdio/Streamable HTTP,
exact discovered skill names, the observed readonly tool name, and booleans for
MCP discovery, successful tool response and absence of write tool exposure.
Include a SHA-256 digest of the separately retained sanitized native-host log;
never embed tool arguments, transcripts, project paths, credentials, or raw
provider responses in this JSON. Follow the exact field contract in
`scripts/check_agent_native_smoke_evidence.py`. Review using:

```sh
uv run --all-extras --frozen python scripts/check_agent_native_smoke_evidence.py \
  --report /path/to/sanitized-native-host-observation.json
```

Passing returns `structurally_complete_not_attested` — **never** a release
compatibility pass. A reviewer must independently inspect the pinned real-host
execution log/digest, the source commit and environment before updating any
published compatibility claim. Synthetic unit-test data cannot serve as evidence.
The normal CI job does not install any agent host or generate passing evidence.
