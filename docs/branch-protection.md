# Branch and Release-Tag Protection

GitHub repository rulesets are stored as reviewed desired state under `.github/rulesets/`:

- `.github/rulesets/main.json` — active branch ruleset `main-standard`, targeting `~DEFAULT_BRANCH`.
- `.github/rulesets/release-tags.json` — active tag ruleset `release-tags`, protecting the published product tag families.

The repository settings audit compares both files with the live GitHub ruleset details. The files are intended to describe the live policy, not a weaker bootstrap approximation.

## Default branch ruleset

`main-standard` requires:

- pull requests for changes to the default branch;
- branch deletion protection;
- non-fast-forward / force-push protection;
- linear history;
- zero mandatory human approvals while the project remains single-maintainer;
- resolved review threads;
- the extra approval safeguard for unattributed changes;
- squash as the only allowed merge method;
- strict required status checks listed in `.github/rulesets/main.json`.

The repository owner has a `pull_request`-mode bypass actor entry. This does not grant an unrestricted always-bypass path: changes still use the pull-request boundary.

`Live Model Release Policy` is intentionally not a default-branch required context. Provider smoke evidence is enforced at the release boundary. `SonarCloud Scan` remains required for the default-branch gate.

## Release-tag ruleset

`release-tags` blocks deletion and update of the real published tag families:

- `protocol-schemas-v*`
- `mcp-server-v*`
- `mcp-npm-v*`
- `kicad-mcp-gui-v*`

Tag creation remains available to the verified release workflows; existing published tags are immutable.

## Applying reviewed desired state

Discover the live rule IDs before updating an existing ruleset:

~~~bash
gh api /repos/oaslananka/kicad-mcp-pro/rulesets
~~~

Create a missing ruleset only after confirming that an equivalent live ruleset does not already exist:

~~~bash
gh api -X POST /repos/oaslananka/kicad-mcp-pro/rulesets \
  --input .github/rulesets/main.json

gh api -X POST /repos/oaslananka/kicad-mcp-pro/rulesets \
  --input .github/rulesets/release-tags.json
~~~

For an existing ruleset, use its verified ID:

~~~bash
gh api -X PUT /repos/oaslananka/kicad-mcp-pro/rulesets/<id> \
  --input .github/rulesets/main.json
~~~

Use the matching desired-state file for the target ruleset. Do not apply a file blindly when the live repository has a stronger intentional policy; reconcile the difference first.

When a required workflow job name changes, update the workflow, `.github/rulesets/main.json`, Mergify conditions, tests, and this documentation as one policy change before modifying the live ruleset.

Enable required human approvals, code-owner review, or additional signing/review controls only when the maintainer model and release actors can satisfy them reliably.
