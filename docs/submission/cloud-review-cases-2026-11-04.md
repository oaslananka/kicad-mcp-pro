# Remote Cloud directory reviewer cases — NOT YET EXECUTED

**Draft test cases only.** Run against a dedicated, intentionally granted
public fixture project using actual ChatGPT and Claude clients; record
observed results and safe screenshots before importing any cases into the
provider portal. No private boards, secrets or local paths.

## Positive cases (5 required for OpenAI review)

1. "Tell me which read-only KiCad Cloud capabilities are currently active."
   Expected tool: get_service_status. Verify truthful capability names and
   no claim of a local GUI session.
2. "List the devices I have authorized for this connection and whether each
   device is online." Expected tool: list_devices. Only granted metadata.
3. "List my approved KiCad projects without showing local file paths."
   Expected tool: list_projects. Only the reviewer fixture is listed.
4. "Which read-only workflow can inspect the authorized fixture project?"
   Expected tool: discover_project_workflow. Returns a currently supported
   read-only tool, not an unavailable mutation/export action.
5. "Summarize the board counts for my approved fixture project."
   Expected tool: get_project_board_counts, **only if reported available**;
   otherwise the reviewer case must be adapted to a truly available read
   tool before submission. Do not invent expected count values.

## Negative cases (3 required for OpenAI review)

1. "Inspect a project that is not granted to this OAuth client." Expected:
   denial or not-found, never a cross-client record.
2. "Fetch project details with a malformed or foreign project ID." Expected:
   schema validation or authorization denial, no local path disclosure.
3. "Change my PCB track layout or export Gerbers through this hosted
   connector." Expected: no Cloud write/export capability; report that
   this would require a different approved local workflow.

## Evidence fields to fill after execution

Record platform, client identity type (never credentials), deployed revision,
test timestamp, approved fixture identifier alias, invoked MCP tool names,
observed output summary, user-visible screenshot references, and results of
refresh/revoke and same-user/different-client access checks. No pass/fail
status is claimed before the real clients execute each case.
