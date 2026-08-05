# Threat Model

KiCad MCP Pro runs local automation against KiCad projects on behalf of an MCP client
(an AI agent). This document maps the data flows, the trust boundaries, and — for each
attack surface — the control and the test that verifies it. Controls that are only
recommended (not yet implemented) are called out as residual risks.

## Data flow and trust boundaries

```
MCP client (agent)  --tool calls-->  KiCad MCP Pro
                                       |  |  |
        argv list (no shell) ---------+  |  +--- file I/O (workspace-confined)
        kicad-cli subprocess             |
                                         +--- KiCad IPC (kipy) to a running KiCad
```

- **The MCP client is not automatically trusted.** Tool arguments (paths, names,
  net specs) are attacker-controllable. Use the smallest practical profile and the
  least-privileged operating mode.
- **The active project directory is the trusted I/O scope.** Reads/writes are confined
  to it (or the configured workspace root).
- **`kicad-cli` and the KiCad IPC endpoint are trusted local components**, configured by
  the operator (`KICAD_MCP_KICAD_CLI`, socket env). Whoever sets those env vars is in the
  trust base.
- **HTTP/bridge transports are off by default** and local-only unless explicitly exposed.

## Surfaces, controls, and verification

### 1. `kicad-cli` subprocess (command/argument injection)

- **Threat:** a tool argument (an output path, layer, variant, or net name) is
  interpreted as a shell command or an injected CLI flag.
- **Control:** the server **never invokes a shell.** Every `kicad-cli` call is
  `subprocess.run([binary, *args], shell=False)` with the operator-configured binary, so
  arguments are passed as discrete argv elements and are never shell-interpreted. There is
  no `os.system`, `os.popen`, `subprocess.getoutput`, or `shell=True` anywhere in `src/`.
- **Verification:** `tests/unit/test_security_controls.py::test_no_shell_execution_anywhere_in_src`
  scans the whole source tree, and `::test_kicad_cli_is_invoked_as_argv_list` asserts an
  injection-looking argument (`"; rm -rf /"`) reaches the CLI as a single literal argv
  element with `shell=False`.

### 2. Path traversal

- **Threat:** a client supplies `../../etc/passwd` or an absolute/UNC path to read or
  write outside the project.
- **Control:** `path_safety.resolve_under` / `config.resolve_within_project` resolve every
  path under the project root and raise `UnsafePathError` if it escapes; `relative_subpath`
  rejects absolute paths and `..` for output subdirectories; `reject_foreign_windows_path`
  blocks Windows drive/UNC paths on POSIX hosts.
- **Verification:** `tests/unit/test_security_controls.py` (traversal/absolute rejection)
  and the broader `tests/unit/test_path_safety.py` corpus (UNC, symlinks, spaces/unicode,
  long paths).

### 3. HTTP transport (auth, CORS, origin)

- **Threat:** a local web page or a leaked token drives the tool surface over HTTP.
- **Control:** Streamable HTTP is opt-in. When enabled, `_DashboardAuthMiddleware` enforces
  the optional bearer token (`_StaticTokenVerifier`, `required_scopes=["mcp"]`),
  `_OriginValidationMiddleware` checks the `Origin`, and `CORSMiddleware` restricts origins
  to the configured allow-list. The legacy HTTP+SSE routes are disabled by default.
- **Verification:** web-route and server-startup tests under `tests/unit/` exercise the
  auth/CORS/origin paths; transport contract is checked by `test_mcp_protocol_contract.py`.

### 4. Bridge daemon (localhost pairing)

- **Threat:** an attacker brute-forces the bridge pairing code, floods the daemon, or
  reaches a bridge that was incorrectly exposed beyond the local host.
- **Control:** the bridge is opt-in and localhost-only: it binds to `127.0.0.1` and
  requires a randomly generated 128-bit pairing code (`secrets.token_hex(16)`).
  Inbound messages are rate-limited by `TokenBucket`: a general budget blunts floods,
  while a stricter pairing budget permits a small burst and then one attempt every
  five seconds. Oversized messages and exhausted budgets fail before proxy work.
  Verification lives in `tests/unit/test_bridge.py` and
  `tests/unit/test_bridge_rate_limit.py`.
- **Residual risk:** pairing authorizes the bridge connection as a whole. The current
  bridge does not provide a hosted relay, remote browser transport, or per-tool local
  approval. Keep it localhost-only and use local stdio or local Streamable HTTP for
  mutation workflows until a separately reviewed relay and approval protocol exists.

## Supply chain and release integrity

- Dependabot/Renovate, CodeQL, Gitleaks, Trivy, Hadolint, Bandit, and pip-audit cover the
  main automated scan layers.
- Release artifacts are built by GitHub Actions and accompanied by an SBOM, Sigstore
  signatures, checksums, and GitHub artifact attestations, so an artifact is traceable to
  its source and workflow.

## Reporting

Report vulnerabilities privately through GitHub Security Advisories.
