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

The static host gate also fails closed if any of the six checked-in client
examples changes its local `kicad` stdio command, arguments, or explicit
`readonly/default` environment. This checks repository configuration, **not**
a genuine host-originated tool call or agent Skill discovery.

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

## Native Codex 0.163.0 model-free readonly tool smoke — 2026-10-26 (#1219)

A real **Codex app-server 0.163.0** on AMD2700X Linux was launched with
temporary `CODEX_HOME`, `HOME`, XDG directories and a temporary MCP
configuration. Its reviewed, source-bound KiCad MCP server was loaded from
`main@57c0efb1f072f5fffbf1f527ee2348448705e32d` using an existing
Python 3.13.17 environment; it used `stdio`, `readonly/default`, and
an explicitly unbound temporary KiCad IPC socket. No live user project,
GUI validation, external agent/model turn or provider inference was requested.

- Native `initialize` and `skills/list` confirmed **7/7** maintained KiCad
  Skills and checked their reported paths inside that exact source checkout.
- Native `thread/start` created an ephemeral thread and
  `mcpServerStatus/list` reported the real `kicad` connection as
  **connected** with **24** discoverable tools. All 24 names were independently
  checked against the *same source revision's* `tool_required_mode()`;
  all require `readonly`, including the context-only project selector.
- Native Codex `mcpServer/tool/call` invoked `kicad_get_server_info` with
  empty arguments: the host returned content with `isError=false`.
  This was **not** a direct generic MCP SDK call and did not invoke KiCad GUI.
- The [sanitized native observation](../evidence/agent-host/2026-10-26-linux-codex-native-smoke.json)
  points to a [bounded sanitized evidence log](../evidence/agent-host/2026-10-26-linux-codex-native-sanitized-log.json)
  by SHA-256. The log intentionally contains no raw diagnostic response,
  absolute machine paths, configuration secrets or unrelated Skill names.

For a bounded independent replay, start from the recorded commit in a
temporary **project-only checkout**, set a temporary `CODEX_HOME` and
`HOME`, and configure `mcp_servers.kicad` to execute that checkout's
source-built Python server over stdio with `readonly/default`. Set
`KICAD_API_SOCKET` to a **fresh unbound socket in the temporary directory**
to prevent accidental attachment to an ambient user GUI. Keep the host
binary version pinned to 0.163.0 and do not copy global agent credentials.

The Codex **app-server JSON-RPC** observation sequence was:
`initialize`; `skills/list` with the checkout cwd and `forceReload=true`;
`thread/start` with `ephemeral=true`; `mcpServerStatus/list` scoped
to `serverName=kicad`, `detail=full` and the resulting thread ID;
then `mcpServer/tool/call` for `kicad_get_server_info` with
`arguments={}`. Validate Skill origins and discovered tool names against
the *same source revision* before calling the diagnostic. Do not initiate
a `turn/start` or any agent/model turn, and do not publish raw responses.
Verify the IPC socket remained unbound; terminate the process group and
delete temporary configuration after the probe. Repeat independently before
promoting any catalog status.

To reproduce this exact Linux/Codex observation, use a trusted source
checkout at the stated commit, installed **Codex 0.163.0**, and an existing
reviewed Python 3.13 environment that already contains the project runtime
dependencies. The probe does **not** install packages, start a model/agent
turn, use ambient GUI IPC, or change the project:

```bash
mkdir /tmp/codex-mcp-native-review
python scripts/probe_codex_native_readonly.py \
  --python /path/to/reviewed/python3.13 \
  --expected-codex-sha256 <independently-reviewed-codex-binary-sha256> \
  --expected-python-sha256 <independently-reviewed-python-binary-sha256> \
  --expected-source-sha 57c0efb1f072f5fffbf1f527ee2348448705e32d \
  --output-dir /tmp/codex-mcp-native-review
PYTHONPATH=. python scripts/check_agent_native_smoke_evidence.py \
  --report /tmp/codex-mcp-native-review/codex-native-smoke.json
```

The two executable SHA-256 values must be obtained from a separate,
trusted review of the *resolved executable artifacts* (not simply the
host's self-reported version). The probe verifies both digests before
running commands and records them in its sanitized log without local paths.
The output directory must be pre-created and must not contain result files.
The source tree must be clean; a descendant PR commit is permitted only if its committed src/ tree exactly matches the pinned source SHA. The probe rejects mismatched host
versions, source SHA, missing Skills, non-readonly advertised tools and
host diagnostics that fail. Keep raw host responses and credentials out of
reports. Its optional output remains review material, not a production gate.

The strict `scripts/check_agent_native_smoke_evidence.py` structural gate
accepts this report as `structurally_complete_not_attested`. **This does not
constitute independent host attestation or authorization to promote** the
six-host static compatibility catalog: a separate reviewer must reproduce
and inspect the source/host evidence. Isolated config and unbound IPC do not
prove universal OS isolation, real KiCad GUI interoperability, or provider
behavior. The other host/transport pairs remain unverified.

## Model-free OpenCode native Skill discovery — 2026-10-25 (#1219)

The actual **OpenCode 1.18.31** CLI on Windows ran
`opencode debug skill --pure` in a temporary checkout of reviewed `main`
revision `1afde5d027d15c309cae77827ff6d1d68adbf9fb` with temporary XDG
config/data/cache/state paths. The command exited 0 without initiating an
agent turn or calling a model. Its structured output contained all **seven**
maintained KiCad skills; every reported source of those seven was inside the
checkout's `.opencode/skills` or `.agents/skills` mirror. The native host also
listed other skills; only the seven project-sourced results are recorded, not
unrelated names or raw skill content.

[Sanitized partial Skill discovery observation](
../evidence/agent-host/2026-10-25-windows-opencode-skills-partial.json)
records CLI version, date, source SHA, exact project skill paths and the
ephemeral output's SHA-256. Raw output was deleted with the temporary checkout.
The isolated XDG paths and `--pure` option do not independently establish
complete isolation from every host-global discovery source.

A separate temporary Windows checkout of the **same exact source revision**
was installed with `uv sync --locked --no-dev`, then OpenCode 1.18.31 ran
`opencode mcp list --pure` against an explicit local stdio MCP configuration
using `readonly/default` settings. The native CLI exited **0** and reported
the isolated source-built `kicad` server as **Connected**. The installation,
MCP configuration and stdout/stderr were removed afterward. The retained
record contains seven repository-relative project Skill paths and no raw
credentials; it does not establish complete isolation from host-global sources.

**Boundary:** this records *real native-host Skill discovery and native MCP
connection health*, but **not** an OpenCode host-originated
`kicad_get_server_info` call, read-only mutation-tool absence or provider
compatibility. No model inference was requested. The strict native smoke
validator rejects the partial record; all catalog `smokeStatus` entries remain
`not-run`. Keep #1219 open pending complete independently reviewed host proof.

## Isolated Windows host connectivity checkpoint — 2026-10-12 (#1219)

A manual, model-free observation of the exact source revision
`ed7bb77eda6e2f1ac087942a5b0302cab718b71f` on Windows used KiCad
10.0.7 and a clean frozen/offline Python environment with KiCad MCP Pro
4.3.0. **No end-user project, model/provider inference, personal config
or credential was read or modified**; CLI configuration homes and repository
clone were restricted to temporary, dedicated locations.

The real **Claude Code 2.1.296** executable reported the actual KiCad MCP
stdio server as `Connected` through a dedicated `CLAUDE_CONFIG_DIR`. The
real **Codex CLI 0.151.0** executable listed the same temporary stdio server
definition using an isolated `CODEX_HOME`, but the Codex CLI's `mcp list`
is **configuration inspection rather than evidence of an active transport**.

An *independent* pinned Python MCP SDK 2.2.0 client (not Claude/Codex) then
performed MCP initialization, listed 24 tools in `readonly/default` mode and
successfully called `kicad_get_server_info`. None of the probed PCB/schematic
file-mutating names appeared. The `kicad_set_project` tool **was** present:
it changes only the server's selected active project context and is
registered with read-tier access. Its write-like name must not be confused
with on-disk schematic/PCB mutation; nor should this be promoted to a
general assertion that every possible side effect has been tested.

[Machine-readable, sanitized partial observations](
../evidence/agent-host/2026-10-12-windows-readonly-stdio-partial.json)
retain the precise distinction between observed real-host connectivity,
Codex static config visibility and the *separate* SDK tool invocation.
No raw host transcripts, executable paths, device/user identities, API
keys or private project content are included.

**Remaining work:** actual Claude/Codex native host-originated
`kicad_get_server_info` call; named-host Skill discovery; supported
Gemini/Cursor/Copilot/OpenCode binary/transport validation; reproducible
pinned manual-dispatch CI evidence. Running a model-bearing CLI session
could require login or incur provider usage and was deliberately not
attempted. The strict native evidence validator intentionally rejects this
partial record, and `integrations/common/agent-host-evidence.json` remains
`not-run` for every host. No compatibility promotion is authorized.
