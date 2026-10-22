# Reviewed Ops benchmark IPC isolation

The reviewed schematic host is designed for **file-backed authoring**, not the
user's currently open PCB Editor. A missing `KICAD_API_SOCKET` setting did **not**
mean no GUI was attached: before this guard, KiPy could discover the system's
default open KiCad IPC socket and expose an unrelated user's PCB to reviewed
write-capable tools. This was observed with a *read-only* version query; no
board mutation was performed.

At its stdio entrypoint the reviewed schematic host now allocates a private,
owner-only directory containing **no IPC socket**, directs all KiPy connections
there (including after settings resets) and rejects inherited socket or token
environment variables. Thus it cannot silently fall back to the user's GUI.
The launcher-level preflight and tool-list attestation reject *both* documented
socket environment spellings and token spellings; a missing or incompatible
config is a block, never a reason to connect a default socket.

The reviewed PCB-phase stdio host intentionally fails closed until an
**independently attested isolated IPC transport** is implemented. A successful
schematic MCP tool-list check does not grant PCB edit permission, remove the
separate live GUI readiness gate or qualify an unisolated GUI for a scored
reference-board attempt. Production KiCad MCP hosts outside this reviewed
benchmark entrypoint retain their existing IPC configuration behavior.
