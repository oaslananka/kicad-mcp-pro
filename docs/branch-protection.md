# Branch Protection

Rulesets are stored as code in `.github/rulesets/main.json`. The canonical repository currently has an active repository ruleset named `main` targeting `refs/heads/main`.

Create in the canonical repository:

```bash
gh api -X POST /repos/oaslananka/kicad-mcp-pro/rulesets --input .github/rulesets/main.json
```

If the ruleset already exists, use the ruleset id:

```bash
gh api /repos/oaslananka/kicad-mcp-pro/rulesets
gh api -X PUT /repos/oaslananka/kicad-mcp-pro/rulesets/<id> --input .github/rulesets/main.json
```

The current single-maintainer policy requires pull requests, linear history, non-fast-forward protection, resolved review threads, and the required CI, Gitleaks, and CodeQL check-run contexts listed in `.github/rulesets/main.json`.

Enable required approvals, code-owner review, and verified commit-signing enforcement after adding a second trusted maintainer and configuring signing for all release actors.

When a required workflow job name changes, update the root branch-protection document and `.github/rulesets/main.json` together before applying the ruleset.
