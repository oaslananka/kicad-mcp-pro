# Review Thread Gate

`scripts/check-review-threads.mjs` queries GitHub GraphQL
`PullRequest.reviewThreads` and summarizes unresolved PR review feedback.

The gate is intentionally conservative:

- resolved threads are ignored;
- outdated threads are ignored;
- unresolved, non-outdated human review threads block;
- bot review threads block only when they contain actionable terms such as
  `Bug:`, `Potential issue:`, `Suggested Fix`, `security`, `release`,
  `publish`, `workflow`, `secret`, `token`, or `unsafe`;
- pure informational bot comments do not block.

The script writes both:

- `review-thread-summary.json`;
- `review-thread-summary.md`.

## Usage

```bash
node scripts/check-review-threads.mjs \
  --repo oaslananka/kicad-mcp-pro \
  --pr 123 \
  --fail-on-blocked
```

The script is read-only by default. It does not resolve review threads and does
not mark a PR ready for review. Humans remain responsible for resolving human
review threads after verifying the fix.
