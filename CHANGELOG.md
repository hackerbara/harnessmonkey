# Changelog

## 0.3.0 2026-07-07

- Stablized threejs render into dawn/webgpu or denu WebGL + Chafa & some SGR Ink cache perf.
- Added Codex agent drawer panel to watch working Codex agent messages in tree.
- Enhanced shared drawer card render display/logic

## 0.2.0 - 2026-07-07

### Added

- Added the `threejs-sidebar-sidecar` package as generic live three.js terminal-gutter infrastructure for Claude Code, including native WebGPU, browser WebGL + Chafa, and Deno WebGL/Eidoverse renderer profiles.
- Added option profiles for selecting the three.js renderer/toolchain, including `threejs-sidebar-sidecar-local`, `threejs-sidebar-sidecar-browser-webgl-chafa`, and `capybara-onsen-threejs-sidecar`.
- Added the `capybara-onsen-threejs-sidecar` scene profile, which uses the real Eidoverse capybara onsen three.js scene as synchronized two-sided sidebars.

### Changed

- Documented the 3JS sidecar package and capybara onsen 3JS option in the README package table.
