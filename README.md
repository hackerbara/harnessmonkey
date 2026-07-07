# HarnessMonkey - UserScripts for Claude Code
![capy-onsen-terminal](https://raw.githubusercontent.com/hackerbara/harnessmonkey/main/assets/demos/capyclaude.gif)
A reference example of a personal UserScript-style modification manager for Claude Code that handles applying/unapplying selected patches, command line options, and prompts to your selected `claude` location via a shim, patch engine, and re-packer.

Provides a Python CLI tool, (ugly) GUI, and menubar manager. Reference for Mac only currently.

## Example scripts

| Package | What it does | Demo |
|---------|--------------|------|
| [`thinking-drawer`](https://github.com/hackerbara/harnessmonkey/tree/main/packages/thinking-drawer) | A footer drawer projecting the model's thinking text, raw and structured. | ![demo](https://raw.githubusercontent.com/hackerbara/harnessmonkey/main/assets/demos/thinking-drawer.gif) |
| [`reminders-drawer`](https://github.com/hackerbara/harnessmonkey/tree/main/packages/reminders-drawer) | A footer drawer with live on/off toggles for seven recurring reminder/accounting attachment families. Runtime control instead of build-time suppression. | ![demo](https://raw.githubusercontent.com/hackerbara/harnessmonkey/main/assets/demos/reminders-drawer.gif) |
| [`mute-reminders`](https://github.com/hackerbara/harnessmonkey/tree/main/packages/mute-reminders) | Statically suppresses those same seven attachment families upstream. The "just make it all quiet" option. Conflicts with `reminders-drawer` — pick one. | — |
| [`hidden-context-drawer`](https://github.com/hackerbara/harnessmonkey/tree/main/packages/hidden-context-drawer) | A footer "Hidden Context" drawer so you can read the model-visible attachment context (reminders, timestamps, token accounting) the harness normally hides from you. | ![demo](https://raw.githubusercontent.com/hackerbara/harnessmonkey/main/assets/demos/hidden-context-drawer.gif) |
| [`hidden-context-inline`](https://github.com/hackerbara/harnessmonkey/tree/main/packages/hidden-context-inline) | Same hidden context, projected straight into the transcript as inline warning rows. Conflicts with the drawer — pick one. | ![demo](https://raw.githubusercontent.com/hackerbara/harnessmonkey/main/assets/demos/hidden-context-inline.gif) |
| [`markdown-preview-drawer`](https://github.com/hackerbara/harnessmonkey/tree/main/packages/markdown-preview-drawer) | Opens local `.md` chat links in a flat shared drawer preview. | — |
| [`threejs-sidebar-sidecar`](https://github.com/hackerbara/harnessmonkey/tree/main/packages/threejs-sidebar-sidecar) | Generic live three.js terminal-gutter infrastructure: Claude sidecar patch, native WebGPU renderer, browser WebGL + Chafa renderer, Deno WebGPU/Eidoverse renderer, and optional two-sided frame-pair layout support for profile packages. | — |
| [`capybara-onsen-threejs-sidecar`](https://github.com/hackerbara/harnessmonkey/tree/main/options/capybara-onsen-threejs-sidecar) | Three.js/Eidoverse capybara onsen profile for `threejs-sidebar-sidecar`: two synchronized live gutters rendered from the real 3D scene via Deno WebGPU + Chafa. | — |
| [`capybara-onsen`](https://github.com/hackerbara/harnessmonkey/tree/main/packages/capybara-onsen) | Capybaras chilling. It's very brave of them to do so if you think about it. Say a trigger phrase like "hopping in the pool" in an assistant reply and the right capybara hops into the onsen for a ~7s soak — the hop also drops a pool-break note onto the hidden-context channel so claude knows they're soaking. Needs a truecolor terminal, Ghostty etc. | ![demo](https://raw.githubusercontent.com/hackerbara/harnessmonkey/main/assets/demos/capybara-onsen.gif) |
| [`heraldic-dragons`](https://github.com/hackerbara/harnessmonkey/tree/main/packages/heraldic-dragons) | Two heraldic fire-breathing pixel-art dragons flanking your terminal, with animated flames. Take it to 11 sometime, you know?  One art scene at a time — conflicts with `capybara-onsen` and `threejs-sidebar`. | ![demo](https://raw.githubusercontent.com/hackerbara/harnessmonkey/main/assets/demos/heraldic-dragons.gif) |
| [`fable-fallback`](https://github.com/hackerbara/harnessmonkey/tree/main/packages/fable-fallback) | Un-hides Fable→Opus safety-classifier downgrade events: warning banner in resumed chats, marker in the `/resume` picker. The original reason this repo exists. | ![demo](https://raw.githubusercontent.com/hackerbara/harnessmonkey/main/assets/demos/fable-fallback.gif) |
| [`drawer-dock`](https://github.com/hackerbara/harnessmonkey/tree/main/packages/drawer-dock) | The shared footer-drawer framework the three drawer scripts above plug into. Enable it alongside any of them. Demo shows the full dock with all three aboard. | ![demo](https://raw.githubusercontent.com/hackerbara/harnessmonkey/main/assets/demos/drawer-dock.gif) |

### Why these scripts?

I was tired of four things with Claude Code:
1. Not being able to see all the tokens the model sees
2. The automated reminders that fire and make Claude anxious and jumpy
3. Not nearly enough vibes
4. Needing an alias to pass my [system prompt](https://github.com/hackerbara/lessanxious-claude) and --dangerously-skip-permissions 

So these are ideas to improve my personal Claude situation, and maybe yours too. But you should think of scripts that speak to you!

## Is this a good idea?

Probably not! Don't violate your Terms of Service, don't get hacked, don't crash your computer hard -- all important things to focus on in your life. Injecting arbitrary web-provided JS into an opaque agent harness with powerful permissions may interfere with these goals! 

(I am neither a lawyer nor cybersecurity expert though so don't listen to me...)

## How do I install?

Requires: a Mac on Apple Silicon, [uv](https://docs.astral.sh/uv/) (brings its own Python), and a local Claude Code install to patch. 

```sh
git clone https://github.com/hackerbara/harnessmonkey
cd harnessmonkey
uv sync
uv run harnessmonkey install
```

That's it — the monkey lands in your menubar (and comes back on login), with all the scripts loaded and switched off. From there, the three steps below.

(If the monkey doesn't appear — launch it directly: `uv run harnessmonkey-gui`.)

Prefer terminal-only? `uv run harnessmonkey install --cli` skips the menubar app; everything it does has a CLI verb (`uv run harnessmonkey --help`).

Changed your mind? `uv run harnessmonkey uninstall` takes the menubar app back out.

### Experimental: Windows (in process)

Native-Windows PE patching is implemented and builds end-to-end against a real Windows `claude.exe`, but it is **unverified on real Windows hardware** — no patched binary has been executed on Windows yet. See [`WINDOWS.md`](./WINDOWS.md) for details.

## How do I use it?

1. **Install the shim** - Click Install from the menubar or GUI page and select your system claude or another location if you want to be saner / use an alias.
2. **Select patches** - Choose your desired patches (if none show available you may have a more recent binary, ask an agent to update your local patches for your latest version)
3. **Apply and rebuild** - Select the rebuild option. You will see a success/failure message. Your next `claude` invocation will contain the latest patches.

## How do I make my own scripts?

Point a reasonably powerful agent at any of the examples as a starter and explain what you want.

Turns out LLMs can speak React crazy-well, even when minified. Making it the perfect framework choice for a mod-able TUI app :)

## Does this automatically patch new versions?

Nope. Just fails closed safely. Every Claude Code update will break the version pins until packages get re-verified against the new binary. When it breaks, throw your agent at re-authoring the package for the new version and carry on.

## Troubleshooting

Ummm, yep, there's a lot of trouble to shoot in this here endeavor! Scripts and things are guaranteed to break over time. It's designed so you can ask your favorite local agent to help keep the duct tape and hot glue running. 

Please do that instead of asking me, whenever possible. It's part of the fun.

If things get sticky: `uv run harnessmonkey doctor` diagnoses the current state, `rollback` restores the previous build, and `use-official` points your shim back at the untouched binary while you sort things out.

<3 Hackerbara
