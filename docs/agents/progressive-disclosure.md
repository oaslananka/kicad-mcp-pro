# Progressive-Disclosure Profiles

KiCad MCP Pro defaults to a bounded tool surface so general-purpose agents do not need to choose from the complete expert catalog.

## Workflow profiles

| Profile | Operating mode | Callable tools | Intended use |
|---|---|---:|---|
| `default` | `readonly` | 25 | Safe general-agent review and next-action discovery |
| `review` | `readonly` | 25 | Explicit read-only DRC, ERC, DFM, visual QA, and component-contract review |
| `build` | `write` | 24 | Plan/apply/verify workflows plus bounded PCB inspect/remove/DRC operations |
| `release` | `manufacturing` | 24 | Validation and human-gated manufacturing package generation |
| `expert` | `experimental` | generated | Complete catalog for trusted advanced clients |

`full` and `agent_full` remain available for backward compatibility. They expose the complete catalog and should not be the default for a general agent.

Beyond the workflow profiles above, the router also registers focused domain profiles such as `pcb_layout`, `pcb_only`, `schematic_authoring`, `manufacturing_release`, `high_speed`, `power`, `simulation`, and `critic`. These resolve to fixed category sets in `src/kicad_mcp/tools/router.py`; `pcb_layout` is an explicit alias of the `pcb_only` category set (project, PCB read, PCB write, and routing). The full list and the operating mode paired with each name are in [Toolset Profiles](toolsets.md). Every profile fails closed: an unrecognized `KICAD_MCP_PROFILE` value resolves to the bounded `default` surface instead of the complete catalog.

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

The profile limits both discovery and direct tool execution. The operating mode is an independent execution-risk gate. Selecting `build` while remaining in `readonly` mode does not silently enable write operations. Selecting `release` without manufacturing mode does not expose the final package operation.

## Safety boundaries

The review profile contains only `READ`-tier capabilities. The eight `review-profile`-tagged golden cases retain 100% expected-tool coverage while exposing none of the destructive tools explicitly forbidden by those cases. The broader tool-selection corpus also covers build, mutation, export, publish, confirmation, and refusal behavior and is not expected to fit inside the review surface.
Category discovery is profile-aware: hidden categories and lower-level tool names are not returned by the discovery tools until the server starts with a profile that allows them.

The build profile exposes workflow-level operations instead of the unrestricted low-level mutation catalog. Schematic work is bounded by `plan`, `preview`, `apply`, `verify`, and `rollback`. For PCB correction, it adds only the focused `pcb_get_tracks`, `pcb_get_vias`, `pcb_delete_items`, `pcb_delete_object`, and `run_drc` path alongside begin, push, drop, and revert transaction controls. Broad placement, routing, copper, and direct-file mutation helpers remain outside this bounded profile. This is intentional: an agent that needs a different MCP capability must request a supported broader profile rather than falling back to ad-hoc `.kicad_pcb` or `.kicad_sch` text rewriting.

The release profile exposes validation, board statistics, checkpoint inspection, and `export_manufacturing_package`. The final manufacturing package remains `HUMAN_ONLY` and requires explicit human confirmation.

## Profile transitions

Profiles are selected when the MCP server process starts. To move from review to build or release, update the environment or CLI arguments and reconnect the MCP client.

KiCad MCP Pro does not currently mutate a session's profile at runtime, so it does not emit `notifications/tools/list_changed` for profile transitions. Clients that support `tools/listChanged` still receive normal server-driven list changes where the underlying MCP implementation supports them, but profile changes require a fresh connection.

## Runtime IPC discovery

With runtime tool filtering enabled, the server's `tools/list` reflects the
current KiCad IPC capability snapshot, cached for approximately one second.
After opening or closing a KiCad PCB or schematic, allow the snapshot to
expire and request `tools/list` again. If the host retains an older catalog
and cannot refresh it, reconnect the MCP session. Do not assume that a
stateless HTTP session receives an automatic catalog-change notification.
A discovered tool is not proof that IPC is still connected when it is called;
the normal operating-mode and native execution guards remain authoritative.

## Versioned local capability contract

The machine-readable contract under integrations/common/capability-catalog.json
is generated from actually registered expert-profile MCP tools and the router
categories. It records input JSON schemas, maturity, effect and permission
tiers, runtime requirements and tested KiCad versions. Run
pnpm capabilities:build to regenerate, or pnpm capabilities:check to detect
drift. The existing repository metadata check also enforces the snapshot.

**Discovery is not authorization.** Every generated local entry declares
remoteCallable=false. Cloud exposes only separately implemented and authorized
Connector adapters for a specific user, client and project. Reading this
catalog cannot automatically expose any local tool for remote execution.
Version compatibility, KiCad presence, permission checks, project isolation
and independent native verification remain separate acceptance gates.
No new MCP runtime tool, provider, credential or service is introduced.

## Evidence and drift checks

The deterministic snapshot at `docs/evidence/progressive-disclosure-profile-snapshot.json` records:

- declared and callable tool counts;
- serialized catalog character and estimated token sizes;
- total, read-only, and profile-tagged golden case coverage;
- forbidden-tool exposure counts;
- reductions relative to the expert catalog.

Regenerate and verify it with:

```bash
pnpm run profiles:build
pnpm run profiles:check
```

The snapshot check runs as part of `check:meta`, so profile or schema changes cannot silently expand the default surface.


## Portable Agent Skills ownership (October 2026)

The **single editable source** is [`skills/`](https://github.com/oaslananka/kicad-mcp-pro/tree/main/skills). Seven KiCad
skills are mirrored to `.opencode/skills/` and `.agents/skills/` for host-native
discovery; these are generated outputs, not independent policy documents.
Copilot's `code-review` skill remains independently owned and is **not** a
portable KiCad user skill.

After editing a canonical skill run:

```bash
python scripts/sync_agent_skills.py --write
python scripts/sync_agent_skills.py --check
```

The workflow-policy CI job fails if generated copies drift. Do not publish a
skill bundle as verified for a host based solely on Markdown/YAML validation:
actual host installation, discovery, MCP connection and safe readonly tool
execution need separate recorded smoke evidence.

### Cloud tool metadata evolution (offline review)

The registered local catalog is regenerated using `pnpm capabilities:build` and
checked for source drift in CI using `pnpm capabilities:check`. It is not the
published Cloud MCP `tools/list` surface: `remoteCallable=false` is deliberate,
and local existence must never imply remote authority.

For a candidate tool release, keep the previously reviewed JSON catalog and run:

```text
uv run --all-extras python scripts/compare_cloud_tool_catalogs.py previous-catalog.json integrations/common/capability-catalog.json --fail-on-breaking
```

The offline comparison reports added, removed, and changed tool definitions.
New optional input fields and description updates are compatible candidates;
removed names, added required inputs, changed argument contracts, or changed
permission/remote-exposure semantics are flagged as **potentially breaking**.
A flag is a review requirement, not permission to change publication policy.
New tools do not become publicly callable because the inventory grew.

A published Cloud MCP tool contract must remain stable while OpenAI reviews
changed metadata. Actual Cloud exposure still requires a separate, explicitly
reviewed public tool definition, current project grants, runtime validation,
and signed Connector authorization. This comparison neither publishes tools
nor performs native KiCad acceptance.
