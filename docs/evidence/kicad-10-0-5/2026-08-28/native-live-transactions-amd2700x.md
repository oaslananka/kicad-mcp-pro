# KiCad 10.0.5 Native-Live Transaction Evidence

- Generated: `2026-08-28`
- Tested implementation checkpoint: `b7c55cc290ae8193e71901040f277b7f16a91da8`
- Tested implementation tree: `646b501bdaec5f5f71c52675c78fbdef647f15ea`
- Host: physical `AMD2700X` Windows workstation
- Interactive desktop session: active console session `1`
- KiCad PCB Editor: `10.0.5 (10.0.5)`
- Fixture baseline: `clean-led-kicad10.kicad_pcb`, 3 tracks, 0 vias
- Fixture file SHA-256: `7460ea575de1083ebebec0efba2c8560c186e5a81c3cd2e37c775eea03927aa2`

This evidence exercises the public MCP transaction tools against an open physical KiCad PCB
Editor through the official KiCad IPC API. The validation harness used GUI input only to prove
normal KiCad Undo behavior; production recovery does not automate the GUI or use unstable KiCad
actions.

## Grouped commit and live verification

Result: **PASS**

1. `pcb_begin_commit` started one native commit group.
2. `pcb_add_track` and `pcb_add_via` returned staged/pending-verification results rather than
   claiming mutation success.
3. Before `pcb_push_commit`, KiCad's live read surface remained at the committed 3-track/0-via
   state, matching KiCad 10's documented commit semantics.
4. `pcb_push_commit` published the group as one native KiCad undo unit.
5. Deferred postcondition verification re-read the live board and verified 4 tracks / 1 via.
6. Public transaction state returned `transaction_supported=true`, `last_outcome=committed`, and
   `recovery_required=false`.

KiCad 10.0.5 was also probed directly during diagnosis: staged creates are not visible through
`get_tracks`, generic `get_items`, `get_items_by_id`, connected-item lookup, or item bounding-box
lookup until the commit is pushed. The implementation therefore does not pretend that a live
postcondition can be re-read before upstream publishes the native commit.

## Native GUI Undo

Result: **PASS**

The committed track+via group was reverted with one real `Ctrl+Z` delivered to the foreground
KiCad PCB Editor in the active interactive Windows session. The board returned from 4 tracks /
1 via to 3 tracks / 0 vias, and the same-session live board digest returned exactly to the
verified pre-operation digest.

This GUI interaction is validation evidence only. It is not a production fallback or an
implementation of unsupported API behavior.

## Native drop

Result: **PASS**

A second transaction staged one track and one via and then called `pcb_drop_commit`. KiCad never
published the staged objects to the live read surface, and the post-drop board was equivalent to
the verified 3-track/0-via pre-operation state.

## Repeated soak

Result: **PASS**

- Iterations: 20
- Mutation classes per iteration: staged track + staged via + native drop
- Completed iterations: 20
- Failures: 0
- File-corruption incidents: 0
- Unexplained state-divergence incidents: 0
- Final board: 3 tracks / 0 vias
- Final same-session live digest: exactly equal to the soak baseline

## Restart and stale-session recovery

Result: **PASS after a physical regression was found and fixed**

The first physical restart test exposed that TTL expiry discarded the authenticated kipy client,
which also discarded KiCad's per-running-instance token. The old transaction could then silently
reconnect to a newly started KiCad process and stage a mutation there. No file was saved, and the
fixture was closed/reopened to restore the clean 3-track/0-via in-memory state.

The fix changes TTL handling to probe the authenticated cached client instead of blindly replacing
it. KiCad's `AS_TOKEN_MISMATCH` response is treated as a continuity break. A timeout, disconnect,
or token mismatch resets the session generation before reconnecting; a healthy same-instance
probe preserves continuity so transactions are not invalidated merely because the TTL elapsed.
Raw KiCad tokens are never read, logged, persisted, or exposed by the MCP layer.

The physical restart test was then repeated with an explicit readiness gate:

1. Begin a native transaction in the original KiCad process.
2. Terminate that fixture PCB Editor without saving.
3. Start a new KiCad 10.0.5 PCB Editor in the same interactive session.
4. Prove the fixture is open and at 3 tracks / 0 vias.
5. Ask the old MCP transaction to add a track.

The old transaction failed closed before mutation with actionable recovery guidance:

`The KiCad IPC session changed during the native-live transaction; recovery is required before another mutation can run.`

Evidence after rejection:

- Board: 3 tracks / 0 vias
- Fixture file SHA-256: unchanged at
  `7460ea575de1083ebebec0efba2c8560c186e5a81c3cd2e37c775eea03927aa2`
- `state=recovery_required`
- `last_outcome=recovery_required`
- `staged_mutation_count=0`
- Duplicate application: none

KiCad can serialize an unchanged board differently after a process restart, so cross-process
recovery evidence intentionally compares board identity, semantic object counts, and the on-disk
fixture digest rather than assuming `get_as_string()` is byte-stable across processes.
