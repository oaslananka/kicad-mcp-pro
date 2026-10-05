# Agent Runtime Integration Instructions

These instructions apply to `integrations/**` and supplement the repository root `AGENTS.md`. More specific instructions may exist for an individual runtime.

## Boundary

This subtree contains runtime-specific MCP configuration examples, installers, validation helpers, and optional client plugins. It adapts KiCad MCP Pro to external agent/IDE configuration formats; it must not invent a second MCP capability or security model.

Read first:

- `docs/agent-runtime-config.md`
- `docs/agents/index.md`
- `docs/agents/compatibility.md`
- `docs/agents/security.md`
- `docs/agents/progressive-disclosure.md`

## Configuration source discipline

Keep these surfaces aligned when they describe the same behavior:

- runtime-specific example files under `integrations/<runtime>/`;
- top-level project examples such as `.mcp.json`, `.codex/`, `.vscode/`, and `opencode.example.jsonc`;
- `integrations/common/install-kicad-mcp.mjs`;
- `integrations/common/validate-mcp-config.py`;
- runtime documentation under `docs/agents/` and `docs/agent-runtime-config.md`.

Do not assume different runtimes share the same config schema. Preserve each client's native format and permission vocabulary.

## Safety defaults

- Default examples should remain read-only/least-privileged unless the runtime-specific documentation explicitly explains a stronger mode.
- Never embed real API tokens, bearer tokens, customer paths, or private project data in examples.
- Use environment-variable references for remote credentials where supported.
- Do not enable mutation/destructive/manufacturing capabilities merely for setup convenience.
- Keep profile and operating-mode concepts distinct: profile controls discovery; operating mode controls execution risk.

Do not hard-code expert catalog sizes in prose. Point to generated profile/toolset evidence when counts matter.

## Installer behavior

Installer changes affect user configuration and filesystem state.

- Preserve existing user config backup/merge semantics.
- Do not overwrite unrelated client settings.
- Validate scope/path handling before writing.
- Use argv-based process execution for external CLIs; do not introduce shell interpolation around user-controlled values.
- Installation success is not proof the MCP server or live KiCad runtime is healthy; keep doctor/diagnostic verification explicit.

## Optional plugins

Client plugins are optional integration layers unless repository policy explicitly promotes them.

Do not make an experimental plugin a hidden requirement for the base MCP configuration. Plugin commands must preserve the same read/write/manufacturing safety model as the server.

## Verification

For integration/config changes run the relevant targeted tests plus:

```bash
python integrations/common/validate-mcp-config.py
pnpm run profiles:check
pnpm run toolsets:check
task pre-push
```

Use the runtime's own validator/doctor when the change is specific to a client. Before handoff, run the repository's normal verification appropriate to the changed files.

## Definition of done

An integration change is complete only when examples, installer behavior, permission defaults, docs, validation, and server profile/mode semantics remain aligned.
