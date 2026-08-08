# Codecov coverage and test analytics

Codecov is an external reporting layer over the repository's existing test
quality gates. It does not replace pytest, the local 83% coverage minimum, or
the Required PR Gate.

## CI contract

The `CI Tests / Coverage` job runs the full Python unit, integration, and
headless E2E suite on Ubuntu for Python and workflow changes, and on every push
to `main`. NPM/schema-only pull requests keep the same visible check but use a
cheap no-op. The test driver continues to force pytest's temporary directory
outside the checkout. The job emits:

- `coverage.xml` for Python source coverage;
- `python.junit.xml` for Codecov Test Analytics and failed-test reporting.

Reports from `main`, manual runs, and repository-owned pull requests are
uploaded with GitHub OIDC, so those contexts do not consume the long-lived
`CODECOV_TOKEN`. Public fork pull requests use Codecov's tokenless public-repo
path. The Codecov Action is pinned to an immutable commit SHA, CLI integrity
validation remains enabled, and Codecov telemetry is disabled.

The pytest step uses `continue-on-error` only to allow coverage and JUnit
reports to upload after a failing test. A final step propagates the original
test failure, so test failures still block the Required PR Gate.

## Rollout policy

Repository-level `codecov.yml` uses relative `auto` targets and initially
marks project and patch statuses as informational. The local pytest gate remains
authoritative at 83%. After a
stable baseline exists across normal pull requests, a separate reviewed change
may make Codecov status checks blocking and add them to the branch ruleset.

Upload failures are non-blocking during this first phase so an external Codecov
outage cannot prevent maintenance or security fixes. Upload logs must still be
reviewed when changing the workflow.

## Coverage scope

Codecov is largely language-agnostic once a supported coverage report exists.
The `python-full` flag currently covers `src/kicad_mcp/` because pytest-cov
already produces Cobertura XML. TypeScript packages currently use
compile-and-execute contract tests without an instrumented coverage producer,
and the Tauri bridge currently runs `cargo check` plus Rust contract tests rather than Rust coverage.
They should not upload fabricated or partial coverage reports.

## Bundle analysis decision

Codecov Bundle Analysis is intentionally not enabled yet. The shipped desktop
frontend and dashboard are inline/static HTML rather than a production
Vite/Rollup/Webpack bundle. Adding a bundler plugin now would not produce a
meaningful module graph. Enable Bundle Analysis when the frontend adopts a real
production bundle pipeline; at that point use OIDC, disable plugin telemetry,
and start with an informational size threshold.

## Validation

Validate repository configuration before merging changes:

```bash
curl --fail-with-body --data-binary @codecov.yml https://codecov.io/validate
```

Workflow changes must also pass the repository action-policy checker,
actionlint, Zizmor, and the focused Codecov contract tests.

## References

- [Codecov Quick Start](https://docs.codecov.com/docs/quick-start)
- [About code coverage](https://docs.codecov.com/docs/about-code-coverage)
- [Supported languages](https://docs.codecov.com/docs/supported-languages)
- [Codecov YAML](https://docs.codecov.com/docs/codecov-yaml)
- [Test Analytics and failed-test reporting](https://docs.codecov.com/docs/test-analytics#failed-test-reporting)
- [JavaScript Bundle Analysis](https://docs.codecov.com/docs/javascript-bundle-analysis)
