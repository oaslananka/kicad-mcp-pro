# KiCad PCM Physical Windows Evidence

- Date: `2026-08-29`
- Product version: `3.33.3`
- Merged source revision: `c25b852d90321754a95199645a450be98b126e76`
- KiCad: `10.0.5`
- Platform: authorized Windows desktop
- Final PCM SHA-256: `e3d1016a47bf8c1270c79a13cb07e1084dcf4e18b8a39d0637841778584d87bd`
- Final PCM size: `9,511` bytes
- Test content: repository fixture board only; no user project was mutated

## Clean install and restart

The host started with no `com_github_oaslananka_kicad-mcp-pro` PCM package and
with the KiCad API disabled. The final merged artifact was installed through the
real KiCad **Plugin and Content Manager -> Install from File** flow. KiCad stored
the package below the user `Documents/KiCad/10.0/3rdparty` tree.

All installed companion/resource files matched the final ZIP entries by SHA-256.
After a full KiCad restart, PCB Editor exposed **External Plugins -> kicad-mcp
companion** for the disposable fixture board.

## Backend and MCP lifecycle

With port `3334` stopped, invoking the real companion showed fail-closed backend
recovery guidance. The KiCad API was then enabled only for the live IPC portion
of the test, and the exact merged backend was started on loopback.
Live health reported backend `3.33.3`, `available=true`, `ipcReachable=true`, and
`livePcbContext=true` against KiCad `10.0.5`. A synchronous native invocation of
the companion returned from the KiCad UI thread in approximately `0.0277 s`, and
the real KiCad dialog confirmed a successful context push for the fixture board.

Protocol-level smoke then verified:

- initialize: HTTP `200`, `serverInfo.version=3.33.3`;
- initialized notification: HTTP `202`;
- tools/list: HTTP `200`, `24` tools;
- `kicad://studio/context`: returned the disposable fixture path;
- read-only `kicad_get_version`: `isError=false`, CLI/IPC both `10.0.5`.

A forced incompatible companion contract was also exercised. The native companion
invocation returned in approximately `0.0258 s`, displayed the expected backend
version incompatibility/recovery guidance, and did not push context. The temporary
compatibility fixture was then restored from the final artifact by hash.

## Uninstall and rollback

A disposable unrelated client configuration was hashed before uninstall. PCM
**Remove -> Apply Pending Changes** removed both plugin and resource directories;
the client configuration SHA-256 remained unchanged.
Rollback used the previously trusted `c5346b2fcec340e36c9fdfab543378837cb6d04b`
artifact, independently rebuilt on Windows with SHA-256
`d19e0e994707304912cd584f31283a138e85106d6f6f0b521d9f9a5a8148e717`.
All rollback-installed files matched that archive by hash, and a full PCB Editor
restart rediscovered the companion. The rollback package was then removed through
PCM again as part of host cleanup.

## Host restoration

The disposable board was closed without saving and retained its original SHA-256
`5004a7d46fdc0c2aba6b1bad83983cb3171b603f17eea05821a51f871167eae2`.
The pre-test `kicad_common.json` snapshot was restored byte-for-byte to SHA-256
`7ef9ef20558346f2a8d1998e21ee7916c1a99dbdace28fcc05d4f69f95ed049f`,
which restored `api.enable_server=false`.

Final cleanup verification showed no companion plugin/resources, no KiCad or
PCB Editor process, no listener on port `3334`, and no test-owned temporary
clone/artifact/fixture directories remaining.

## Platform boundary

This is real Windows PCM GUI lifecycle evidence, not a CI substitute. Together
with the independent Linux-host runs, physical PCM install/restart/health/MCP/
incompatible/uninstall/rollback behavior is verified on Linux and Windows.
A physical macOS host is still unavailable in the authorized device set, so macOS
CI remains explicitly CI-only rather than physical PCM evidence.