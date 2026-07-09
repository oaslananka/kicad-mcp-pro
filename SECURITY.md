# Security Policy

KiCad MCP Pro is an MCP server and companion toolchain for KiCad EDA workflows. Security reports are handled privately so users are not exposed to unpatched issues.

## Supported versions

| Package / artifact | Supported line | Security status |
| --- | --- | --- |
| Python package `kicad-mcp-pro` | Latest released minor line | Supported |
| npm wrapper `kicad-mcp-pro` | Version matching the latest Python package | Supported |
| Docker image `ghcr.io/oaslananka/kicad-mcp-pro` | Tags matching the latest release | Supported |
| Tauri GUI installers | Latest GUI release tag | Supported |
| Old release lines | Best effort only | Upgrade recommended |

Security fixes are normally released in the next patch version. Critical fixes may be released as an out-of-band hotfix.

## Report a vulnerability

Use GitHub private vulnerability reporting for the canonical repository:

<https://github.com/oaslananka/kicad-mcp-pro/security/advisories/new>

Do not open public issues for active vulnerabilities. Do **not** open a public issue for an active vulnerability.

Include as much of the following as possible:

- affected package or artifact: Python, npm, Docker, GUI, docs, or workflow;
- affected version, install method, operating system, Python version, Node version, KiCad version, and MCP client;
- minimal reproduction steps or proof of concept;
- expected and observed impact;
- whether credentials, private design files, generated Gerbers, netlists, or board metadata are exposed;
- any known mitigations or configuration flags that reduce exploitability.

Remove real tokens, API keys, private customer board data, and internal paths from logs before attaching them.

## Response process

1. A maintainer acknowledges the report and keeps the discussion private.
2. The maintainer scopes affected artifacts and assigns a preliminary severity.
3. The maintainer creates a mitigation plan, patch branch, public issue placeholder, or advisory depending on impact.
4. The fix is validated through CI and release evidence before publication.
5. Users are notified through an advisory, release notes, or documented mitigation when appropriate.

## Response targets

| Severity | Example impact | First response target | Fix / mitigation target |
| --- | --- | ---: | ---: |
| Critical | credential exfiltration, arbitrary command execution, destructive board mutation without consent | 24 hours | 7 days |
| High | unauthorized file access, supply-chain compromise, unsafe default network exposure | 3 business days | 14 days |
| Medium | denial of service, policy bypass requiring local access, incorrect permission boundary | 7 business days | 30 days |
| Low | hardening issue, documentation ambiguity, low-impact information disclosure | 14 business days | next normal release when accepted |

Targets depend on maintainer availability. If a target is at risk, maintainers should document the status in the private advisory and, when safe, publish a mitigation note.

## Vulnerability credit

Reporters who want public credit should include the preferred name, handle, and link in the private report. Maintainers credit reporters in the GitHub Security Advisory, changelog, or release notes unless the reporter requests anonymity or public mention would increase user risk.

Credit is given after the fix or mitigation is available, after coordinated disclosure timing is agreed, or when a report is closed as informational and the reporter agrees to public mention.

## Disclosure process

1. A maintainer acknowledges the private report and assigns an initial severity.
2. The report is reproduced or scoped. If the report is not a vulnerability, the maintainer explains why.
3. A fix, mitigation, documentation update, or release-blocking policy change is prepared on a private branch when needed.
4. Release artifacts are built through GitHub Actions, with checksums, SBOMs, and attestations where the workflow supports them.
5. The advisory is published after patched artifacts are available or after coordinated disclosure is agreed.

## Security model summary

- Telemetry and error reporting are disabled by default.
- External API credentials are opt-in and must be provided by the user environment.
- KiCad-driving tools should route through the adapter and policy seams documented in the architecture and workflow-security docs.
- Destructive operations must be explicit, documented, and test-covered.
- Release and publishing workflows should use GitHub-side automation, protected environments, OIDC/trusted publishing where supported, SBOM generation, checksums, and artifact attestations.

See also:

- [`docs/security/threat-model.md`](docs/security/threat-model.md)
- [`docs/security/release-signing.md`](docs/security/release-signing.md)
- [`docs/security/assurance-case.md`](docs/security/assurance-case.md)
- [`docs/security/input-validation.md`](docs/security/input-validation.md)
- [`docs/security/requirements.md`](docs/security/requirements.md)
- [`docs/security/release-integrity.md`](docs/security/release-integrity.md)
- [`docs/security/release-security.md`](docs/security/release-security.md)
- [`docs/workflow-security.md`](docs/workflow-security.md)
