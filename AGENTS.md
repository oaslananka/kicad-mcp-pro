# Repository Agent Router

Use this file as a router, not as a duplicate engineering manual. Follow the canonical sources below and keep changes evidence-driven.

## Start here
- Architecture and dependency direction: `ARCHITECTURE.md`
- Contribution and review contract: `CONTRIBUTING.md`
- Security boundaries and reporting: `SECURITY.md`
- Common local commands: `Taskfile.yml`
- Agent profile/surface policy: `docs/agents/progressive-disclosure.md`
- Tool-selection workflow: `docs/tools-agent-workflow.md`
- Generated tool reference: `docs/tools-reference.generated.md`
- KiCad compatibility contract: `compatibility.yaml`

## Working rules
1. Inspect the relevant architecture/service/adapter boundary before editing.
2. Prefer existing domain services and adapter seams; do not bypass them with ad-hoc KiCad file rewriting.
3. Add or change tests before production behaviour changes, then run the smallest relevant suite and the repository gates.
4. Treat generated files as outputs. Use their documented generator/check command instead of hand-editing them.
5. Preserve explicit GitHub Actions permissions, SHA-pinned Actions, path guards, and human-only manufacturing controls.
6. Do not claim native KiCad, manufacturing, or live-model success without the repository's required evidence.

## Validation
Use `task verify` for the normal local quality gate and `task ci` for the local CI equivalent when the pinned toolchain is available. For change-scoped validation, `scripts/hook_pre_push.py` maps touched files to the required checks.

For agent/profile changes also run `pnpm run profiles:check`, `pnpm run toolsets:check`, and `pnpm run tool-contracts:check`. For workflow changes run `pnpm run workflows:policy`, `pnpm run workflows:lint`, and `pnpm run workflows:security`.

## Scope-specific instructions
More specific `AGENTS.md` files may exist under integrations. When working in such a subtree, follow the nearest file in addition to this root router. Repository-level security, architecture, and release constraints still apply.