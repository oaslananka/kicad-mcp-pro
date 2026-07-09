# Security Assurance Case

This assurance case summarizes why KiCad MCP Pro is expected to meet its documented security requirements. It is not a formal proof; it is a structured set of claims, arguments, and evidence that must be kept current as the project evolves.

## Top-level claim

KiCad MCP Pro can be used as a professional MCP automation layer for KiCad workflows without granting agents uncontrolled access to local files, credentials, release infrastructure, or undocumented destructive actions.

## Claim 1: Inputs are bounded before use

**Argument.** MCP arguments and integration inputs are validated before filesystem, subprocess, KiCad, or release-workflow use. Path-sensitive code uses canonicalization, workspace allowlisting, extension allowlists, and child-path containment checks.

**Evidence.**

- [`input-validation.md`](input-validation.md)
- CodeQL path-injection remediation history
- CI security job and CodeQL workflow
- fuzz target for shared S-expression helpers

## Claim 2: Release artifacts are traceable to protected CI

**Argument.** Package and container publishing happens through GitHub Actions from the canonical repository. Release jobs produce checksums, SBOMs, attestations, package-manager provenance, or Sigstore/cosign signatures depending on artifact type.

**Evidence.**

- [`release-security.md`](release-security.md)
- [`release-integrity.md`](release-integrity.md)
- [`release-signing.md`](release-signing.md)
- publish workflows under `.github/workflows/`

## Claim 3: Security reports can be handled privately and predictably

**Argument.** The security policy documents supported artifacts, private vulnerability reporting, response targets, disclosure flow, and release response expectations.

**Evidence.**

- [`SECURITY.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/SECURITY.md)
- GitHub private vulnerability reporting
- [`scorecard-exceptions.md`](scorecard-exceptions.md)

## Claim 4: Supply-chain risk is actively reduced

**Argument.** Dependencies are declared, audited, pinned where practical, and updated through reviewable changes. Release workflows use minimized permissions and pinned third-party Actions.

**Evidence.**

- [`dependency-management.md`](../development/dependency-management.md)
- dependency audit workflow and scripts
- digest-pinned Dockerfile images
- workflow-security checks

## Claim 5: The project avoids unsupported security claims

**Argument.** Documentation distinguishes verified behavior from heuristics, requires test evidence for changes, and avoids claiming that AI-generated EDA output replaces professional engineering sign-off.

**Evidence.**

- [`CONTRIBUTING.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/CONTRIBUTING.md)
- generated tool reference
- PR template safety checklist
- release checklist in [`release-security.md`](release-security.md)

## Known limitations

- The canonical repository currently has a single maintainer; continuity and bus-factor risk are documented in [`GOVERNANCE.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/GOVERNANCE.md).
- Some EDA validations are heuristic and must be treated as review aids, not sign-off authority.
- Dynamic assertion policy is still maturing; fuzzing exists, but assertion-specific hardening remains a future improvement.
