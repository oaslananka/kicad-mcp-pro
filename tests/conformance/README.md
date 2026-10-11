# MCP 2026-07-28 mandatory server conformance

The official conformance suite requires diagnostic tools, prompts and resources
with prescribed names and content. `serve.py` registers these **only in an
isolated test process**, on the real `build_server("minimal")` implementation and
its actual SDK, transport, security middleware and protocol handlers. Neither
production profiles nor generated tool contracts include these fixtures.

Use the repository's pinned Python dependencies and Node.js/npm. In a dedicated
local shell, start the loopback test server:

```bash
export PYTHONPATH=src
export MCP_CONFORMANCE_PORT=39780
.venv/bin/python -m tests.conformance.serve
```

Then, in another shell, run the exact **frozen** required server suite for the
final protocol revision:

```bash
npx --yes @modelcontextprotocol/conformance@0.2.0-alpha.12 server \
  --url http://127.0.0.1:39780/mcp \
  --requirements 2026-07-28
```

The required **server** scenarios must all pass. The suite also reports optional
extension and *pending* scenarios which do not affect its required conformance
exit status. This verifies the MCP server wire contract and fixtures, **not**
real KiCad hardware operations, board task-success, client/OAuth behavior,
manufacturing acceptance or release readiness. Never expose the fixture server
on non-loopback addresses or ship it as part of the application.

The strict stateless 2026 lane serves streaming responses to support progress;
normal stable/legacy mode retains its JSON response default. Keep those modes
separate in compatibility regression testing.
