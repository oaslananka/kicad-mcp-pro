# Failure Classifier

`scripts/classify-gh-failure.mjs` maps failed GitHub Actions logs to repository
operations failure classes. It is a read-only helper for maintainers and the
manual `actions-maintenance.yml` workflow.

The classifier emits:

- `classification`;
- `root_cause`;
- `safe_fix`;
- `auto_fix_allowed`;
- `publish_must_stop`;
- `human_approval_required`.

## Classes

- `trusted-publisher-mismatch`
- `non-python-asset-uploaded-to-pypi`
- `sigstore-uv-config-conflict`
- `release-metadata-drift`
- `changelog-release-please-noise`
- `post-publish-smoke-propagation-delay`
- `release-tag-collision`
- `workflow-syntax`
- `test-failure`
- `typecheck-failure`
- `lint-failure`
- `infra-flake`
- `unknown`

## Usage

Classify a saved log:

```bash
node scripts/classify-gh-failure.mjs --file failed.log
```

Classify a GitHub Actions run with `gh`:

```bash
node scripts/classify-gh-failure.mjs \
  --repo oaslananka/kicad-mcp-pro \
  --run-id 123456789 \
  --json
```

The classifier must not be used to justify publishing after a release failure.
If `publish_must_stop=true`, stop the release path and fix the root cause in a
normal PR.
