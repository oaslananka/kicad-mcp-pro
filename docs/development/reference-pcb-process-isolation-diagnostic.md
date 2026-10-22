# Diagnostic: Linux process identity of an isolated PCB IPC server

This **read-only diagnostic** supports #1214's pending real KiCad GUI/PCB-phase isolation prerequisite. It intentionally **does not unlock** the reviewed PCB `reference_ops_server` phase, execute an agent, modify a PCB, reserve an attempt, authorize a manufacturing operation or contribute task-success credit.

## Invoke only against a disposable GUI and fixture

Create a fresh, separate KiCad PCB Editor process under a different, restricted Linux OS account, with its own KiCad settings, temporary runtime directory and an **independent copy** of the fixture board. Never point this diagnostic at the active user's KiCad GUI, default `/tmp/kicad/api.sock`, a golden/corpus reference file or a shared `review`/`build` MCP host.

```bash
uv run python -m scripts.attest_reference_pcb_ipc_process \
  --ipc-socket ipc:///absolute/private-test-root/tmp/kicad/api.sock \
  --board-file /absolute/private-test-root/work/fixture.kicad_pcb \
  --sandbox-root /absolute/private-test-root
```

The Linux-specific diagnostic rejects symlinked/unscoped paths and unsafe writable sandbox roots. It checks the real `SO_PEERCRED` Unix socket peer PID/UID, checks the socket, board and sandbox ownership against that peer UID, and requires that peer UID be neither root nor the caller's UID. Where permitted it checks `/proc/PID/exe`; on systems that restrict cross-UID executable reads it can fall back to the process `comm` and command line. The latter are **observations, not cryptographic process identity**, and must never qualify an edit grant. A bounded real KiCad 10 IPC `get_version()` plus `get_board()` response must confirm the expected board basename. Kernel socket identity is then checked again to catch ordinary process/socket replacement during the probe.

A positive result means **`status=observed_isolated_gui`** only, with `approved_for_editing=false`, `attempt_reserved=false`, `executes_agent=false` and `counts_as_task_success=false` in every case. Blocked results use sanitized reason codes and exit 2. Source paths, peer PIDs/UIDs, project content and socket addresses are not copied into the JSON result. A fresh/unknown socket, wrong UID, inaccessible process evidence, first-run GUI wizard, changed socket, unexpected board and unsupported KiCad version must fail closed.

## Known limits and remaining gates

A different UID and process name do **not** prove sandbox containment or authorization of the MCP client: processes can change their `comm`, access permissions may differ, shared temporary paths might be exposed to other local users, and the observer and GUI could race. Some test environments need client-side permission changes on the disposable socket; that is **not** an approved benchmark transport setup. The diagnostic is not a replacement for a protected OS sandbox, access-controlled IPC endpoint, separate provider/agent credential scope, GUI-readiness stage-two verification, a reviewed request/response transcript, server tracing, clean attempt manifests and independent native design validation.

**Keep the reviewed PCB-phase stdio host's existing fail-closed behavior in place.** A separately reviewed, stricter transport policy must be implemented before a PCB editor is made writable by a benchmark agent. The temporary LED fixture is a smoke test, not a serious STM32F072 corpus design and never counts toward #729 or #730.
