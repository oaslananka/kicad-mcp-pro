# Scorecard Exceptions and Remediation Plan

This page records OpenSSF Scorecard findings that are not immediate code vulnerabilities and explains the current project policy, accepted risk, and remediation path.

## Current accepted exceptions

| Check | Current status | Rationale | Remediation path |
| --- | --- | --- | --- |
| CI-Tests | Accepted upstream false positive | OpenSSF Scorecard v5.0.0 continued to report 0/30 after receiving the required read-only metadata scopes. A checksum-verified reproduction identified the exact 30 pull-request HEAD SHAs, and direct GitHub REST verification found completed, successful `github-actions` CheckRuns on 30/30 of them. | Keep the protected operating-system matrices, `CI Tests / Coverage`, and `Required PR Gate`. A long-lived PAT must not be added solely to satisfy this low-severity heuristic. Re-evaluate after an upstream Scorecard client or Action update. Evidence: `docs/evidence/scorecard-ci-tests-rest-verification-2026-07-21.json`. |
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

Code-bearing pull requests cannot merge unless the protected operating-system
server matrix, `CI Tests / Coverage`, and `Required PR Gate` succeed. The
Scorecard job retains read-only access to `pull-requests`, `checks`, `statuses`,
and `actions`; it receives no write permission for those metadata scopes.

The deployed OpenSSF Scorecard v5.0.0 binary was downloaded from the official
release, verified against its published SHA-256 checksum, and run against the
repository with the `CI-Tests` check and debug details enabled. It reproduced
`0 out of 30 merged PRs checked by a CI test` and listed the exact 30 pull-request
HEAD SHAs used by the detector.

Each listed SHA was then queried through GitHub's Check Runs REST endpoint. All
30/30 SHAs had completed, successful CheckRuns owned by the `github-actions`
application. Each SHA had 15–27 successful CheckRun records, representing 14–26
distinct successful check names. The checked-in machine-readable evidence is:

- `docs/evidence/scorecard-ci-tests-rest-verification-2026-07-21.json`

The upstream implementation explains the mismatch:

- The `CI-Tests` collector associates merged pull requests with their HEAD SHA
  and requests CheckRuns for that SHA.
- The probe accepts a successful CheckRun when the application slug matches a
  recognized CI provider, including `github-actions`.
- The GitHub client contains an explicit warning that its GraphQL CheckSuite
  query does not work with `GITHUB_TOKEN` and works only with a PAT. An
  empty-but-successful GraphQL result can therefore avoid the REST cache-miss
  fallback even though REST returns the successful CheckRuns.

Exact upstream sources for the deployed Scorecard commit:

- <https://github.com/ossf/scorecard/blob/ea7e27ed41b76ab879c862fa0ca4cc9c61764ee4/checks/raw/ci_tests.go>
- <https://github.com/ossf/scorecard/blob/ea7e27ed41b76ab879c862fa0ca4cc9c61764ee4/probes/testsRunInCI/impl.go>
- <https://github.com/ossf/scorecard/blob/ea7e27ed41b76ab879c862fa0ca4cc9c61764ee4/clients/githubrepo/checkruns.go>

## CI-Tests risk decision

Code-scanning alert #10 is classified as a false positive, not as remediated CI
behavior. Introducing a repository or organization PAT would add a long-lived
credential and broader operational risk without strengthening the actual merge
gate. A long-lived PAT must not be added solely to make this heuristic report a
higher score.

The alert may be dismissed with reason `false_positive` only while all of the
following remain true:

1. The evidence file verifies successful `github-actions` CheckRuns on every SHA
   that Scorecard reports as untested.
2. The protected branch continues to require the operating-system test matrix,
   CodeQL, dependency review, Gitleaks, and `Required PR Gate`.
3. `CI Tests / Coverage` continues to run the full Python suite and upload both
   coverage and JUnit/Test Analytics evidence.
4. No successful upstream Scorecard run contradicts the recorded detector
   limitation.

Re-open the investigation after a Scorecard Action/client upgrade, a change to
GitHub token behavior, or any modification to the required-check ruleset.
