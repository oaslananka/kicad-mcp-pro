---
name: code-review
description: >-
  Use this skill for GitHub Copilot pull request and code reviews in
  oaslananka/kicad-mcp-pro. Review Python MCP server changes, KiCad adapter and
  tool-contract changes, tests, npm/package wrappers, Tauri/Rust desktop code,
  GitHub Actions, security controls, documentation, generated metadata, and
  compatibility/release surfaces. Use it whenever reviewing a PR or diff in this
  repository, especially changes under src/, tests/, packages/, src-tauri/,
  .github/workflows/, or public MCP metadata/configuration.
license: MIT
compatibility: >-
  GitHub Copilot code review for oaslananka/kicad-mcp-pro. Use GitHub MCP context
  when available. KiCad MCP Pro tools are optional and must remain read-only
  during review.
---

# KiCad MCP Pro Code Review

Review pull requests for **correctness, security, contract stability, compatibility,
test coverage, and release safety**. Prefer a small number of high-confidence,
actionable findings over broad style feedback.

KiCad MCP Pro is a production MCP server that drives real KiCad projects. Treat
unsafe mutations, incorrect tool contracts, path/subprocess mistakes, protocol
regressions, and misleading engineering verdicts as high-risk.

## Review stance

- Review the changed code and the behavior introduced by the change.
- Comment on unchanged code only when the PR newly makes an existing defect reachable
  or materially increases its impact.
- Do not invent failures, tool behavior, KiCad behavior, CI results, or browser evidence.
- Distinguish a demonstrated defect from a possible improvement.
- Prefer correctness and user-impact findings over formatting or naming nits already
  enforced by repository tooling.
- Do not require a broad refactor when a focused fix addresses the defect.
- If no actionable defect is found, do not manufacture a comment.

## 1. Gather review context first

Before writing findings:

1. Read the PR title, description, changed files, and diff.
2. Use GitHub MCP context when available to inspect:
   - linked issues or incidents referenced by the PR;
   - review-relevant PR metadata;
   - changed-file scope;
   - workflow/check status;
   - failed job logs when a failure is relevant to the changed code.
3. Consult repository policy and architecture when needed:
   - `ARCHITECTURE.md`
   - `CONTRIBUTING.md`
   - `SECURITY.md`
   - `docs/development/coding-standards.md`
   - `docs/development/testing-policy.md`
   - `docs/security/threat-model.md`
   - `.github/PULL_REQUEST_TEMPLATE.md`
4. Treat the PR head branch as the source of repository instructions and skill content.
5. Use existing CI evidence when it is from the reviewed head commit and covers the
   exact concern. Do not claim a check passed if you did not observe it.

## 2. MCP context policy

### GitHub MCP

Use GitHub MCP tools when they provide concrete review evidence, especially for linked
issues, PR intent, CI/check state, or failed workflow details. Do not browse unrelated
repository history just to increase context.

### Playwright MCP

When changes affect the dashboard or desktop/web UI and the application can be run in
the review environment, use Playwright MCP for focused user-visible verification.

Relevant areas include:

- `src/kicad_mcp/web/`
- dashboard routes/templates/assets
- `src-tauri/frontend/`
- desktop flows that depend on the local dashboard

Do not report a browser regression unless you have code evidence or observed behavior.
Lack of a runnable browser environment is not itself a defect.

### KiCad MCP Pro MCP server

If a KiCad MCP Pro server is configured in repository Copilot settings and the PR
changes KiCad-facing behavior, `.kicad_*` fixtures, validation logic, or project
inspection behavior, use it only when it adds concrete evidence.

Prefer the bounded read-only/default review surface and inspection/validation tools such
as:

- `kicad_get_project_info`
- `kicad_get_version`
- `project_quality_gate`
- `schematic_quality_gate`
- `pcb_quality_gate`
- `run_erc`
- `run_drc`
- `pcb_get_board_summary`
- `sch_get_symbols`

During code review, **do not invoke write, destructive, manufacturing, export, or
mutation tools**. Never change a user's board or schematic as part of review.

## 3. Architecture review

KiCad MCP Pro has a five-layer design. Preserve the boundaries described in
`ARCHITECTURE.md`.

### KiCad adapter seam

Flag changes that bypass the KiCad adapter seam or spread KiCad-version fragility into
pure domain code.

KiCad-facing behavior belongs behind the established seams, including:

- `src/kicad_mcp/kicad/`
- `src/kicad_mcp/connection.py`
- `src/kicad_mcp/ipc/`
- `src/kicad_mcp/discovery.py`
- thin tool adapters that delegate to stable domain/services

Pure deterministic logic should remain testable without KiCad and should not import
KiCad-specific runtime internals unnecessarily.

### Composition roots

For tool registration and validation composition:

- keep `register()` and `_register_*` helpers focused on wiring;
- do not add new business logic directly to large registration/composition roots;
- preserve the repository's architecture-boundary checks;
- prefer typed domain services plus thin MCP adapters.

### Real-state rule

The server must not invent board, schematic, DRC/ERC, manufacturing, or KiCad state.
Behavior should be based on real KiCad engines, real project files, or explicitly
documented deterministic/heuristic calculations.

If a calculation is approximate, heuristic, partial, or first-pass, ensure the API,
docstring, docs, and verdict communicate that limitation. Do not allow code or docs to
present first-order estimates as formal engineering sign-off.

## 4. MCP tool and public contract review

Treat the MCP surface as a public compatibility contract.

When a tool is added, removed, renamed, reclassified, or its schema/behavior changes,
check the relevant contract surfaces:

- implementation in the appropriate domain/tool module;
- `TOOL_CATEGORIES` and profile membership in `src/kicad_mcp/tools/router.py`;
- experimental classification when applicable;
- tool annotations/metadata in `src/kicad_mcp/tools/metadata.py`;
- read-only/destructive/headless/requires-KiCad semantics;
- operating-mode restrictions;
- generated tool documentation;
- tool-surface snapshots and contract tests;
- profile/toolset/adapter/compatibility matrices when affected.

Flag any change that silently exposes mutating or destructive behavior through a
read-only/default review surface.

Preserve stable error behavior. Agent-visible failures should use the repository's
typed error model and stable error codes rather than leaking raw implementation
exceptions or ambiguous strings.

For transport/protocol changes, review:

- MCP initialization and protocol compatibility;
- `stdio` and Streamable HTTP behavior;
- session/header behavior;
- discovery endpoints;
- backward-compatibility implications;
- explicit handling of unsupported client/KiCad capabilities.

## 5. Security review

Security findings take priority over style or convenience.

### Subprocess and command execution

Flag:

- `shell=True`;
- `os.system`, `os.popen`, or equivalent shell execution in production paths;
- string-built shell commands containing user-controlled data;
- untrusted values interpreted as CLI flags unintentionally;
- missing error handling around subprocess boundaries.

KiCad CLI calls should use discrete argv elements with `shell=False`.

### Filesystem and path safety

Treat MCP/tool arguments, project paths, filenames, output paths, and imported artifact
names as attacker-controlled.

Check for:

- canonicalization before access;
- confinement to the project/workspace root;
- `..` traversal;
- absolute-path escapes;
- symlink escapes;
- Windows drive/UNC path edge cases;
- unsafe file extensions where an allowlist is expected;
- TOCTOU risks before destructive mutations.

Security-sensitive filesystem/subprocess changes need negative tests for hostile inputs
and failure paths.

### HTTP and local service boundaries

For Streamable HTTP, dashboard, bridge, or auth changes, verify the intended local and
authentication boundaries are preserved, including:

- bearer-token enforcement when configured;
- origin validation;
- CORS allowlists;
- localhost-only assumptions where required;
- stateful/stateless session policy;
- no silent re-enabling of deprecated/legacy exposure.

### Secrets and private design data

Flag code, tests, logs, fixtures, screenshots, or workflow artifacts that can expose:

- credentials or API tokens;
- private board/schematic data;
- generated Gerbers/netlists/manufacturing files;
- customer-specific paths or logs.

### Destructive behavior

Any destructive or KiCad-mutating operation must be explicit, policy-gated,
test-covered, and documented. A convenience path must not bypass operating-mode or
human-approval boundaries.

### GitHub Actions

For `.github/workflows/**`, check:

- third-party actions are pinned to full commit SHAs;
- default permissions remain least-privilege;
- write permissions are scoped to the job that needs them;
- untrusted GitHub expressions are passed through `env:` before shell use;
- PR-controlled values do not reach shell commands unsafely;
- release credentials use GitHub/OIDC/trusted-publishing patterns where applicable;
- artifact, checksum, SBOM, signing, and attestation steps are not weakened silently.

If a public PR introduces a sensitive vulnerability, explain the fix-relevant risk
without publishing weaponized exploit details, secrets, or private data. Follow
`SECURITY.md` for disclosure handling.

## 6. Testing and regression review

Behavior changes require evidence at the narrowest useful layer.

Check the repository's testing policy:

- pure Python logic -> unit tests and type checks;
- KiCad artifact parsing -> representative fixture tests;
- MCP tool contract changes -> metadata/generated-doc checks and surface/contract tests;
- filesystem/subprocess changes -> hostile-input and failure-mode tests;
- bug fixes -> regression test when reproducible;
- workflow/release changes -> workflow-security and dry-run/metadata checks;
- docs-only changes -> docs/link-sensitive review rather than unrelated runtime tests.

For tests that create or mutate Git repositories, verify test-owned temporary
directories and isolated Git configuration are used so contributor/system hooks and
configuration cannot leak into fixtures.

Do not demand live KiCad execution for logic that is deliberately unit-testable without
KiCad. Conversely, do not accept mocked-only evidence when the change specifically
depends on a live KiCad integration contract and the repository has a dedicated
KiCad-enabled CI path for it.

## 7. Generated files and canonical metadata

Identify the source of truth before commenting on generated surfaces.

Important repository rules include:

- `pyproject.toml` is a canonical package metadata/version source;
- `compatibility.yaml` is a canonical KiCad/MCP support-policy source;
- `server.json` and several public surfaces are generated/synchronized;
- generated tool docs, parity/toolset/profile/adapter outputs should be regenerated
  from their canonical inputs rather than hand-edited.

Flag generated drift, but do not ask contributors to hand-edit generated files when the
repository generator is authoritative.

## 8. Packaging, release, and desktop review

For Python/npm/container/release changes, check:

- package metadata remains internally consistent;
- npm wrapper behavior/version policy does not drift from the Python package contract;
- lockfile changes match dependency changes;
- release checks still run before publishing;
- trusted publishing / provenance controls are not bypassed;
- public compatibility claims match `compatibility.yaml`;
- generated registry/container metadata stays synchronized.

For Tauri/desktop changes, also review:

- backend/frontend version compatibility and startup handshake;
- local server lifecycle and port/bind assumptions;
- permission/capability changes;
- error handling when the backend cannot start or does not match;
- user-visible flows with web/GUI tests when practical.

## 9. Focused validation commands

Prefer the smallest relevant validation set. Use CI evidence instead of re-running a
check only when the reviewed head commit already ran the same check successfully.

### Baseline Python/server changes

```bash
corepack pnpm run format:check
corepack pnpm run lint
corepack pnpm run typecheck
corepack pnpm run test:unit
```

### Public MCP/tool/metadata/compatibility changes

```bash
corepack pnpm run metadata:check
corepack pnpm run docs:tools:check
corepack pnpm run tool-contracts:check
corepack pnpm run architecture:check
corepack pnpm run profiles:check
corepack pnpm run adapter-matrix:check
corepack pnpm run compat:check
```

### Workflow/security changes

```bash
corepack pnpm run workflows:lint
corepack pnpm run workflows:security
```

### Package/release changes

```bash
corepack pnpm run package:check
corepack pnpm run release:dry-run
```

### Dashboard changes

```bash
task test:web
```

Use Playwright-backed tests when the environment supports them and the change is
user-visible.

### Cross-boundary changes

Use `task verify` for the repository's local quality gate. Use `task ci` only when the
change crosses enough package, compatibility, workflow, security, or release boundaries
to justify the full local CI equivalent.

Do not make "run the entire suite" the only review recommendation when a specific,
smaller regression test would prove the issue.

## 10. Finding quality bar

Write a review finding only when all of the following are true:

1. The issue is introduced or made materially worse by the PR.
2. There is a concrete failure mode, security risk, compatibility break, or maintenance
   hazard.
3. The affected scenario is realistic for this repository.
4. The comment can point to the smallest relevant changed range.
5. The author can act on the feedback.

For each finding:

- state the problem first;
- explain the trigger/scenario;
- explain the impact;
- cite concrete code/CI/MCP evidence when available;
- give a focused fix direction;
- mention the missing test only when a test would materially prevent regression.

Use severity proportional to impact:

- **Blocker**: vulnerability, data loss, unsafe mutation, release/supply-chain break,
  major public-contract break, or a deterministic build/runtime failure.
- **Major**: likely user-facing correctness, compatibility, protocol, or regression risk.
- **Minor**: concrete maintainability or test gap with plausible future impact.
- Omit pure style nits and speculative suggestions.

Avoid duplicate comments for the same root cause. Prefer one precise finding that
covers the causal defect.

## 11. Do not flag these by default

Do not create review comments solely because:

- code could be written in a different style;
- a formatter/linter would already catch it;
- generated output changed together with its canonical source;
- a documentation-only change lacks unrelated runtime tests;
- a full `task ci` run is absent but the relevant focused checks passed;
- the code uses an intentional project pattern documented in `ARCHITECTURE.md`;
- a theoretical edge case has no realistic path from repository inputs.

The goal is a review that maintainers can trust: **few comments, high confidence,
clear impact, and repository-specific evidence.**
