# ChatGPT Apps Submission

Use this document for the ChatGPT Apps submission path.

## Developer Dashboard

- Dashboard URL: `https://platform.openai.com/apps`.
- Use the OpenAI Developer Platform account controlled by Osman Aslan.
- Track review status in the platform dashboard after submission.
- Keep public status mirrored in [`docs/public-listing.md`](../public-listing.md).

## Domain Verification

- [ ] Primary docs domain: `oaslananka.github.io`; final ChatGPT Apps custom-domain value must be verified in the platform before submission.
- [ ] Add the TXT record exactly as shown by the OpenAI Developer Platform.
- [ ] Do not invent the TXT token before the dashboard shows it.
- [ ] Confirm DNS propagation for the final platform-provided TXT record with `dig TXT <verified-domain>` or an equivalent DNS checker.
- [ ] Keep the TXT record until the dashboard reports verified.
- [ ] Do not put the TXT token into repository files.
- [ ] If verification fails, check registrar DNS, Cloudflare proxy state, and record name.
- [ ] Record verification completion in [`docs/public-listing.md`](../public-listing.md) notes.

## App Metadata

- [ ] Name: `KiCad MCP Pro`.
- [ ] Short description: `KiCad PCB and schematic automation through local MCP.`
- [ ] Short description length: 58 characters, below the 80 character limit.
- [ ] Long description: `KiCad MCP Pro connects ChatGPT-compatible MCP clients to local KiCad projects for project setup, schematic review, PCB inspection, validation gates, DFM checks, and gated manufacturing export. It runs locally over stdio by default, and OpenTelemetry export is disabled unless explicitly configured by the operator.`
- [ ] Long description length: below 500 characters.
- [ ] Category: `Developer Tools`.
- [ ] Support URL: `https://github.com/oaslananka/kicad-mcp/issues`.
- [ ] Privacy URL: `https://oaslananka.github.io/kicad-mcp/privacy/`.
- [ ] Repository URL: `https://github.com/oaslananka/kicad-mcp`.
- [ ] Documentation URL: `https://oaslananka.github.io/kicad-mcp`.

## Tool Annotation Exports

- [ ] Confirm annotations are exported from `src/kicad_mcp/tools/metadata.py`.
- [ ] Confirm `readOnlyHint` is surfaced for read-only inspection tools.
- [ ] Confirm `destructiveHint` is surfaced for tools that can write files or mutate projects.
- [ ] Confirm `openWorldHint` is surfaced where external or broader context may be involved.
- [ ] Confirm reviewer-facing docs describe read-only default workflows.
- [ ] Confirm destructive workflows require explicit user intent.
- [ ] Confirm manufacturing export remains gate controlled.
- [ ] Run `pnpm run submission:check` after annotation changes.

## Localization

- [ ] Launch language: English only.
- [ ] Do not claim Turkish localization at launch.
- [ ] Roadmap note: Turkish localization can be added after first approval.
- [ ] Keep screenshots and reviewer prompts in English for initial review.
- [ ] Keep privacy policy in English for directory review.
- [ ] If Turkish is added later, update metadata and docs together.

## Screenshot Requirements

- [ ] Minimum screenshot size: at least 1280x800.
- [ ] Committed screenshot slots are 1920x1080.
- [ ] Screenshot directory: `docs/assets/screenshots/`.
- [ ] Use `01-claude-desktop-quality-gate.png` for Claude Desktop quality gate capture.
- [ ] Use `02-cursor-schematic-build.png` for Cursor schematic build capture.
- [ ] Use `03-vscode-pcb-inspection.png` for VS Code PCB inspection capture.
- [ ] Use `04-tools-reference.png` for tools reference capture.
- [ ] Use `05-export-manufacturing.png` for gated manufacturing export capture.
- [ ] Run `SUBMISSION_MODE=1 pnpm run submission:check` before final upload.
- [ ] Confirm public-listing media passes final submission mode before public production submission.

## Residency Note

- [ ] Default stdio mode processes files on the user machine.
- [ ] The server itself does not operate a hosted backend.
- [ ] The server itself does not store user files remotely.
- [ ] The server itself does not collect IP addresses.
- [ ] The server itself does not set cookies.
- [ ] Optional third-party integrations are governed by their own policies.
- [ ] Nexar or Freerouting usage must be explicitly configured by the user.
- [ ] Document residency as local processing only for the default path.

## Review Controls

- [ ] Run `pnpm run submission:check` before dashboard submission.
- [ ] Run `uv run --all-extras properdocs build -f mkdocs.yml --strict` before dashboard submission.
- [ ] Attach only screenshots that avoid private paths and hostnames.
- [ ] Use fixture project evidence for all reviewer tests.
- [ ] Do not upload secrets, logs with tokens, or private KiCad designs.
- [ ] Update [`docs/public-listing.md`](../public-listing.md) after submission.

## Final ChatGPT Apps Dashboard Controls

- [ ] Confirm app name is exactly `KiCad MCP Pro`.
- [ ] Confirm short description is still at or below 80 characters.
- [ ] Confirm long description is still at or below 500 characters.
- [ ] Confirm category is `Developer Tools` unless a hardware design category is offered.
- [ ] Confirm support URL points to GitHub issues.
- [ ] Confirm privacy URL points to the GitHub Pages privacy page.
- [ ] Confirm repository URL points to the canonical GitHub repository.
- [ ] Confirm documentation URL points to the GitHub Pages site.
- [ ] Confirm the domain verification TXT record is copied only from the dashboard.
- [ ] Confirm the domain verification TXT record is not committed to the repository.
- [ ] Confirm no stale placeholder domain remains in submission docs before final upload.
- [ ] Confirm no dashboard field references a retired owner namespace.
- [ ] Confirm tool annotation evidence references `src/kicad_mcp/tools/metadata.py`.
- [ ] Confirm `readOnlyHint` is present for inspection-oriented tools.
- [ ] Confirm `destructiveHint` is present for project mutation tools.
- [ ] Confirm `openWorldHint` is present where broader context may be used.
- [ ] Confirm annotation exports are regenerated after tool registry changes.
- [ ] Confirm the complete tool catalog is generated before dashboard upload.
- [ ] Confirm screenshots are at least 1280x800.
- [ ] Confirm committed screenshot slots remain 1920x1080.
- [ ] Confirm committed public-listing screenshots pass final submission mode before final launch.
- [ ] Confirm screenshot filenames match the manifest in `docs/assets/screenshots/README.md`.
- [ ] Confirm screenshots avoid local usernames, machine names, and private paths.
- [ ] Confirm screenshots use the fixture project or sanitized demo data only.
- [ ] Confirm reviewer prompts are copied from `docs/submission/reviewer-test-prompts.md`.
- [ ] Confirm machine-readable prompts match `tests/reviewer/prompts.json`.
- [ ] Confirm the app does not claim hosted data residency for stdio mode.
- [ ] Confirm the app describes default processing as local-only.
- [ ] Confirm the app says OpenTelemetry export is disabled by default and operator-configured only.
- [ ] Confirm the app does not request OAuth for local stdio review.
- [ ] Confirm optional HTTP mode is described as a separate configured deployment path.
- [ ] Confirm HTTP mode notes mention bearer auth for production.
- [ ] Confirm HTTP mode notes mention explicit CORS allowlists for production.
- [ ] Confirm optional Freerouting Docker is described as opt-in.
- [ ] Confirm optional Nexar integration is described as user configured.
- [ ] Confirm `pnpm run submission:check` passes before dashboard save.
- [ ] Confirm `pnpm run assets:icons:check` passes before icon upload.
- [ ] Confirm `pnpm run docs:tools:check` passes before tool evidence upload.
- [ ] Confirm `uv run --all-extras properdocs build -f mkdocs.yml --strict` passes before docs URL review.
- [ ] Confirm `lychee --verbose --no-progress README.md docs/**/*.md` passes before link review.
- [ ] Confirm `SUBMISSION_MODE=1 pnpm run submission:check` fails only for real blockers before final screenshots are approved.
- [ ] Confirm `SUBMISSION_MODE=1 pnpm run submission:check` passes after real screenshots are committed.
- [ ] Confirm the README demo GIF exists before dashboard reviewers open the repository.
- [ ] Confirm the README demo GIF contains no real hostnames or local filesystem paths.
- [ ] Confirm the privacy page states personal information is not collected.
- [ ] Confirm the privacy page states telemetry is disabled by default and optional OpenTelemetry export is explicit.
- [ ] Confirm the privacy page explains optional third-party integrations separately.
- [ ] Confirm the safety statement explains filesystem scope restrictions.
- [ ] Confirm the safety statement explains subprocess scope.
- [ ] Confirm the safety statement explains reproducible release verification.
- [ ] Confirm package version values are synchronized before submission.
- [ ] Confirm PyPI, GHCR, and documentation links match the current version being reviewed.
- [ ] Confirm reviewer-facing copy remains in English at launch.
- [ ] Confirm Turkish localization is described only as future work.
- [ ] Confirm approval and rejection status are recorded in [`docs/public-listing.md`](../public-listing.md) after dashboard updates.
- [ ] Confirm no private dashboard screenshots are committed.
- [ ] Confirm no API keys, OAuth secrets, or auth cookies appear in evidence.
- [ ] Confirm no customer board files are attached to the submission.
- [ ] Confirm the current branch is clean before final evidence is captured.
- [ ] Confirm GitHub checks for the submission branch are green before merging.
- [ ] Confirm the public docs site is reachable after the merge to `main`.
- [ ] Confirm post-approval operations are recorded in the public listing source of truth.
