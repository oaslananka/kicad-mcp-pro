# OpenCode Integration Maintainer Instructions

These instructions apply to `integrations/opencode/**` and supplement `integrations/AGENTS.md` and the repository root instructions.

This file is for repository maintenance. User-facing OpenCode setup and usage belong in `integrations/opencode/README.md`, `docs/agents/opencode.md`, and `docs/agent-runtime-config.md`.

## Configuration contract

OpenCode uses its own `mcp` configuration schema. Preserve local versus remote server semantics and keep the installer-facing `integrations/opencode/opencode.example.json` aligned with the documented project-level OpenCode example where they describe the same server behavior.

- New OpenCode permission configuration uses `permission`; do not reintroduce the deprecated legacy `tools` boolean model.
- Preserve wildcard behavior such as `kicad_*` when documenting or testing MCP tool permissions.
- Keep conservative/read-only defaults for general review.
- Do not embed literal remote bearer tokens; use environment references or the supported OpenCode secret mechanism.
- A runtime permission rule does not replace KiCad MCP Pro's profile, operating-mode, confirmation, manufacturing, or server-side security controls.

## Experimental plugin

`plugins/kicad-mcp-plugin/` is optional and experimental.

- Do not make the plugin required for normal MCP discovery or configuration.
- Plugin review/doctor helpers should remain bounded to their documented role.
- Any plugin path that can invoke KiCad capabilities must preserve the server's read/write/destructive/manufacturing semantics rather than creating a parallel bypass.

## Validation

For OpenCode integration changes:

```bash
python integrations/common/validate-mcp-config.py
task pre-push
```

Also update the OpenCode README/docs when user-visible configuration or permission syntax changes. Validate with an actual OpenCode runtime when claiming runtime-specific behavior; static JSON validation alone does not prove client compatibility.

## Definition of done

An OpenCode integration change is complete only when installer input, examples, docs, permission semantics, optional plugin behavior, and server safety expectations agree.
