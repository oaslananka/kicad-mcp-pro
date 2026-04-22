# Repository and CI/CD Topology

This project uses two GitHub repositories with different responsibilities:

- Personal source repository: `https://github.com/oaslananka/kicad-mcp-pro`
- GitHub organization CI/CD mirror: `https://github.com/oaslananka-lab/kicad-mcp-pro`

The personal repository remains the primary public source, package metadata, issue, and documentation reference. The organization mirror owns automated GitHub CI/CD.

## Trigger Policy

| Surface | Role | Trigger policy |
|---|---|---|
| GitHub personal (`oaslananka`) | Main source repository | Manual workflows only; automatic jobs are gated off |
| GitHub org (`oaslananka-lab`) | GitHub CI/CD owner | CI and security run on `push`/`pull_request`; publish remains manual |
| Azure DevOps | Manual fallback and release support | Manual only |
| GitLab | Manual fallback mirror | Manual only |

Because the same workflow files are mirrored to both GitHub repositories, push events may appear in the personal repository UI. The jobs are guarded with `github.repository_owner == 'oaslananka-lab'`, so they do not execute automatically outside the organization mirror.

## Recommended Remotes

Use explicit remotes so source pushes reach both GitHub repositories and Azure:

```bash
git remote add github git@github.com:oaslananka/kicad-mcp-pro.git
git remote add github-org git@github.com:oaslananka-lab/kicad-mcp-pro.git
git remote add azure git@ssh.dev.azure.com:v3/oaslananka/open-source/kicad-mcp-pro
```

If a GitLab mirror is used, add it as a separate manual remote:

```bash
git remote add gitlab <gitlab-repository-url>
```

## Publishing

Package publishing to PyPI or TestPyPI must remain a deliberate manual action. Queue the publish workflow from the organization GitHub repository or from Azure DevOps only when the version, changelog, and artifacts are ready.

## Doppler Secrets

The recommended secret model is to store only `DOPPLER_TOKEN` in CI/CD systems and keep the actual release secrets in Doppler:

- `PYPI_TOKEN`
- `TEST_PYPI_TOKEN`
- `SAFETY_API_KEY`
- `NPM_TOKEN`
- `OVSX_PAT`
- `VSCE_PAT`

GitHub organization workflows, Azure DevOps, and GitLab all use the same pattern: install the Doppler CLI, then execute sensitive commands through `doppler run -- ...` so Doppler injects secrets as environment variables at runtime.

Minimum setup:

- GitHub org repository secret: `DOPPLER_TOKEN`
- Azure DevOps secret variable or variable group entry: `DOPPLER_TOKEN`
- GitLab CI/CD variable: `DOPPLER_TOKEN`

Keep old native secrets such as `PYPI_TOKEN` and `TEST_PYPI_TOKEN` only if you want fallback publishing without Doppler.
