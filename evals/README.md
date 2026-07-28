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

### Adding cases

Keep IDs unique and tool names identical to registered MCP names. Tool-call cases
must contain at least one expected tool. Confirmation, refusal, and ordinary-answer
cases must contain no expected tools. Prefer adversarial cases that enforce stable
behavioral and safety contracts rather than provider-specific wording.
