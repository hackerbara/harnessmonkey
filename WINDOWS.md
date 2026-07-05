# HarnessMonkey on Windows (experimental)

> **Experimental.** Native-Windows PE patching builds end-to-end against a real
> Windows `claude.exe`, but it has **not yet been verified by running a patched
> binary on Windows**. Everything below is implemented and tested as far as a
> non-Windows machine allows; treat the rest as unverified.

Claude Code ships as a Bun `--compile` standalone executable on every platform,
so the same patching approach HarnessMonkey uses on macOS applies on Windows.
This page covers what's implemented, how to try it, and what remains.

## How it works

The embedded JS module-graph payload lives in a container section — `__BUN`/`__bun`
on the macOS Mach-O binary, a section named **`.bun`** on the Windows PE binary —
and the payload format (the `"\n---- Bun! ----\n"` trailer, the 32-byte `Offsets`
struct, the 52-byte module records) is byte-identical across platforms. So the
payload parser is shared unchanged; only the outer container differs. The PE
patcher is simpler than the Mach-O one: `.bun` is always the last section in the
file, so resizing it moves nothing else.

## Implemented and tested

These have automated tests. The real-binary tests run against a downloaded
Windows `claude.exe` and self-skip when it's absent.

| Piece | File | What it does |
|---|---|---|
| PE parser | `src/harnessmonkey/pe.py` — `find_pe_layout` | Parses PE32+ headers, locates the `.bun` section, exposes the Authenticode/checksum offsets. Raises `PEError` (never `struct.error`) on malformed input. |
| Resize repack | `src/harnessmonkey/pe.py` — `repack_changed_modules` | Strips Authenticode, applies arbitrary-length module edits, resizes `.bun`, fixes `SizeOfImage`, recomputes the PE checksum. Mirrors the Mach-O repack interface. |
| PE checksum | `src/harnessmonkey/pe.py` — `pe_checksum` | Hand-rolled Microsoft image checksum, reproducing a real binary's stored checksum exactly. No third-party dependency. |
| Format dispatch | `src/harnessmonkey/binary_format.py` | `detect_binary_format` / `locate_bun_section` / `repack_for_format` route Mach-O vs PE. The Mach-O path is unchanged. |
| Payload prefix | `src/harnessmonkey/bun_graph.py` | Accepts the Windows bunfs path prefix `B:/~BUN/` (macOS uses `/$bunfs/`). |
| Build hygiene | `src/harnessmonkey/builder_v15.py` | PE builds skip macOS `codesign` and emit `claude.exe` instead of `claude`. |
| Manifest format | `src/harnessmonkey/manifest_v2.py` | Recognizes `requiredBinaryFormat: "bun_standalone_pe64"`. |
| Platform plumbing | `src/harnessmonkey/platform_support.py` | Windows state dir (`%LOCALAPPDATA%\HarnessMonkey`), executable name (`claude.exe`), install-path discovery, and a real executability check (`os.access(X_OK)` is a no-op on Windows). macOS behavior is unchanged. |
| End-to-end build | `scripts/win_spike_driver.py`, `tests/test_windows_pipeline.py` | Drives a real length-changing patch through the full `manifest → module_patch → PE-repack` path against a real `claude.exe`, satisfying fail-closed pinning and producing a structurally valid patched `claude.exe`. |

### Trying it

```bash
# 1. Download a Windows Claude Code binary (not committed to the repo):
mkdir -p ~/.local/share/harnessmonkey-dev/win32-x64/2.1.201
curl -s -o ~/.local/share/harnessmonkey-dev/win32-x64/2.1.201/claude.exe \
  https://downloads.claude.ai/claude-code-releases/2.1.201/win32-x64/claude.exe

# 2. Run the pipeline test and the build driver:
uv run pytest tests/test_windows_pipeline.py -v
uv run python scripts/win_spike_driver.py      # writes build/win-spike/claude.exe
```

The driver produces a patched `claude.exe`. On a non-Windows machine you can only
inspect it — parse it, verify the checksum, confirm the edit landed. Launching it
requires Windows.

## Not yet implemented

Native Windows support isn't complete. The remaining work falls into three areas,
and most of it can only be validated on a real Windows machine.

### 1. Validation on real hardware

Measurements that determine how much of the rest is needed:

- Whether a patched, unsigned `claude.exe` launches under stock Defender/SmartScreen.
- Whether the official Windows updater replaces a patched binary — this decides
  whether the binary-protection/repair machinery needs a Windows analog at all.
- ConPTY animation throughput and glyph fidelity for the cosmetic packages, across
  Windows Terminal (1.24+), WezTerm, and Alacritty.

### 2. OS integration

Windows-native counterparts for the parts that are POSIX-specific today:

- **Launcher shim** — a compiled `claude.exe` stub or a `claude.cmd` wrapper on
  `PATH`, in place of the `chmod`'d script. A minimal `.cmd`:
  ```bat
  @echo off
  "%USERPROFILE%\.harnessmonkey\bin\claude.exe" %*
  ```
- **Install / replace under file locks** — Windows locks running executables, so
  replacing them needs `MoveFileEx(..., MOVEFILE_REPLACE_EXISTING)` (or a
  reboot-scheduled replace) and a clear "close Claude and retry" on failure,
  rather than an in-place overwrite.
- **Start-at-login** — a registry `Run` value, a Startup shortcut, or a scheduled
  task in place of the macOS LaunchAgent.
- **Process control** — `CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT` (and
  `taskkill`) in place of POSIX process groups.
- **Elevation** likely isn't needed at all — Windows installs live under
  `%USERPROFILE%`, writable without elevation.

The PySide6 tray GUI otherwise carries over: its macOS-only calls are already
platform-guarded and become no-ops on Windows.

### 3. Cosmetic-package art

A patch targets specific text inside Claude Code's minified bundle, and that text
is **not identical across platforms**: for a given version, the Windows build
minifies the shared source with different symbol names than macOS, and `cli.js`
differs in both length and hash. So porting a visual package isn't a re-pin —
every anchor and every referenced identifier has to be realigned to the Windows
bundle's names, and the result's on-screen rendering can only be confirmed by
running it in a Windows terminal.

`examples/capybara-onsen-generator/translate_to_windows.py` performs this
realignment automatically by token-aligning the two bundles, and regenerates
`packages/capybara-onsen-win/`. That package builds through the full patch/repack
path against a real Windows `claude.exe`; its rendering is still unverified.

## Windows notes

- **No re-signing needed.** Bun's compiler strips Authenticode on Windows builds
  and unsigned executables run; the PE patcher strips the certificate as part of
  repack.
- **`.bun` is the last section in the file**, so resizing it moves nothing else.
- **Windows module paths use the `B:/~BUN/` prefix** (macOS uses `/$bunfs/`).
- **Detect truecolor via `WT_SESSION`/`TERM_PROGRAM`, not `COLORTERM`** — Windows
  Terminal renders truecolor but doesn't set `COLORTERM`. Keep cosmetic art to
  box-drawing/half-block glyphs, which are unambiguously one column wide across
  Windows Terminal's width modes.
- **Native Windows only** — not WSL, which runs the Linux binary.
- **Install topology:** launcher at `%USERPROFILE%\.local\bin\claude.exe`,
  versioned binaries under `%USERPROFILE%\.local\share\claude\versions\`, config
  under `%USERPROFILE%\.claude`. Everything is per-user.

## Prior art

[`vicnaum/bun-demincer`](https://github.com/vicnaum/bun-demincer) round-trips Bun
standalone binaries across platforms.
