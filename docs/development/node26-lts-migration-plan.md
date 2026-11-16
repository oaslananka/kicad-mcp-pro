# Node.js 26 LTS migration implementation plan (issue #1643)

**Status:** Proposed — plan only; no runtime migration, release, or deployment is authorized by this document alone.
**Baseline:** `origin/main` at `d64545efa70fcfc541d55ebe6aa2b9c66131cd68`, inspected 2026-11-16. Reconcile with current `main` before executing.
**Goal:** Make Node.js 26 LTS the verified default for this repository's JavaScript/TypeScript development, Cloud production image, CI, and release/packaging paths without silently breaking existing Node 24 consumers or the Python/KiCad product.

**Requirements:** [Issue #1643](https://github.com/oaslananka/kicad-mcp-pro/issues/1643). **Upstream evidence:** [Node.js release schedule](https://github.com/nodejs/Release#release-schedule), [Node 26.13.1 security release](https://nodejs.org/en/blog/release/v26.13.1/), [Node 26 LTS Linux `libatomic` note](https://nodejs.org/en/blog/release/v26.13.0), [Corepack's distribution policy](https://github.com/nodejs/corepack/blob/main/README.md), [official Node Docker images](https://github.com/nodejs/docker-node).

## 1. Decision and user outcome

A fresh contributor can follow the documented bootstrap without a preinstalled Corepack, run the supported checks, build and package the supported MCP/Apps SDK surfaces, and get the same results as the pinned CI toolchain. A Cloud deployment built from an immutable Node 26 image starts and passes its real readiness and connector checks. Existing Node 24 users do not suddenly lose working published tooling merely because the default build runtime advances.

Use a **bounded dual-runtime proof followed by one coherent migration change**. First execute Node 24 and Node 26 comparisons without changing production pins. Only after passing the gates below should the implementation PR update pins, dependency types/locks, CI and release paths together. Do not introduce a repo-wide framework upgrade, provider migration, paid runners, a new mandatory service, or other repositories.

**Acceptance horizons:**
- **Plan PR (now):** approve/merge this document only; it does **not** close #1643.
- **Implementation PR (later):** land the tested, internally consistent Node 26 default and compatibility controls on an exact CI-reviewed head. Prefer **one issue / one implementation PR**; split only if a real blocker makes the diff unsafe to review.
- **Release/production cutover (separate gate):** prove an independently tested immutable Cloud image and publish/deploy only after the implementation is accepted and the rollback decision is explicit. No production action follows merely from merging this plan.

## 2. Verified baseline, assumptions to recheck

| Surface | Observed on 2026-11-16 | Intended treatment |
| --- | --- | --- |
| `.node-version` | `24.22.1` | Node 26.13.1 is the initial candidate; refresh the latest security-patched 26.x before implementation |
| Root `package.json` | `engines.node: >=24.22.1 <25`, `packageManager: pnpm@11.28.6` | Preserve tested Node 24 consumer compatibility while making 26 the default; express both supported majors explicitly if both pass, excluding unsupported Node 25 |
| `scripts/dev-toolchain.env` | Node 24.22.1, checksum-pinned Linux x64/arm64 archives; pinned pnpm | Change version, URLs and **verified official SHA-256** together; never copy an old digest |
| `apps/cloud/package.json` / lock | `engines.node: >=24`, `@types/node: ^24.9.1` | Test Cloud on both majors; align supported range, types, lock and behavior |
| `apps/cloud/Dockerfile` | Node 24 `trixie-slim` with digest in both build and runtime stages | Resolve **multi-platform** Node 26 digest; pin both stages to the verified manifest |
| `.github/workflows/cloud-ci.yml` | Fixed Node 24; PostgreSQL-backed check, production-image build, edge contract test | Add temporary 24/26 evidence; only after acceptance select the production default |
| `.github/workflows/ci.yml` | Ubuntu 24.04, Windows 2025, macOS 15; uses `.node-version` in several jobs | Preserve the existing required check names and full supported-host evidence |
| `.github/workflows/prepare-*.yml`, `publish-*.yml`, `regression-zoo.yml` | Node provisioned from `.node-version` | Audit every package/prepare/publish lane rather than assuming the main CI matrix covers release |
| `integrations/chatgpt-app/apps-sdk/` | Separate npm lockfile; Node 26 type definitions already in manifest | Test under both runtimes; preserve Apps SDK runtime and transport behavior |
| `packages/mcp-npm/`, `packages/protocol-schemas/`, `packages/kicad-fixtures/`, `evals/live/` | Mixed npm/pnpm lockfiles; some `@types/node` packages already at 26 | Verify each maintained surface; do not blindly reinstall or rewrite unrelated locks |
| Root `Dockerfile` | Python/KiCad container, not a Node base image | Check metadata and any JS build coupling, but **do not** migrate Python/KiCad images for this issue |

**Mandatory compatibility fact:** Corepack was bundled through Node 24 but **not** with Node 25+. Several workflows currently execute `corepack enable` / `corepack pnpm`. A preconfigured developer machine passing those commands is not a valid fresh-install proof for Node 26.

**Security baseline:** Node 26.13.1 and Node 24.22.3 were issued on 2026-11-11. The checked-in 24.22.1 is a historical repository pin, not a claim that it is the latest secure fallback. Compare against the checked-in baseline for reproducibility, then use a verified current patched Node 24 for any production rollback. Refresh official releases/security advisories at execution time.

## 3. Non-negotiable invariants

1. No Cloud production deploy, release/tag/npm/PyPI/container publish, DNS/credential change, provider support contact or cross-repo change in the **planning** or compatibility-probe steps.
2. Preserve the local Python MCP server, KiCad read/write permission model, supported Python/KiCad versions, signatures, OIDC/trusted publishing, SBOM/provenance and published package interfaces.
3. Keep Node 24 functional until Node 26 passes the complete gates. Public package `engines` must reflect **actually tested** major versions, not merely the chosen developer default; do not unintentionally admit Node 25.
4. Do not change protected required job names, action SHA pins, permission grants, release identities or path-filter behavior without reconciling the authoritative policy/ruleset.
5. Use official verified release files, SHA-256 checksums and immutable **multi-architecture** OCI digests. Do not use `node:latest`, floating `node:26` for production, or a single-architecture digest disguised as a manifest-list digest.
6. Preserve lockfile determinism: no broad `npm update`, `pnpm update --latest`, unrelated major dependency bump, forced lock regeneration or new mandatory paid runners.
7. Tests and smoke runs use disposable projects/DBs and synthetic credentials; no live KiCad design mutation or unapproved owner Cloud WRITE test.
8. The rollout and rollback gates are distinct from green PR CI. Exact-head evidence remains authoritative.

## 4. Implementation tasks (defer all below until plan review)

Each task uses **RED (contract/assertion that catches old behavior) -> minimal edit -> GREEN (named command and evidence) -> review**. Commit coherent task groups on the implementation branch, not a PR per checkbox. If the main branch changes, reconcile paths before editing.

### Task 1 — Freeze inventory and comparative baseline

**Files to inspect:** `.node-version`, `package.json`, `pnpm-lock.yaml`, `pnpm-workspace.yaml`, `scripts/dev-toolchain.env`, `scripts/dev_environment.py`, `docs/development/reproducible-bootstrap.md`, `compatibility.yaml`, `scripts/check_compatibility_matrix.py`, `apps/cloud/{package.json,package-lock.json,Dockerfile}`, `packages/{mcp-npm,protocol-schemas,kicad-fixtures}/`, `integrations/chatgpt-app/apps-sdk/`, `evals/live/`, and all affected `.github/workflows/`.

- [ ] Search tracked files for Node versions, engines, Corepack calls, pnpm/npm invocations, Node-native/ABI dependencies, executable/shebang assumptions, npm lock versions, Docker bases, docs and setup scripts. Record file:line and whether the surface is required, conditional or historical.
- [ ] Capture immutable `main` SHA, current required checks and action/ruleset names; identify existing issue/PR overlap before modifying code.
- [ ] Under **current checked-in Node 24**, record baseline `node -v`, `npm -v`, `corepack --version`, `corepack pnpm --version` and quick existing checks. Avoid installing anything into the unrelated main checkout.
- [ ] Under a **clean, separately installed** Node 26.13.1 (or a newer officially patched 26.x), record the same commands and the exact missing-Corepack failure. Preserve repro commands and exit codes.
- [ ] Audit `node-gyp`, native `.node` addons, optional platform binaries (including `esbuild`), `libatomic` needs, package-engine constraints and transitive tool compatibility. Label absent/proven findings; do not assert native ABI problems without reproduction.
- [ ] For the initial quick comparison run `npm ci --ignore-scripts --no-audit --no-fund` and `npm run check` in `apps/cloud`, `npm ci` plus `npm run typecheck && npm run build && npm run test:smoke` in `integrations/chatgpt-app/apps-sdk`, and `npm pack --dry-run` plus existing npm wrapper tests where available. Record 24-versus-26 PASS/FAIL/SKIP by runtime and host.

**Evidence / pass:** A file-level inventory, a reproducible red/green comparison and a list of specific blockers; no production pin or engine change. Unavailable native-host runs remain NOT VERIFIED.

### Task 2 — Make the Node 26 toolchain bootstrap reproducible

**Files to modify:** `.node-version`, `scripts/dev-toolchain.env`, `scripts/dev_environment.py` only if needed, `package.json`, `compatibility.yaml`, `scripts/check_compatibility_matrix.py` only where the contract actually changes, `docs/development/reproducible-bootstrap.md`, and relevant existing tests. **Create if needed:** `tests/unit/test_node_runtime_contract.py`.

- [ ] **RED:** Add runtime-contract assertions that detect inconsistent `.node-version`, Node release tarball filenames and digests, root engine range, `compatibility.yaml`, and documentation; run `uv run --all-extras pytest tests/unit/test_node_runtime_contract.py -q`. Include a case that rejects accidentally admitting Node 25.
- [ ] Pin the selected released Node 26 **exact patch version** and official per-architecture tarball SHA-256 (x64/aarch64) after comparing to signed upstream `SHASUMS256.txt`. If the selected version has changed, update all version/digest references as one decision.
- [ ] Choose and document the **published root engine range** based on actual compatibility, e.g. `>=24.22.3 <25 || >=26.13.1 <27` if Node 24 and 26 both pass. Do not drop a published supported major solely to match CI default; reconcile `compatibility.yaml` and its validator.
- [ ] Confirm clean Windows, Linux and macOS tooling can select the pinned version without relying on ambient global state. Verify Linux x64/arm64 archive execution and `libatomic` resolution where relevant.
- [ ] **GREEN:** Run the targeted runtime-contract test, `corepack pnpm run compat:check` once package-manager bootstrap from Task 3 exists, and the repository's reproducible-bootstrap validation/doctor. Record checksum/engine checks explicitly.

**Evidence / pass:** One immutable Node 26 selection across bootstrap, development docs, supported engines and compatibility validation. A clean-machine setup works without preinstalled tools beyond documented prerequisites.

### Task 3 — Repair Corepack/pnpm for Node 26 fresh runners

**Files:** `.github/workflows/ci.yml`, affected prepare/publish/regression workflows, `scripts/dev-toolchain.env` or bootstrap scripts only if needed, `package.json`, and policy tests; keep `pnpm@11.28.6` unless separately justified.

- [ ] **RED:** Add/extend a workflow regression in the existing GitHub Actions policy test suite (or a focused new `tests/unit/test_node26_workflow_bootstrap.py`) that fails whenever a Node 26 job executes `corepack enable`/`corepack pnpm` without first provisioning a compatible pinned Corepack/pnpm. Verify it fails on the pre-migration pattern.
- [ ] Select the **smallest maintainable** fix: install a verified, exact Corepack version (initial candidate 0.36.0, checked for Node 26) before existing `corepack` commands, **or** replace those invocations with a pinned direct pnpm setup if evidence shows a better smaller diff. Do not introduce conflicting package-manager installations. Choose one method for the affected workflows.
- [ ] Cover each `actions/setup-node` use, including `ci.yml`, `cloud-ci.yml` where applicable, release preparation, npm/protocol/MCPB publication, and `regression-zoo.yml`; preserve full action SHAs and existing permissions. Confirm only paths that actually invoke Corepack receive the new bootstrap.
- [ ] Verify root `packageManager`, `pnpm-lock.yaml`, npm subproject locks and the shell/PowerShell behavior on Ubuntu 24.04, Windows 2025 and macOS 15. Prove the setup with a clean environment/PATH—not only a developer's Node 26 installation that already has Corepack globally.
- [ ] **GREEN:** Run `corepack pnpm install --frozen-lockfile`, `corepack pnpm run workflows:policy`, `corepack pnpm run workflows:lint` and `corepack pnpm run workflows:security` with the new documented bootstrap in place. Confirm the clean Node 26 test and the retained Node 24 test.

**Evidence / pass:** Both majors can install the locked workspace on clean machines, no broken release lane, no new workflow permission, required-check or security bypass.

### Task 4 — Validate and align Cloud and Apps SDK runtime behavior

**Files:** `apps/cloud/{package.json,package-lock.json,Dockerfile}`, `apps/cloud/test/`, `integrations/chatgpt-app/apps-sdk/{package.json,package-lock.json}` only as required, and relevant Cloud tests.

- [ ] **RED:** In existing Cloud tests, assert deterministic startup, health/revision, OAuth/MCP handshake, signed device/connector session lifecycle, PostgreSQL-backed operations, cancellation/timeouts, graceful shutdown and log/error contracts. Reproduce any difference under Node 26 without changing production behavior. Add minimal targeted regressions only for observed failures.
- [ ] Run **Node 24 and Node 26** separately against `apps/cloud`: `npm ci --ignore-scripts --no-audit --no-fund`; `npm run typecheck`; `npm run build`; `npm test`; `node --test scripts/test-cloudflare-edge.mjs`. Use an isolated disposable PostgreSQL fixture as the current Cloud CI does; never connect tests to production.
- [ ] Align Cloud `@types/node` (currently `^24.9.1`) and lock only when Node 26 typecheck requires it, then verify typecheck/build/tests on both runtimes. Audit `better-auth`, `@modelcontextprotocol/*`, `tsx`, `ws`, `pg`, `esbuild` and platform-specific/native optional packages for real failure evidence.
- [ ] Run the Apps SDK `npm ci && npm run typecheck && npm run build && npm run test:smoke` under both majors. Confirm package/transport/handshake semantics, not merely TypeScript compilation.
- [ ] **GREEN:** Evidence table shows both majors' typecheck, build, tests, Cloud health, app handshake and clean shutdown, with reproducible fixes for each initially failing scenario. Non-testable external integrations remain NOT VERIFIED and block claims of live acceptance.

**Evidence / pass:** Same user-facing Cloud/MCP functionality with no silent auth, project-permission, connector or data contract regression.

### Task 5 — Validate npm/protocol/release and supported OS paths

**Files:** `packages/mcp-npm/`, `packages/protocol-schemas/`, `packages/kicad-fixtures/`, `evals/live/`, `packaging/mcpb/`, corresponding lockfiles and `.github/workflows/prepare-*.yml` / `publish-*.yml` if required.

- [ ] **RED:** Identify reproducible packaging, CLI lifecycle and manifest validation failures under Node 26. Add focused tests to the owning existing suite before editing production packaging behavior.
- [ ] On **Ubuntu 24.04, Windows 2025 and macOS 15**, run the existing `mcp-server` and `mcp-npm` CI jobs under Node 26 (and compare retained Node 24 behavior). Preserve explicit SKIP for native KiCad/GUI functionality not actually runnable on a given CI host.
- [ ] On supported hosts run `npm ci`, `npm pack --dry-run`, `npm run build` and the existing package tests in `packages/mcp-npm`; `corepack pnpm --filter @oaslananka/kicad-protocol-schemas run check` only if the actual scripts expose `check`, otherwise use the existing exact `format:check`, `lint`, `typecheck`, `test`, `build` commands; execute fixture and MCPB checks using their own checked-in scripts.
- [ ] Validate agent CLI/MCP lifecycle, stdio startup and shutdown, HTTP mode smoke, npm wrapper dry-run, protocol schemas, Apps SDK and MCPB manifest/packaging against Node 26. Record artifact inspection and OS/arch where the behavior is real; avoid claims from mocks as real KiCad UI evidence.
- [ ] Independently inspect every release preparation and publish workflow for source SHA, permissions, exact-node setup, artifact identity, OIDC/provenance/SBOM and package-manager setup. Do not trigger an actual publish while verifying.
- [ ] **GREEN:** Existing targeted per-package tests and `corepack pnpm run release:dry-run` / `corepack pnpm run mcpb:validate` where appropriate, plus CI OS-matrix evidence and reviewed dry-run artifact contents.

**Evidence / pass:** Supported packaged developer/user flows work and no actual release occurs in this work package.

### Task 6 — Node 26 Cloud OCI multi-architecture and deployment preflight

**Files:** `apps/cloud/Dockerfile`, `.github/workflows/cloud-ci.yml`, Cloud deploy/preflight workflows only if they directly pin/assume Node, and existing image/health policy checks.

- [ ] **RED:** Add/extend an existing Docker metadata/runtime policy test to reject a mismatched build/runtime Node major, unpinned image, non-manifest digest, missing runtime healthcheck or leaked build-time secrets. Reproduce the old/invalid image acceptance before fixing.
- [ ] Resolve a published official `node:26-trixie-slim` (or proven equivalent) **manifest-list digest** that includes both `linux/amd64` and `linux/arm64`. Validate via `docker buildx imagetools inspect`, not a single host pull. Use identical immutable digest in both stages.
- [ ] On representative amd64 and arm64 environments, build the Cloud image; verify `node -v`, `ldd`/runtime `libatomic` where relevant, production-only dependencies, non-root operation and the existing `HEALTHCHECK`. Do not publish the probe image or bake secrets into layers.
- [ ] Run synthetic same-contract HTTP/Cloud health, MCP connector, PostgreSQL migration **dry-run on a disposable DB**, authentication/session smoke, graceful stop and restart. Compare against Node 24 image with equivalent source SHA.
- [ ] If using an isolated **nonproduction** deployment acceptance environment, use the repository's current preflight only, keep it bounded and free-tier compatible, and verify application revision/artifact digest and recovery behavior. Do not introduce mandatory staging infrastructure or require a second provider account for #1643.
- [ ] **GREEN:** Exact image digest, architecture manifests, build logs, healthcheck results, artifact/source linkage, startup/shutdown/DB tests and signed Cloud preflight are recorded. If arm64/runtime or network/DB checks cannot run, mark NOT VERIFIED and hold production.

**Evidence / pass:** Node 26 image is deployable and behaviorally equivalent, rather than only syntactically buildable.

### Task 7 — Authoritative CI, security and package compatibility gate

**Files:** `.github/workflows/ci.yml`, `.github/workflows/cloud-ci.yml`, `.github/actions-policy.json` and policy tests only when genuinely needed. Preserve the existing `Required PR Gate` context.

- [ ] First run a **bounded proof matrix**: Ubuntu Node 24 + Node 26 Cloud with PostgreSQL, supported OS Node 24/26 npm + server smoke and package tests, and Node 26 Apps SDK. Avoid doubling every unrelated Python test or adding paid/self-hosted runners.
- [ ] After proof passes, change the default `.node-version`/Cloud image and existing CI path consistently. Keep only the necessary Node 24 compatibility lane if public packages still claim that support; minimize redundant CI resource consumption.
- [ ] Run the repository's workflow policy/lint/security and compatibility checks before pushing. Do not weaken action SHA pins, permissions, required contexts, path filtering, provenance or protected environments.
- [ ] Open **one implementation PR** linked to #1643 (do not use a closing keyword until it actually completes the issue). Resolve all actionable SonarCloud new-code smells, Codacy, CodeQL, dependency/security alerts and required checks on the **exact final head**. Keep analyzer availability separate from a code failure; do not invent a green check.
- [ ] Independently inspect PR artifacts and per-host logs: Cloud build/test, MCP/Apps SDK tests, publish dry-runs, OCI manifests, Node versions, security/quality gate and release provenance preflight. Confirm the current protected main rules, review requirements and mergeability before eligible merge.

**Evidence / pass:** The exact reviewed implementation commit has no failing/pending required gate, no introduced Sonar issues, validated OS compatibility and reproducible artifacts. Missing evidence blocks merge; no owner/admin bypass.

### Task 8 — Controlled production readiness, rollback, docs and closure

**Files:** `docs/development/reproducible-bootstrap.md`, relevant install/release/Cloud operating docs and, only if necessary, release workflow references; release/production records live in their existing evidence system, not new infrastructure.

- [ ] Reconcile actual published-package `engines`, `compatibility.yaml`, bootstrap commands, README/install guidance, release notes and Node 24 fallback requirements with the final tested behavior.
- [ ] Preserve the last known good **security-patched** Node 24 Cloud image/source digest and configuration as a recoverable candidate; verify rollback procedure in the existing deployment model without mutating customer data or introducing backups not required by actual risk.
- [ ] Record pre-cutover Node 26 artifact/source hash, image digest, baseline readiness/latency/error metrics, DB compatibility and deployment health target; do not silently switch production.
- [ ] Under the normal release/deployment authority, execute the existing production gate only after a separately verified signed preflight and readiness decision. Compare health, connector sessions, auth, MCP calls and tool logs after cutover. If regressions appear, use the documented Node 24 **known-good immutable image** rollback (database forward/backward compatibility must be checked before rollback), stop and preserve incident evidence.
- [ ] Verify post-cutover real end-to-end representative user operations and published npm/MCPB/package acquisition if release is part of the accepted milestone. Close #1643 only when these required outcomes and provenance evidence exist; otherwise keep it open with exact blockers.

**Evidence / pass:** Reproducible developer setup, verified supported packaging, production health and explicit safe recovery—not just green CI or successful image build.

## 5. Required acceptance matrix

| Gate | Node 24 | Node 26 | Source of evidence |
| --- | --- | --- | --- |
| Fresh Node and package-manager bootstrap | Required comparison | **Required** | Verified binary/checksums; clean PATH, `node/npm/corepack/pnpm` versions |
| Root runtime engine, schema and metadata | Required if publicly supported | **Required** | `compat:check`, runtime-contract tests, `metadata:check` |
| Cloud TS typecheck, build, tests, Postgres | Required comparison | **Required** | `apps/cloud npm run check` and CI DB fixture |
| Cloud HTTP, OAuth/MCP, connector lifecycle, edge | Required comparison | **Required** | Focused integration tests + Cloudflare edge contract |
| Official Cloud container amd64/arm64 + health | Current-good baseline | **Required** | digest manifests, builds, `HEALTHCHECK`/revision and stop/restart |
| Apps SDK smoke + tool protocol | Required comparison | **Required** | exact npm CI/install/typecheck/build/smoke tests |
| npm wrapper and MCPB/protocol packaging | Required if supported | **Required** | pack/dry-run and artifact inspection |
| Linux / Windows / macOS supported-host paths | Required comparison | **Required** | exact CI runner matrix evidence |
| SonarCloud, Codacy, CodeQL and security | Required PR policy | **Required** | exact final-head required-check statuses |
| Production preflight / release / rollback | Prior known-good | **Required before cutover** | immutable artifact, independent smoke, rollback record |

A test that could not run is **NOT VERIFIED**, never a pass. A platform not supported by the existing product should not silently become a mandatory target because it appears in this table.

## 6. Failure and stop rules

**Stop before modifying runtime defaults** if a required core dependency has no Node 26 support, package manager cannot be bootstrapped on a fresh supported host, protected required check behavior would change, the official ARM64 image or `libatomic` is unavailable, or the Node 24 published compatibility promise cannot be honored or intentionally revised with a documented release decision.

**Stop before merging** if any required check, SonarCloud new-code gate, CodeQL, dependency/security gate, review or exact-head evidence is pending, failing, stale or unavailable. Fix within the issue where viable; otherwise document a minimal reproducible blocker and maintain Node 24.

**Stop before production** if independent OCI/artifact verification, signed preflight, DB rollback safety or real connector/auth/MCP user-journey smoke is missing, or if the Cloud/release owner approval boundary has not been met. No forced promotion, hidden bypass, support ticket or paid-service workaround.

**Rollback:** Redeploy the previously verified immutable and security-patched Node 24 image at the last compatible source/config state; preserve DB state/compatibility and public package identity, and inspect post-rollback health and sessions. Revert only the Node 26 migration commit(s) if code-level rollback is needed. Never repoint immutable release tags or overwrite published artifacts.

## 7. Resource, maintenance and change-scope budget

- One coherent implementation branch/PR, not repetitive micro-PRs. Use the existing supported hosted runners and cached dependency installs; keep the temporary Node 24+26 matrix scoped and remove redundant probes after final proof.
- **No new permanent service, account, paid runner, additional secret, daemon, Docker cache-retention policy or fleet-wide migration.** Cross-repository migrations remain out of scope.
- Prefer one pinned package-manager bootstrap mechanism over parallel Corepack/pnpm installations. Keep a single root version authority where feasible and the existing necessary SHA-pinned platform downloads.
- Treat feature/Cloud WRITE, UX redesign, Renovate pilot #1449, KiCad versions, license changes, Python Docker image and new platform support as separate work.
- Implementation review must enumerate changes to: services/processes (none), dependency majors (Node 26 only), configuration surfaces (pin/engines/bootstrap), workflows (bounded compatibility proof), secrets/privileges (none), state systems (none), manual actions (clean setup/rollback documented).
- **Stop rule:** Once the #1643 accepted runtime and user-path gates pass and evidence is recorded, close the issue; do not turn optional CI modernization or unrelated app refactoring into completion conditions.

## 8. Execution handoff

1. Review and approve this plan independently of implementation. The **plan PR is documentation-only**; it must not auto-close issue #1643.
2. Start the implementation later from a **fresh** current `origin/main` in an isolated task worktree. Confirm actual issue/PR state, scripts and official Node security release before editing; do not reuse the plan worktree or touch unrelated dirty checkouts.
3. Implement Tasks 1–8 in order with focused failing assertions/tests, minimal fixes, passing commands, source review and evidence capture per gate. Do not claim unrun user/device acceptance.
4. Link the implementation PR, CI artifacts and final cutover/rollback results back to #1643; close only upon verified acceptance.

**Explicitly excluded from this plan PR:** writing implementation code, installing/upgrading toolchains, running a production build or deployment, publishing packages, modifying root runtime pins and merging the migration.
