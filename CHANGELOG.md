# Changelog

All notable changes to the `kicad-mcp-pro` Python server will be documented in
this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this package adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Comparison links will be added after the first public component tags are
published.

## [3.18.0](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.17.1...mcp-server-v3.18.0) (2026-07-04)


### Features

* close July release readiness gaps ([ca9941e](https://github.com/oaslananka/kicad-mcp/commit/ca9941e18f9cee8fe64df80d533e93f37a8a924d))


### Bug Fixes

* unblock release readiness checks ([99ea584](https://github.com/oaslananka/kicad-mcp/commit/99ea5842a544fd9fab62066fd2aacf67981b0bba))

## [3.17.1](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.17.0...mcp-server-v3.17.1) (2026-07-03)


### Bug Fixes

* **container:** drop uv from runtime image ([#265](https://github.com/oaslananka/kicad-mcp/issues/265)) ([88b0907](https://github.com/oaslananka/kicad-mcp/commit/88b0907c08760c692a72c9c8c66f5dcfc50c1a15))

## [3.17.0](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.16.0...mcp-server-v3.17.0) (2026-07-03)


### Features

* **schematic:** auto-add PWR_FLAG to undriven power rails ([#257](https://github.com/oaslananka/kicad-mcp/issues/257)) ([db12813](https://github.com/oaslananka/kicad-mcp/commit/db1281309af364b4d663c62fd6f10b5ba7c09343))


### Bug Fixes

* **schematic:** reject non-existent symbols instead of placing them silently ([#252](https://github.com/oaslananka/kicad-mcp/issues/252)) ([d00958a](https://github.com/oaslananka/kicad-mcp/commit/d00958a74307941a1d85a464ce766e21548ba07a))
* **schematic:** resolve +/- differential-pin names in net endpoints ([#255](https://github.com/oaslananka/kicad-mcp/issues/255)) ([1866228](https://github.com/oaslananka/kicad-mcp/commit/1866228394b4265c5f02e558cab9e124ff201114))
* **security:** harden bridge and http contracts ([249c970](https://github.com/oaslananka/kicad-mcp/commit/249c9704a4e6a25c447b4e8f3bf17cc3c8568341))


### Documentation

* add professional oss maturity evidence ([b389904](https://github.com/oaslananka/kicad-mcp/commit/b3899046b3031a703657705f8108d9dcda2e47dc))
* align maturity evidence for solo maintainer ([5618b8a](https://github.com/oaslananka/kicad-mcp/commit/5618b8a58f47fb02c59074220d79f6adec2b155e))

## [3.16.0](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.15.1...mcp-server-v3.16.0) (2026-06-30)


### Features

* schematic + PCB readability and placement engine ([#247](https://github.com/oaslananka/kicad-mcp/issues/247)) ([d7b9a15](https://github.com/oaslananka/kicad-mcp/commit/d7b9a15a62d5209d92b546bc4fa099f563690716))
* **schematic:** size-aware netlist auto-layout so large parts get room ([#254](https://github.com/oaslananka/kicad-mcp/issues/254)) ([79664c5](https://github.com/oaslananka/kicad-mcp/commit/79664c5611ef3722be9fc054dbc54e87e9092fc1))


### Bug Fixes

* **rules:** recognise suffixed/compound supply-rail names ([#250](https://github.com/oaslananka/kicad-mcp/issues/250)) ([0f0fab1](https://github.com/oaslananka/kicad-mcp/commit/0f0fab1a90f0445a58f6284b1f19cd2c2e4bdf0e))
* **schematic:** scale terminal-label stub length to the net name ([#253](https://github.com/oaslananka/kicad-mcp/issues/253)) ([1de03cc](https://github.com/oaslananka/kicad-mcp/commit/1de03ccf8053daa8cb1aa7dc751389037a032363))


### Documentation

* **prompts:** wire readability QA into design workflows ([#249](https://github.com/oaslananka/kicad-mcp/issues/249)) ([4e4067c](https://github.com/oaslananka/kicad-mcp/commit/4e4067c0bfa222a0fc0cf3f5b9def0bc75b9b560))

## [3.15.1](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.15.0...mcp-server-v3.15.1) (2026-06-29)


### Bug Fixes

* harden ChatGPT app filesystem paths ([f8603ef](https://github.com/oaslananka/kicad-mcp/commit/f8603ef8af2ed8f41bf5901cc418506928ec0f9b))
* remove pip installs from container build ([987cc9d](https://github.com/oaslananka/kicad-mcp/commit/987cc9da04e3e609b8b848e985428629091fe7c8))
* use public links for Silver evidence ([9635b5d](https://github.com/oaslananka/kicad-mcp/commit/9635b5d8e6e04f8b3ae9311e2ce8210f816834ee))


### Documentation

* add OpenSSF Silver evidence ([#243](https://github.com/oaslananka/kicad-mcp/issues/243)) ([37bb987](https://github.com/oaslananka/kicad-mcp/commit/37bb98750ea2a77b98da95abbf38309c9aebea02))
* align Silver coverage evidence ([#245](https://github.com/oaslananka/kicad-mcp/issues/245)) ([e27229d](https://github.com/oaslananka/kicad-mcp/commit/e27229d0dcfc470858ecdb4069fce012235da975))
* document Scorecard exceptions ([c7e4122](https://github.com/oaslananka/kicad-mcp/commit/c7e4122cc3f5c5c688b5691d2546d74e0336ab79))
* show OpenSSF Silver badge ([e962369](https://github.com/oaslananka/kicad-mcp/commit/e962369db94363e113f4f584bf66e43d7ec47f49))
* tidy README header badges ([62cd680](https://github.com/oaslananka/kicad-mcp/commit/62cd6800669eae9330cf98b01e4fb50190adfb0e))

## [3.15.0](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.14.1...mcp-server-v3.15.0) (2026-06-27)


### Features

* 2-D finite-difference copper-plane thermal spreading solver (P3-T4) ([1aa70c5](https://github.com/oaslananka/kicad-mcp/commit/1aa70c5bee163b82f74f52f58648e30e69f9ae6f))
* add experimental MCP Tasks extension support ([fdec012](https://github.com/oaslananka/kicad-mcp/commit/fdec01224cde78f481d962ab0fcacf2488a1093f))
* add KiCad capability-parity matrix and kicad_capability_parity tool (P0-T4) ([c742a9e](https://github.com/oaslananka/kicad-mcp/commit/c742a9e0a303dc1245163490a384b959522f8947))
* add project release readiness workflow ([5fa6f1c](https://github.com/oaslananka/kicad-mcp/commit/5fa6f1cbfd18cc76b3945e2a3506d947934758e3))
* add SPICE model assignment and library management tools ([ec14eb6](https://github.com/oaslananka/kicad-mcp/commit/ec14eb6c4dc01d0632b1f4b6b8ac3fd5cbe1c9f0))
* add tool-selection eval harness and golden dataset ([#174](https://github.com/oaslananka/kicad-mcp/issues/174)) ([ca93d94](https://github.com/oaslananka/kicad-mcp/commit/ca93d94ce3c4af5bc80f821115ef4dac545e3301))
* **agent:** project_design_workflow phase state machine surface ([#194](https://github.com/oaslananka/kicad-mcp/issues/194), [#195](https://github.com/oaslananka/kicad-mcp/issues/195)) ([#232](https://github.com/oaslananka/kicad-mcp/issues/232)) ([bc2bd1a](https://github.com/oaslananka/kicad-mcp/commit/bc2bd1a6577751d30326f82e1960991a2563421f))
* **analysis:** expose solver signoff verdicts ([63ab2d4](https://github.com/oaslananka/kicad-mcp/commit/63ab2d42adc90537597823a032cb9fe737c7f1b4))
* apply routed Specctra SES to the board headlessly (P4-T1) ([#91](https://github.com/oaslananka/kicad-mcp/issues/91)) ([0563efc](https://github.com/oaslananka/kicad-mcp/commit/0563efce3d5f54aa413cddde9f325d010f974a78))
* bound deferred tool registration with a timeout (P5-T5) ([081f87b](https://github.com/oaslananka/kicad-mcp/commit/081f87b05e949b75a18fae638a0c4e3cc70e481e))
* **cli:** add init, status, log commands with improved errors ([e66a6ef](https://github.com/oaslananka/kicad-mcp/commit/e66a6ef20e461651dc2983915a8f5054b89c9e74))
* **compat:** refresh KiCad 10.0.4 baseline ([38ae60c](https://github.com/oaslananka/kicad-mcp/commit/38ae60cd24163717f9d631cca13ce1a9dffeb975))
* complete all 20-phase plan — 22 new tools, 31 new files, full KiCad MCP feature parity ([34a1d92](https://github.com/oaslananka/kicad-mcp/commit/34a1d92001cae2ca7d8936a0b01a2a3386022276))
* complete error transient-class and tool idempotency contract (P1-T5, K9) ([97460dd](https://github.com/oaslananka/kicad-mcp/commit/97460dd587316e78a04a7142075bad1c939331bd))
* component derating + approved-vendor (AVL) sourcing gate (P4-T3) ([2e5e3e9](https://github.com/oaslananka/kicad-mcp/commit/2e5e3e954a6a2004abf83f69f16b8b5cd9a30ae5))
* **contracts:** enforce tier/side-effect consistency in tool-contract lint ([#196](https://github.com/oaslananka/kicad-mcp/issues/196)) ([#225](https://github.com/oaslananka/kicad-mcp/issues/225)) ([7784f16](https://github.com/oaslananka/kicad-mcp/commit/7784f166a4fc3e52ac23d4233ef178fd12ae5776))
* **dashboard:** surface AI agent setup and prompt links in the sidebar ([#99](https://github.com/oaslananka/kicad-mcp/issues/99)) ([db56aa8](https://github.com/oaslananka/kicad-mcp/commit/db56aa83a7230beab0ae72ef832d9ea4be2cd356))
* deterministic convergence-based placement, no wall-clock cap (P4-T2, K7) ([cade887](https://github.com/oaslananka/kicad-mcp/commit/cade8877d6158f214c394cf39b5ebcf028a60148))
* deterministic, provenance-stamped reproducible release manifest (P2-T5) ([a6d9de2](https://github.com/oaslananka/kicad-mcp/commit/a6d9de21790a7f272af5d0103fc31550830e89c8))
* **dev:** add hot reload, inspector command, IPC mock fixtures, better error logging, pre-commit pytest ([ed583f0](https://github.com/oaslananka/kicad-mcp/commit/ed583f04c1b98d76000e630b07e1a3f79c87d505))
* **docs:** add GitHub Pages deployment workflow for MkDocs site ([eadecd6](https://github.com/oaslananka/kicad-mcp/commit/eadecd6492c96eec21154a4fb1d6dbcc2d1a7231))
* **drc:** add drc_check_rule_conflicts to reconcile .kicad_dru rules ([#202](https://github.com/oaslananka/kicad-mcp/issues/202)) ([#221](https://github.com/oaslananka/kicad-mcp/issues/221)) ([5fe9443](https://github.com/oaslananka/kicad-mcp/commit/5fe9443241b45321e740e435a7c24fa700dd3ba0))
* edit-impact analysis to scope re-validation after edits (P4-T4) ([fca853f](https://github.com/oaslananka/kicad-mcp/commit/fca853ffcdcfc016af00fbd10170423110c08722))
* **emc:** add honest solver seam so EMC results are critic-only ([#206](https://github.com/oaslananka/kicad-mcp/issues/206)) ([#220](https://github.com/oaslananka/kicad-mcp/issues/220)) ([1768fd7](https://github.com/oaslananka/kicad-mcp/commit/1768fd7db1241786bdfe043760a7b298bfe26b42))
* **erc:** expose structured run_erc finding metadata ([a744635](https://github.com/oaslananka/kicad-mcp/commit/a744635d5ec5a61890aa7691179c19047197e01c))
* **evals:** golden project corpus and eval harness ([#210](https://github.com/oaslananka/kicad-mcp/issues/210)) ([1d276fd](https://github.com/oaslananka/kicad-mcp/commit/1d276fd0cde64350fd8963bba077fd8c9100a2c9))
* **execution:** add TaskManager for MCP Tasks extension lifecycle ([62806fb](https://github.com/oaslananka/kicad-mcp/commit/62806fb23a47926b09a1bf267a187191a279aa32))
* expand schematic authoring and PCB quality validation ([#190](https://github.com/oaslananka/kicad-mcp/issues/190)) ([0a6acd6](https://github.com/oaslananka/kicad-mcp/commit/0a6acd6f8d93c279658381f08b164a9850a058a6))
* field-solver adapter seam + honest impedance method labeling (P3-T1) ([11a4a4d](https://github.com/oaslananka/kicad-mcp/commit/11a4a4d10ebff4a4b3bed83e4f71cc44ce197b1a))
* **footprint:** documentation-layer completeness check ([#201](https://github.com/oaslananka/kicad-mcp/issues/201)) ([#227](https://github.com/oaslananka/kicad-mcp/issues/227)) ([6d3d3a2](https://github.com/oaslananka/kicad-mcp/commit/6d3d3a288fe95a98b3ab769a1c7fb15b79574ac8))
* **footprint:** embed IPC-7351 density in generated footprints ([#201](https://github.com/oaslananka/kicad-mcp/issues/201)) ([#228](https://github.com/oaslananka/kicad-mcp/issues/228)) ([2303c20](https://github.com/oaslananka/kicad-mcp/commit/2303c20f562dd83e037ba26f0a28d2e2ca08aaaa))
* **footprint:** pad-count vs package-name cross-check ([#201](https://github.com/oaslananka/kicad-mcp/issues/201)) ([#226](https://github.com/oaslananka/kicad-mcp/issues/226)) ([32c54c9](https://github.com/oaslananka/kicad-mcp/commit/32c54c9b3d4732ca97dba1e0727184a0de00e88e))
* harden tool contracts and operating mode coverage ([5e67cfc](https://github.com/oaslananka/kicad-mcp/commit/5e67cfcaf4d49052149f1cdb99dbd994302f3de1))
* high-speed channel insertion-loss / eye analysis via ngspice (P3-T3) ([e3f3778](https://github.com/oaslananka/kicad-mcp/commit/e3f377833a73267c253773c8d800438c7864cf2e))
* honest FreeRouting manual-step handling and headless DSN attempt (P1-T7, K1) ([e0154f5](https://github.com/oaslananka/kicad-mcp/commit/e0154f572b51ab23973d631187dff3a493433420))
* implement schematic manipulation tools and configuration management for KiCad MCP server ([fd802b5](https://github.com/oaslananka/kicad-mcp/commit/fd802b58a7f8fa0be2117431e612b1ac37df82fa))
* initial migration from kicad-studio-kit monorepo ([#1](https://github.com/oaslananka/kicad-mcp/issues/1)) ([be9b16f](https://github.com/oaslananka/kicad-mcp/commit/be9b16f33aaea94fbea525edd173a93a7e3e5012))
* IPC-2221 current-density fusing + honest distributed-PDN labeling (P3-T2) ([4e278d8](https://github.com/oaslananka/kicad-mcp/commit/4e278d8f8bad3decb02de826ee92df983f905783))
* IPC-7351B footprint validation hard-gate for chip packages (P4-T3) ([6db8e46](https://github.com/oaslananka/kicad-mcp/commit/6db8e461b9555acc425c30364c954ded64872a35))
* **ir:** semantic EDA intermediate representation — data model, KiCad → IR parser, lint, diff, and MCP tool ([#199](https://github.com/oaslananka/kicad-mcp/issues/199)) ([0f4d93a](https://github.com/oaslananka/kicad-mcp/commit/0f4d93a072a6eb01e5b7937cbd8786aff69da313))
* **library:** enrich component intelligence with lifecycle, RoHS, datasheet URL, and filters ([#200](https://github.com/oaslananka/kicad-mcp/issues/200)) ([74dd089](https://github.com/oaslananka/kicad-mcp/commit/74dd089a19909bb41b579cd558c536cfdd1c16de))
* **library:** lib_certify_footprint MCP tool surfacing [#201](https://github.com/oaslananka/kicad-mcp/issues/201) checks ([#201](https://github.com/oaslananka/kicad-mcp/issues/201)) ([#229](https://github.com/oaslananka/kicad-mcp/issues/229)) ([cbf464e](https://github.com/oaslananka/kicad-mcp/commit/cbf464eb0207cccaf2c27e135be3efe776d353be))
* live Mouser keyword-search client completes the distributor trio (P4-T3) ([ee613ae](https://github.com/oaslananka/kicad-mcp/commit/ee613ae712923d280667892fb882bfc99fbf178b))
* manufacturing sign-off report binding requirements to checks (P5-T3) ([de3c500](https://github.com/oaslananka/kicad-mcp/commit/de3c500fdecbd4b451876af93608485e5cfec1c9))
* **mcp:** protocol contract tests, progress/cancellation tests, and output-schema evolution policy ([#209](https://github.com/oaslananka/kicad-mcp/issues/209)) ([bb19e5f](https://github.com/oaslananka/kicad-mcp/commit/bb19e5f36ff5eaee273323b1a01ba33b2609e14a))
* Nexar lifecycle/RoHS sourcing data + actionable quota error (P4-T3) ([f6b98c7](https://github.com/oaslananka/kicad-mcp/commit/f6b98c7ddc9941c3bb5ea259d005efec67db7adc))
* parity coverage-regression gate, baseline, and README badge (P5-T6) ([b02eebe](https://github.com/oaslananka/kicad-mcp/commit/b02eebe0400c7457de1d49a633114dd934cd21bf))
* PDN + thermal solver-adapter seams with honest method labeling (P3-T2/T4 seams) ([8d3af87](https://github.com/oaslananka/kicad-mcp/commit/8d3af879ee02197c6d87f952d7caf7b449502a9c))
* **placement,manufacturing,compat:** placement critic, release evidence bundle, KiCad 11 IPC seam ([#203](https://github.com/oaslananka/kicad-mcp/issues/203), [#208](https://github.com/oaslananka/kicad-mcp/issues/208), [#192](https://github.com/oaslananka/kicad-mcp/issues/192)) ([44b1401](https://github.com/oaslananka/kicad-mcp/commit/44b1401b88142a3a8f11843b17785af7f87bc54d))
* publish protocol-schemas as public npm package ([f09a57e](https://github.com/oaslananka/kicad-mcp/commit/f09a57ebedeab9a28c5bab6f34052baf1a4aed49))
* rate-limit the bridge daemon against floods and pairing brute force (P5-T5, K8) ([1fecc9d](https://github.com/oaslananka/kicad-mcp/commit/1fecc9d5ebb009db87091daf6828cba82fca3624))
* real DigiKey Product Information (v4) client (P4-T3) ([b9b36d4](https://github.com/oaslananka/kicad-mcp/commit/b9b36d43880ddacd2691ab3c655b1ee401c9c8ae))
* real Nexar Supply client + .env credential loading (P4-T3) ([d797759](https://github.com/oaslananka/kicad-mcp/commit/d797759413c1de9a43c5fc2e306a9ca2d4edac4b))
* real PASS/WARN/FAIL verdicts for SI gates (P1-T3, K2) ([915c752](https://github.com/oaslananka/kicad-mcp/commit/915c752dd900c2388750f6c53924829d826d0ada))
* real task cancellation + execution timeout in the Tasks layer (P5-T5) ([c1f96cb](https://github.com/oaslananka/kicad-mcp/commit/c1f96cbcabeb879007b37dd5e186a54f76064e13))
* round-trip-safe schematic edit primitive with corruption guard (P2-T1/T2, K5/K6) ([2e1dbf6](https://github.com/oaslananka/kicad-mcp/commit/2e1dbf66f44e2e687743ea5075d43e531eeffd70))
* **routing:** close FreeRouting loop with headless SES apply, add generate_board_constraints ([#204](https://github.com/oaslananka/kicad-mcp/issues/204), [#202](https://github.com/oaslananka/kicad-mcp/issues/202)) ([a2f3722](https://github.com/oaslananka/kicad-mcp/commit/a2f37220fa165d19b2c11b1a213262ad03ac5996))
* **routing:** make route_autoroute_freerouting task-aware ([7d389cd](https://github.com/oaslananka/kicad-mcp/commit/7d389cda02f75a363b2aefd9c6ac2ada3bdc9561))
* **schematic-rules:** Ethernet diff-pair rule pack ([#205](https://github.com/oaslananka/kicad-mcp/issues/205)) ([#223](https://github.com/oaslananka/kicad-mcp/issues/223)) ([f54f985](https://github.com/oaslananka/kicad-mcp/commit/f54f985c418d016a71144dad7cdfc76eb8e0e0d3))
* **schematic-rules:** external-port ESD/TVS/protection rule pack ([#205](https://github.com/oaslananka/kicad-mcp/issues/205)) ([#230](https://github.com/oaslananka/kicad-mcp/issues/230)) ([9af9970](https://github.com/oaslananka/kicad-mcp/commit/9af99706dab486f788b12e0f518063edb9d4e072))
* **schematic-rules:** flag conflicting supply rails on one net ([#197](https://github.com/oaslananka/kicad-mcp/issues/197)) ([#219](https://github.com/oaslananka/kicad-mcp/issues/219)) ([148124b](https://github.com/oaslananka/kicad-mcp/commit/148124b6019060ff80de84c8c09399fc6d10ffe1))
* **schematic-rules:** SMPS (switching-regulator) rule pack ([#205](https://github.com/oaslananka/kicad-mcp/issues/205)) ([#224](https://github.com/oaslananka/kicad-mcp/issues/224)) ([4d45a4e](https://github.com/oaslananka/kicad-mcp/commit/4d45a4e5dfdad5ef4b14e30bdf50322d035ab0ab))
* **schematic-rules:** USB domain rule pack (diff-pair + USB-C CC) ([#205](https://github.com/oaslananka/kicad-mcp/issues/205)) ([#222](https://github.com/oaslananka/kicad-mcp/issues/222)) ([476fa59](https://github.com/oaslananka/kicad-mcp/commit/476fa596140a0c63967ba9205caccc85956f1956))
* **schematic:** reject duplicate-UUID writes ([#216](https://github.com/oaslananka/kicad-mcp/issues/216)) ([430f220](https://github.com/oaslananka/kicad-mcp/commit/430f220d7a82b41fafe4f0800831a01725828670))
* **schematic:** report native Populate/DNP status ([#186](https://github.com/oaslananka/kicad-mcp/issues/186)) ([#215](https://github.com/oaslananka/kicad-mcp/issues/215)) ([5cec47a](https://github.com/oaslananka/kicad-mcp/commit/5cec47a50e6c081048ff5840de30d92ab0f83add))
* selective re-validation after edit completes first-class edit mode (P4-T4) ([#88](https://github.com/oaslananka/kicad-mcp/issues/88)) ([d827523](https://github.com/oaslananka/kicad-mcp/commit/d82752362b9924b54868a778a457f1ceed803a4e))
* **server:** wire MCP Tasks protocol handlers (get/list/cancel/get_payload) ([182e676](https://github.com/oaslananka/kicad-mcp/commit/182e67633fdcc943ed9e4b1520338ae10f34e0e0))
* structural IPC error classification + restart cache invalidation (P5-T5) ([bdb7cb4](https://github.com/oaslananka/kicad-mcp/commit/bdb7cb4d87727f879b9367c3520c3e8b6e70943f))
* structured verdict payloads for high-traffic gate tools (P1-T4) ([ee3c21a](https://github.com/oaslananka/kicad-mcp/commit/ee3c21a6b2b27f6954a7530b26635330169351ac))
* **visual:** closed-loop visual verification and diff ([#207](https://github.com/oaslananka/kicad-mcp/issues/207)) ([6caf0cd](https://github.com/oaslananka/kicad-mcp/commit/6caf0cd48c5609a5dcaa405bf32d76f9145a325e))


### Bug Fixes

* add errors='replace' to subprocess.run for Turkish Windows encoding ([#21](https://github.com/oaslananka/kicad-mcp/issues/21)) ([911d307](https://github.com/oaslananka/kicad-mcp/commit/911d307d9cacfd48a4c0c5a996d7147b74227911))
* add repository.url for npm provenance verification ([42045f5](https://github.com/oaslananka/kicad-mcp/commit/42045f5d35404c22c3023806c1714e768ba4f1f0))
* address code-review feedback on merged [#167](https://github.com/oaslananka/kicad-mcp/issues/167) ([#172](https://github.com/oaslananka/kicad-mcp/issues/172)) ([3bf7bb3](https://github.com/oaslananka/kicad-mcp/commit/3bf7bb3d8e9a498a2f8292d737926a946056f50e))
* address issues [#56](https://github.com/oaslananka/kicad-mcp/issues/56), [#57](https://github.com/oaslananka/kicad-mcp/issues/57), [#61](https://github.com/oaslananka/kicad-mcp/issues/61) (pagination, DNP test, canary extension) ([1d4e7b3](https://github.com/oaslananka/kicad-mcp/commit/1d4e7b39fe059b8dc2b89d4a1f0acf22cdeedeeb))
* address review feedback - dru.py IndexError guard, schematic O(N^2) optimization ([5f74011](https://github.com/oaslananka/kicad-mcp/commit/5f74011ea1a85e50dd27d020ec2cffe369eba443))
* align main ruleset with real CI check names + guard (P5-T4) ([f23ac33](https://github.com/oaslananka/kicad-mcp/commit/f23ac3328f6b58a5013d59d1ad097f74ca48aac2))
* avoid generic regulator contract false matches ([0b91796](https://github.com/oaslananka/kicad-mcp/commit/0b91796101fdbe8366176a93ff333f0be8271fee))
* bump compatibility.yaml and README version to 3.7.3 ([f71149e](https://github.com/oaslananka/kicad-mcp/commit/f71149ed69e720f2b5c0a64552150bf938c8f9a4))
* bump compatibility.yaml version from 3.9.1 to 3.9.2 ([a9ef4ff](https://github.com/oaslananka/kicad-mcp/commit/a9ef4ff2d85b0862b69f77812910a81450d88426))
* bump hardcoded version references 3.8.0 -&gt; 3.9.0 ([7f15c44](https://github.com/oaslananka/kicad-mcp/commit/7f15c44c244d863ba0df4e099c3d8212c8f447ff))
* bump hardcoded version refs from 3.9.1 to 3.9.2 in tests, dashboard, compatibility, README ([40a080b](https://github.com/oaslananka/kicad-mcp/commit/40a080b1b3251d0fce46e621be5a4808731fc18e))
* bump playwright e2e test version assertion v3.9.1 -&gt; v3.9.2 ([28ffa0a](https://github.com/oaslananka/kicad-mcp/commit/28ffa0a49453848cc1d68945fe1941f2fe540a05))
* **capabilities:** classify lib_certify_footprint as a READ tool ([#233](https://github.com/oaslananka/kicad-mcp/issues/233)) ([ee98c5b](https://github.com/oaslananka/kicad-mcp/commit/ee98c5be1f49e525effa071c3b0e3ddcc841199e))
* **chatgpt-app:** add path-traversal guards, XSS escaping, and rate limiting ([0084de5](https://github.com/oaslananka/kicad-mcp/commit/0084de587e8639a50caebde230e2ac35c165bcaa))
* **ci:** repair container build hash-pinning and patch starlette CVE-2026-54283 ([023ee30](https://github.com/oaslananka/kicad-mcp/commit/023ee30dc25dc4c015f8f981a3baa4a0b89f5c3d))
* **ci:** resolve all workflow issues found in CI/CD audit ([7778fde](https://github.com/oaslananka/kicad-mcp/commit/7778fdec94f215a8ba5f90a265a2c3329e9f5841))
* **ci:** update sync_mcp_metadata.py source with correct descriptions and empty remotes ([9889890](https://github.com/oaslananka/kicad-mcp/commit/98898905e95a0a0a4c626d3d390348c5247ba94c))
* clear vertical pin terminals from symbol text ([7b3bec0](https://github.com/oaslananka/kicad-mcp/commit/7b3bec06b89700dfb30a6985e0b9b7a556331be4))
* correct Specctra SES coordinate scale (1 mm = 1000 units, not 10000) ([#92](https://github.com/oaslananka/kicad-mcp/issues/92)) ([565a020](https://github.com/oaslananka/kicad-mcp/commit/565a02030d68cdb2b0bcddd325f5f5a1014ef66f))
* disable Dependabot (Renovate handles updates), fix macOS benchmark flake ([2ed47a2](https://github.com/oaslananka/kicad-mcp/commit/2ed47a248f685a858d9c5fc449bfeff8073f32d7))
* discover symbol/footprint libraries via sym-/fp-lib-table ([#78](https://github.com/oaslananka/kicad-mcp/issues/78)) ([#90](https://github.com/oaslananka/kicad-mcp/issues/90)) ([72fce79](https://github.com/oaslananka/kicad-mcp/commit/72fce791eaf87e48255807799a19595923c34d8a))
* docker tag pattern, sync versions, add branch protection, cleanup ([#14](https://github.com/oaslananka/kicad-mcp/issues/14)) ([1ba09db](https://github.com/oaslananka/kicad-mcp/commit/1ba09dbeb1cccaacaca94e5d3559d79c4b117297))
* **docs:** add deploy job guard for pull_request events ([bf815ff](https://github.com/oaslananka/kicad-mcp/commit/bf815ffeedcd0547eaa3c0ca6322d3dc5c5e1b8f))
* **docs:** repair broken links causing mkdocs --strict build failure ([ab7c7d5](https://github.com/oaslananka/kicad-mcp/commit/ab7c7d5d8b0bd128afae508edc2a6beafb58a233))
* **docs:** update configure-pages and deploy-pages to latest pinned SHAs ([c8b2143](https://github.com/oaslananka/kicad-mcp/commit/c8b2143712f999e22951c98a3aba390feb780023))
* **docs:** use --extra dev not --group dev for mkdocs deps ([617c428](https://github.com/oaslananka/kicad-mcp/commit/617c428758481834986fe79ab26e6d7c1b311db9))
* **docs:** use python -m mkdocs for reliable binary discovery ([3acb5e2](https://github.com/oaslananka/kicad-mcp/commit/3acb5e2e9cb4e61752bc89545688edd03204dd4c))
* **e2e:** bump version assertion in E2E tests to 3.9.0 ([e90c410](https://github.com/oaslananka/kicad-mcp/commit/e90c410c74c94e2d4a2506c0b27462c8127afab9))
* guard watch and _run_with_watch params against leaked OptionInfo objects ([bef4a06](https://github.com/oaslananka/kicad-mcp/commit/bef4a064dd7a6ef58d3d2acbca9a9d82f529a53d))
* **gui-release:** upload only installer assets ([20c76c6](https://github.com/oaslananka/kicad-mcp/commit/20c76c657a41d71d8113bbfefae2b32063be0ebe))
* **gui:** add checkout step to create-release for gh run download ([2575cc3](https://github.com/oaslananka/kicad-mcp/commit/2575cc3abd6d0f3be36f11cc91e707b76f8acb3a))
* **gui:** disable updater signing, fix macOS universal target ([aab53aa](https://github.com/oaslananka/kicad-mcp/commit/aab53aa1cdefdc4bb22b2b7e50c8f41dd8211268))
* **gui:** pin a working backend version and stop the startup timeout from failing on cold installs ([#97](https://github.com/oaslananka/kicad-mcp/issues/97)) ([8d15056](https://github.com/oaslananka/kicad-mcp/commit/8d15056d032484cd9683f2d9b244758cb907075d))
* **gui:** restore Rust quality gates ([0345b9c](https://github.com/oaslananka/kicad-mcp/commit/0345b9ced9a1f6b04c1a0f122060ec17e5a23cea))
* **gui:** skip codesigning on macOS (no Apple cert) ([e311062](https://github.com/oaslananka/kicad-mcp/commit/e3110623e31b002a4737fa85ee876087a1c34ef1))
* handle partial document availability in kicad_get_version ([41e031a](https://github.com/oaslananka/kicad-mcp/commit/41e031a37428c259fc7d7981a2a32fe2ee5eb934))
* handle scoped tarball name mismatch in verify-npm-release, make publish idempotent ([#5](https://github.com/oaslananka/kicad-mcp/issues/5)) ([6e8f09b](https://github.com/oaslananka/kicad-mcp/commit/6e8f09b92fdae9ab0cd6f2a97ad2df26ccc2c731))
* harden ChatGPT app server ([#182](https://github.com/oaslananka/kicad-mcp/issues/182)) ([c5f6368](https://github.com/oaslananka/kicad-mcp/commit/c5f6368bfa33fa8034d28fa3cf36c208d8c37fd1))
* ignore explicit no-connect pins in connectivity gate ([cbaefaf](https://github.com/oaslananka/kicad-mcp/commit/cbaefafef8ee97f29566c14b5a8f4a5196713889))
* ignore informational gate metrics in findings ([3f3f197](https://github.com/oaslananka/kicad-mcp/commit/3f3f19779d17f0ec475867cd042b61e6617eb366))
* keep dense pin label terminals on natural rows ([3c2f400](https://github.com/oaslananka/kicad-mcp/commit/3c2f400feecac7f24f50c521c7e66355d163e020))
* KiCad 10 bugs, version gating, DRU parser, and KiCad 11 paths ([8e60880](https://github.com/oaslananka/kicad-mcp/commit/8e60880830ad3ccdd2f4d050ecb7fda0b29760be))
* KiCad 10 bugs, version gating, DRU parser, KiCad 11 paths ([3143874](https://github.com/oaslananka/kicad-mcp/commit/3143874f4d4f3cf640d1e455532055694da402ac))
* KiCad 10 bugs, version gating, DRU parser, KiCad 11 paths ([3143874](https://github.com/oaslananka/kicad-mcp/commit/3143874f4d4f3cf640d1e455532055694da402ac))
* KiCad IPC lifecycle — TTL cache, exponential backoff, IpcDisconnectedError ([cd930c7](https://github.com/oaslananka/kicad-mcp/commit/cd930c7997e1ea727330b4ac12fdea427e0b9b58)), closes [#42](https://github.com/oaslananka/kicad-mcp/issues/42)
* **lint:** resolve all 49 ruff lint errors (unused vars, long lines, missing annotations, undefined name) ([4965355](https://github.com/oaslananka/kicad-mcp/commit/4965355263f25b2120e94584122bb7f13539489f))
* load CLI on Typer versions without the vendored _click module ([#105](https://github.com/oaslananka/kicad-mcp/issues/105)) ([5dc2b9f](https://github.com/oaslananka/kicad-mcp/commit/5dc2b9f9669b98875a6a448c40ef6d96fae023b3))
* move importlib.util import to top of tray.py to fix ruff E402 ([8f3c230](https://github.com/oaslananka/kicad-mcp/commit/8f3c23012c55c768cbbcc591caaafe625c1af230))
* pass NPM_TOKEN as NODE_AUTH_TOKEN for publish ([48a27fa](https://github.com/oaslananka/kicad-mcp/commit/48a27fa4e5f26bf276076962446c150ccb22f4ec))
* preserve schematic paper size on build ([8cbecf6](https://github.com/oaslananka/kicad-mcp/commit/8cbecf680dc598e52003419e3e14c7013615a5d2))
* preserve unsnapped power symbol coordinates ([b10794d](https://github.com/oaslananka/kicad-mcp/commit/b10794ddfb7ca68b5153b45f975126f5c89f7623))
* **protocol-schemas:** export package.json for require.resolve consumers ([e4c6f6f](https://github.com/oaslananka/kicad-mcp/commit/e4c6f6f75c70ea63eec5fd55063fcdc913e7ac94))
* **release:** add kicad-mcp-gui to linked-versions + fix GUI release pipeline ([a40fc13](https://github.com/oaslananka/kicad-mcp/commit/a40fc1308c4d5bb739f42f26f9e4b5f153a00b10))
* **release:** set group-pull-request-title-pattern to include version ([784aea4](https://github.com/oaslananka/kicad-mcp/commit/784aea49831f2347cbcbb3729bd232824790347d))
* remove invalid subfolder '.' from server.json ([#20](https://github.com/oaslananka/kicad-mcp/issues/20)) ([b335546](https://github.com/oaslananka/kicad-mcp/commit/b335546fa3e1a7f5e07fb7295327ed162c48c914))
* remove structuredContent from error CallToolResult to avoid IPC schema validation error ([12a4982](https://github.com/oaslananka/kicad-mcp/commit/12a4982a60aae9dfbc7f0ee25aeeab9d89e5fdfc))
* resolve 15 pre-existing schematic integration test failures ([f298b5a](https://github.com/oaslananka/kicad-mcp/commit/f298b5a2580f12f19f16442c2bd7fc3818d5d133))
* resolve all 15 audit issues from TEMP audit ([48dec8c](https://github.com/oaslananka/kicad-mcp/commit/48dec8c61e2452f71eb53cf07459fca16307166b))
* resolve CI failures - README version marker mismatch and ruff 0.15.10 macOS crash ([059c78b](https://github.com/oaslananka/kicad-mcp/commit/059c78bd9b3a665650e02384263109a2925947c8))
* resolve ci lint failure in schematic render error path ([88d3a52](https://github.com/oaslananka/kicad-mcp/commit/88d3a52d7d6d061c2f2c92cc2c4d1389cf5015f5))
* resolve mypy type errors in _task_manager attr and get_result_text ([c31b940](https://github.com/oaslananka/kicad-mcp/commit/c31b940d27b035d9c86c62f7277d8b5365668e85))
* resolve mypy type errors in tray.py and routes.py ([70dd6bf](https://github.com/oaslananka/kicad-mcp/commit/70dd6bf1dc0ef411aa53da34a240004498465b2b))
* restore release readiness baseline ([bc08eca](https://github.com/oaslananka/kicad-mcp/commit/bc08eca753a32da76355ad1c1fb20a8ddcceb6b2)), closes [#6](https://github.com/oaslananka/kicad-mcp/issues/6)
* ruff format for 4 files (net_analysis.py, test_project_embedded_files.py, test_validation_tools.py, test_variants_extended.py) ([4095167](https://github.com/oaslananka/kicad-mcp/commit/409516783d1f2648c66a1c85be8f3706c567252a))
* satisfy typecheck in capability parity and schematic tools ([4c1d8b4](https://github.com/oaslananka/kicad-mcp/commit/4c1d8b4802ace1d0c1fdd5f964ef61b3e3c399c3))
* **server.json:** correct default port from 8090 to 3334 ([cbaab66](https://github.com/oaslananka/kicad-mcp/commit/cbaab666c9f8aa11ec079b85127af522df9951ce))
* silence mypy no-redef on the typer/click fallback import ([#106](https://github.com/oaslananka/kicad-mcp/issues/106)) ([6e51411](https://github.com/oaslananka/kicad-mcp/commit/6e514112c1484a865836fdf7c0a49afc422dc1dd))
* support pin labels on power symbols ([#185](https://github.com/oaslananka/kicad-mcp/issues/185)) ([291bf62](https://github.com/oaslananka/kicad-mcp/commit/291bf62f40cfb6b1849db954a1193442267e7de5))
* surface partially-unresolved nets in sch_build_circuit result (P2-T4) ([b046f86](https://github.com/oaslananka/kicad-mcp/commit/b046f866ac55f16fe682920b1e84e9df38755f75))
* sync embedded COMPATIBILITY_MATRIX version to 3.7.3 ([2b662bb](https://github.com/oaslananka/kicad-mcp/commit/2b662bb5078b09f896a682d64b29a75f42c88a03))
* sync GUI app version in tauri.conf.json and auto-bump it on release ([#98](https://github.com/oaslananka/kicad-mcp/issues/98)) ([5c0b6b5](https://github.com/oaslananka/kicad-mcp/commit/5c0b6b563bc3c97fd77676dec1f6c9984e6a1ff8))
* sync MCP metadata generator with server.json to fix CI metadata check ([1cf031d](https://github.com/oaslananka/kicad-mcp/commit/1cf031dbd214f97fc2b860b1ad2897a62d71df9a))
* sync server.json metadata after dashboard code changes ([3a37425](https://github.com/oaslananka/kicad-mcp/commit/3a37425cb8d4330f48e8431fdfbb50e30be6961d))
* sync tauri.conf.json version to 3.12.0 ([#102](https://github.com/oaslananka/kicad-mcp/issues/102)) ([90add7a](https://github.com/oaslananka/kicad-mcp/commit/90add7a47e30fa83ac6a984332573a657d5511e1))
* sync version to 3.7.5 in __init__.py and compatibility.py ([9c3c389](https://github.com/oaslananka/kicad-mcp/commit/9c3c38901ce4f764896aa8078d9b59dcc47ccc42))
* **tauri:** disable compression feature to exclude brotli, fixing Allocator trait conflict ([6503444](https://github.com/oaslananka/kicad-mcp/commit/650344402e33b4d31ae75cee5c3bf678ab7f951d))
* **tauri:** force alloc-no-stdlib v3.0.0 via patch to fix Rust 1.85+ Allocator conflict ([e3ebb71](https://github.com/oaslananka/kicad-mcp/commit/e3ebb71d6f3fcb170b1302f1dc8eb45e415a5407))
* **tauri:** pin Rust 1.84 via rust-toolchain.toml for brotli allocator compatibility ([28f5443](https://github.com/oaslananka/kicad-mcp/commit/28f5443ef47e9e2f87c7d2f9e02851af8f2fd783))
* **tests:** fix 3 integration test failures (visual diff alpha channel, router orphans, toolsets drift, snapshot) ([4f89829](https://github.com/oaslananka/kicad-mcp/commit/4f898297e4a8e3d65e79ead7bcd61bcd7ce29452))
* **tests:** resolve 2 unit test failures in test_circuit_ir (pin metadata sch_dir fallback, relax connection assertion) ([658d0c4](https://github.com/oaslananka/kicad-mcp/commit/658d0c4b02328379e6b77048b937c3cb4ae039f6))
* **tests:** update kicad 9.x removal assertion to 3.9.0 after compatibility.yaml change ([2a048cf](https://github.com/oaslananka/kicad-mcp/commit/2a048cfc9ded6dcec15d8393eae0f1295553fdc9))
* three CI test failures (cli missing binary, footprint 3d dir, Dockerfile UV_VERSION) ([c2512da](https://github.com/oaslananka/kicad-mcp/commit/c2512daded1d369e11aac7805ca44f1123a79f47))
* **typecheck:** resolve 12 mypy errors across 4 files (placement_rules, schematic, routing, ir) ([9d038d6](https://github.com/oaslananka/kicad-mcp/commit/9d038d608db7a87b9b2da953f3505dde6d1fd96f))
* **typecheck:** resolve 7 mypy strict errors in server.py ([dacca41](https://github.com/oaslananka/kicad-mcp/commit/dacca4133880ac4d2ab95cb81a1d2e248b504350))
* update stale 3.8.0 version references to 3.9.0 ([505bdfd](https://github.com/oaslananka/kicad-mcp/commit/505bdfda3f84c0ece8a252d2eb0f40eca0bcecdf))
* use power symbols for pin label power terminals ([c2fb17b](https://github.com/oaslananka/kicad-mcp/commit/c2fb17b738cbe8bffb2ca8f4127b1516cbdaee22))
* warn on checkout version drift in doctor ([59a54f8](https://github.com/oaslananka/kicad-mcp/commit/59a54f8de43f3593eff60ce3b12da28aa91955ea))
* **watch:** start server in subprocess, kill and respawn on changes ([26473f2](https://github.com/oaslananka/kicad-mcp/commit/26473f21fc2213590108d438c3afd3911437ddca))
* **workflows:** add actions:read permission to scorecard and codeql ([9a973d4](https://github.com/oaslananka/kicad-mcp/commit/9a973d48768542969cf4af14cc9c854dadf49488))
* **workflows:** add GITHUB_TOKEN to release-please and scorecard ([5c51bc3](https://github.com/oaslananka/kicad-mcp/commit/5c51bc3413d7d1e49eef6ffa52b4b250683d9359))
* **workflows:** pass GITHUB_TOKEN explicitly to CodeQL init and analyze steps ([3bc4083](https://github.com/oaslananka/kicad-mcp/commit/3bc408363854e31f66e725054c3007201ce3ffca))
* **workflows:** remove explicit token parameter in CodeQL steps ([e2913b4](https://github.com/oaslananka/kicad-mcp/commit/e2913b43f423f7a3a7e81256edae865948ff78db))
* **workflows:** run CodeQL matrix jobs sequentially to avoid token rate limits ([d3e308c](https://github.com/oaslananka/kicad-mcp/commit/d3e308c04a805cd26003c192b9b8b4f4c443abb6))
* **workflows:** update docs actions for Node 24 ([af7b849](https://github.com/oaslananka/kicad-mcp/commit/af7b849ae8336c7a78e6a1d1fcb202b59eda01ef))
* **workflows:** update docs actions for Node 24 ([f4c80fb](https://github.com/oaslananka/kicad-mcp/commit/f4c80fbc9b09b5ffdb5e8ed5f58242f586bb405d))


### Documentation

* add centered hero tagline and quick links to README ([#104](https://github.com/oaslananka/kicad-mcp/issues/104)) ([9b680b5](https://github.com/oaslananka/kicad-mcp/commit/9b680b53ae037797ffa5f8434048fa2577d08cdd))
* add MCP client guides for Cline, Windsurf, Continue, and Zed ([#96](https://github.com/oaslananka/kicad-mcp/issues/96)) ([102f662](https://github.com/oaslananka/kicad-mcp/commit/102f662f1d43393a0be0524c96d16c48482676ba))
* add PyPI, npm, CI, license, scorecard badges to README ([#30](https://github.com/oaslananka/kicad-mcp/issues/30)) ([22564f7](https://github.com/oaslananka/kicad-mcp/commit/22564f7ea7dee04e1dd6f0e7368a3be770ff6473))
* add root ARCHITECTURE.md and link from README (P0-T1) ([0b231f6](https://github.com/oaslananka/kicad-mcp/commit/0b231f60bc13db4ae8afa851ba85662c6e795724))
* add synced error-code catalog and consolidate install docs (P1-T8) ([d2497a8](https://github.com/oaslananka/kicad-mcp/commit/d2497a87bbe15ae4aff25bd5d4c9025dda667a2e))
* bus-factor governance — succession, continuity, tool on-ramp (P5-T1) ([a2e243c](https://github.com/oaslananka/kicad-mcp/commit/a2e243cce78ce59bd94d43eeb05a3b73b43fbada))
* center README badges and show total downloads ([#103](https://github.com/oaslananka/kicad-mcp/issues/103)) ([b7eeb7e](https://github.com/oaslananka/kicad-mcp/commit/b7eeb7e5b4833c8a200012385560dd89b9ac8990))
* **changelog:** document audit remediation ([3cf7370](https://github.com/oaslananka/kicad-mcp/commit/3cf7370a36cb770c1d173a314b937f862e42bc14))
* doc-code honesty pass for footprints, sourcing, and analysis (P1-T6, K10/K4) ([4e1a5e9](https://github.com/oaslananka/kicad-mcp/commit/4e1a5e9a4057f1864f6f1425f3cc6cde799e570a))
* document SERVER_INITIALIZING in the error catalog (fix sync test) ([847e7e6](https://github.com/oaslananka/kicad-mcp/commit/847e7e6b819b85702e6c4e5d67c895fad31d5314))
* fix broken references to deleted files (mcp.json, PUBLIC_LISTING.md, Dockerfile.kicad10) ([5166714](https://github.com/oaslananka/kicad-mcp/commit/5166714b116a047a5e0a3562329761d7df4191d2))
* fix CLI command examples ([e76c79e](https://github.com/oaslananka/kicad-mcp/commit/e76c79eba0f12a7830ae3ac471b9946472934e7d))
* group mkdocs navigation by purpose ([d78923e](https://github.com/oaslananka/kicad-mcp/commit/d78923eb5091aa9a4c5fcebe15802db7cc256ed0))
* organize documentation landing page ([4af54b9](https://github.com/oaslananka/kicad-mcp/commit/4af54b9fc29c757ad9f5c9e48065059a122946d6))
* **readme:** organize badges and project identity ([8328168](https://github.com/oaslananka/kicad-mcp/commit/832816892f55539f5a635205842eab49b0dff327))
* **readme:** point telemetry note to privacy docs ([5ebef49](https://github.com/oaslananka/kicad-mcp/commit/5ebef49ab835a2f5f1c872fd4d924bece567d59d))
* regenerate tool catalog (311-&gt;314) for schematic label tools ([b887175](https://github.com/oaslananka/kicad-mcp/commit/b88717569a32c63f5db665e345e708ab183bdaa1))
* regenerate tool catalog for P1-T7 routing summary changes ([6e5d910](https://github.com/oaslananka/kicad-mcp/commit/6e5d910c329e028f9730c1a793dad478982d9ff2))
* remove obsolete release setup and add contributor guide ([66a4ed1](https://github.com/oaslananka/kicad-mcp/commit/66a4ed1ff3d10f9b2f8af421c1f9476641dbd15b))
* **security:** rigorous threat model with verified CLI-injection/path controls (P5-T2, K8) ([b075b44](https://github.com/oaslananka/kicad-mcp/commit/b075b446ef2eb8d561aaee3e3f1b4fd07ade1e13))
* sync tools-reference after pcb_export_stats profile update ([683ad46](https://github.com/oaslananka/kicad-mcp/commit/683ad46bd1e3cf07fa56f92b63b5dcc3d92357bb))
* sync tools-reference to 270 tools (regenerated) ([#64](https://github.com/oaslananka/kicad-mcp/issues/64)) ([3275791](https://github.com/oaslananka/kicad-mcp/commit/3275791a99231b36b962010125ea31c4e3ce814b))
* tidy README badges and add PyPI/npm download badges ([#100](https://github.com/oaslananka/kicad-mcp/issues/100)) ([29ab016](https://github.com/oaslananka/kicad-mcp/commit/29ab0164b8fcab2ab1dd669073e905df10c29768))
* turn manufacturing-export skeleton into a real sourcing-to-signoff guide ([daba9e3](https://github.com/oaslananka/kicad-mcp/commit/daba9e3372e601a0c5d19de3b6f1e6c43840b24c))
* unpin version from README install/transport examples ([#94](https://github.com/oaslananka/kicad-mcp/issues/94)) ([d4d6955](https://github.com/oaslananka/kicad-mcp/commit/d4d6955f8968a3c7c785c929dd91d2d4f8e38bb8))

## [3.15.0](https://github.com/oaslananka/kicad-mcp/compare/v3.14.1...v3.15.0) (2026-06-27)

### Features

* **placement:** constraint-driven placement critic with 4 rules (PLR-001–PLR-004): decap distance, crystal distance, SMPS hot-loop area, analog/digital separation (#203)
* **manufacturing:** `mfg_create_release_evidence` bundle with 4 compliance gates (artifact coverage, DRC, ERC, HV safety), stable content hash, machine-readable verdict (#208)
* **compat:** KiCad 11 headless-IPC strategy — `kicad-ipc-headless` backend, `headless_ipc_available` property, `KICAD_11_HEADLESS_IPC_MIN_VERSION` constant (#192)
* **ir:** semantic EDA intermediate representation — data model, KiCad → IR parser, lint, diff, and `sch_get_circuit_ir` MCP tool (#199)
* **library:** enrich component intelligence with lifecycle, RoHS, datasheet URL, and filters (#200)
* **routing:** close FreeRouting loop with headless SES apply and `generate_board_constraints` tool (#204, #202)
* **visual:** closed-loop visual verification and diff with alpha-channel fix (#207)
* **evals:** golden project corpus and eval harness (#210)
* **mcp:** protocol contract tests, progress/cancellation tests, and output-schema evolution policy (#209)
* **agent:** project design workflow phase state machine surface (#194, #195)

### Bug Fixes

* fix visual diff alpha-channel bug — flatten RGBA onto white before pixel diff
* fix 3 integration test failures (router orphans, toolsets drift, snapshot drift)
* add SWIG guard CI test to block `import pcbnew` in source

## [3.14.1](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.14.0...mcp-server-v3.14.1) (2026-06-21)


### Bug Fixes

* harden ChatGPT app server ([#182](https://github.com/oaslananka/kicad-mcp/issues/182)) ([c5f6368](https://github.com/oaslananka/kicad-mcp/commit/c5f6368bfa33fa8034d28fa3cf36c208d8c37fd1))
* support pin labels on power symbols ([#185](https://github.com/oaslananka/kicad-mcp/issues/185)) ([291bf62](https://github.com/oaslananka/kicad-mcp/commit/291bf62f40cfb6b1849db954a1193442267e7de5))

## [3.14.0](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.13.0...mcp-server-v3.14.0) (2026-06-21)


### Features

* add tool-selection eval harness and golden dataset ([#174](https://github.com/oaslananka/kicad-mcp/issues/174)) ([ca93d94](https://github.com/oaslananka/kicad-mcp/commit/ca93d94ce3c4af5bc80f821115ef4dac545e3301))


### Bug Fixes

* address code-review feedback on merged [#167](https://github.com/oaslananka/kicad-mcp/issues/167) ([#172](https://github.com/oaslananka/kicad-mcp/issues/172)) ([3bf7bb3](https://github.com/oaslananka/kicad-mcp/commit/3bf7bb3d8e9a498a2f8292d737926a946056f50e))


### Documentation

* fix CLI command examples ([e76c79e](https://github.com/oaslananka/kicad-mcp/commit/e76c79eba0f12a7830ae3ac471b9946472934e7d))

## [3.13.0](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.12.1...mcp-server-v3.13.0) (2026-06-21)


### Features

* add project release readiness workflow ([5fa6f1c](https://github.com/oaslananka/kicad-mcp/commit/5fa6f1cbfd18cc76b3945e2a3506d947934758e3))
* **erc:** expose structured run_erc finding metadata ([a744635](https://github.com/oaslananka/kicad-mcp/commit/a744635d5ec5a61890aa7691179c19047197e01c))
* harden tool contracts and operating mode coverage ([5e67cfc](https://github.com/oaslananka/kicad-mcp/commit/5e67cfcaf4d49052149f1cdb99dbd994302f3de1))


### Bug Fixes

* avoid generic regulator contract false matches ([0b91796](https://github.com/oaslananka/kicad-mcp/commit/0b91796101fdbe8366176a93ff333f0be8271fee))
* clear vertical pin terminals from symbol text ([7b3bec0](https://github.com/oaslananka/kicad-mcp/commit/7b3bec06b89700dfb30a6985e0b9b7a556331be4))
* handle partial document availability in kicad_get_version ([41e031a](https://github.com/oaslananka/kicad-mcp/commit/41e031a37428c259fc7d7981a2a32fe2ee5eb934))
* ignore explicit no-connect pins in connectivity gate ([cbaefaf](https://github.com/oaslananka/kicad-mcp/commit/cbaefafef8ee97f29566c14b5a8f4a5196713889))
* ignore informational gate metrics in findings ([3f3f197](https://github.com/oaslananka/kicad-mcp/commit/3f3f19779d17f0ec475867cd042b61e6617eb366))
* keep dense pin label terminals on natural rows ([3c2f400](https://github.com/oaslananka/kicad-mcp/commit/3c2f400feecac7f24f50c521c7e66355d163e020))
* preserve schematic paper size on build ([8cbecf6](https://github.com/oaslananka/kicad-mcp/commit/8cbecf680dc598e52003419e3e14c7013615a5d2))
* preserve unsnapped power symbol coordinates ([b10794d](https://github.com/oaslananka/kicad-mcp/commit/b10794ddfb7ca68b5153b45f975126f5c89f7623))
* resolve ci lint failure in schematic render error path ([88d3a52](https://github.com/oaslananka/kicad-mcp/commit/88d3a52d7d6d061c2f2c92cc2c4d1389cf5015f5))
* satisfy typecheck in capability parity and schematic tools ([4c1d8b4](https://github.com/oaslananka/kicad-mcp/commit/4c1d8b4802ace1d0c1fdd5f964ef61b3e3c399c3))
* use power symbols for pin label power terminals ([c2fb17b](https://github.com/oaslananka/kicad-mcp/commit/c2fb17b738cbe8bffb2ca8f4127b1516cbdaee22))
* warn on checkout version drift in doctor ([59a54f8](https://github.com/oaslananka/kicad-mcp/commit/59a54f8de43f3593eff60ce3b12da28aa91955ea))

## [3.12.1](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.12.0...mcp-server-v3.12.1) (2026-06-18)


### Bug Fixes

* load CLI on Typer versions without the vendored _click module ([#105](https://github.com/oaslananka/kicad-mcp/issues/105)) ([5dc2b9f](https://github.com/oaslananka/kicad-mcp/commit/5dc2b9f9669b98875a6a448c40ef6d96fae023b3))
* silence mypy no-redef on the typer/click fallback import ([#106](https://github.com/oaslananka/kicad-mcp/issues/106)) ([6e51411](https://github.com/oaslananka/kicad-mcp/commit/6e514112c1484a865836fdf7c0a49afc422dc1dd))
* sync tauri.conf.json version to 3.12.0 ([#102](https://github.com/oaslananka/kicad-mcp/issues/102)) ([90add7a](https://github.com/oaslananka/kicad-mcp/commit/90add7a47e30fa83ac6a984332573a657d5511e1))


### Documentation

* add centered hero tagline and quick links to README ([#104](https://github.com/oaslananka/kicad-mcp/issues/104)) ([9b680b5](https://github.com/oaslananka/kicad-mcp/commit/9b680b53ae037797ffa5f8434048fa2577d08cdd))
* center README badges and show total downloads ([#103](https://github.com/oaslananka/kicad-mcp/issues/103)) ([b7eeb7e](https://github.com/oaslananka/kicad-mcp/commit/b7eeb7e5b4833c8a200012385560dd89b9ac8990))
* tidy README badges and add PyPI/npm download badges ([#100](https://github.com/oaslananka/kicad-mcp/issues/100)) ([29ab016](https://github.com/oaslananka/kicad-mcp/commit/29ab0164b8fcab2ab1dd669073e905df10c29768))

## [3.12.0](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.11.0...mcp-server-v3.12.0) (2026-06-18)


### Features

* **dashboard:** surface AI agent setup and prompt links in the sidebar ([#99](https://github.com/oaslananka/kicad-mcp/issues/99)) ([db56aa8](https://github.com/oaslananka/kicad-mcp/commit/db56aa83a7230beab0ae72ef832d9ea4be2cd356))


### Bug Fixes

* **gui:** pin a working backend version and stop the startup timeout from failing on cold installs ([#97](https://github.com/oaslananka/kicad-mcp/issues/97)) ([8d15056](https://github.com/oaslananka/kicad-mcp/commit/8d15056d032484cd9683f2d9b244758cb907075d))
* sync GUI app version in tauri.conf.json and auto-bump it on release ([#98](https://github.com/oaslananka/kicad-mcp/issues/98)) ([5c0b6b5](https://github.com/oaslananka/kicad-mcp/commit/5c0b6b563bc3c97fd77676dec1f6c9984e6a1ff8))


### Documentation

* add MCP client guides for Cline, Windsurf, Continue, and Zed ([#96](https://github.com/oaslananka/kicad-mcp/issues/96)) ([102f662](https://github.com/oaslananka/kicad-mcp/commit/102f662f1d43393a0be0524c96d16c48482676ba))
* unpin version from README install/transport examples ([#94](https://github.com/oaslananka/kicad-mcp/issues/94)) ([d4d6955](https://github.com/oaslananka/kicad-mcp/commit/d4d6955f8968a3c7c785c929dd91d2d4f8e38bb8))

## [3.11.0](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.10.0...mcp-server-v3.11.0) (2026-06-17)


### Features

* apply routed Specctra SES to the board headlessly (P4-T1) ([#91](https://github.com/oaslananka/kicad-mcp/issues/91)) ([0563efc](https://github.com/oaslananka/kicad-mcp/commit/0563efce3d5f54aa413cddde9f325d010f974a78))
* selective re-validation after edit completes first-class edit mode (P4-T4) ([#88](https://github.com/oaslananka/kicad-mcp/issues/88)) ([d827523](https://github.com/oaslananka/kicad-mcp/commit/d82752362b9924b54868a778a457f1ceed803a4e))


### Bug Fixes

* correct Specctra SES coordinate scale (1 mm = 1000 units, not 10000) ([#92](https://github.com/oaslananka/kicad-mcp/issues/92)) ([565a020](https://github.com/oaslananka/kicad-mcp/commit/565a02030d68cdb2b0bcddd325f5f5a1014ef66f))
* discover symbol/footprint libraries via sym-/fp-lib-table ([#78](https://github.com/oaslananka/kicad-mcp/issues/78)) ([#90](https://github.com/oaslananka/kicad-mcp/issues/90)) ([72fce79](https://github.com/oaslananka/kicad-mcp/commit/72fce791eaf87e48255807799a19595923c34d8a))

## [3.10.0](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.9.2...mcp-server-v3.10.0) (2026-06-17)


### Features

* 2-D finite-difference copper-plane thermal spreading solver (P3-T4) ([1aa70c5](https://github.com/oaslananka/kicad-mcp/commit/1aa70c5bee163b82f74f52f58648e30e69f9ae6f))
* add KiCad capability-parity matrix and kicad_capability_parity tool (P0-T4) ([c742a9e](https://github.com/oaslananka/kicad-mcp/commit/c742a9e0a303dc1245163490a384b959522f8947))
* bound deferred tool registration with a timeout (P5-T5) ([081f87b](https://github.com/oaslananka/kicad-mcp/commit/081f87b05e949b75a18fae638a0c4e3cc70e481e))
* complete error transient-class and tool idempotency contract (P1-T5, K9) ([97460dd](https://github.com/oaslananka/kicad-mcp/commit/97460dd587316e78a04a7142075bad1c939331bd))
* component derating + approved-vendor (AVL) sourcing gate (P4-T3) ([2e5e3e9](https://github.com/oaslananka/kicad-mcp/commit/2e5e3e954a6a2004abf83f69f16b8b5cd9a30ae5))
* deterministic convergence-based placement, no wall-clock cap (P4-T2, K7) ([cade887](https://github.com/oaslananka/kicad-mcp/commit/cade8877d6158f214c394cf39b5ebcf028a60148))
* deterministic, provenance-stamped reproducible release manifest (P2-T5) ([a6d9de2](https://github.com/oaslananka/kicad-mcp/commit/a6d9de21790a7f272af5d0103fc31550830e89c8))
* edit-impact analysis to scope re-validation after edits (P4-T4) ([fca853f](https://github.com/oaslananka/kicad-mcp/commit/fca853ffcdcfc016af00fbd10170423110c08722))
* field-solver adapter seam + honest impedance method labeling (P3-T1) ([11a4a4d](https://github.com/oaslananka/kicad-mcp/commit/11a4a4d10ebff4a4b3bed83e4f71cc44ce197b1a))
* high-speed channel insertion-loss / eye analysis via ngspice (P3-T3) ([e3f3778](https://github.com/oaslananka/kicad-mcp/commit/e3f377833a73267c253773c8d800438c7864cf2e))
* honest FreeRouting manual-step handling and headless DSN attempt (P1-T7, K1) ([e0154f5](https://github.com/oaslananka/kicad-mcp/commit/e0154f572b51ab23973d631187dff3a493433420))
* IPC-2221 current-density fusing + honest distributed-PDN labeling (P3-T2) ([4e278d8](https://github.com/oaslananka/kicad-mcp/commit/4e278d8f8bad3decb02de826ee92df983f905783))
* IPC-7351B footprint validation hard-gate for chip packages (P4-T3) ([6db8e46](https://github.com/oaslananka/kicad-mcp/commit/6db8e461b9555acc425c30364c954ded64872a35))
* live Mouser keyword-search client completes the distributor trio (P4-T3) ([ee613ae](https://github.com/oaslananka/kicad-mcp/commit/ee613ae712923d280667892fb882bfc99fbf178b))
* manufacturing sign-off report binding requirements to checks (P5-T3) ([de3c500](https://github.com/oaslananka/kicad-mcp/commit/de3c500fdecbd4b451876af93608485e5cfec1c9))
* Nexar lifecycle/RoHS sourcing data + actionable quota error (P4-T3) ([f6b98c7](https://github.com/oaslananka/kicad-mcp/commit/f6b98c7ddc9941c3bb5ea259d005efec67db7adc))
* parity coverage-regression gate, baseline, and README badge (P5-T6) ([b02eebe](https://github.com/oaslananka/kicad-mcp/commit/b02eebe0400c7457de1d49a633114dd934cd21bf))
* PDN + thermal solver-adapter seams with honest method labeling (P3-T2/T4 seams) ([8d3af87](https://github.com/oaslananka/kicad-mcp/commit/8d3af879ee02197c6d87f952d7caf7b449502a9c))
* rate-limit the bridge daemon against floods and pairing brute force (P5-T5, K8) ([1fecc9d](https://github.com/oaslananka/kicad-mcp/commit/1fecc9d5ebb009db87091daf6828cba82fca3624))
* real DigiKey Product Information (v4) client (P4-T3) ([b9b36d4](https://github.com/oaslananka/kicad-mcp/commit/b9b36d43880ddacd2691ab3c655b1ee401c9c8ae))
* real Nexar Supply client + .env credential loading (P4-T3) ([d797759](https://github.com/oaslananka/kicad-mcp/commit/d797759413c1de9a43c5fc2e306a9ca2d4edac4b))
* real PASS/WARN/FAIL verdicts for SI gates (P1-T3, K2) ([915c752](https://github.com/oaslananka/kicad-mcp/commit/915c752dd900c2388750f6c53924829d826d0ada))
* real task cancellation + execution timeout in the Tasks layer (P5-T5) ([c1f96cb](https://github.com/oaslananka/kicad-mcp/commit/c1f96cbcabeb879007b37dd5e186a54f76064e13))
* round-trip-safe schematic edit primitive with corruption guard (P2-T1/T2, K5/K6) ([2e1dbf6](https://github.com/oaslananka/kicad-mcp/commit/2e1dbf66f44e2e687743ea5075d43e531eeffd70))
* structural IPC error classification + restart cache invalidation (P5-T5) ([bdb7cb4](https://github.com/oaslananka/kicad-mcp/commit/bdb7cb4d87727f879b9367c3520c3e8b6e70943f))
* structured verdict payloads for high-traffic gate tools (P1-T4) ([ee3c21a](https://github.com/oaslananka/kicad-mcp/commit/ee3c21a6b2b27f6954a7530b26635330169351ac))


### Bug Fixes

* align main ruleset with real CI check names + guard (P5-T4) ([f23ac33](https://github.com/oaslananka/kicad-mcp/commit/f23ac3328f6b58a5013d59d1ad097f74ca48aac2))
* bump compatibility.yaml version from 3.9.1 to 3.9.2 ([a9ef4ff](https://github.com/oaslananka/kicad-mcp/commit/a9ef4ff2d85b0862b69f77812910a81450d88426))
* bump hardcoded version refs from 3.9.1 to 3.9.2 in tests, dashboard, compatibility, README ([40a080b](https://github.com/oaslananka/kicad-mcp/commit/40a080b1b3251d0fce46e621be5a4808731fc18e))
* bump playwright e2e test version assertion v3.9.1 -&gt; v3.9.2 ([28ffa0a](https://github.com/oaslananka/kicad-mcp/commit/28ffa0a49453848cc1d68945fe1941f2fe540a05))
* **chatgpt-app:** add path-traversal guards, XSS escaping, and rate limiting ([0084de5](https://github.com/oaslananka/kicad-mcp/commit/0084de587e8639a50caebde230e2ac35c165bcaa))
* **ci:** repair container build hash-pinning and patch starlette CVE-2026-54283 ([023ee30](https://github.com/oaslananka/kicad-mcp/commit/023ee30dc25dc4c015f8f981a3baa4a0b89f5c3d))
* resolve 15 pre-existing schematic integration test failures ([f298b5a](https://github.com/oaslananka/kicad-mcp/commit/f298b5a2580f12f19f16442c2bd7fc3818d5d133))
* surface partially-unresolved nets in sch_build_circuit result (P2-T4) ([b046f86](https://github.com/oaslananka/kicad-mcp/commit/b046f866ac55f16fe682920b1e84e9df38755f75))


### Documentation

* add root ARCHITECTURE.md and link from README (P0-T1) ([0b231f6](https://github.com/oaslananka/kicad-mcp/commit/0b231f60bc13db4ae8afa851ba85662c6e795724))
* add synced error-code catalog and consolidate install docs (P1-T8) ([d2497a8](https://github.com/oaslananka/kicad-mcp/commit/d2497a87bbe15ae4aff25bd5d4c9025dda667a2e))
* bus-factor governance — succession, continuity, tool on-ramp (P5-T1) ([a2e243c](https://github.com/oaslananka/kicad-mcp/commit/a2e243cce78ce59bd94d43eeb05a3b73b43fbada))
* doc-code honesty pass for footprints, sourcing, and analysis (P1-T6, K10/K4) ([4e1a5e9](https://github.com/oaslananka/kicad-mcp/commit/4e1a5e9a4057f1864f6f1425f3cc6cde799e570a))
* document SERVER_INITIALIZING in the error catalog (fix sync test) ([847e7e6](https://github.com/oaslananka/kicad-mcp/commit/847e7e6b819b85702e6c4e5d67c895fad31d5314))
* regenerate tool catalog (311-&gt;314) for schematic label tools ([b887175](https://github.com/oaslananka/kicad-mcp/commit/b88717569a32c63f5db665e345e708ab183bdaa1))
* regenerate tool catalog for P1-T7 routing summary changes ([6e5d910](https://github.com/oaslananka/kicad-mcp/commit/6e5d910c329e028f9730c1a793dad478982d9ff2))
* **security:** rigorous threat model with verified CLI-injection/path controls (P5-T2, K8) ([b075b44](https://github.com/oaslananka/kicad-mcp/commit/b075b446ef2eb8d561aaee3e3f1b4fd07ade1e13))
* turn manufacturing-export skeleton into a real sourcing-to-signoff guide ([daba9e3](https://github.com/oaslananka/kicad-mcp/commit/daba9e3372e601a0c5d19de3b6f1e6c43840b24c))

## [Unreleased]

### Added

### Fixed

### Changed

## [3.9.1](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.9.0...mcp-server-v3.9.1) (2026-06-10)


### Fixed

- Resolved CI test failure (`test_readme_listing_references_use_current_package_version`) caused by README version marker not matching the table format in `check_submission_readiness.py`.
- Pinned `ruff!=0.15.10` in dev dependencies to avoid a dyld rebase crash on macOS ARM64 runners.
- Fixed TypeScript syntax error in `apps-sdk/src/server.ts` where optional chaining was incorrectly applied after a type assertion.
- Removed the final obsolete release-token setup instruction.
- Hardened release workflows against excessive permissions, template injection,
  and publish-job cache poisoning.
- Restored the missing root contribution guide and required README sections.
- Restored the Tauri Rust format and Clippy quality gates.

### Changed

- Aligned the enforced full-suite coverage baseline with the measured repository
  coverage so the local quality gate detects regressions and remains runnable.

## [3.9.0](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.8.0...mcp-server-v3.9.0) (2026-06-07)


### Features

* add SPICE model assignment and library management tools ([ec14eb6](https://github.com/oaslananka/kicad-mcp/commit/ec14eb6c4dc01d0632b1f4b6b8ac3fd5cbe1c9f0))
* **cli:** add init, status, log commands with improved errors ([e66a6ef](https://github.com/oaslananka/kicad-mcp/commit/e66a6ef20e461651dc2983915a8f5054b89c9e74))
* complete all 20-phase plan — 22 new tools, 31 new files, full KiCad MCP feature parity ([34a1d92](https://github.com/oaslananka/kicad-mcp/commit/34a1d92001cae2ca7d8936a0b01a2a3386022276))
* **dev:** add hot reload, inspector command, IPC mock fixtures, better error logging, pre-commit pytest ([ed583f0](https://github.com/oaslananka/kicad-mcp/commit/ed583f04c1b98d76000e630b07e1a3f79c87d505))


### Bug Fixes

* address issues [#56](https://github.com/oaslananka/kicad-mcp/issues/56), [#57](https://github.com/oaslananka/kicad-mcp/issues/57), [#61](https://github.com/oaslananka/kicad-mcp/issues/61) (pagination, DNP test, canary extension) ([1d4e7b3](https://github.com/oaslananka/kicad-mcp/commit/1d4e7b39fe059b8dc2b89d4a1f0acf22cdeedeeb))
* **ci:** update sync_mcp_metadata.py source with correct descriptions and empty remotes ([9889890](https://github.com/oaslananka/kicad-mcp/commit/98898905e95a0a0a4c626d3d390348c5247ba94c))
* guard watch and _run_with_watch params against leaked OptionInfo objects ([bef4a06](https://github.com/oaslananka/kicad-mcp/commit/bef4a064dd7a6ef58d3d2acbca9a9d82f529a53d))
* KiCad IPC lifecycle — TTL cache, exponential backoff, IpcDisconnectedError ([cd930c7](https://github.com/oaslananka/kicad-mcp/commit/cd930c7997e1ea727330b4ac12fdea427e0b9b58)), closes [#42](https://github.com/oaslananka/kicad-mcp/issues/42)
* move importlib.util import to top of tray.py to fix ruff E402 ([8f3c230](https://github.com/oaslananka/kicad-mcp/commit/8f3c23012c55c768cbbcc591caaafe625c1af230))
* remove structuredContent from error CallToolResult to avoid IPC schema validation error ([12a4982](https://github.com/oaslananka/kicad-mcp/commit/12a4982a60aae9dfbc7f0ee25aeeab9d89e5fdfc))
* resolve all 15 audit issues from TEMP audit ([48dec8c](https://github.com/oaslananka/kicad-mcp/commit/48dec8c61e2452f71eb53cf07459fca16307166b))
* resolve mypy type errors in tray.py and routes.py ([70dd6bf](https://github.com/oaslananka/kicad-mcp/commit/70dd6bf1dc0ef411aa53da34a240004498465b2b))
* ruff format for 4 files (net_analysis.py, test_project_embedded_files.py, test_validation_tools.py, test_variants_extended.py) ([4095167](https://github.com/oaslananka/kicad-mcp/commit/409516783d1f2648c66a1c85be8f3706c567252a))
* **server.json:** correct default port from 8090 to 3334 ([cbaab66](https://github.com/oaslananka/kicad-mcp/commit/cbaab666c9f8aa11ec079b85127af522df9951ce))
* sync MCP metadata generator with server.json to fix CI metadata check ([1cf031d](https://github.com/oaslananka/kicad-mcp/commit/1cf031dbd214f97fc2b860b1ad2897a62d71df9a))
* **tests:** update kicad 9.x removal assertion to 3.9.0 after compatibility.yaml change ([2a048cf](https://github.com/oaslananka/kicad-mcp/commit/2a048cfc9ded6dcec15d8393eae0f1295553fdc9))
* three CI test failures (cli missing binary, footprint 3d dir, Dockerfile UV_VERSION) ([c2512da](https://github.com/oaslananka/kicad-mcp/commit/c2512daded1d369e11aac7805ca44f1123a79f47))
* **typecheck:** resolve 7 mypy strict errors in server.py ([dacca41](https://github.com/oaslananka/kicad-mcp/commit/dacca4133880ac4d2ab95cb81a1d2e248b504350))
* **watch:** start server in subprocess, kill and respawn on changes ([26473f2](https://github.com/oaslananka/kicad-mcp/commit/26473f21fc2213590108d438c3afd3911437ddca))


### Documentation

* sync tools-reference after pcb_export_stats profile update ([683ad46](https://github.com/oaslananka/kicad-mcp/commit/683ad46bd1e3cf07fa56f92b63b5dcc3d92357bb))

## [3.8.0](https://github.com/oaslananka/kicad-mcp/releases/tag/mcp-server-v3.8.0) (2026-06-06)

### Added

- **Phase 2 CLI-parity tools** — 20+ new footprint, symbol, jobset, upgrade, and
  manufacturing board import wrappers completing KiCad 10.0.3 CLI parity.
- **3D render formats**: BREP, GLB, GenCAD, IPC-D356, PLY, STL, U3D, VRML, PS
  with camera panning controls and variant support.
- **Schematic export expansion**: DXF, SVG, PS, python_bom, sch_upgrade.
- **Footprint tools**: `fp_export_svg`, `fp_upgrade`.
- **Symbol tools**: `sym_export_svg`, `sym_upgrade`.
- **Jobset tools**: `jobset_run`, `jobset_list_templates`, `jobset_list_outputs`.
- **Manufacturing board import**: PADS, gEDA, Specctra, Allegro (blocked) formats.
- **KiCad 10.0.3 contract canaries**: shared fixtures, Windows primary smoke
  coverage, scheduled 9.x/10.x lanes.
- **Doctor diagnostics**: `kicad-mcp-pro doctor`, JSON diagnostics, and redacted
  support bundles for setup troubleshooting.

### Fixed

- **Security**: Path traversal hardening across footprint, symbol, jobset, and
  upgrade tools — output paths validated with `resolve_under` and `Path().name`.
- **Fragile import in manufacturing.py**: `_run_cli_variants` imported from
  `.export_support` instead of `.export`.
- **Integer division bug**: `_human_size` uses float division preserving
  fractional byte sizes across KB/MB/GB conversions.
- **Pan logic**: Simplified falsy check for `pan_x`/`pan_y` in 3D render tool.
- **CI pipeline**: Format, lint, and typecheck errors resolved across all
  platforms (macOS, Windows, Linux).

### Deprecated

- Marked KiCad 9.x as a deprecated best-effort compatibility line in MCP
  discovery metadata while retaining scheduled non-blocking canary coverage.

## [3.7.6](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.7.5...mcp-server-v3.7.6) (2026-06-05)

### Bug Fixes

- **ci:** harden scorecard workflow ([#27](https://github.com/oaslananka/kicad-mcp/issues/27)) ([f5a163d](https://github.com/oaslananka/kicad-mcp/commit/f5a163dfc297839c6752a83669af4d0ee55af18b))
- **security:** add gitleaks pre-commit hook ([#28](https://github.com/oaslananka/kicad-mcp/issues/28)) ([5dad852](https://github.com/oaslananka/kicad-mcp/commit/5dad85216ef50fc6feb8e4feac2fc39e84f0f29e))

## [3.7.0](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.6.0...mcp-server-v3.7.0) (2026-06-03)

### Features

- initial migration from kicad-studio-kit monorepo ([#1](https://github.com/oaslananka/kicad-mcp/issues/1)) ([be9b16f](https://github.com/oaslananka/kicad-mcp/commit/be9b16f33aaea94fbea525edd173a93a7e3e5012))
- publish protocol-schemas as public npm package ([f09a57e](https://github.com/oaslananka/kicad-mcp/commit/f09a57ebedeab9a28c5bab6f34052baf1a4aed49))

### Bug Fixes

- add repository.url for npm provenance verification ([42045f5](https://github.com/oaslananka/kicad-mcp/commit/42045f5d35404c22c3023806c1714e768ba4f1f0))
- handle scoped tarball name mismatch in verify-npm-release, make publish idempotent ([#5](https://github.com/oaslananka/kicad-mcp/issues/5)) ([6e8f09b](https://github.com/oaslananka/kicad-mcp/commit/6e8f09b92fdae9ab0cd6f2a97ad2df26ccc2c731))
- pass NPM_TOKEN as NODE_AUTH_TOKEN for publish ([48a27fa](https://github.com/oaslananka/kicad-mcp/commit/48a27fa4e5f26bf276076962446c150ccb22f4ec))
- **protocol-schemas:** export package.json for require.resolve consumers ([e4c6f6f](https://github.com/oaslananka/kicad-mcp/commit/e4c6f6f75c70ea63eec5fd55063fcdc913e7ac94))
- restore release readiness baseline ([bc08eca](https://github.com/oaslananka/kicad-mcp/commit/bc08eca753a32da76355ad1c1fb20a8ddcceb6b2)), closes [#6](https://github.com/oaslananka/kicad-mcp/issues/6)

## [3.6.0](https://github.com/oaslananka/kicad-mcp/compare/mcp-server-v3.5.2...mcp-server-v3.6.0) (2026-05-27)

### Features

- **compat:** add release compatibility matrix ([f35ba2d](https://github.com/oaslananka/kicad-mcp/commit/f35ba2d34327a51890ad702cba7b188f10597a4b))
- **kicad-mcp-pro:** add multi-arch container publishing ([db4f98a](https://github.com/oaslananka/kicad-mcp/commit/db4f98a3cccd3dbd2e504d44662f743b0b3cf9b6))
- **kicad-mcp-pro:** add multi-arch container publishing ([2dc0ebc](https://github.com/oaslananka/kicad-mcp/commit/2dc0ebcfa2d755278a833149d81c44ec2dc26d5f))
- **kicad-mcp-pro:** add OpenTelemetry observability ([b34ab19](https://github.com/oaslananka/kicad-mcp/commit/b34ab192f59c6186a6090951139c8b801612641d))
- **kicad-mcp-pro:** add OpenTelemetry observability ([b4f38b8](https://github.com/oaslananka/kicad-mcp/commit/b4f38b80b4c4ceeecd2acf73e92354ae1aee8f9a))
- **kicad-mcp-pro:** add structured logging lifecycle ([3e4f9bf](https://github.com/oaslananka/kicad-mcp/commit/3e4f9bf03b25d58328de9ea5baf645ee35f7cde9))
- **kicad-mcp-pro:** add structured logging lifecycle ([8293e25](https://github.com/oaslananka/kicad-mcp/commit/8293e25840f2ee8dbbeb56466e58353e01c15bc3))
- **kicad-studio/kicad-mcp-pro:** add doctor diagnostics ([88dca0c](https://github.com/oaslananka/kicad-mcp/commit/88dca0cc015a24d50b8d8b2db948783be68240ff)), closes [#74](https://github.com/oaslananka/kicad-mcp/issues/74)
- **kicad-studio/kicad-mcp-pro:** add KiCad IPC capability gating ([835e488](https://github.com/oaslananka/kicad-mcp/commit/835e48820404ad93c24b8cfd66bb68710ef2983c))
- **kicad-studio/kicad-mcp-pro:** add KiCad IPC capability gating ([c81db7a](https://github.com/oaslananka/kicad-mcp/commit/c81db7ac31b275be1d667d12eb61cdb96ad03cd7))
- **kicad-studio/kicad-mcp-pro:** add localization infrastructure ([49f949e](https://github.com/oaslananka/kicad-mcp/commit/49f949e7dc4914a8a4fc58486eca388694da1a60))
- **kicad-studio/kicad-mcp-pro:** add localization infrastructure ([fbe63e0](https://github.com/oaslananka/kicad-mcp/commit/fbe63e0d156e6d044cc5b515e1919b51ea86581e))
- **kicad-studio/kicad-mcp-pro:** add monorepo dev doctor ([7766750](https://github.com/oaslananka/kicad-mcp/commit/77667509d6ffef1e9c5779b63701b95c39433939))
- **kicad-studio/kicad-mcp-pro:** add monorepo dev doctor ([11f2168](https://github.com/oaslananka/kicad-mcp/commit/11f2168c9482daeceff89f74806b21697d4fc9df))
- **kicad-studio/kicad-mcp-pro:** add operating modes ([2cd849a](https://github.com/oaslananka/kicad-mcp/commit/2cd849a050e0119cd9ec7bb02463b3e37ff0a35a)), closes [#73](https://github.com/oaslananka/kicad-mcp/issues/73)
- **kicad-studio/kicad-mcp-pro:** add opt-in privacy-safe reporting ([55ca498](https://github.com/oaslananka/kicad-mcp/commit/55ca498d881d30cb725e532b6200bccefe3662e0))
- **kicad-studio/kicad-mcp-pro:** add opt-in privacy-safe reporting ([4d0e902](https://github.com/oaslananka/kicad-mcp/commit/4d0e902d938fa196a9d9c4c4468c918f7205b2b7))
- **kicad-studio/kicad-mcp-pro:** add product release provenance evidence ([#195](https://github.com/oaslananka/kicad-mcp/issues/195)) ([e2caccd](https://github.com/oaslananka/kicad-mcp/commit/e2caccd5663e394585b017554305ef0954b62d66))
- **kicad-studio/kicad-mcp-pro:** add shared protocol schemas package ([684ef9f](https://github.com/oaslananka/kicad-mcp/commit/684ef9fd9b8363914120a7228fa8cbf82e65d4db)), closes [#53](https://github.com/oaslananka/kicad-mcp/issues/53)
- **kicad-studio/kicad-mcp-pro:** add STEPZ and XAO exports ([b098507](https://github.com/oaslananka/kicad-mcp/commit/b098507762c456a875a4525108ab7eea58a60172)), closes [#232](https://github.com/oaslananka/kicad-mcp/issues/232)
- **mcp:** add server info capabilities contract ([759ef3a](https://github.com/oaslananka/kicad-mcp/commit/759ef3ae7c18d6c0f87eb1049ccc80d743eb3bc9))
- **repo:** add KiCad 10 parity matrix ([394f819](https://github.com/oaslananka/kicad-mcp/commit/394f81976e249ba7f728cfd11c812629d035bba5))
- **repo:** add KiCad 10.0.3 parity matrix ([7c3e9f7](https://github.com/oaslananka/kicad-mcp/commit/7c3e9f7bf0d8f3bfcc9de3905f63b3a86d2c3665))
- **repo:** harden KiCad 11 IPC readiness ([41f6376](https://github.com/oaslananka/kicad-mcp/commit/41f637646e51f0c557a60e10c700a38e9e077e4f)), closes [#182](https://github.com/oaslananka/kicad-mcp/issues/182)

### Bug Fixes

- keep MCP manifest tests release-safe ([7688545](https://github.com/oaslananka/kicad-mcp/commit/7688545af24745ea5a0ee0462fba5c2bbeea78c9))
- keep release preparation checks stable ([66123b7](https://github.com/oaslananka/kicad-mcp/commit/66123b7f1b10e6c4cdf81291aaecfa7a6fb0682a))
- **kicad-mcp-pro:** bind container http to all interfaces ([b89a967](https://github.com/oaslananka/kicad-mcp/commit/b89a96728cecff0a2d17190ce755c12e8044ee3a))
- **kicad-mcp-pro:** bump starlette security floor ([68cadc9](https://github.com/oaslananka/kicad-mcp/commit/68cadc9203f6dca94ea4711376b11cc0e1607e48))
- **kicad-mcp-pro:** make npm launcher build smoke cross-platform ([f96baca](https://github.com/oaslananka/kicad-mcp/commit/f96baca8b349856ae61bd5ee21cfed33c670bcef)), closes [#191](https://github.com/oaslananka/kicad-mcp/issues/191)
- **kicad-mcp-pro:** use shared GUI smoke fixture ([18b64df](https://github.com/oaslananka/kicad-mcp/commit/18b64dfc3ded282b6d9013d4dd32f56452339566)), closes [#186](https://github.com/oaslananka/kicad-mcp/issues/186)
- **kicad-mcp-pro:** use trivy-clean container base ([498c212](https://github.com/oaslananka/kicad-mcp/commit/498c21225c0b60ae8c8828fecb9b816ccec88168))
- **kicad-studio/kicad-mcp-pro:** mark KiCad 9.x deprecated ([11fb19a](https://github.com/oaslananka/kicad-mcp/commit/11fb19a6aceb7932fd200077bc97082c725f61fb))
- **kicad-studio/kicad-mcp-pro:** mark KiCad 9.x deprecated ([11fb19a](https://github.com/oaslananka/kicad-mcp/commit/11fb19a6aceb7932fd200077bc97082c725f61fb))
- **kicad-studio/kicad-mcp-pro:** mark KiCad 9.x deprecated ([c421156](https://github.com/oaslananka/kicad-mcp/commit/c42115697dab897d2bbc9ae5fb20853ebf62cf04))
- **kicad-studio/kicad-mcp-pro:** raise public compatibility floors ([98283a7](https://github.com/oaslananka/kicad-mcp/commit/98283a7374fcd666c392044e95aafb0c330d896e)), closes [#209](https://github.com/oaslananka/kicad-mcp/issues/209)
- **kicad-studio/kicad-mcp-pro:** reset extension marketplace identity ([2f907a1](https://github.com/oaslananka/kicad-mcp/commit/2f907a14c9b28b8d9c80f6581409f24ed53e66d0))
- **kicad-studio/kicad-mcp-pro:** reset extension marketplace identity ([11f3fd0](https://github.com/oaslananka/kicad-mcp/commit/11f3fd0e99bdaf761e99dc733a9a8b8c26fc403f))
- link release package versions ([a5879a8](https://github.com/oaslananka/kicad-mcp/commit/a5879a805594de843c9f2159747260f619183a6b))
- **mcp:** extend pcb file-backed read fallback ([0d14589](https://github.com/oaslananka/kicad-mcp/commit/0d14589fb250683da95a11f1d854b3dea9e7cef9))
- **mcp:** support stateless http and pcb file fallback ([6ebe260](https://github.com/oaslananka/kicad-mcp/commit/6ebe260cb005b6c3bb3dd769b96201ddafdf1047))
- **repo:** enforce pnpm supply-chain policy ([92eb31c](https://github.com/oaslananka/kicad-mcp/commit/92eb31cc8ea24e296a366945a4ccff98fd421c7b))
- **repo:** enforce pnpm supply-chain policy ([92eb31c](https://github.com/oaslananka/kicad-mcp/commit/92eb31cc8ea24e296a366945a4ccff98fd421c7b))
- **repo:** enforce pnpm supply-chain policy ([0943f9e](https://github.com/oaslananka/kicad-mcp/commit/0943f9ed5e770bef6fb865399c360c7f01b85de4)), closes [#202](https://github.com/oaslananka/kicad-mcp/issues/202)
- **security:** make python audit gate deterministic ([5350ec8](https://github.com/oaslananka/kicad-mcp/commit/5350ec818e1b8d9c1a17aeec744a612a50c73044))

### Documentation

- **kicad-mcp-pro:** normalize MCP client onboarding config ([dce5001](https://github.com/oaslananka/kicad-mcp/commit/dce5001e810e57a61f118a6e2885066825ecb500))
- **kicad-studio/kicad-mcp-pro/repo:** normalize changelog format ([a921810](https://github.com/oaslananka/kicad-mcp/commit/a9218103228f02f26455873e83acac8e9a85d8cb))
- **kicad-studio/kicad-mcp-pro/repo:** normalize changelog format ([234e274](https://github.com/oaslananka/kicad-mcp/commit/234e27446dd52141c47c776234b4275d48e2c309))
- **kicad-studio/kicad-mcp-pro/repo:** use past-tense changelog entries ([d162686](https://github.com/oaslananka/kicad-mcp/commit/d162686f3a8e69a783a2ac23c71e43efd2b6bdcb))
- **kicad-studio/kicad-mcp-pro:** add agent MCP onboarding pack ([1375574](https://github.com/oaslananka/kicad-mcp/commit/13755744b741b6a95369806656955417856cab0a))
- **kicad-studio:** add marketplace listing assets ([4dceac5](https://github.com/oaslananka/kicad-mcp/commit/4dceac5e3a5d18cdb44bf8c406394f7944a1e5d1))
- **repo:** add platform client setup examples ([#166](https://github.com/oaslananka/kicad-mcp/issues/166)) ([20440e0](https://github.com/oaslananka/kicad-mcp/commit/20440e0d2d452e06225703109158390731a87346))
- **repo:** align ownership policy checks ([fa52a74](https://github.com/oaslananka/kicad-mcp/commit/fa52a746c9bc19a5ab307f3327acab6a054a5a31)), closes [#64](https://github.com/oaslananka/kicad-mcp/issues/64)
- **repo:** clarify MCP client config destinations ([6049ca3](https://github.com/oaslananka/kicad-mcp/commit/6049ca3077db5b8e6490205a55b4581b367a0009))

## [1.0.0] - 2026-05-20

### Added

- Released the baseline KiCad MCP Pro server from the canonical monorepo.
