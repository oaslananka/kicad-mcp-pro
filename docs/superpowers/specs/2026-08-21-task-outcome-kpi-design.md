# End-to-End PCB Task Outcome KPI Design

Issue: #729  
Related: #728, #730, #210

## Problem

KiCad MCP Pro already measures tool-selection quality, golden-fixture correctness, quality-gate behavior, and live-model reliability. Those measurements are useful diagnostics, but none is the canonical answer to the product question: did an agent complete a professional PCB task safely, recoverably, and reproducibly from the declared starting state?

The repository therefore needs a versioned outcome-evidence layer whose denominator is the complete set of benchmark attempts, not successful demonstrations or individual tool calls.

## Design goals

The design must:

- make end-to-end PCB task success the headline aggregate metric;
- preserve lower-level evals as diagnostic inputs rather than replacing them;
- define explicit denominators and excluded/invalid-run accounting;
- consume mutation/recovery evidence from #728 rather than create a second mutation engine;
- consume real-board attempts from #730 without depending on success-only artifacts;
- make required ERC/DRC execution part of task correctness, not an optional side metric;
- treat file corruption as a hard incident count with zero tolerated events;
- verify manufacturing reproducibility by regenerating and comparing outputs;
- record enough pinned runtime identity to make reports independently interpretable;
- remain FastMCP-independent and usable by CI, local benchmark runners, and future published evidence pipelines.

## Approaches considered

### A. Extend the existing live-model evidence schema directly

Add task-success, recovery, DRC, and manufacturing fields to `EvaluationReport` in `live_runner.py`.

This minimizes the number of files and lets existing live-model reports expose the new metrics immediately. It is rejected because `live_runner.py` measures model/tool-selection observations, not complete KiCad project attempts. Coupling project-state evidence to provider evaluation would make non-model and physical-host benchmark runs awkward, blur denominators, and force mutation/manufacturing concepts into the wrong abstraction.

### B. Extend the golden-corpus result model directly

Teach `corpus.py` to represent complete attempts and aggregate the requested KPIs.

This reuses an existing project-level harness, but the current corpus primarily validates fixed fixtures and answer keys. A real attempt contains runtime identity, validation execution, recovery events, reproducibility evidence, and potentially multiple runs per benchmark case. Overloading `GoldenProject` and `CorpusEvalResult` would turn the golden-fixture layer into both fixture definition and historical attempt ledger.

### C. Add a separate versioned task-outcome evidence layer

Introduce a small FastMCP-independent `task_outcomes` module plus a versioned benchmark contract. Existing live-model, golden-corpus, transaction/recovery, validation, and manufacturing evidence are translated into this contract at orchestration boundaries. Aggregation operates only on complete attempt records.

This is the chosen approach. It keeps ownership clear, allows #728 and #730 to feed the same scorer, and avoids changing the semantics of existing eval reports.

## Architecture

### 1. Task contract

A versioned task contract defines which stages are required for one benchmark task class. Initial stages are:

- requirements/specification parsed;
- schematic authored/modified;
- ERC required/executed/consumed/dispositioned;
- PCB authored/modified;
- DRC required/executed/consumed/dispositioned;
- declared constraints verified;
- manufacturing artifacts required/generated;
- manufacturing artifacts regenerated and compared;
- no hidden/manual repair;
- final project parse/reopen verification.

The contract must explicitly mark stages not applicable to a task. An absent stage is not equivalent to a passed stage.

The schema identifier will be string-versioned (for example `pcb-task-outcome.v1`) rather than relying on an unqualified integer. Backward-incompatible scoring changes require a new schema version.

### 2. Attempt record

Every benchmark attempt produces one sanitized machine-readable record. Required identity fields:

- attempt id;
- task id and task-contract version;
- benchmark/spec version;
- exact repository/source SHA;
- KiCad version;
- toolchain/runtime contract version or digest;
- agent/model/provider identity where applicable;
- MCP profile and operating mode;
- starting fixture/state digest;
- start/end timestamps or durations as allowed by the benchmark contract.

Required accounting fields:

- final attempt classification;
- design/tool/recovery/provider/infrastructure failure category when unsuccessful;
- retry count;
- whether the attempt began clean or from a reviewed recovered state;
- whether any manual repair occurred;
- validation execution records;
- mutation/recovery summary;
- parse/reopen result;
- manufacturing reproducibility result where applicable.

Secrets, prompts containing private data, absolute user paths, raw provider responses, and unrelated board content remain forbidden evidence.

### 3. Attempt classifications and denominator rules

An attempt has exactly one top-level classification:

- `success`: every task-required stage passed;
- `task_failure`: execution completed but a required product/task condition failed;
- `recovery_failure`: mutation/recovery safety contract failed;
- `provider_failure`: model/provider failed after a valid benchmark start;
- `tool_failure`: repository/tool contract failed during the attempt;
- `infrastructure_invalid`: the benchmark could not form a valid attempt because a reviewed infrastructure precondition failed before task execution.

Only `infrastructure_invalid` can be excluded from the product-success denominator, and it must still be counted and reported separately with a stable reason code. Provider failures after a valid attempt has started remain in the denominator. This prevents cherry-picking and preserves the issue's fail-closed intent.

### 4. Task success scoring

`task_success` is true only when:

- classification is `success`;
- every stage required by the task contract is present and passed;
- required ERC/DRC were executed and their results consumed;
- no hidden/manual repair is recorded;
- final project parse/reopen passes;
- required manufacturing reproducibility passes;
- no corruption incident is associated with the attempt.

The aggregate PCB Design Task Success Rate is:

`successful valid attempts / all valid attempts`

with invalid infrastructure attempts reported alongside, never silently discarded.

### 5. Mutation recovery and corruption

The outcome layer does not perform transactions. It consumes normalized recovery evidence from #728.

For each attempted mutating operation or logical transaction, evidence records:

- mutation attempted;
- interruption/failure state;
- recovery required;
- deterministic recovery succeeded;
- duplicate application detected after retry/reconnect;
- unexplained before/after divergence detected;
- corruption detected;
- final affected state verified.

Mutation Recovery is calculated over mutations/transactions for which recovery was required:

`successful deterministic recoveries / recovery-required mutations`

The report must also publish total mutations, recovery-required mutations, duplicate incidents, divergence incidents, and corruption incidents. `file_corruption_count > 0` is always a hard KPI failure regardless of averages.

### 6. Validation execution accounting

Validation evidence is represented independently from validation outcome. For ERC and DRC, record:

- required by contract;
- execution attempted;
- execution completed;
- result consumed by the workflow;
- findings resolved, accepted under an explicit reviewed disposition, or left blocking;
- supported exception reason if the task contract explicitly permits one.

Required DRC Execution Rate is:

`tasks with required DRC correctly executed and consumed / valid tasks requiring DRC`

A task requiring DRC cannot score successful if DRC was skipped, merely requested but not completed, or completed without its result being consumed.

### 7. Manufacturing reproducibility

For a task requiring release artifacts, the benchmark records two independently generated artifact sets from the same pinned source/toolchain contract.

Comparison has three outcomes:

- `byte_identical`;
- `normalized_equivalent` under reviewed normalization rules;
- `divergent`.

Presence-only checks do not count. The evidence records the artifact manifest/digests and the normalization rule-set version, not private absolute paths. Manufacturing Reproducibility is successful for byte-identical or reviewed normalized-equivalent results, and fails on unexplained divergence.

### 8. Aggregation and uncertainty

A pure aggregator accepts attempt records and returns a versioned summary containing at minimum:

- valid attempts, successes, failures, infrastructure-invalid runs;
- task success rate;
- task failure taxonomy;
- mutation attempts and recovery denominator/success rate;
- duplicate-application count;
- state-divergence count;
- corruption count;
- required DRC denominator/execution rate;
- manufacturing-release denominator/reproducibility rate;
- confidence interval for rate metrics when the denominator is non-zero;
- target evaluation (`met`, `not_met`, `insufficient_evidence`).

Initial target values come from #729 but target evaluation must distinguish insufficient sample evidence from a passing percentage. The first implementation should use a reviewed binomial confidence interval rather than inventing model-specific statistical assumptions.

### 9. Existing eval integration

Existing layers remain authoritative for their domains:

- `tool_selection.py` / live model reports: tool-selection and provider diagnostics;
- `corpus.py`: fixture and expected-gate correctness;
- #728 transaction evidence: mutation state/recovery/duplicate/divergence facts;
- ERC/DRC and project gates: validation execution/results;
- manufacturing/export layers: artifact generation and normalized comparisons;
- #730 attempt manifests: real-board benchmark inputs and complete run history.

Adapters translate these facts into the task-outcome schema. They must not reinterpret a failing domain result as success.

### 10. Report surfaces

The same summary object drives:

- a deterministic JSON evidence artifact for CI/release publication;
- a human-readable Markdown/text summary;
- later README/release evidence once the maintained corpus has sufficient representative attempts.

Raw tool count remains capability inventory only and must not be promoted into the headline quality section.

## Error handling and fail-closed rules

- Unknown schema versions are rejected.
- Missing required stage evidence fails the task rather than defaulting to pass.
- Unknown failure categories are rejected or mapped to an explicit `unclassified_failure` that remains in the denominator; they are never dropped.
- Evidence with forbidden sensitive keys/values fails sanitization before publication.
- A missing recovery proof after an interrupted mutation is a recovery failure.
- A missing parse/reopen check on a task that produces a KiCad project is a task failure.
- A required DRC execution marked unavailable without a contract-approved exception fails the task.
- Manufacturing comparison errors are failures unless the whole attempt is demonstrably infrastructure-invalid before task execution.

## Testing strategy

### Contract/unit tests

- schema parsing accepts one complete v1 record and rejects unknown/missing/ambiguous fields;
- each required-stage omission causes task failure;
- task classes correctly exempt genuinely non-applicable stages;
- provider failures stay in the valid-attempt denominator;
- only reviewed infrastructure-invalid attempts are separated from the denominator;
- required DRC skip fails task success and lowers DRC execution rate;
- recovery denominator counts only recovery-required mutations;
- duplicate application/state divergence/corruption produce hard failures;
- manufacturing presence without regeneration comparison cannot pass reproducibility;
- aggregate output is deterministic and stable under input ordering;
- evidence sanitization rejects secrets/private paths.

### Integration/eval-contract tests

- translate existing synthetic/golden evidence into one complete attempt record;
- aggregate mixed success/failure/invalid manifests without cherry-pick loss;
- verify report JSON and human summary from the same aggregate object;
- validate schema/attempt manifests intended for #730.

### Physical/KiCad evidence

#729 does not itself duplicate #728's physical mutation tests. As #728 and #730 land, their E2E artifacts feed this scorer and must prove the target denominators with real KiCad evidence.

## Delivery slices

1. **Contract slice:** versioned task/attempt schema, parser/validator, failure taxonomy, deterministic serialization.
2. **Scoring slice:** task-success rules, DRC execution accounting, mutation recovery/corruption metrics, manufacturing reproducibility metric, uncertainty/target status.
3. **Integration slice:** adapters from current eval/gate evidence and report renderers.
4. **Evidence slice:** #728 recovery facts and #730 complete real-board attempt manifests feed maintained headline reports.
5. **Publication slice:** update product/release docs only after representative evidence is sufficient.

## Non-goals

- implementing a second PCB mutation/transaction subsystem;
- replacing ERC/DRC/domain gates with one aggregate score;
- treating provider/infrastructure failures as product successes;
- expanding the default MCP profile to improve a marketing metric;
- claiming target attainment from toy fixtures or an insufficient attempt denominator;
- changing existing public MCP tool contracts as part of the initial KPI contract slice.

## Acceptance mapping

This design directly covers #729's versioned schema, explicit denominators, complete attempt accounting, pinned runtime identity, required validation accounting, recovery/corruption metrics, regenerated manufacturing reproducibility, deterministic machine/human reporting, and outcome-over-tool-count positioning. #728 supplies live mutation evidence; #730 supplies representative complete attempt history. Neither dependency is duplicated here.
