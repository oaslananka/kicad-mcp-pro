# Native KiCad Companion

This is the existing KiCad MCP Pro PCM integration, now using KiCad 10's IPC
plugin framework. One package identifier is retained for upgrades:
com.github.oaslananka.kicad-mcp-pro.

The PCM artifact and its SHA256SUMS/evidence are produced by the established
release tool:

    python scripts/build_kicad_pcm.py --output-dir /tmp/kicad-pcm --verify

An installed package contains plugin.json, companion.py, companion_core.py,
context.py, compatibility.json, requirements.txt and icon.png under plugins/.
KiCad provisions kicad-python into the plugin's isolated Python environment.

Click Open MCP Pro Companion in the PCB Editor toolbar. A modeless wxPython window
shows read-only board counts and the local backend state. The user can open
the existing dashboard or explicitly publish board context to the existing
MCP backend (using the versioned contract in context.py). No board mutations
or security-gate bypasses occur here.

### Sidecar UI and docking limitations

KiCad 10's **IPC plugins run in separate processes**. Its supported plugin
manifest allows toolbar actions, not docking a third-party widget as an editor
pane. The Companion is consequently a **normal, non-always-on-top window**, not
a native KiCad sidebar: it starts compact and, where display geometry allows,
positions near the **right edge of the monitor where the toolbar was clicked**.
It neither resizes/repositions the PCB Editor nor follows KiCad when the editor
moves. You may move/resize it or use the operating system's window tiling to
place it beside KiCad. Do not rely on OS-specific window embedding or the
legacy in-process SWIG plugin API for an apparently docked appearance.

For day-to-day PCB work, the Companion keeps **only the active PCB, selected
footprint, connection indicator and Sync** on its default surface. KiCad DRC,
dashboard, refresh and service details live in an opt-in **More tools** section
inside the same window. The window fits its visible content: on the physical
HDMI test display it was 330 × 352 without a selection and 330 × 497 with a
selected footprint; expanding advanced tools grows it only as needed. Dependency
repair is visible only when IPC setup genuinely fails. The separate DRC findings
dialog is reduced to 720 × 490 and placed within the physical monitor that
contains the Companion where supported. These changes reduce clutter but
**do not create native docking or move/resize KiCad automatically**. If the editor is
maximized, the sidecar initially overlaps it. **More tools → Arrange beside
KiCad…** offers opt-in, confirmed desktop tiling on Linux X11/XWayland only.
It requires an already maximized single local PCB Editor matching the active
board's filename, verifies the same monitor and the desktop manager's resulting
geometry, then puts KiCad on the left and Companion on the right. **Restore
previous KiCad layout** explicitly requests the original maximized state.
Closing Companion also attempts restoration on a best-effort basis, but
window-manager close behavior varies. **More tools → Close Companion** is a
reliable in-app exit path: it explicitly restores KiCad first, and **refuses to
close if restoration fails**. External title-bar / remote window-close commands
are not a verified method for restoring the editor; users should choose Restore
or the in-app Close Companion action. The command never runs during startup, never edits PCB data,
and never installs window-manager dependencies. Unmaximized editors,
Windows/macOS, unsupported displays, and missing/multiple KiCad matches fail
closed with a message; manual OS window tiling is the fallback. Desktop
compositor behavior can vary; this remains separate windows, not a KiCad dock. The active PCB and selected footprint are re-read when the
Companion regains focus, and **Sync reads fresh selection** in a worker before
publishing. If KiCad cannot provide the current selection, Sync fails closed.
When exactly one footprint is selected, a compact read-only inspector shows
its KiCad value, library footprint name, pad count and assigned net names.
Where other board footprints share those net assignments, the inspector names
their references under **Also assigned**; this is **logical net membership**,
not proof of routed copper, connectivity, DRC or electrical correctness. Only
references from the already-fetched board snapshot are read; no extra network
service or board mutations are required. Multiple selection hides the
per-footprint card rather than attributing details to the wrong item.
An additional **Check saved PCB** button explicitly runs KiCad CLI DRC on a
private temporary copy of the saved board with its local project/rule files.
It never runs automatically, refills zones, saves the editor board or modifies
production design data. The report displays separate violations (errors and
warnings) and unconnected items and is **not** a release/manufacturing gate;
unsaved KiCad edits and schematic parity are NOT included. The report is a
snapshot from the latest manual check, not a live DRC state. When KiCad provides
individual findings, **View DRC findings** opens a read-only table of rule types,
severity and reported X/Y coordinates, with the full KiCad item descriptions
for the selected row. **Copy selected finding** explicitly copies its rule, reported location and
KiCad-provided affected-item descriptions to the OS clipboard. The editor
itself is not moved or selected. No unverified footprint matching or automatic
GUI jump, selection, edit, or correction is performed; absent locations remain
absent. In particular, KiCad can generate different ephemeral object IDs when
the saved file has no persistent UUIDs; text/coordinate similarity is NOT a
safe live-object identity check. For a saved PCB containing persistent UUIDs,
**Select exact items in KiCad** is enabled only when the report identifies each
item by a unique persisted UUID. On explicit click it rechecks the saved board
hash and active KiCad project identity, then resolves every reported UUID to
exactly one selectable live `BoardItem` before changing only the editor
selection. If any ID is missing, ambiguous, unsupported (such as a text field),
or the saved file changed, it selects nothing. After DRC finishes, a bounded
read-only live IPC preflight also filters out nonselectable fields before
enabling each finding's action; selection click revalidates all IDs again.
The dialog always warns that unsaved edits may invalidate the saved DRC
snapshot. This is **not** proof that the saved DRC issue remains valid
in unsaved editor changes, and it never scrolls,
zooms, modifies, or saves the PCB.
The KiCad CLI must be on the companion's PATH; missing/unusable CLI,
unsupported reports or source file changes fail closed as **DRC unavailable**. Local temporary reports are
deleted after parsing. This is deliberately independent of MCP backend health.
Refresh and the local Dashboard are secondary. The dependency-repair
button only appears when the IPC Python runtime actually needs it. Status and
sync results are separate so a successful backend connection is not confused
with a completed sync. The UI never edits PCB data. This is a focused IPC
companion, **not a full embedded KiCad engineering command panel**. A genuine
KiCad-docked pane requires an upstream-supported embedded extension surface.

Requirements: KiCad 10.x, IPC enabled, a graphical wxPython-enabled KiCad runtime,
and the separately installed/running KiCad MCP Pro backend for dashboard or
context-sync actions. The plugin supports Python 3.9+ because the official
macOS KiCad 10 bundle may still ship Python 3.9; it does not require the user
to replace KiCad's selected interpreter. The UI does not silently launch or configure a server.

To install for development, put the package contents directly under a
subdirectory of the KiCad 10 IPC plugins directory, for example
~/.local/share/kicad/10.0/plugins/kicad-mcp-pro (Linux; lowercase
`kicad` is significant on case-sensitive filesystems).

In KiCad 10, enable the **IPC API server** in Preferences before opening the
companion. On Linux, the setting corresponds to `api.enable_server: true`
in the versioned KiCad common preferences file. Do not change another
user's preferences as part of installation.

If KiCad's managed Python environment accidentally considers packages from
the user's global Python site installed, the toolbar plugin can report
"KiCad IPC dependencies incomplete". In that case choose **Repair KiCad IPC
dependencies**, review the confirmation and approve an install into the
**KiCad-managed virtualenv only**. This explicit repair uses the packaged
requirements and disables the user site during dependency resolution; it
does not modify global/system Python.

The backend is a **separately installed** process. An incompatible backend
version or an unsaved/not-open board is reported rather than guessed. The
companion will not install or start the backend automatically.

Real KiCad 10.0.7 GUI acceptance on an isolated Linux test profile confirmed:
KiCad discovered the manifest, provisioned kicad-python 0.8.0, the toolbar
action opened the wxPython window and the official IPC API read a saved
board's project name, three footprints and one net. Windows and macOS
acceptance is still required; the PCM version remains development pending
that verification.

Reference: https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/
