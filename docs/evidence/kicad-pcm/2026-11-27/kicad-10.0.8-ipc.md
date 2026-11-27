# KiCad 10.0.8 IPC PCM qualification

- Date: 2026-11-27
- Current release: [4.24.0](https://github.com/oaslananka/kicad-mcp-pro/releases/tag/mcp-server-v4.24.0)
- Source revision: `6a2b7908a19e8be53b5dd3927a45787baeae1f2d`
- Published PCM ZIP SHA-256: `4390c704c4343765c2cab9e37a8f74b7f7a42cbdf2112e72e11ff34eceaa6733`
- Backend wheel SHA-256: `c5ccb810f0d7542c70a6f498195026e3046cd272d98661ed9e51fd6eb79a61c3`
- Previous PCM 4.23.0 ZIP SHA-256: `96ff857f569fb0720ef9aa15ffa1b85278661143f60a5c4a7b52bc09b009f04d`
- Previous source revision: `bbf749a83d7a4554ec868d7f4221c0f83200fce9`
- Status: development; official PCM listing not submitted.

Published asset digests and provenance were verified. The runs used
disposable profiles and fixture boards, not real user projects.

## Linux: separate real KiCad runs

Actual KiCad 10.0.8 used a private Xvfb virtual display.

| Check | Observed result | Evidence |
| --- | --- | --- |
| PCM file lifecycle | Install 4.23.0 → update 4.24.0 → uninstall, Installed (0) → rollback 4.23.0 → normal Quit; 10 payload hashes matched. | [Lifecycle](https://github.com/oaslananka/kicad-mcp-pro/issues/412#issuecomment-7207765802) |
| Native toolbar | Exact payload manual staging into disposable PCM path, native dependency provisioning, real toolbar click opened managed Companion; board 3 footprints/3 nets. | [Toolbar](https://github.com/oaslananka/kicad-mcp-pro/issues/412#issuecomment-7208602916) |
| Dependency recovery | External user-site packages could satisfy pip but be missing at runtime. Actual repair dialog No preserved missing dependencies; Yes repaired private environment, pip check and same-window board read passed. | [Repair](https://github.com/oaslananka/kicad-mcp-pro/issues/412#issuecomment-7208724023) |
| Compatible backend | Actual Sync button, exact published 4.24.0 wheel, independent MCP resource read at `kicad://studio/context` confirmed fixture board and project root. | [Sync](https://github.com/oaslananka/kicad-mcp-pro/issues/412#issuecomment-7208144407) |
| Selection and incompatibility | Actual transient IPC selection R1/LED1, 2 pads each; multi hides card, clear resets. Programmatic wx activation refreshed selection without another health request. Synthetic 4.25.0 health response disabled Sync/Dashboard; POST count 0. | [Behavior](https://github.com/oaslananka/kicad-mcp-pro/issues/412#issuecomment-7209168260) |

The IPC action is on the PCB Editor toolbar, not the legacy External Plugins
menu. These earlier separate runs are distinct from the integrated virtual-display
acceptance below. The earlier sync run used direct managed Python launch and
existing isolated wheel dependencies, not a clean wheel install. Selection/focus was programmatic, not a physical gesture. The
incompatible response was synthetic, not a real incompatible backend.
Several successful inner probes reported outer command exit 1; original
records retain these distinctions. One earlier quit/restart changed the
disposable project hash (semantic diff unavailable), but PCB/SCH hashes
were unchanged. Later selection tests preserved all four fixture files.

## Linux: integrated PCM install-to-sync acceptance

A subsequent run used the same disposable KiCad profile throughout, on a
private Xvfb display with isolated D-Bus, documents and plugin directories.
The actual PCM file chooser installed the verified 4.24.0 ZIP, reported
Installed (1), and all 10 payload files matched. After normal manager Quit
(exit 0), a fresh PCB Editor opened the fixture. Its own IPC socket and the
backend's own loopback listener were verified independently.

The exact published 4.24.0 wheel was extracted and used with existing isolated
dependencies (not a clean wheel install). With an explicit `ipc://` endpoint,
the backend returned HTTP 200, `ok: true`, runtime available and live PCB
context available. The actual editor toolbar launched the installed Companion.
After explicit private-environment repair consent, pip check passed and the
window reported Connected, 3 footprints, 3 nets and 0 selected.

The actual Sync PCB context button reported `PCB context synced.` An independent
MCP initialize/initialized/resources/read sequence verified
`kicad://studio/context`, server version 4.24.0, the exact fixture PCB and
project root. All four PCB/SCH/PRO/DRU hashes were unchanged; cleanup and
independent absence of remaining fixture processes/directories were verified.
The inner flow exited 0; the outer command reported exit 1. This is
integrated virtual-display install-to-sync evidence, not physical-display
acceptance or a single integrated update/uninstall/rollback run.

[Integrated acceptance](https://github.com/oaslananka/kicad-mcp-pro/issues/412#issuecomment-7210504870)
and [backend-down install/read acceptance](https://github.com/oaslananka/kicad-mcp-pro/issues/412#issuecomment-7210177059).
A separate same-socket diagnostic found that a raw absolute filesystem socket
path was rejected as an invalid address, while the explicit NNG `ipc://` URI
worked. Use the URI for this tested configuration; the raw-path compatibility
gap is separate from PCM qualification and has not been fixed here.
[Endpoint diagnostic](https://github.com/oaslananka/kicad-mcp-pro/issues/412#issuecomment-7210349668).

## Windows interactive acceptance: pending

Actual KiCad 10.0.8 verified 10/10 package files, bundled Python 3.11.5 and
wxPython 4.3.1, private kicad-python 0.9.2/protobuf 5.29.6/pynng 0.9.0 imports
and pip check. [Dependency evidence](https://github.com/oaslananka/kicad-mcp-pro/issues/412#issuecomment-7208889320).

On an inactive private desktop, a wx control window appeared but PCB Editor
did not display its board even without the plugin. The IPC named pipe was
reachable and its server PID matched the test editor. The bounded read-only
probe repeatedly returned AS_NOT_READY (probe exit 2, diagnostic driver exit 0).
Four fixture hashes were unchanged and the environment was cleaned.
[Readiness evidence](https://github.com/oaslananka/kicad-mcp-pro/issues/412#issuecomment-7209168260).

This is a tested-environment readiness blocker, not proof of a normal
interactive Windows product defect. Integrated PCM lifecycle, toolbar and
live read/sync remain outstanding.

## macOS physical acceptance: pending

No physical macOS host was available. Historical
[Linux](../2026-08-29/linux-kicad-10.0.5.md) and
[Windows](../2026-08-29/windows-kicad-10.0.5.md) SWIG-era evidence does not
qualify current IPC. Retain development status; no official submission
before the outstanding integrated and platform checks pass. See the
[readiness matrix](../../../status/distribution-readiness.md) and
[submission plan](../../../submission/kicad-pcm.md).
