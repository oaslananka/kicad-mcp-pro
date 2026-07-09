# Governance

KiCad MCP Pro is maintained by `@oaslananka`. The project uses maintainer-led decisions with lazy consensus for routine changes.

## Roles and responsibilities

| Role | Responsibility | Current owner |
| --- | --- | --- |
| Project owner | Final decision authority, repository settings, and release environment policy | `@oaslananka` |
| Release owner | Release-please review, package publish approval, and release evidence verification | `@oaslananka` |
| Security contact | Private report triage, severity assignment, and advisory publication | `@oaslananka` |
| Documentation owner | Documentation structure, generated reference consistency, and OpenSSF evidence | `@oaslananka` |
| Future co-maintainers | Review and merge within documented scope; share release and security continuity duties | Listed in [`MAINTAINERS.md`](MAINTAINERS.md) when added |

Maintainer scope and onboarding expectations are tracked in [`MAINTAINERS.md`](MAINTAINERS.md).

## Project model

The project is maintainer-led. Routine fixes use lazy consensus. Changes that alter public tool contracts, release policy, destructive behavior, or security boundaries require an issue, discussion, or RFC before implementation.

## Decision Process

- Small fixes, docs updates, tests, and CI maintenance can be merged after normal review.
- User-facing behavior, public tool contracts, profile changes, transport behavior, and release policy changes need an issue or discussion before implementation.
- Major public API or workflow changes require an RFC under `docs/rfcs/`.

## RFC Process

1. Create `docs/rfcs/000N-title.md` with motivation, design, compatibility, migration, and alternatives.
2. Open a GitHub Discussion and keep it open for at least 14 days.
3. Maintainers accept, reject, or request revision.
4. Accepted RFCs become the source of truth for implementation PRs.

## Release Authority

Automated CI/CD is owned by the canonical `oaslananka/kicad-mcp-pro`
GitHub repository. Publishing uses GitHub Actions environments and trusted
publishing where supported. Releases are driven by release-please and the CI
pipeline rather than by privileged local steps, so a release can be cut by any
maintainer with merge rights — no single person's workstation is in the path.

## Succession and continuity

This project currently has a single maintainer (bus factor = 1). That risk is
mitigated by design rather than hidden:

- **Everything needed to continue is in the repository.** Architecture
  ([`docs/development/architecture.md`](docs/development/architecture.md)), the build/release pipeline
  (`.github/workflows/`), the quality gates (`task verify` / `task ci`), and the
  contributor on-ramp ([`CONTRIBUTING.md`](CONTRIBUTING.md)) are documented and
  enforced in CI. A competent contributor can fork and continue without tribal
  knowledge.
- **Adding a co-maintainer.** A sustained contributor (several merged,
  well-tested PRs across more than one subsystem, and demonstrated understanding
  of the adapter-seam/honesty rules) may be invited as a co-maintainer. Onboarding
  grants are listed in [`MAINTAINERS.md`](MAINTAINERS.md).
- **If the sole maintainer becomes unavailable.** The canonical repository and
  package names are recorded in [`MAINTAINERS.md`](MAINTAINERS.md). Because
  publishing uses GitHub-side trusted publishing and CI environments, a new
  maintainer added to the repository can resume releases without recovering any
  individual's local secrets. If the repository itself becomes unreachable, the
  MIT license permits a community fork to continue under a new name.

## Security response

Vulnerabilities are reported privately per [`SECURITY.md`](SECURITY.md). The
primary security contact is the maintainer listed in
[`MAINTAINERS.md`](MAINTAINERS.md). To avoid a single point of failure, security
reports may also be filed as a GitHub private vulnerability report on the
canonical repository, which any current maintainer can triage. Co-maintainers
inherit security-triage responsibility when added.

## Bus factor status

The project currently has a bus factor of 1. This is an accepted and documented risk, not a hidden claim. The mitigation plan is to keep all build, release, security, and governance knowledge in the repository; avoid local-only release secrets; and invite a second trusted maintainer after sustained, high-quality contributions across multiple subsystems.

Until a second trusted maintainer is available, required human approvals and code-owner review are not enforced because they can block urgent maintenance. Branch protection, required CI, CodeQL, Gitleaks, review-thread resolution, no force-push, no deletion, and linear history remain enforced.
