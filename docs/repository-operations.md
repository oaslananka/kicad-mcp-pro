# Repository Operations

## Repositories

- Canonical: `oaslananka/kicad-mcp-pro`
- CI/CD mirror: `oaslananka-lab/kicad-mcp-pro`

The canonical repository is the public source of truth. The lab repository is the automation runner.

## Synchronization

The lab repository pulls from canonical every 15 minutes with `.github/workflows/sync-from-canonical.yml`.

Direction:

- Branches and tags: canonical to lab
- GitHub Releases and release assets: lab to canonical

The canonical repository should not run Actions. All workflow jobs are guarded so they only run when the repository is `oaslananka-lab/kicad-mcp-pro`.

## Disable Personal Actions

Recommended one-time hardening:

```bash
gh api -X PUT /repos/oaslananka/kicad-mcp-pro/actions/permissions -f enabled=false
```

Re-enable only if needed:

```bash
gh api -X PUT /repos/oaslananka/kicad-mcp-pro/actions/permissions -f enabled=true -f allowed_actions=all
```

## Manual Sync

Use this only if the scheduled lab pull is unavailable:

```bash
bash scripts/sync-remotes.sh main
```

```powershell
.\scripts\sync-remotes.ps1 -Branch main
```

Both scripts require a clean working tree.

## Mirror Recovery

1. Confirm `DOPPLER_GITHUB_SERVICE_TOKEN` exists in Doppler and is synced to the lab repository.
2. Run `.github/workflows/sync-from-canonical.yml` manually in `oaslananka-lab/kicad-mcp-pro`.
3. If the workflow is unavailable, run the manual sync helper from a clean local clone.
4. Re-run lab CI on the mirrored branch.

## Release Artifact Back-Mirror

The `Mirror releases back to canonical` workflow republishes lab GitHub Releases to canonical. It uses `DOPPLER_GITHUB_SERVICE_TOKEN`.

## Branch Cleanup

Review planned cleanup actions:

```bash
bash scripts/repo-cleanup.sh
```

Apply after reviewing the dry run:

```bash
bash scripts/repo-cleanup.sh --apply
```

The monthly `Branch hygiene report` workflow is report-only. It opens or updates an issue and does not delete branches.

## Auto-Delete Merged PR Branches

Recommended one-time setting on canonical:

```bash
gh api -X PATCH /repos/oaslananka/kicad-mcp-pro -f delete_branch_on_merge=true
```
