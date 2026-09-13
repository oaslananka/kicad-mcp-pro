# KiCad 11 Preview Courtyard Rule Compatibility Design

## Problem

The KiCad 11 preview lane currently installs KiCad nightly `10.99.0` and fails DRC before rule execution because the maintained fixture rule predicate

```text
(condition "A.Footprint != '' && B.Footprint != ''")
```

no longer compiles. The failing rules are the fixture courtyard-clearance rules. KiCad 10.0.6 remains green.

A same-SHA rerun reproduced the failure. A diagnostic workflow isolated the failures to `clean-drc` and `dirty-drc`, both returning code 3 with `DRC incomplete: could not compile custom design rules`. Removing only the predicate from copies of the two failing `.kicad_dru` files made the complete KiCad 10.99 canary pass.

## Design

Keep the courtyard-clearance constraint and remove only the now-invalid `A.Footprint`/`B.Footprint` predicate from every maintained fixture that carries the same rule pattern. The constraint itself is already courtyard-specific, so the predicate is redundant for the fixture intent.

Add a regression test that scans the shared fixture corpus and rejects the removed KiCad 10.99 `Footprint` rule property so the incompatibility cannot silently return.

The fixture README currently documents a generator and root scripts that are absent from this repository and absent from its imported history. Do not invent a new generator in this compatibility fix. Correct the maintenance instructions to describe the checked-in fixture corpus and the validation commands that actually exist.

## Scope

Change only:

- the seven maintained `.kicad_dru` fixtures that contain the invalid predicate;
- the KiCad canary unit regression test;
- fixture maintenance documentation;
- this design and its implementation plan.

Do not change MCP product behavior, compatibility claims, feature gates, canary pass/fail semantics, or the KiCad 10.0.6 expected DRC outcomes.

## Acceptance

- Regression test fails on current `main` because at least one maintained fixture contains `A.Footprint` / `B.Footprint`.
- After the fixture update, the focused unit test and full `test_kicad_canary.py` pass.
- Fixture package validation passes.
- Repository lint/format/diff checks for changed files pass.
- Pull-request CI passes the stable KiCad 10.0.6 canary.
- Pull-request KiCad 11 preview smoke passes against the then-current nightly, or any new failure is independently diagnosed rather than suppressed.
## CI trigger coverage discovered during implementation

The live KiCad workflow originally watched `tests/fixtures/**` but not the actual shared corpus at `packages/kicad-fixtures/fixtures/**`. That meant a fixture-only compatibility repair could bypass the live KiCad pull-request canaries. The bounded fix therefore also adds the shared corpus path to both pull-request and main-push filters, protected by a workflow-contract regression test.
