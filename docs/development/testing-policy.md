# Testing Policy

KiCad MCP Pro requires automated validation for behavior changes, public tool contract changes, release workflow changes, and security-sensitive changes.

## Required tests by change type

| Change type | Required validation |
| --- | --- |
| Pure Python logic | Unit tests and type checks. |
| KiCad artifact parsing | Fixture tests with representative `.kicad_*` samples. |
| MCP tool contract | Metadata checks, generated docs, and tool-surface snapshot tests. |
| TypeScript integration | TypeScript typecheck and unit tests where available. |
| Filesystem or subprocess behavior | Negative tests for traversal, unsafe extensions, missing files, and failure modes. |
| Release or package workflow | Dry-run or metadata verification plus workflow-security checks. |
| Documentation-only change | Markdown/docs build and link-sensitive review. |

## Regression tests

Bug fixes should include a regression test when the defect is reproducible in unit, fixture, or integration scope. If a regression test cannot be added, the PR must explain why and include manual validation evidence.

## Coverage policy

The Python coverage gate is configured in `pyproject.toml` with `tool.coverage.report.fail_under = 83`, which satisfies the OpenSSF Silver 80% statement-coverage target for the Python package. Coverage should continue to increase over time, but critical tool paths remain prioritized over raw percentage targets.

## Continuous integration

CI runs on pull requests and pushes to `main`. Required jobs cover server behavior, npm/package wrappers, protocol schemas, security checks, CodeQL, docs, Gitleaks, and Scorecard.

## Fuzzing

Atheris fuzz smoke testing covers shared KiCad S-expression helpers. Fuzzing should expand to additional parsers and file import boundaries as those surfaces grow.

## Git subprocess isolation

Tests that initialize or mutate Git repositories must use test-owned temporary directories and an isolated process environment. Set `HOME`, `XDG_CONFIG_HOME`, `GIT_CONFIG_GLOBAL`, and `GIT_CONFIG_SYSTEM` to test-owned paths, disable system configuration, and use an empty `GIT_TEMPLATE_DIR` so contributor hooks and templates cannot enter fixtures.

Production Git helpers discard repository-local variables such as `GIT_DIR`, `GIT_WORK_TREE`, and `GIT_INDEX_FILE` before spawning Git. Regression tests must seed hostile caller values and prove the source checkout status, unstaged diff, and staged diff remain unchanged across normal and failure paths. Destructive operations must revalidate the resolved repository root immediately before mutation.
