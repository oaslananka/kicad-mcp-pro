# Issue #731 PCM and Guided Onboarding Implementation Plan

> **Workflow:** execute task-by-task with RED -> GREEN -> refactor. Do not write production behavior before observing the corresponding test fail.

**Goal:** Close #731 with a deterministic KiCad PCM package, fail-closed backend compatibility/status, explicit reversible guided client onboarding, release provenance, and real KiCad evidence.

**Spec:** `docs/superpowers/specs/2026-08-28-issue-731-pcm-onboarding-design.md`

## Global constraints

- Base is exact `main@cc91138e2834204d5eb0e9c285cf4ab07cd209ae`.
- No new runtime dependency unless a standard-library/current-dependency solution is impossible.
- Current plugin is SWIG ActionPlugin; package metadata must say `runtime: swig`.
- No public network exposure or secret logging.
- Preview paths must have zero external side effects.
- Existing client config must be merged narrowly, backed up, atomically written, and restorable.
- Existing public MCP tools/contracts remain unchanged.
- Do not close #731 from package creation alone; physical install/update/uninstall/rollback and MCP lifecycle evidence are required.

### Task 1: Guard existing setup mutations

**Tests first:** `tests/unit/test_setup.py`, server CLI tests.

- [ ] RED: Claude Code preview does not invoke native `claude mcp add`.
- [ ] RED: `init` without `--write` calls setup with `write=False`; explicit `--write` uses `True`.
- [ ] GREEN: gate Claude native install behind `write=True`; default `init` to preview.
- [ ] Verify focused tests + Ruff/mypy.

### Task 2: Make config writes merge-safe and reversible

**Tests first:** `tests/unit/test_setup.py`, `tests/unit/test_cli_init.py`.

- [ ] RED: JSON write preserves unrelated top-level settings and another MCP server.
- [ ] RED: Codex TOML write preserves unrelated tables/comments/server entries.
- [ ] RED: invalid existing config leaves original byte-identical.
- [ ] RED: atomic replace failure leaves original byte-identical and no temp residue.
- [ ] RED: backup can restore the pre-write file.
- [ ] GREEN: implement in-memory merge, validation, backup, atomic replace.
- [ ] Reuse shared transaction semantics from interactive wizard where practical.
- [ ] Verify Claude Code, Codex, Cursor guided paths.

### Task 3: Define and build the PCM package

**Tests first:** create `tests/unit/test_kicad_pcm_packaging.py`.

- [ ] RED: builder module/CLI missing.
- [ ] RED: package metadata contract v2, unique identifier, root-version sync, runtime `swig`, no internal `download_*`.
- [ ] RED: archive has exact reviewed paths and rejects symlink/path traversal/unexpected content.
- [ ] RED: two builds are byte-identical and checksum evidence matches.
- [ ] GREEN: add `packaging/kicad-pcm/` metadata source and deterministic standard-library builder.
- [ ] Verify against official schema semantics without CI network dependency.

### Task 4: Add companion compatibility and health

**Tests first:** `tests/unit/test_companion_context.py` and package-copy parity test.

- [ ] RED: compatibility contract accepts same release line and rejects malformed/out-of-range backend.
- [ ] RED: loopback health GET parses ready/unreachable/unhealthy/incompatible states.
- [ ] RED: non-loopback health URL is rejected.
- [ ] RED: context push is not attempted when health/compatibility fails.
- [ ] GREEN: extend canonical `src/kicad_mcp/companion/context.py` and keep vendored package copy byte-identical.
- [ ] GREEN: ActionPlugin presents actionable status/recovery text.

### Task 5: Release provenance and CI contract

**Tests first:** release/workflow policy tests.

- [ ] RED: release metadata validation expects PCM builder/package inputs.
- [ ] RED: workflow contract requires tag/source/version verification, checksum, attestation, upload, published-digest verification.
- [ ] GREEN: add `publish-kicad-pcm.yml` with least privileges and existing pinned actions.
- [ ] GREEN: add PR package validation to appropriate existing CI/release validation path without publishing.
- [ ] Verify actionlint/yaml parser/zizmor policy.

### Task 6: Documentation and objective distribution matrix

- [ ] Update companion install docs with PCM `Install from File`, update/uninstall/rollback and uvx fallback.
- [ ] Add explicit SWIG->modern KiCad plugin API/IPC readiness section; no unsupported future-version claim.
- [ ] Update distribution matrix only with evidence-backed statuses/links.
- [ ] Document client preview/write/backup/restore behavior and conflicts.
- [ ] Add official repository submission steps but do not claim listing before it exists.

### Task 7: Local verification

- [ ] Focused setup/PCM/companion/release tests.
- [ ] Full relevant unit/integration suite.
- [ ] Ruff lint + format check.
- [ ] Mypy changed modules.
- [ ] Bandit/security policy.
- [ ] `uv build`.
- [ ] release metadata/preflight/workflow policy/actionlint/zizmor.
- [ ] `git diff --check` and secret/temp/generated artifact scan.

### Task 8: Physical KiCad 10.0.5 evidence

- [ ] Snapshot Windows KiCad/plugin/client config state.
- [ ] Transfer exact built PCM ZIP by digest-verified channel.
- [ ] Install through KiCad PCM `Install from File`; restart/discovery proof.
- [ ] Verify unreachable then healthy compatible backend status.
- [ ] Run MCP initialize/list-tools and one read-only fixture-safe call.
- [ ] Exercise compatible update/reinstall.
- [ ] Exercise incompatible backend fixture and prove fail-closed behavior.
- [ ] Uninstall PCM package and prove unrelated client config retained.
- [ ] Roll back/reinstall prior trusted package.
- [ ] Restore pre-test host state.
- [ ] Commit only sanitized evidence, never local config/token/private path.

### Task 9: PR and merge verification

- [ ] Review entire diff against issue acceptance criteria.
- [ ] Push exact verified tree; open one focused PR `Closes #731`, `Refs #412` only if physical evidence is complete.
- [ ] Resolve human/bot/Sonar/CodeQL/Codecov/Dependabot/security findings at root cause.
- [ ] Require exact-head CI, Required PR Gate, Codecov patch >= target, Sonar 0 unresolved new issues/hotspots, CodeQL and security gates.
- [ ] Squash merge only when all required checks are terminal and clean.
- [ ] Verify exact merge SHA post-merge CI/CD/security.
- [ ] Clean only owned clean worktree/temp artifacts; preserve unrelated dirty worktrees.
