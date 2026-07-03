# Submission Readiness Checklist

This page is the working index for public listing submissions.
It links platform-specific instructions to the listing source of truth: [`docs/public-listing.md`](../public-listing.md).
Use this checklist before entering any external review form.

## Platform Documents

- [ ] Open [`anthropic-directory.md`](anthropic-directory.md) before submitting to the Anthropic Connector Directory.
- [ ] Open [`chatgpt-apps.md`](chatgpt-apps.md) before submitting to ChatGPT Apps.
- [ ] Open [`openai-mcp-registry.md`](openai-mcp-registry.md) before publishing to the OpenAI/MCP registry.
- [ ] Open [`reviewer-test-prompts.md`](reviewer-test-prompts.md) before sending reviewer instructions.
- [ ] Open [`safety-and-permissions.md`](safety-and-permissions.md) before answering security questions.
- [ ] Open [`docs/public-listing.md`](../public-listing.md) before recording submission status.

## Identity Fields

- [ ] Owner account is `oaslananka`.
- [ ] Maintainer name is `Osman Aslan`.
- [ ] Contact handle is `oaslananka`.
- [ ] Primary docs domain is `oaslananka.github.io`; ChatGPT Apps custom-domain verification remains a manual platform step before final submission.
- [ ] Repository URL is `https://github.com/oaslananka/kicad-mcp`.
- [ ] Documentation URL is `https://oaslananka.github.io/kicad-mcp`.
- [ ] Privacy URL is `https://oaslananka.github.io/kicad-mcp/privacy/`.
- [ ] Support URL is `https://github.com/oaslananka/kicad-mcp/issues`.
- [ ] MCP server name is `io.github.oaslananka/kicad-mcp-pro`.
- [ ] Package name is `kicad-mcp-pro`.
- [ ] Container image is `ghcr.io/oaslananka/kicad-mcp-pro:<version>`.
- [ ] Transport for directory reviewers is `stdio`.

## Repository Evidence

- [ ] Confirm `pyproject.toml` version matches `server.json` and `src/kicad_mcp/__init__.py`.
- [ ] Confirm `server.json` declares `name` as `io.github.oaslananka/kicad-mcp-pro`.
- [ ] Confirm `server.json` declares repository URL as `https://github.com/oaslananka/kicad-mcp`.
- [ ] Confirm README references the demo media slot `docs/assets/demo.gif`.
- [ ] Confirm README links to the public listing page.
- [ ] Confirm README links to the privacy policy.
- [ ] Confirm `docs/privacy.md` states telemetry is disabled by default and optional OpenTelemetry export is explicit.
- [ ] Confirm `docs/assets/icon.svg` exists and is the canonical vector icon.
- [ ] Confirm `docs/assets/icon-512.png` is 512x512.
- [ ] Confirm `docs/assets/screenshots/` contains five 1920x1080 image slots.
- [ ] Confirm `docs/assets/demo.cast` parses as asciinema v2 JSON Lines.
- [ ] Confirm `tests/reviewer/prompts.json` contains exactly five prompts.

## Anthropic Directory Checklist

- [ ] Use submission URL `https://clau.de/mcp-directory-submission`.
- [ ] Set product name to `KiCad MCP Pro`.
- [ ] Set category to `EDA / Hardware Design` when available.
- [ ] Use fallback category `Developer Tools` only if EDA is unavailable.
- [ ] Set transport to `stdio`.
- [ ] Paste repository URL exactly as `https://github.com/oaslananka/kicad-mcp`.
- [ ] Paste privacy URL exactly as `https://oaslananka.github.io/kicad-mcp/privacy/`.
- [ ] Paste support URL exactly as `https://github.com/oaslananka/kicad-mcp/issues`.
- [ ] State that OAuth is not required because the server is local stdio.
- [ ] State that manufacturing export is gated by `project_quality_gate`.

## ChatGPT Apps Checklist

- [ ] Use the OpenAI Developer Platform app submission area at `https://platform.openai.com/apps`.
- [ ] Verify the final ChatGPT Apps custom domain using the TXT record required by the platform before submitting the ChatGPT Apps form.
- [ ] Use app name `KiCad MCP Pro`.
- [ ] Use short description no longer than 80 characters.
- [ ] Use long description no longer than 500 characters.
- [ ] Set category to `Developer Tools`.
- [ ] Use support URL `https://github.com/oaslananka/kicad-mcp/issues`.
- [ ] Use privacy URL `https://oaslananka.github.io/kicad-mcp/privacy/`.
- [ ] Use screenshots from `docs/assets/screenshots/`.
- [ ] Confirm tool annotations expose `readOnlyHint`, `destructiveHint`, and `openWorldHint`.

## OpenAI MCP Registry Checklist

- [ ] Run `pnpm run submission:check` before registry dry run.
- [ ] Run `uv run --all-extras python scripts/publish_mcp_registry.py --dry-run` before live publish.
- [ ] Use `server.json` as the registry source of truth.
- [ ] Confirm PyPI Trusted Publisher OIDC is enabled for release workflow.
- [ ] Confirm GHCR image is available as `ghcr.io/oaslananka/kicad-mcp-pro:<version>`.
- [ ] Confirm release artifacts include SBOM evidence.
- [ ] Confirm release artifacts include SHA-256 checksums.
- [ ] Confirm release artifacts include Sigstore signatures.
- [ ] Confirm release artifacts include GitHub provenance attestations.
- [ ] Do not publish if metadata version values differ.

## Reviewer Package Checklist

- [ ] Use fixture directory `tests/fixtures/benchmark_projects/pass_sensor_node/` for all reproducible reviewer prompts.
- [ ] Use fixture project `tests/fixtures/benchmark_projects/pass_sensor_node/demo.kicad_pro` for project-specific prompts.
- [ ] Run prompt `p1-health` to verify tool discovery and KiCad CLI readiness.
- [ ] Run prompt `p2-set-project-quality-gate` to verify project quality gate behavior.
- [ ] Run prompt `p3-schematic-connectivity` to verify schematic read path.
- [ ] Run prompt `p4-pcb-state` to verify PCB state read path.
- [ ] Run prompt `p5-manufacturing-export-gate` to verify gated export behavior.
- [ ] Explain wrong-path failures as caller configuration issues, not server defects.
- [ ] Include PASS response shape for each prompt.
- [ ] Do not include private boards or customer design files in reviewer evidence.

## Preflight Commands

- [ ] Run `pnpm run metadata:check`.
- [ ] Run `pnpm run mcp:manifest:check`.
- [ ] Run `pnpm run assets:icons:check`.
- [ ] Run `pnpm run submission:check`.
- [ ] Run `SUBMISSION_MODE=1 pnpm run submission:check` and require it to pass before final external submissions.
- [ ] Run `pnpm run docs:tools:check` after the generated catalog exists.
- [ ] Run `pnpm run release:dry-run`.
- [ ] Run `uv run --all-extras properdocs build -f mkdocs.yml --strict`.

## Manual Submission Log

- [ ] Record every submission in [`docs/public-listing.md`](../public-listing.md) after the external form is sent.
- [ ] Record target name exactly as `Anthropic Connector Directory`, `ChatGPT Apps`, or `OpenAI/MCP Registry`.
- [ ] Record submitted timestamp in UTC.
- [ ] Record approved timestamp in UTC when approval arrives.
- [ ] Record listing URL only after it is public.
- [ ] Record rejection notes without copying private reviewer messages into public issues.
- [ ] Open a GitHub issue for any required repo change from a reviewer.
- [ ] Close the issue only after the listing source of truth is updated.

## Final Gate

- [ ] Do not submit while `pnpm run submission:check` fails.
- [ ] Do not submit while `properdocs build -f mkdocs.yml --strict` fails.
- [ ] Do not submit while version metadata is out of sync.
- [ ] Do not submit unless final public-listing screenshot assets pass `SUBMISSION_MODE=1`.
- [ ] Do not submit with any secret value in logs or screenshots.
- [ ] Do not submit with old organization namespace strings.
- [ ] Confirm CI and trusted publishing workflows use GitHub-hosted runners.
## Final Evidence Controls

- [ ] Confirm every platform-specific document has been reviewed in the same branch as the submission.
- [ ] Confirm [`docs/public-listing.md`](../public-listing.md) is the only place where external submission status is recorded.
- [ ] Confirm the README public listing section links to the root status file.
- [ ] Confirm the README documentation section does not duplicate the same public listing link.
- [ ] Confirm the demo GIF exists locally and is committed.
- [ ] Confirm link checking passes with the same lychee command used by the docs workflow.
- [ ] Confirm generated icon assets pass dimension checks before any dashboard upload.
- [ ] Confirm reviewer prompt JSON remains synchronized with the human-readable prompt guide.
- [ ] Confirm release evidence is current before referencing Sigstore or provenance in forms.
- [ ] Confirm public-listing screenshots are committed and pass final submission mode before production submission.
- [ ] Confirm final submission mode fails only for real blockers, not for stale placeholder media.
- [ ] Confirm the current branch has no unrelated dirty files before merge.
- [ ] Confirm all GitHub PR checks are green before merging to `main`.
- [ ] Confirm the PR is merged or closed so no stale submission PR remains open.
- [ ] Confirm the remote feature branch is deleted after merge if GitHub does not delete it automatically.
- [ ] Confirm docs deployment from `main` succeeds before marking listing docs live.
- [ ] Confirm GitHub Pages serves the privacy policy after deployment.
- [ ] Confirm the maintainer records manual directory submissions only after external forms are sent.
- [ ] Confirm any reviewer rejection is tracked as an issue with no private content.
- [ ] Confirm the next public listing pass starts by rerunning this checklist.
- [ ] Confirm all copied URLs are taken from this repo, not browser history or stale notes.
- [ ] Confirm no private workspace path appears in copied evidence.
- [ ] Confirm no automation token or auth state appears in copied evidence.
- [ ] Confirm post-approval operations update docs and manifests in the same release cycle.
- [ ] Confirm the final release branch contains no temporary `.bak`, `.orig`, or `.new` files.
- [ ] Confirm NotebookLM sync notes, if used, do not include secrets or local auth files.
