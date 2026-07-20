# Scorecard Exceptions and Remediation Plan

This page records OpenSSF Scorecard findings that are not immediate code vulnerabilities and explains the current project policy, accepted risk, and remediation path.

## Current accepted exceptions

| Check | Current status | Rationale | Remediation path |
| --- | --- | --- | --- |
| CI-Tests | Remediation in progress | The Scorecard job declared an explicit permission map but omitted `checks`, `statuses`, and `pull-requests`. GitHub therefore supplied `none` for those scopes, so Scorecard could not inspect the successful CheckRuns attached to recent merged pull requests and reported 0/30 despite the protected multi-platform CI gate. | Grant read-only access to those three metadata scopes, keep all mutation scopes disabled, rerun Scorecard, and retain the required `mcp-server` test matrix plus `Required PR Gate` in the main ruleset. |
| Branch-Protection | Accepted temporary exception | `main` is protected by a GitHub ruleset that blocks deletion and force-pushes, requires pull requests, requires linear history, requires CI/CodeQL/Gitleaks checks, and requires resolved review threads. Required human approval, code-owner review, and last-push approval are intentionally not enabled while the repository has a single trusted maintainer because doing so can block routine maintenance and security fixes. | Enable required approvals, code-owner review, and last-push approval after adding a second trusted maintainer with verified signing and review availability. |
| Code-Review | Accepted temporary exception | Recent changes are single-maintainer changes. Bot review and automated analysis are not a substitute for independent human review, so Scorecard correctly cannot award full credit yet. | Recruit at least one additional trusted maintainer and require independent human review for protected-branch merges. |
| Maintained | Accepted time-based exception | The repository is new, and Scorecard intentionally treats projects younger than 90 days as too new to assess long-term maintenance. | Re-run Scorecard after the repository has more than 90 days of public history and weekly maintenance activity. |
| SAST | Monitoring | CodeQL is configured for Python and JavaScript/TypeScript and runs on pull requests, pushes to `main`, schedules, and manual dispatches. Scorecard currently reports partial credit because recent commit history is still catching up with SAST evidence. | Continue running CodeQL on every protected branch change; the signal should improve as reviewed/merged changes accumulate with CodeQL results. |
| CII-Best-Practices | Pending external form update | The repository has local evidence for OpenSSF Best Practices, but the public OpenSSF badge remains `InProgress` until the external Best Practices form is completed and submitted. | Complete the OpenSSF Best Practices checklist using `docs/openssf-best-practices.md` evidence links, then re-run Scorecard. |

## Findings remediated in this hardening pass

- CodeQL `js/path-injection` findings were remediated by `SafeFsPath` validation and upload-root containment in the ChatGPT Apps SDK integration.
- Scorecard `Pinned-Dependencies` findings for the container build were remediated by replacing Dockerfile `pip install` steps with a digest-pinned `uv` image and `uv`-based install steps.
- Scorecard `Fuzzing` was remediated by adding an Atheris fuzz target and scheduled fuzz workflow.

## Review policy

Accepted Scorecard exceptions must be revisited before each release and after any maintainer or repository-permission change. Do not dismiss a finding without either fixing it or documenting the accepted-risk rationale here.
## CI-Tests detection contract

The Scorecard CI-Tests check reads recent pull-request associations, CheckRuns, and commit statuses. The Scorecard job therefore has read-only access to `pull-requests`, `checks`, and `statuses`; it does not receive write access to any of them. Code-bearing pull requests remain unable to merge unless the operating-system server matrix and `Required PR Gate` succeed under the active `main` ruleset.

A Scorecard run after a permission change is the authoritative detection check. Keep the alert open if the upstream detector still cannot associate successful GitHub Actions checks, and record that limitation rather than weakening the merge gate.
