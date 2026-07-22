# Progressive-Disclosure Profiles

KiCad MCP Pro defaults to a bounded tool surface so general-purpose agents do not need to choose from the complete expert catalog.

## Workflow profiles

| Profile | Operating mode | Callable tools | Intended use |
|---|---|---:|---|
| `default` | `readonly` | 24 | Safe general-agent review and next-action discovery |
| `review` | `readonly` | 24 | Explicit read-only DRC, ERC, DFM, visual QA, and component-contract review |
| `build` | `write` | 24 | Plan, preview, apply, verify, rollback, PCB transaction, and checkpoint workflows |
| `release` | `manufacturing` | 24 | Validation and human-gated manufacturing package generation |
| `expert` | `experimental` | 377 | Complete catalog for trusted advanced clients |

`full` and `agent_full` remain available for backward compatibility. They expose the complete catalog and should not be the default for a general agent.

## Recommended configuration

Review is the safe default:

```text
KICAD_MCP_PROFILE=default
KICAD_MCP_OPERATING_MODE=readonly
```

Controlled source editing requires both the build profile and write mode:

```text
KICAD_MCP_PROFILE=build
KICAD_MCP_OPERATING_MODE=write
```

Manufacturing handoff requires both the release profile and manufacturing mode:

```text
KICAD_MCP_PROFILE=release
KICAD_MCP_OPERATING_MODE=manufacturing
```

The profile controls discovery. The operating mode is an independent execution-risk gate. Selecting `build` while remaining in `readonly` mode does not silently enable write operations. Selecting `release` without manufacturing mode does not expose the final package operation.

## Safety boundaries

The review profile contains only `READ`-tier capabilities. Its golden tool-selection cases retain 100% expected-tool coverage while exposing none of the destructive tools forbidden by those cases.
Category discovery is profile-aware: hidden categories and lower-level tool names are not returned by the discovery tools until the server starts with a profile that allows them.

The build profile exposes workflow-level operations instead of the unrestricted low-level mutation catalog. Schematic work is bounded by `plan`, `preview`, `apply`, `verify`, and `rollback`. PCB work is bounded by begin, push, drop, and revert transaction operations. Direct destructive helpers such as bulk deletion are not part of the profile.

The release profile exposes validation, board statistics, checkpoint inspection, and `export_manufacturing_package`. The final manufacturing package remains `HUMAN_ONLY` and requires explicit human confirmation.

## Profile transitions

Profiles are selected when the MCP server process starts. To move from review to build or release, update the environment or CLI arguments and reconnect the MCP client.

KiCad MCP Pro does not currently mutate a session's profile at runtime, so it does not emit `notifications/tools/list_changed` for profile transitions. Clients that support `tools/listChanged` still receive normal server-driven list changes where the underlying MCP implementation supports them, but profile changes require a fresh connection.

## Evidence and drift checks

The deterministic snapshot at `docs/evidence/progressive-disclosure-profile-snapshot.json` records:

- declared and callable tool counts;
- serialized catalog character and estimated token sizes;
- golden tool-selection case coverage;
- forbidden-tool exposure counts;
- reductions relative to the expert catalog.

Regenerate and verify it with:

```bash
pnpm run profiles:build
pnpm run profiles:check
```

The snapshot check runs as part of `check:meta`, so profile or schema changes cannot silently expand the default surface.
