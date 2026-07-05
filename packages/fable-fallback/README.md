# Fable fallback visibility

Shows Fable fallback events in resumed Claude Code history and marks affected sessions in `/resume`.

This is a HarnessMonkey V1.5 package: it targets `/$bunfs/root/src/entrypoints/cli.js` in Bun module coordinates and is built with the graph-aware repack engine, not legacy byte-slot padding.

This package injects executable JavaScript bytes into a copied Claude Code binary. It is declarative, but the replacement payload still executes inside Claude Code after patching. Visual history/resume behavior should still be manually smoke-tested before trusting a release artifact.
