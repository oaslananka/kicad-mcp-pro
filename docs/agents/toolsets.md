# Toolset Profiles

KiCad MCP has a broad expert catalog. General agents should use the bounded workflow toolsets below instead of loading the complete catalog. Current expert-surface size is recorded in `docs/evidence/progressive-disclosure-profile-snapshot.json`.

`integrations/common/toolsets.json` is **generated from the router profile source of
truth** (`src/kicad_mcp/tools/router.py`) by `scripts/build_toolsets.py`; each toolset
resolves to a router profile (and operating mode). Do not edit it by hand — run
`pnpm run toolsets:build`. CI enforces it never drifts (`pnpm run toolsets:check`) and
that every listed tool is really registered.

## Available Toolsets

| Profile | Router profile / mode | Tools | Use Case |
|---------|-----------------------|------:|----------|
| `default` | `default` / readonly | 24 | Safe general-agent review |
| `review` | `review` / readonly | 24 | DRC/ERC/DFM and visual review |
| `build` | `build` / write | 24 | Plan/apply/verify/rollback workflows |
| `release` | `release` / manufacturing | 24 | Human-gated manufacturing handoff |
| `expert` | `expert` / experimental | generated | Complete trusted-client catalog |
| `readonly` | `review` / readonly | 24 | Backward-compatible review alias |
| `schematic` | `schematic` / experimental | generated | Schematic design, library, export |
| `pcb_layout` | `pcb_only` / experimental | generated | PCB layout and routing |
| `manufacturing` | `manufacturing` / experimental | generated | Broad manufacturing surface |
| `simulation` | `simulation` / experimental | generated | SPICE simulation |
| `high_speed` | `high_speed` / experimental | generated | High-speed design review |
| `full_write` | `expert` / experimental | generated | Backward-compatible expert alias |

Broad-profile counts are generated from `toolsets.json` and the profile snapshot rather than duplicated here. The default/review/build/release surfaces are checked by `pnpm run profiles:check`; see [Progressive-Disclosure Profiles](progressive-disclosure.md).

## Using Toolsets

### Codex CLI
```toml
[mcp_servers.kicad]
enabled_tools = ["kicad_get_project_info", "project_quality_gate", "run_erc", "run_drc"]
```

### Gemini CLI
```json
{
  "mcpServers": {
    "kicad": {
      "includeTools": ["kicad_get_project_info", "project_quality_gate"]
    }
  }
}
```

### OpenCode
```json
{
  "agent": {
    "pcb-review": {
      "tools": { "kicad_*": true }
    }
  }
}
```

### VS Code
```json
{
  "sandbox": {
    "filesystem": { "allowWrite": ["${workspaceFolder}"] }
  }
}
```

## Why Use Toolsets?

- Reduces context token usage by MCP server tool registration
- Prevents accidental destructive operations
- Keeps agent focused on the task at hand
- Improves discovery latency (fewer tools to list)

## References

- `integrations/common/toolsets.json` — machine-readable toolset definitions
- `integrations/common/profiles.md` — deployment profiles
