# Issue #889 Server CPU Hang Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent synchronous MCP tool implementations from blocking the server's asyncio event loop, so long-running board inspection cannot freeze MCP/HTTP responsiveness.

**Architecture:** Fix the concurrency boundary centrally in `KiCadFastMCP.tool()`: synchronous tool functions will be registered through an async wrapper that executes the original callable in AnyIO's worker thread pool. FastMCP will continue to own argument validation/result conversion, while the server event loop remains free to serve status/health/other requests. Keep async tools unchanged and preserve function signatures/metadata via `functools.wraps` so generated schemas do not drift.

**Tech Stack:** Python 3.13, asyncio, AnyIO, MCP SDK 1.28.1, pytest.

**Spec:** GitHub issue `oaslananka/kicad-mcp-pro#889`.

## Global Constraints

- Prove the event-loop starvation before changing production code.
- Do not fix the symptom by merely increasing IPC or HTTP timeouts.
- Keep existing tool schemas, annotations, return conversion, metrics, audit logging, and operating-mode checks unchanged.
- Async tool functions must not be double-offloaded.
- Synchronous tool exceptions must continue through FastMCP/`KiCadFastMCP.call_tool()` error handling.

---

### Task 1: Add an event-loop responsiveness regression test

**Files:**
- Modify: `tests/unit/test_server_startup.py`

**Interfaces:**
- Consumes: `KiCadFastMCP.tool()` and `KiCadFastMCP.call_tool()`.
- Produces: a deterministic assertion that a synchronous blocking tool does not monopolize the asyncio loop.

- [ ] **Step 1: Write the failing test**

Register a synchronous test tool that appends `tool-start`, waits on a `threading.Event`, then appends `tool-end`. Start a `threading.Timer` that releases it after ~200 ms and concurrently run an async heartbeat that sleeps ~10 ms and appends `heartbeat`. Assert ordering is `tool-start`, then `heartbeat`, then `tool-end`.

- [ ] **Step 2: Run test to verify it fails on current MCP behavior**

Run: `uv run --all-extras pytest tests/unit/test_server_startup.py -q`
Expected: FAIL because FastMCP 1.28.1 invokes synchronous functions directly on the event-loop thread, producing `tool-start`, `tool-end`, `heartbeat`.

### Task 2: Offload synchronous tool functions at registration

**Files:**
- Modify: `src/kicad_mcp/server.py`
- Modify: `tests/unit/test_server_startup.py`

**Interfaces:**
- Consumes: existing `KiCadFastMCP.tool(...)` decorator and `anyio.to_thread.run_sync`.
- Produces: an async wrapper for sync functions, with the original function signature/doc/name exposed through `functools.wraps`.

- [ ] **Step 1: Implement the minimal central wrapper**

Inside `KiCadFastMCP.tool().decorator`, leave coroutine functions untouched. For ordinary synchronous callables, create an `async def` wrapper that calls the original function with `functools.partial(func, *args, **kwargs)` through `anyio.to_thread.run_sync`. Apply `functools.wraps(func)` before registration.

- [ ] **Step 2: Re-run the responsiveness test**

Run: `uv run --all-extras pytest tests/unit/test_server_startup.py -q`
Expected: PASS with `heartbeat` observed before `tool-end`.

- [ ] **Step 3: Add/retain schema and exception regression coverage**

Verify a sync tool's generated input schema still reflects its original parameters and an exception is still surfaced through the existing tool error path. Verify an async tool remains an async callable and is not sent to the worker pool.

### Task 3: Validate affected server and dashboard surfaces

**Files:**
- Test only unless profiling proves an additional blocking status-route probe is required.

**Interfaces:**
- Consumes: completed concurrency fix.
- Produces: evidence that server discovery, tool invocation, and dashboard routes still work.

- [ ] **Step 1: Run server/web focused tests**

Run: `uv run --all-extras pytest tests/unit/test_server_startup.py tests/unit/test_web_routes.py tests/unit/test_pcb_board_inspection_registration.py tests/unit/test_pcb_board_inspection_service.py -q`

- [ ] **Step 2: Run integration checks for board summary/tool calls**

Run: `uv run --all-extras pytest tests/integration/test_pcb_tools.py tests/integration/test_verdict_reports.py -q`

- [ ] **Step 3: Run change-scoped repository gate**

Run: `python3 scripts/run_uv.py run --all-extras python scripts/hook_pre_push.py`

- [ ] **Step 4: Review diff and timing evidence**

Confirm no timeout inflation, no MCP schema drift, and no unrelated catalog/index changes were introduced. If the central offload removes the starvation reproduction, do not add speculative symbol-catalog rewrites.
