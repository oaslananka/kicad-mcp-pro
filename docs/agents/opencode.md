# OpenCode Integration

KiCad MCP Pro supports OpenCode as both an MCP client integration and a
maintainer-triggered pull-request repair agent.

## MCP quick start

```bash
kicad-mcp-pro setup opencode
```

A minimal manual configuration is:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "kicad": {
      "type": "local",
      "command": ["uvx", "kicad-mcp-pro"],
      "enabled": true,
      "timeout": 30000,
      "environment": {
        "KICAD_MCP_PROJECT_DIR": ".",
        "KICAD_MCP_PROFILE": "default",
        "KICAD_MCP_OPERATING_MODE": "readonly"
      }
    }
  }
}
```

OpenCode permissions match tool names and support wildcards. Prefer the current
`permission` schema over the deprecated legacy `tools` booleans:

```json
{
  "permission": {
    "kicad_*": "deny",
    "edit": "ask",
    "bash": "ask"
  },
  "agent": {
    "pcb-review": {
      "description": "KiCad PCB review and manufacturing readiness agent",
      "mode": "primary",
      "permission": {
        "kicad_*": "allow",
        "edit": "deny",
        "bash": "ask"
      }
    }
  }
}
```

## Verification

```bash
opencode mcp list
kicad-mcp-pro doctor --agent opencode
```

## Pull-request repair automation

The repository includes `.github/workflows/opencode.yml`. A maintainer with
repository write permission can request a repair on a same-repository pull request
by adding a new PR conversation comment that starts with either command:

```text
/oc fix the failing workflow policy test and keep the change scoped to this PR
```

```text
/opencode update the regression test for this bug and run the relevant checks
```

The workflow uses the `pr-repair` primary agent and the `repo-repair` skill stored
under `.opencode/`. The agent edits the checked-out PR working tree, runs
repository-native validation, and leaves commit/push operations to a separate
trusted publisher.

### Security model

The automation is intentionally stricter than OpenCode's stock GitHub Action
example:

- Only `OWNER`, `MEMBER`, or `COLLABORATOR` comments are considered, and the
  workflow independently verifies that the triggering actor still has GitHub
  `write`, `maintain`, or `admin` permission.
- Fork pull requests are not mutated. This keeps repository write credentials away
  from code owned by a different repository.
- The workflow checks out the trusted default branch first and copies the agent,
  skill, repository instructions, and publisher into runner-temporary storage.
  Pull-request changes therefore cannot replace the CI agent policy.
- OpenCode runs with `OPENCODE_DISABLE_PROJECT_CONFIG=1` and `--pure`, so PR-local
  OpenCode configuration, agents, skills, and plugins are not trusted by the
  automation.
- The repair agent receives no `GITHUB_TOKEN`, `GH_TOKEN`, or OIDC write
  credential. Network tools and external-directory access are denied.
- The tokenless repair job exports only a bounded blob bundle with a sorted
  manifest, file modes, sizes, and SHA-256 checksums. The write-capable publish
  job never checks out the PR branch: it checks out only the trusted default
  branch to obtain the publisher, validates the downloaded bundle as data, rejects
  branch races, and constructs the repaired tree and commit directly with the
  GitHub Git Data API.
- `actions/checkout` remains pinned to an immutable SHA and uses
  `persist-credentials: false`.
- The OpenCode CLI is downloaded from the fixed `v1.18.32` release asset and is
  verified against the committed SHA-256 digest before execution.
- The workflow uses `opencode/nemotron-3.5-lightning-free`. In the pinned
  OpenCode v1.18.32 provider implementation, unauthenticated public mode keeps
  zero-cost models enabled while disabling paid models, so this workflow does not
  require a provider API secret.

The workflow receives `contents: write` and `pull-requests: write` only in its
`publish` job. The latter is used for PR conversation comments. The repair job is
limited to `contents: read` and `pull-requests: read`.
Those writes are recorded in `.github/actions-policy.json`, matching the
repository's least-privilege workflow policy.

### Validation

Changes to this automation must pass:

```bash
task workflows:lint
task workflows:policy
task workflows:security
python -m pytest tests/unit/test_opencode_pr_repair.py
```

For broad changes, run `task verify` as well.

## Experimental plugin

An experimental OpenCode plugin is available at
`integrations/opencode/plugins/kicad-mcp-plugin/`. It provides diagnostics and
KiCad review helpers, but it is not required by the MCP configuration or PR repair
workflow.
