# Changelog

## [2.0.0](https://github.com/oaslananka/kicad-mcp-pro/compare/protocol-schemas-v1.6.0...protocol-schemas-v2.0.0) (2026-10-05)


### ⚠ BREAKING CHANGES

* **protocol-schemas:** tool-effect-manifest now requires schema major 2 and the protocol-schemas package must release on the 2.x line.

### Features

* **contracts:** expose reviewed argument breadth facts ([28e6112](https://github.com/oaslananka/kicad-mcp-pro/commit/28e6112eff4f8e1f1c4fda73beb252207f48e76d))
* **protocol-schemas:** document tool-effect manifest v2 ([9ab85d5](https://github.com/oaslananka/kicad-mcp-pro/commit/9ab85d57f7f968281843eab98f17310c404eaa2d))
* **schemas:** define tool effect manifest v2 argument shapes ([a743c5d](https://github.com/oaslananka/kicad-mcp-pro/commit/a743c5d554fc153f84f6bd783fae8f52654b7025))
* **schemas:** type argument shape facts ([1d14bd9](https://github.com/oaslananka/kicad-mcp-pro/commit/1d14bd91ad5deabb94f0535f455a90525685b325))


### Bug Fixes

* **protocol-schemas:** prioritize unsupported major errors ([f23ca72](https://github.com/oaslananka/kicad-mcp-pro/commit/f23ca72241668f5c99e69d14c183838786aa64cf))

## [1.6.0](https://github.com/oaslananka/kicad-mcp-pro/compare/protocol-schemas-v1.5.0...protocol-schemas-v1.6.0) (2026-10-02)


### Features

* **mcp:** promote public protocol contract ([#1039](https://github.com/oaslananka/kicad-mcp-pro/issues/1039)) ([a1fdaad](https://github.com/oaslananka/kicad-mcp-pro/commit/a1fdaadf481a63c33371e8002f78b35ce166d12f))

## [1.5.0](https://github.com/oaslananka/kicad-mcp-pro/compare/protocol-schemas-v1.4.2...protocol-schemas-v1.5.0) (2026-10-02)


### Features

* **contracts:** publish reviewed tool effect manifest ([#1014](https://github.com/oaslananka/kicad-mcp-pro/issues/1014)) ([e5065df](https://github.com/oaslananka/kicad-mcp-pro/commit/e5065df453a57367cf1ea83437717967d36de77c))

## [1.4.2](https://github.com/oaslananka/kicad-mcp-pro/compare/protocol-schemas-v1.4.1...protocol-schemas-v1.4.2) (2026-09-04)


### Bug Fixes

* remediate engineering audit findings ([#838](https://github.com/oaslananka/kicad-mcp-pro/issues/838)) ([16fa63b](https://github.com/oaslananka/kicad-mcp-pro/commit/16fa63bf703ff5239b43906142d3ac89b4fbfbc8))

## [1.4.1](https://github.com/oaslananka/kicad-mcp-pro/compare/protocol-schemas-v1.4.0...protocol-schemas-v1.4.1) (2026-08-13)


### Reverts

* roll back grouped dependency update [#628](https://github.com/oaslananka/kicad-mcp-pro/issues/628) ([#631](https://github.com/oaslananka/kicad-mcp-pro/issues/631)) ([54a2d54](https://github.com/oaslananka/kicad-mcp-pro/commit/54a2d54a063548ad663978c0fee25d054980d69b))

## [1.4.0](https://github.com/oaslananka/kicad-mcp-pro/compare/protocol-schemas-v1.3.0...protocol-schemas-v1.4.0) (2026-07-26)


### Features

* **compat:** add the KiCad 11 adapter matrix and canaries ([#442](https://github.com/oaslananka/kicad-mcp-pro/issues/442)) ([457138d](https://github.com/oaslananka/kicad-mcp-pro/commit/457138decbb8d8c4894e05e5eee144d2f4b41f62)), closes [#411](https://github.com/oaslananka/kicad-mcp-pro/issues/411)

## [1.3.0](https://github.com/oaslananka/kicad-mcp-pro/compare/protocol-schemas-v1.2.0...protocol-schemas-v1.3.0) (2026-06-27)


### Features

* **compat:** refresh KiCad 10.0.4 baseline ([38ae60c](https://github.com/oaslananka/kicad-mcp-pro/commit/38ae60cd24163717f9d631cca13ce1a9dffeb975))
* harden tool contracts and operating mode coverage ([5e67cfc](https://github.com/oaslananka/kicad-mcp-pro/commit/5e67cfcaf4d49052149f1cdb99dbd994302f3de1))
* initial migration from kicad-studio-kit monorepo ([#1](https://github.com/oaslananka/kicad-mcp-pro/issues/1)) ([be9b16f](https://github.com/oaslananka/kicad-mcp-pro/commit/be9b16f33aaea94fbea525edd173a93a7e3e5012))
* publish protocol-schemas as public npm package ([f09a57e](https://github.com/oaslananka/kicad-mcp-pro/commit/f09a57ebedeab9a28c5bab6f34052baf1a4aed49))


### Bug Fixes

* add repository.url for npm provenance verification ([42045f5](https://github.com/oaslananka/kicad-mcp-pro/commit/42045f5d35404c22c3023806c1714e768ba4f1f0))
* **protocol-schemas:** export package.json for require.resolve consumers ([e4c6f6f](https://github.com/oaslananka/kicad-mcp-pro/commit/e4c6f6f75c70ea63eec5fd55063fcdc913e7ac94))

## [1.2.0](https://github.com/oaslananka/kicad-mcp-pro/compare/protocol-schemas-v1.1.1...protocol-schemas-v1.2.0) (2026-06-21)


### Features

* harden tool contracts and operating mode coverage ([5e67cfc](https://github.com/oaslananka/kicad-mcp-pro/commit/5e67cfcaf4d49052149f1cdb99dbd994302f3de1))

## [1.1.1](https://github.com/oaslananka/kicad-mcp-pro/compare/protocol-schemas-v1.1.0...protocol-schemas-v1.1.1) (2026-06-03)


### Bug Fixes

* add repository.url for npm provenance verification ([42045f5](https://github.com/oaslananka/kicad-mcp-pro/commit/42045f5d35404c22c3023806c1714e768ba4f1f0))
* **protocol-schemas:** export package.json for require.resolve consumers ([e4c6f6f](https://github.com/oaslananka/kicad-mcp-pro/commit/e4c6f6f75c70ea63eec5fd55063fcdc913e7ac94))

## [1.1.0](https://github.com/oaslananka/kicad-mcp-pro/compare/protocol-schemas-v1.0.0...protocol-schemas-v1.1.0) (2026-06-01)


### Features

* initial migration from kicad-studio-kit monorepo ([#1](https://github.com/oaslananka/kicad-mcp-pro/issues/1)) ([be9b16f](https://github.com/oaslananka/kicad-mcp-pro/commit/be9b16f33aaea94fbea525edd173a93a7e3e5012))
* publish protocol-schemas as public npm package ([f09a57e](https://github.com/oaslananka/kicad-mcp-pro/commit/f09a57ebedeab9a28c5bab6f34052baf1a4aed49))
