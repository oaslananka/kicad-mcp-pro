# SDD ledger — plan: static-analysis-remediation-plan.md

Pre-flight: no shared interfaces — tasks are independent refactoring batches
Task 0: complete (commits cad4f3ad..dfe450d7, security fixes: SHA256 migration, subprocess hardening, SQL PRAGMA and web artifact path traversal annotations)
Task 1: complete (Tier 1 Cognitive Complexity CC >= 40 all 22 items decomposed and verified)
Task 2: complete (S107 Too Many Parameters all 6 target functions refactored to dataclasses or kwargs)
Task 3: complete (Tier 2 Cognitive Complexity CC 25-39: all SonarCloud issues remediated and verified with 0 issues on PR #1355 diff; decomposed stackup parsing and bitmap art in tools/pcb.py; aligned ProjectDesignSpecServiceProtocol parameter type; Semgrep and Codacy clean; SonarCloud quality gate status OK). PR: https://github.com/oaslananka/kicad-mcp-pro/pull/1355
