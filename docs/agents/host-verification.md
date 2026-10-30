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
# Built-in, source-reviewed archive (no arbitrary CLI input path):
uv run --all-extras --frozen python scripts/check_agent_native_smoke_evidence.py \
  --report 2026-10-26-linux-codex-native-smoke.json
```

Passing returns `structurally_complete_not_attested` — **never** a release
compatibility pass. For a retained Codex observation, use the optional
`--verify-sanitized-log` flag to check the **actual sibling log bytes** against
the report: its SHA-256 digest, host/source identity, Skill origins, source-pinned
readonly tool inventory, native diagnostic and basic redaction constraints.
Binary digests in the log are **format-checked only**; they are not compared
with the real executables or any report fields. An unreviewed source revision
is rejected until its readonly tool policy is separately reviewed and pinned:

```sh
PYTHONPATH=. python scripts/check_agent_native_smoke_evidence.py \
  --report docs/evidence/agent-host/2026-10-26-windows-codex-native-smoke.json \
  --verify-sanitized-log
```

This offline check accepts reviewed, fixed archive identifiers only; arbitrary
operator-selected file **paths are no longer passed to filesystem operations**.
Dated archives must agree with the report date/OS. Newly captured reports
outside the checkout use a **bounded stdin JSON envelope** containing
name, report_b64 and log_b64 (empty only without log verification).
The envelope is size-limited and decoded JSON rejects duplicate keys. The
native-probe name codex-native-smoke.json is supported as data, not a path.
Unreviewed archives require an explicit source allowlist addition after review.
The validator fails closed on missing, altered or unsanitized data, and does
not independently attest any native host.

## Gemini CLI PyPI 4.4.0 package identity review — 2026-10-28 (#1219)

The Gemini pilot extension now pins its `uvx --from` package requirement to
its own published version, with a fail-closed static check and metadata-sync
coupling. The [dated PyPI artifact provenance review](../evidence/agent-host/2026-10-28-gemini-pypi-provenance-review.md)
records the independently downloaded wheel/sdist SHA-256 matches, the
published source-commit identity and the limits of that evidence. Version
pinning is **not** independent attestation verification, an exact transitive
lock, a native Gemini diagnostic call or a full compatibility smoke. No host
catalog status is promoted by the artifact review.

## Linux Gemini CLI 0.60.0 pinned-PyPI native connection — 2026-10-28 (#1219)

The real Gemini CLI — **not an MCP SDK client** — reported a
`kicad` **Connected** stdio server with the reviewed published-version
launch (`uvx --from kicad-mcp-pro==4.4.0`), using a temporary
`readonly/default` configuration and no provider credentials or KiCad IPC.
An independent PyPI PEP 740 publisher-verification check passed for both
4.4.0 artifacts. Two disposable uv cache copies matched the checked wheel's
460 selected files each, excluding installer-generated `RECORD`.

The [dated partial Gemini observation](../evidence/agent-host/2026-10-28-linux-gemini-pinned-stdio-partial.json)
is **not** a full native-host smoke report: the settings were recreated from
the reviewed extension, the raw logs were not retained, and no model-free
Gemini-originated `kicad_get_server_info` / `tools/call`, readonly write-tool
absence or independent running-process attestation was established. It does
not pass the strict native smoke validator. This observation must **not**
change the six-host `repository-static` / `not-run` catalog or close #1219.

## Installed Gemini CLI core model-free MCP diagnostic — 2026-10-28 (#1219)

A **separate** isolated Linux probe loaded the real installed Gemini CLI
**0.60.0 core** `McpClient` and `DiscoveredMCPToolInvocation` implementations,
rather than directly constructing a generic MCP SDK client. With the
published-version-pinned 4.4.0 `uvx` stdio launcher, temporary HOME/workspace,
empty inherited provider-credential environment, unbound KiCad IPC socket and
`readonly/default`, this Gemini **core** path:

- Discovered 24 named tools, all recognized by the **same source revision's**
  `tool_required_mode()` as `readonly`, with no unknown tools.
- Invoked **only** `kicad_get_server_info` via
  `DiscoveredMCPToolInvocation.execute()`, with empty arguments and a
  nonempty, non-error result. Neither the raw response nor private paths were
  retained. Temporary cache/workspace were deleted.
- Observed **six tools without `readOnlyHint: true` annotations** in Gemini
  metadata despite their readonly source-policy classification. This is an
  annotation/UX ambiguity and **not evidence that write tools were executed**.

The [sanitized result](../evidence/agent-host/2026-10-28-linux-gemini-core-readonly.json)
includes the installed core module SHA-256 and discovered tool names. The
probe verifies the pinned SHA-256 **before importing any Gemini core module**,
refuses symlinked core files, and does not import unknown sibling core files.
Path-related analysis is handled without suppressing scanner rules: the
operator explicitly chooses the installed CLI entrypoint, the extension
manifest path is fixed to this source checkout, and discovered core filenames
must be single regex-validated basenames. All package, manifest and core reads
use bounded regular-file handles with a symlink-resistant `O_NOFOLLOW` open
where supported, plus pre-open file identity checks. The installed core module
SHA-256 is verified **before it is imported**. For portable test subprocesses
with a replacement environment, the probe accepts only a numeric macOS
CoreFoundation `__CF_USER_TEXT_ENCODING` marker on macOS or an absolute Windows
`SystemRoot` directory on Windows; credential/project environment variables
remain prohibited. The Windows test passes `SystemRoot` explicitly so Node/V8
can start. Candidate core file checks run in a bounded group (at most six)
without serial `await` in a loop. Test subprocesses use fixed argv, no shell
and bounded timeouts. These controls do **not** attest every transitive bundled
module or eliminate every possible filesystem race. Review the evidence against the same-source operating-mode catalog with:

```bash
PYTHONPATH=src python scripts/check_gemini_core_readonly_evidence.py
```

On a trusted isolated Linux machine with locally installed Gemini CLI 0.60.0,
Node.js 24+, `uvx` and installed Python 3.13+, run the reviewed, **model-free**
probe from that same source checkout using a minimal environment:

```bash
env -i PATH="$PATH" HOME="$(mktemp -d)" UV_PYTHON=/absolute/path/to/python3.13   node scripts/probe_gemini_core_readonly.mjs   --gemini-entry "$(readlink -f "$(command -v gemini)")"
```

The command prints sanitized JSON only; use a disposable HOME and remove it
afterward. It refuses inherited provider credentials and any manifest that
enables trusted tools or unpinned versions. Only the named diagnostic can be
called, and no model turn or live KiCad project is involved.

**Evidence boundary:** This is a programmatic invocation of the installed
**Gemini CLI core library**, **not** an actual interactive Gemini CLI session,
host-originated model tool selection, extension-precedence validation,
independently attested running executable, reproducible source build or
complete host acceptance. The temporary folder is explicitly considered
trusted only to start the reviewed stdio command; tool trust remains false.
The script executes an operator-approved diagnostic without Gemini UI consent.
Missing MCP readonly annotations also prevent asserting that every discovered
tool advertises itself as readonly. All six compatibility catalog entries
remain `repository-static/not-run`; #1219 is still open.

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
# The CLI uses no filesystem paths from untrusted report arguments.
# Feed new operator-selected files as DATA via a bounded stdin envelope.
python - \
  /tmp/codex-mcp-native-review/codex-native-smoke.json \
  /tmp/codex-mcp-native-review/codex-native-sanitized-log.json <<'PY' | \
  PYTHONPATH=. python scripts/check_agent_native_smoke_evidence.py \
    --report - --verify-sanitized-log
import base64
import json
import sys
from pathlib import Path

report, log = (Path(arg) for arg in sys.argv[1:])
print(json.dumps({
    "name": report.name,
    "report_b64": base64.b64encode(report.read_bytes()).decode("ascii"),
    "log_b64": base64.b64encode(log.read_bytes()).decode("ascii"),
}))
PY
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

## Second model-free Codex readonly replay — 2026-10-27 (#1219)

An independently started Codex CLI **0.163.0** Linux/stdio/default/readonly
app-server session repeated native Skill discovery (**7/7**), live MCP
connection and source-checked readonly tool inventory (**24**), and a real
`mcpServer/tool/call` invocation of `kicad_get_server_info`. The tested source
was protected `main@d910e24ad864a1fcf92947fcdefbe0a60c099ff2`, whose
committed `src` tree exactly matches the previous reviewed source
`57c0efb1f072f5fffbf1f527ee2348448705e32d`. Both actual executable
SHA-256 digests were verified before running. The pinned Python 3.13.17
dependencies were prepared in a disposable worktree using cached **uv 0.13.5**
with `--offline --frozen --no-dev`; no provider call, model turn, user design
file, ambient KiCad IPC or persistent user-project modification occurred.

The [2026-10-27 sanitized report](../evidence/agent-host/2026-10-27-linux-codex-native-smoke.json)
links by SHA-256 to its [sanitized log](../evidence/agent-host/2026-10-27-linux-codex-native-sanitized-log.json).
Both pass the same strict structural/log binding checker and a checked-in
regression. This is a **repeat host-native observation on the same Linux
platform**, not independent binary-source provenance attestation, complete GUI
compatibility or a claim about any other host/OS/transport. The native checker
still reports `structurally_complete_not_attested`; the six-host catalog
remains `repository-static` / `not-run` pending independent acceptance.

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


## Codex 0.163.0 read-only host replay on v4.5.0 — 2026-10-31 (#1219)

On an isolated Linux process with ephemeral home, an actual Codex app-server
0.163.0 (prechecked executable SHA-256) connected to the **v4.5.0 release-tagged
source** at `9aa519b1bb82b3907eefedbba26285cf4431d856`, not a published-wheel
installation. It discovered all seven source-owned KiCad Skills, inventoried 24
default-profile tools, and invoked `kicad_get_server_info` through the native
`mcpServer/tool/call` interface. The complete discovered tool-name set matches
the reviewed read-only source policy. No model/agent turn, user project, GUI
IPC socket, or write operation was used.

The new source SHA was accepted **only after** reviewing the versioned
`capabilities.py`, `operating_modes.py` and `tools/router.py` against the prior
pinned source: the operating-mode implementation is unchanged; a single newly
registered `pcb_add_track_segment` tool is WRITE-tier, not part of the default
24 read-only tools. The stored log and report are redacted, digest-bound, and
checked by `scripts/check_agent_native_smoke_evidence.py` (fixed archive and
bounded stdin paths). The original unpinned evidence was correctly rejected
until this source-policy review.

Evidence: `docs/evidence/agent-host/2026-10-31-linux-codex-native-smoke.json`
and its same-stem `sanitized-log.json`. The structural result remains
`structurally_complete_not_attested`. This replay does **not** establish
independent executable provenance, macOS/Windows applicability, verified PyPI
wheel execution, actual graphical KiCad integration, or full real-host
compatibility. The six-host catalog remains `repository-static/not-run`.
