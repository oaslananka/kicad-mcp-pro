# Anthropic Connector Directory Submission

Use this document when submitting KiCad MCP Pro to the Anthropic Connector Directory.

## Submission URL

- Submit at `https://clau.de/mcp-directory-submission`.
- Keep a copy of the submitted field values in [`docs/public-listing.md`](../public-listing.md).
- Use UTC timestamps for submitted and approved dates.
- Do not paste secret values into the submission form.

## Exact Field Values

- [ ] Server name: `KiCad MCP Pro`.
- [ ] Short description: `Local KiCad MCP server for PCB, schematic, validation, and manufacturing workflows.`
- [ ] Category: `EDA / Hardware Design`.
- [ ] Fallback category: `Developer Tools`.
- [ ] Transport: `stdio`.
- [ ] Repository URL: `https://github.com/oaslananka/kicad-mcp-pro`.
- [ ] Privacy URL: `https://oaslananka.github.io/kicad-mcp-pro/privacy/`.
- [ ] Support URL: `https://github.com/oaslananka/kicad-mcp-pro/issues`.
- [ ] Documentation URL: `https://oaslananka.github.io/kicad-mcp-pro`.
- [ ] Package install command: `uvx kicad-mcp-pro`.
- [ ] MCP server name: `io.github.oaslananka/kicad-mcp-pro`.
- [ ] License: `MIT`.

## OAuth Section

- [ ] State: `KiCad MCP Pro is a local stdio MCP server and does not require OAuth.`
- [ ] State: `The server does not host a user account system.`
- [ ] State: `The server does not request Anthropic user credentials.`
- [ ] State: `The server does not require browser redirect flows.`
- [ ] State: `HTTP mode is optional and separate from the directory review path.`
- [ ] State: `Any optional bearer token is local operator configuration, not OAuth.`
- [ ] Do not claim OAuth support in the Anthropic form.
- [ ] Do not attach OAuth screenshots.

## Safety Story

- [ ] Default reviewer path is local stdio.
- [ ] The server processes KiCad project files on the reviewer machine.
- [ ] Telemetry is disabled by default; optional OpenTelemetry export requires explicit operator configuration.
- [ ] No network egress is required for the default stdio workflow.
- [ ] KiCad CLI is the only required subprocess for default operation.
- [ ] Optional Freerouting Docker is separate and operator-enabled.
- [ ] Manufacturing package export is gated by `project_quality_gate`.
- [ ] Read-only tools are annotated as read-only in metadata.
- [ ] Destructive tools are marked with destructive metadata.
- [ ] Open-world behavior is surfaced through tool annotations.
- [ ] Filesystem scope is constrained by project directory and workspace root.
- [ ] Diagnostics report token presence only, not token values.

## Reviewer Test Plan

- [ ] Fixture path: `tests/fixtures/benchmark_projects/pass_sensor_node/`.
- [ ] Fixture project: `tests/fixtures/benchmark_projects/pass_sensor_node/demo.kicad_pro`.
- [ ] Prompt 1: `Call kicad-mcp-pro's health check and tell me which subsystems are ready.`
- [ ] Prompt 1 expected tool call: `kicad_get_version`.
- [ ] Prompt 1 expected result: version and KiCad CLI status are reported.
- [ ] Prompt 2: `Set the project to the pass_sensor_node fixture and run project_quality_gate.`
- [ ] Prompt 2 expected tool calls: `kicad_set_project`, `project_quality_gate`.
- [ ] Prompt 2 expected result: gate summary and fix queue are visible.
- [ ] Prompt 3: `Inspect schematic connectivity for the pass_sensor_node fixture without editing files.`
- [ ] Prompt 3 expected tool call: `schematic_connectivity_gate`.
- [ ] Prompt 3 expected result: connectivity status is returned without file edits.

## Example Reviewer Prompts

- [ ] Example prompt A: `Use KiCad MCP Pro to verify the fixture project health and summarize ready subsystems.`
- [ ] Example prompt B: `Run the project quality gate on tests/fixtures/benchmark_projects/pass_sensor_node/demo.kicad_pro and explain any blockers.`
- [ ] Example prompt C: `Attempt a manufacturing package export and explain why it is allowed or blocked by the gate.`
- [ ] For every prompt, instruct the reviewer to use the committed fixture, not a private board.
- [ ] For every prompt, explain that wrong absolute paths are client configuration failures.

## Expected Timeline

- [ ] Set expectation to approximately two weeks for initial review.
- [ ] Do not promise a fixed Anthropic approval date.
- [ ] Check email and GitHub issues daily during the review period.
- [ ] If rejected, copy only actionable technical requirements into a public issue.
- [ ] If approved, update [`docs/public-listing.md`](../public-listing.md) with the public listing URL.

## Rejection-Prevention Checklist

- Known rejection cause: Unclear server identity.
- Concrete repo control: Use `KiCad MCP Pro` and `io.github.oaslananka/kicad-mcp-pro` consistently.
- Reviewer response: point to the exact file or command, then rerun `pnpm run submission:check`.
- Known rejection cause: Missing privacy policy.
- Concrete repo control: Use `https://oaslananka.github.io/kicad-mcp-pro/privacy/` and `docs/privacy.md`.
- Reviewer response: point to the exact file or command, then rerun `pnpm run submission:check`.
- Known rejection cause: Unsafe filesystem access.
- Concrete repo control: Reference `path_safety.py`, project dir, and workspace root.
- Reviewer response: point to the exact file or command, then rerun `pnpm run submission:check`.
- Known rejection cause: Unbounded write operations.
- Concrete repo control: Reference destructive annotations and gated manufacturing export.
- Reviewer response: point to the exact file or command, then rerun `pnpm run submission:check`.
- Known rejection cause: No reviewer fixture.
- Concrete repo control: Use `tests/fixtures/benchmark_projects/pass_sensor_node/demo.kicad_pro`.
- Reviewer response: point to the exact file or command, then rerun `pnpm run submission:check`.
- Known rejection cause: OAuth confusion.
- Concrete repo control: State that local stdio does not need OAuth.
- Reviewer response: point to the exact file or command, then rerun `pnpm run submission:check`.
- Known rejection cause: Network egress concern.
- Concrete repo control: State that default stdio has no server network egress.
- Reviewer response: point to the exact file or command, then rerun `pnpm run submission:check`.
- Known rejection cause: Package provenance concern.
- Concrete repo control: Reference PyPI Trusted Publisher, Sigstore, GHCR provenance, and SBOM.
- Reviewer response: point to the exact file or command, then rerun `pnpm run submission:check`.
- Known rejection cause: Incomplete tool annotations.
- Concrete repo control: Reference `src/kicad_mcp/tools/metadata.py`.
- Reviewer response: point to the exact file or command, then rerun `pnpm run submission:check`.
- Known rejection cause: Broken docs URL.
- Concrete repo control: Verify `https://oaslananka.github.io/kicad-mcp-pro` before submission.
- Reviewer response: point to the exact file or command, then rerun `pnpm run submission:check`.

## Final Anthropic Consistency Controls

- [ ] Compare the submitted server name with `server.json` before opening the form.
- [ ] Compare the submitted short description with the README opening paragraph.
- [ ] Confirm the category selection still says `EDA / Hardware Design` when the option exists.
- [ ] Confirm the fallback category still says `Developer Tools` when EDA is unavailable.
- [ ] Verify the repository URL resolves without redirects to the canonical owner.
- [ ] Verify the documentation URL resolves to the GitHub Pages site.
- [ ] Verify the privacy URL renders the current no-telemetry statement.
- [ ] Verify the support URL opens the GitHub issue tracker.
- [ ] Confirm the transport answer says local stdio, not hosted OAuth.
- [ ] Confirm the OAuth answer says not required for this local server path.
- [ ] Confirm the safety answer mentions read-only inspection as the default posture.
- [ ] Confirm the safety answer mentions explicit user intent for file writes.
- [ ] Confirm the safety answer mentions `project_quality_gate` before manufacturing export.
- [ ] Confirm the safety answer mentions no server-operated backend in default mode.
- [ ] Confirm the safety answer mentions telemetry is disabled by default and optional OpenTelemetry export is explicit.
- [ ] Confirm the reviewer fixture path exists locally before sending prompts.
- [ ] Confirm each reviewer prompt names the fixture project exactly once.
- [ ] Confirm wrong-path failures are documented as client configuration issues.
- [ ] Confirm screenshots do not show private usernames, hostnames, or paths.
- [ ] Confirm screenshots are final captures if this is a production submission.
- [ ] Confirm placeholder screenshots are disclosed if this is a pre-submission packet.
- [ ] Confirm `pnpm run submission:check` passes before the form is submitted.
- [ ] Confirm `pnpm run docs:tools:check` passes after tool metadata changes.
- [ ] Confirm `uv run --all-extras properdocs build -f mkdocs.yml --strict` passes after docs edits.
- [ ] Confirm `lychee --verbose --no-progress README.md docs/**/*.md` passes after link edits.
- [ ] Confirm `server.json` version matches the package version.
- [ ] Confirm the PyPI package name remains `kicad-mcp-pro`.
- [ ] Confirm the OCI image namespace remains `ghcr.io/oaslananka/kicad-mcp-pro`.
- [ ] Confirm no retired owner namespace appears in copied form text.
- [ ] Confirm no token, cookie, private key, or `.env` value appears in evidence.
- [ ] Confirm no customer KiCad project is uploaded as reviewer evidence.
- [ ] Confirm optional Nexar or Freerouting notes do not imply default network egress.
- [ ] Confirm the expected review timeline is recorded as an estimate, not a promise.
- [ ] Confirm any rejection response is tracked in a GitHub issue before resubmission.
- [ ] Confirm [`docs/public-listing.md`](../public-listing.md) is updated only after the form is actually sent.
- [ ] Confirm approval status is recorded only after the public listing URL is visible.
- [ ] Confirm the maintainer identity is Osman Aslan with handle `oaslananka`.
- [ ] Confirm the final submission packet contains this document, reviewer prompts, and safety statement.
- [ ] Confirm reviewer-facing language remains English for the initial launch.
- [ ] Confirm release evidence references Sigstore, SBOM, and provenance only when artifacts exist.
- [ ] Confirm the final copied text does not mention internal automation notes.
- [ ] Confirm the current branch has a clean working tree before submission evidence is captured.
