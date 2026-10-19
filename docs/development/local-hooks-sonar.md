# Local hooks and SonarQube IDE feedback

This repository uses **Lefthook**, with pinned **pre-commit** hooks, for rapid
developer feedback. The final authority is still the required GitHub CI
**SonarCloud Scan / Quality Gate** (including coverage and PR analysis).

## One-time setup per Git worktree

From the root of the worktree in which you commit or push:

    corepack pnpm install --frozen-lockfile
    task hooks

The installer verifies the shims. On repositories with
extensions.worktreeConfig=true, core.hooksPath is set only in the current
worktree's configuration; global Git config and sibling worktrees remain
untouched. On a normal clone without that extension, the installer uses
the repository's own Git hooks directory. Custom hook paths are not overwritten.

Verify installation:

    git config --show-origin --get core.hooksPath
    corepack pnpm exec lefthook check-install

A lefthook.yml file alone does not activate hooks. If global core.hooksPath
points at an empty directory, local Git checks may be silently skipped.
Run task hooks **separately in each worktree** where checks are required.

## Check placement

| Trigger | Checks |
| --- | --- |
| pre-commit | staged private filename guard, whitespace, EOF, merge markers, YAML/JSON/TOML, case conflicts, symlinks, key detection, Ruff, Gitleaks |
| pre-push | changed-file Ruff/mypy, targeted pytest, architecture and tool contracts, workflow policies, hook config contract tests |
| CI | full OS matrix, Python/Node, coverage, CodeQL, Gitleaks and required SonarCloud Quality Gate |

The filename guard rejects staged private .env files, .npmrc, .pypirc,
private key and certificate filenames and selected credentials JSON filenames.
.env.example, .env.sample and .env.template are allowed. The guard
only checks **names**; Gitleaks checks contents. If a legitimate certificate
fixture must be committed, review it explicitly rather than disabling required
CI security checks.

Do **not** add full SonarScanner analysis to either hook: it depends on a
server profile, coverage, analyzer runtimes, remote connectivity and tokens,
and can make every push slow or non-reproducible offline.

## SonarQube for IDE connected mode

The tracked .vscode/extensions.json recommends SonarQube for IDE
(SonarSource.sonarlint-vscode). After installing it in VS Code, open the
extension's Connected Mode view, connect to SonarQube Cloud (EU:
sonarcloud.io), and bind to the existing project:

- Organization: oaslananka
- Project key: oaslananka_kicad-mcp-pro

Sign in through the IDE connection wizard with your own SonarQube Cloud
account/token. **Never commit tokens or connection secrets.** Shared
binding metadata must not contain credentials. Connected mode aligns
editor rules more closely with the server, including cognitive complexity
warnings, but it does not reproduce the complete CI Quality Gate or directly
synchronize pull-request analysis.

Provider instructions:
https://docs.sonarsource.com/sonarqube-for-vs-code/connect-your-ide/setup
