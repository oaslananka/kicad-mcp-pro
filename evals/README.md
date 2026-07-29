# KiCad MCP Pro evaluations

This directory contains versioned, model-agnostic quality contracts for the
agent-facing surface. The primary risk is incorrect tool selection: choosing an
unrelated capability, invoking a write for a read-only request, or behaving
inconsistently across repeated runs.

## Tool-selection evaluation

The schema-v2 dataset at [`tool_selection/cases.yaml`](tool_selection/cases.yaml)
contains representative and adversarial intents across six categories:

- inspection;
- authoring;
- mutation;
- validation;
- release;
- confirmation/refusal.

Each case declares:

- `expected_tools`: capabilities that must be selected for a tool-call case;
- `allowed_tools`: optional setup/context calls that are not counted as unnecessary;
- `forbidden_tools`: explicit behavioral exclusions for commonly confused tools;
- `safety`: the maximum capability boundary (`read_only`, `write`, `export`,
  `publish`, `human_only`, or `no_tool`);
- `expected_behavior`: `tool_calls`, `answer`, `confirmation`, or `refusal`;
- `max_calls`: a per-case call budget;
- category and tags for coverage analysis.

Safety is evaluated against the canonical capability registry. A `read_only` case
therefore rejects every write, export, publish, human-only, or unclassified call
even when the tool is not repeated in `forbidden_tools`.

The deterministic scorer in
[`src/kicad_mcp/evals/tool_selection.py`](../src/kicad_mcp/evals/tool_selection.py)
reports:

- expected-tool recall and response-behavior match;
- explicit forbidden and capability-tier safety violations;
- unnecessary calls and call-budget violations;
- latency and token usage when supplied by the host adapter;
- repeated-run instability and per-case nondeterminism.

Release thresholds and permitted baseline variance are versioned in
[`tool_selection/thresholds.yaml`](tool_selection/thresholds.yaml). Latency and
token ceilings remain unset until repeated live benchmarks establish comparable
baselines across supported hosts.

### Legacy agent adapter

Existing callers can continue returning only selected tool names:

```python
from kicad_mcp.evals.tool_selection import aggregate, load_cases, run_eval

cases = load_cases("evals/tool_selection/cases.yaml")


def agent(prompt: str) -> list[str]:
    # Drive an MCP host/model and return called tool names.
    ...


results = run_eval(cases, agent)
print(aggregate(results))
```

An empty legacy result is interpreted as an ordinary answer. Confirmation and
refusal cases require the richer adapter below.

### Rich agent observation

```python
from kicad_mcp.capabilities import all_records
from kicad_mcp.evals.tool_selection import AgentRun, load_cases, run_eval_repeated

cases = load_cases("evals/tool_selection/cases.yaml")
tiers = {name: record.tier for name, record in all_records().items()}


def agent(prompt: str) -> AgentRun:
    return AgentRun(
        called_tools=("run_drc",),
        response_kind="tool_calls",
        latency_ms=420.0,
        input_tokens=900,
        output_tokens=80,
    )


runs = run_eval_repeated(cases, agent, repeats=3, tool_tiers=tiers)
```

Live provider execution remains a separate, bounded, billed step. Credentials must
come from the configured secret source at runtime and must never be written to the
repository, traces, reports, or CI artifacts.

## Provider-neutral live runner

The runner in
[`src/kicad_mcp/evals/live_runner.py`](../src/kicad_mcp/evals/live_runner.py)
keeps provider and host integrations outside the deterministic scorer. It supports
one strict configuration schema with two adapter kinds:

- `replay`: reads sanitized JSONL observations and resets the trace before each
  repeated corpus run;
- `subprocess`: invokes an external adapter with an argument list, `shell=False`,
  a per-attempt timeout, bounded retries, and an explicit environment allowlist.

A configuration record declares all limits. Missing limits are rejected rather
than replaced with permissive defaults:

```yaml
schema_version: 1
configurations:
  - id: replay-golden
    host: fixture
    model: deterministic-golden
    adapter: replay
    trace_path: replay-golden.jsonl
    limits:
      timeout_seconds: 5
      max_retries: 0
      max_cases: 325
      max_total_tool_calls: 500
      max_total_tokens: 100000
      max_total_cost_micros: 0

  - id: host-a
    host: supported-host-a
    model: supported-model-a
    adapter: subprocess
    command: [host-a-eval-adapter, --json]
    required_env: [HOST_A_API_KEY]
    limits:
      timeout_seconds: 60
      max_retries: 2
      max_cases: 325
      max_total_tool_calls: 1000
      max_total_tokens: 500000
      max_total_cost_micros: 10000000

  - id: host-b
    host: supported-host-b
    model: supported-model-b
    adapter: subprocess
    command: [host-b-eval-adapter]
    required_env: [HOST_B_TOKEN]
    limits:
      timeout_seconds: 90
      max_retries: 1
      max_cases: 325
      max_total_tool_calls: 1000
      max_total_tokens: 500000
      max_total_cost_micros: 10000000
```

Configuration files contain environment variable names only. Inline credentials
in command arguments are rejected. The subprocess receives only a small safe base
environment plus variables named in `required_env`; unrelated process secrets are
not inherited.

### Adapter JSON contract

For each case, the runner writes one JSON request to adapter stdin:

```json
{"case_id":"board_overview","prompt":"...","schema_version":1}
```

The prompt is runtime input and is never copied to evidence. A successful adapter
writes exactly one JSON object to stdout:

```json
{
  "schema_version": 1,
  "status": "ok",
  "response_kind": "tool_calls",
  "called_tools": ["pcb_get_board_summary"],
  "latency_ms": 420,
  "input_tokens": 900,
  "output_tokens": 80,
  "estimated_cost_micros": 250
}
```

A host or provider failure uses the restricted error shape:

```json
{"failure_kind":"provider_rate_limit","schema_version":1,"status":"error"}
```

Supported classifications are `adapter_unavailable`, `timeout`, `protocol_error`,
`provider_auth`, `provider_rate_limit`, `provider_unavailable`, `budget_exceeded`,
`model_error`, and `unknown`. Only timeout, provider rate limiting, and provider
unavailability are retried. A valid model response that selects the wrong tool is
not an adapter failure; it reaches the scorer and is reported separately as a
selection failure.

Raw provider payloads, messages, stack traces, transcripts, and extra response
fields are rejected. Stderr is not retained in the report.

### Replay and evidence

Run the committed 65-case replay without network access or credentials:

```bash
uv run --all-extras python scripts/run_live_model_eval.py \
  --configuration replay-golden \
  --source-revision "$(git rev-parse HEAD)" \
  --repeats 1 \
  --output /tmp/kicad-mcp-live-eval-evidence.json
```

The schema-versioned evidence contains configuration identity, source revision,
case IDs, normalized tool calls, telemetry, failure classifications, scorer
results, aggregate metrics, and threshold outcome. It deliberately excludes
prompts, commands, environment variable names, raw request/response content,
transcripts, credentials, and private absolute paths. The same configuration,
trace, source revision, and repeat count produce byte-identical JSON.

### Protected billed runs

`.github/workflows/live-model-eval.yml` is manual-only. Replay mode is safe to run
without secrets. Live mode is restricted to `main` and the protected
`live-model-evals` environment. Provider credentials are synchronized from Doppler
into that GitHub environment and are injected only into the billed job. The
workflow does not require a long-lived Doppler token in GitHub Actions.

Live adapter configuration records are versioned in
[`live/configurations.yaml`](live/configurations.yaml) and contain no credential
values. In addition to the deterministic replay, the protected benchmark surface
contains three reviewed cross-publisher NVIDIA NIM records:

- `nvidia/nemotron-3-nano-30b-a3b`;
- `mistralai/mistral-medium-3.5-128b`;
- `google/gemma-4-31b-it`.

These are specific NVIDIA-hosted sample configurations, not a claim that one host,
publisher, or model family represents universal model quality. The adapter uses the
OpenAI-compatible chat-completions endpoint directly through the existing HTTP
client dependency; no vendor SDK is added. It supplies a deterministic 62-tool
catalog built from every expected, allowed, and forbidden tool referenced by the
versioned corpus plus the machine-generated public tool summaries. Case expectations
and prompts are never copied to evidence.

`.github/workflows/live-model-release-gate.yml` runs the three configurations
sequentially from protected `main`, with at least three full-corpus repetitions per
configuration. Each matrix job always emits a small status record and uploads only
sanitized evidence. The aggregate job distinguishes:

- destructive/safety failures;
- tool-selection and baseline quality regressions;
- adapter/provider/incomplete-run infrastructure failures;
- unavailable token or latency telemetry.

Approved compact baselines live in [`live/baselines.yaml`](live/baselines.yaml).
The committed file starts with `approved: false`, so the aggregate release gate
fails closed while still producing reviewable benchmark artifacts. After the first
protected runs, only reviewed aggregate metrics and permitted variance are versioned;
raw provider responses, reasoning, transcripts, prompts, credentials, and user
projects remain excluded.

The workflows upload only sanitized JSON. The repository does not commit provider
credentials, vendor SDKs, raw authorization material, live model transcripts, or
proprietary project content. Provider usage counters are recorded when exposed;
missing counters remain a telemetry-availability result rather than being mislabeled
as an adapter failure.

### Adding cases

Keep IDs unique and tool names identical to registered MCP names. Tool-call cases
must contain at least one expected tool. Confirmation, refusal, and ordinary-answer
cases must contain no expected tools. Prefer adversarial cases that enforce stable
behavioral and safety contracts rather than provider-specific wording.
