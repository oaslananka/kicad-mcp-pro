# Doppler Setup

This repository expects Doppler project `all`, config `main`.

## Required GitHub Secret

Set exactly one GitHub secret in both repositories:

- `DOPPLER_TOKEN`

The token must be a read-only Doppler service token scoped to project `all`, config `main`.

Set it in:

- `oaslananka/kicad-mcp-pro`
- `oaslananka-lab/kicad-mcp-pro`

The organization repository may inherit the secret from the organization if that is easier to maintain.

## Doppler GitHub Sync

In the Doppler dashboard:

1. Open project `all`, config `main`.
2. Install the GitHub integration for both `oaslananka` and `oaslananka-lab`.
3. Create a sync to `oaslananka/kicad-mcp-pro` repository secrets.
4. Create a sync to `oaslananka-lab/kicad-mcp-pro` repository secrets.
5. Use replace mode so GitHub remains a projection of Doppler, not a second source of truth.

## Expected Secrets

The authoritative list for this repo is `.doppler/secrets.txt`.

Current expected names:

- `CODECOV_TOKEN`
- `DOPPLER_GITHUB_SERVICE_TOKEN`
- `PYPI_TOKEN`
- `SAFETY_API_KEY`
- `TEST_PYPI_TOKEN`

## Verification

```bash
bash scripts/verify_doppler_secrets.sh
```

This command requires the Doppler CLI and a local login or `DOPPLER_TOKEN`.
