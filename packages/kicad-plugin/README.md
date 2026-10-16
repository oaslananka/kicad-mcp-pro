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
