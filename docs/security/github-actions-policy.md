# GitHub Actions security policy

KiCad MCP Pro treats workflow automation as a privileged production surface. Repository settings and committed policy checks therefore apply least privilege at two layers.

## Repository settings baseline

The repository is configured with:

- read-only default `GITHUB_TOKEN` permissions;
- workflow pull-request approval disabled;
- only selected GitHub Actions allowed;
- immutable commit-SHA references required;
- GitHub-owned Actions allowed, with every other Action repository explicitly allowlisted.

The expected settings and third-party Action repositories are recorded in `.github/actions-policy.json`.

## Workflow permission rules

Every workflow declares `contents: read` at workflow scope. Write permissions are permitted only at job scope and must exactly match the matrix in `.github/actions-policy.json`.

Publishing jobs receive only the scopes required for their destination. Examples include `id-token: write` for trusted publishing, `packages: write` for the container registry, and `contents: write` only where a release or documentation deployment must update repository state.

A new write scope requires all of the following in the same pull request:

1. a narrowly scoped job-level permission;
2. an update to `.github/actions-policy.json`;
3. a security rationale in the pull-request description;
4. successful workflow policy and security checks.

## Action allowlist changes

A third-party Action may be added only when its repository is listed in `.github/actions-policy.json` and the workflow references a full 40-character commit SHA. Tags and branches are rejected even for allowlisted repositories.

Prefer GitHub-owned Actions or existing allowlisted repositories. Review the Action source, release history, permissions, network behavior, and maintenance status before expanding the allowlist.

## Protected paths

`.github/CODEOWNERS` explicitly covers workflows, the Actions policy, release metadata, package manifests, registry metadata, and the security policy. These rules make security-sensitive changes visible to the maintainer and are designed to support required CODEOWNER review when an independent maintainer is available.

## Local verification

Run:

```bash
corepack pnpm run workflows:policy
corepack pnpm run workflows:lint
corepack pnpm run workflows:security
```

The policy check fails when a workflow gains an undeclared write scope, uses an unapproved Action repository, references a mutable Action tag, omits the read-only workflow baseline, or removes a protected CODEOWNERS rule.

## Rollback

If a required workflow is blocked after a repository-policy change:

1. identify the exact Action repository or missing job permission from the failed run;
2. validate the proposed exception in a pull request;
3. update the committed policy and repository setting together;
4. retain SHA pinning and read-only defaults during rollback.

Do not restore unrestricted Actions or repository-wide write permissions as a temporary workaround.
