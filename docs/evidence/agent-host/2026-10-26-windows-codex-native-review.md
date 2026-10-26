# Bounded native Codex readonly observation — Windows, 2026-10-26

This is a **single model-free, host-originated MCP observation**, not independent
compatibility attestation or permission to promote smokeStatus from not-run.
It supplements the separately recorded Linux/Codex 0.163.0 observation for #1219.

## Source and host provenance

- OS: Windows x64, Codex app-server **0.144.4** (pre-existing installation).
- Native Codex executable SHA-256:
  51398051c2332b6afe08dc3b9dbb4056085c197f35ca57a307ee303d450cada5.
- Reviewed Python environment: CPython 3.13, created under a **temporary public
  repository checkout**, using repository-pinned uv==0.13.5 and
  uv sync --locked --no-dev. Python executable SHA-256:
  1af8886c553330f790e92ed60b208c568b1be19dcbe6d03ca60f26df086c30d6.
- Exact server source: main@f9a21b4e7fad0267bc162b864faea7be1081acbe;
  source-loaded package version **4.4.0** and a clean src/ tree.
- Transport stdio; operating mode readonly; profile default;
  a fresh **unbound** KiCad IPC socket path and separate temporary
  CODEX_HOME, HOME, USERPROFILE, APPDATA, LOCALAPPDATA, and XDG paths.

No ambient user KiCad project was selected or opened, no GUI IPC socket was
connected, no provider credentials were loaded, no model/agent turn was started,
and no mutating tool was invoked. The sandbox generated temporary KiCad
application-settings JSON files **inside the temporary checkout**, which were
removed after inspection; no real project data was modified.

## Native host sequence (not an SDK surrogate)

1. Native initialize returned successfully.
2. Native skills/list discovered all **7 project-owned** KiCad skills,
   matching checkout-resident files and rejecting duplicate/off-checkout origins.
3. thread/start created an ephemeral thread without turn/start.
4. Native mcpServerStatus/list returned kicad serverInfo and **24 tools**.
   **Version distinction:** Codex 0.144.4 omits the runtimeStatus field
   observed on Linux Codex 0.163.0. Do not infer or fabricate that field.
5. Every advertised tool name was checked against the **same checkout's**
   capability and OperatingMode.READONLY policy. This includes
   kicad_set_project, which changes server selection context, **not**
   on-disk schematic/PCB content. No write tool was called.
6. Native **mcpServer/tool/call** successfully invoked
   **kicad_get_server_info**, with non-error and nonempty native response.
   Raw response content was not retained.
7. The native host and descendants were terminated; temporary homes,
   generated application settings and working files were cleaned.

## Sanitized evidence

- [Structural smoke report](2026-10-26-windows-codex-native-smoke.json).
- [Source-bound sanitized native observation](2026-10-26-windows-codex-native-sanitized-log.json),
  SHA-256 6ace3f8b2e54119ef21e2614129ce3b99931aab6a2a7a83881b199d5e130223e.
- Check the report with scripts/check_agent_native_smoke_evidence.py,
  using --report docs/evidence/agent-host/2026-10-26-windows-codex-native-smoke.json
  from the repository root with that root in PYTHONPATH.
- Expected verdict: **structurally_complete_not_attested** and
  establishes_real_host_compatibility=false, not a release gate.

## Independent review and limits

An independent reviewer must verify binary trust/pinning, environment
isolation, exact source/tool policy, native RPC sequence and sanitized digest,
preferably by replaying on a separately prepared fixture, before accepting
any named-host compatibility statement. Windows 0.144.4 differs from Linux
0.163.0; the observations are not interchangeable. No real KiCad GUI
interoperability, other transport/host, provider behavior or
destructive-call behavior is established. The entire six-host static
evidence catalog remains not-run until separately reviewed reconciliation.
**Issue #1219 remains open.**
