"""Translate the macOS capybara-onsen package into a Windows (win32-x64) one.

The Windows and macOS Claude Code bundles are the *same source*, minified with
*different* identifier names — so a straight re-pin of `packages/capybara-onsen`
does not work: every anchor and every host-identifier reference in the patch
glue must be realigned to the Windows minifier's names.

Method (no guessing):
  1. Extract `cli.js` from both the macOS Mach-O binary and the Windows PE binary.
  2. Align the shared app-shell function body (`VKo` on macOS, its Windows twin)
     token-by-token. Same source => non-identifier tokens line up exactly;
     identifiers at the same position are a verified rename pair.
  3. Anchor `exact`/`requireWithinRange`: byte-exact span-mapped from the bundles.
  4. Payload replacements: token-translate through the rename map (the `__co*`
     helper names and the jsx runtime alias are not in the map, so they pass
     through unchanged). Payload 01's baked helper is host-only translated so its
     own local parameters are never touched.
  5. Postconditions/preconditions: token-translate values; swap the bunfs path.

The result BUILDS through the real PE pipeline against the pinned Windows binary
(fail-closed pins satisfied, the pipeline's own postconditions pass). Visual
rendering is NOT verified here — that requires running the patched claude.exe on
Windows (see WINDOWS.md).

Usage:
    uv run python examples/capybara-onsen-generator/translate_to_windows.py \
        --mac-source ~/.local/share/claude/versions/2.1.201 \
        --win-source ~/.local/share/harnessmonkey-dev/win32-x64/2.1.201/claude.exe

Both sources default to the standard dev locations. Output is written to
`packages/capybara-onsen-win/`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from harnessmonkey.bun_graph import parse_bun_section  # noqa: E402
from harnessmonkey.binary_format import locate_bun_section  # noqa: E402

MAC_MODULE = "/$bunfs/root/src/entrypoints/cli.js"
WIN_MODULE = "B:/~BUN/root/src/entrypoints/cli.js"
VERSION = "2.1.201"
VERSION_OUT = "2.1.201 (Claude Code)"
MAC_PKG = REPO / "packages" / "capybara-onsen"
OUT = REPO / "packages" / "capybara-onsen-win"

TOKEN_RE = re.compile(
    r'(?P<str>"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`)'
    r"|(?P<num>0[xXbBoO][0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?)"
    r"|(?P<id>[A-Za-z_$][A-Za-z0-9_$]*)"
    r"|(?P<punct>=>|\?\?|===|!==|==|!=|<=|>=|&&|\|\||\+\+|--|\.\.\.|[-+*/%<>=!&|^~?:;,.\[\]{}()])"
    r"|(?P<ws>\s+)"
    r"|(?P<other>.)"
)


def module_content(binary: Path, module_path: str) -> str:
    data = binary.read_bytes()
    start, length = locate_bun_section(data)
    graph = parse_bun_section(data[start : start + length])
    return graph.module_by_path(module_path).content.decode("utf-8")


def extract_body(src: str, header: str) -> tuple[int, int]:
    i = src.find(header)
    if i < 0:
        raise RuntimeError(f"header not found: {header!r}")
    depth = 0
    for k in range(i + len(header) - 1, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return i, k + 1
    raise RuntimeError("unbalanced braces")


def toks(s: str, base: int = 0):
    return [
        (m.lastgroup, m.group(), base + m.start(), base + m.end())
        for m in TOKEN_RE.finditer(s)
        if m.lastgroup != "ws"
    ]


def build_rename_map(mac: str, win: str):
    """Align the macOS `VKo` body with its Windows twin and return
    (rename_map, mac_tokens, win_tokens) with absolute offsets."""
    ma, mb = extract_body(mac, "function VKo(e){")
    # The Windows twin is the function whose body aligns; locate it by the fact
    # that VKo's macro shape `function <id>(e){let t=<id>.c(78)` is preserved.
    win_header = _find_win_shell_header(win)
    wa, wb = extract_body(win, win_header)
    tm = toks(mac[ma:mb], base=ma)
    tw = toks(win[wa:wb], base=wa)
    if len(tm) != len(tw):
        raise RuntimeError(
            f"app-shell bodies diverge ({len(tm)} vs {len(tw)} tokens) — "
            "the Windows bundle is not the same source revision as macOS"
        )
    mapping: dict[str, str] = {}
    for (ak, av, *_), (bk, bv, *_) in zip(tm, tw):
        if ak == "id" and bk == "id" and av != bv:
            if av in mapping and mapping[av] != bv:
                raise RuntimeError(
                    f"inconsistent rename for {av!r}: maps to both "
                    f"{mapping[av]!r} and {bv!r} — app-shell alignment is ambiguous, "
                    "the two bundles may not be the same source revision"
                )
            mapping[av] = bv
    return mapping, tm, tw


def _find_win_shell_header(win: str) -> str:
    """Find `function <id>(e){let t=<id>.c(78)` in the Windows bundle."""
    m = re.search(r"function ([A-Za-z_$][\w$]*)\(e\)\{let t=[A-Za-z_$][\w$]*\.c\(78\)", win)
    if not m:
        raise RuntimeError("could not locate the Windows app-shell function")
    return f"function {m.group(1)}(e){{"


def translate(text: str, mapping: dict[str, str]) -> str:
    out, pos = [], 0
    for kind, val, a, b in toks(text):
        out.append(text[pos:a])
        out.append(mapping.get(val, val) if kind == "id" else val)
        pos = b
    out.append(text[pos:])
    return "".join(out)


def win_exact_for(mac_substr: str, mac: str, win: str, tm, tw) -> str:
    cpos = mac.find(mac_substr)
    if cpos < 0:
        raise RuntimeError(f"mac anchor not found: {mac_substr[:60]!r}")
    cend = cpos + len(mac_substr)
    idx = [i for i, (k, v, a, b) in enumerate(tm) if a >= cpos and b <= cend]
    if not idx:
        raise RuntimeError(f"anchor not inside app-shell body: {mac_substr[:60]!r}")
    return win[tw[idx[0]][2] : tw[idx[-1]][3]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mac-source", default=str(Path.home() / ".local/share/claude/versions" / VERSION))
    ap.add_argument(
        "--win-source",
        default=str(Path.home() / ".local/share/harnessmonkey-dev/win32-x64" / VERSION / "claude.exe"),
    )
    args = ap.parse_args()

    mac_bin, win_bin = Path(args.mac_source).expanduser(), Path(args.win_source).expanduser()
    mac = module_content(mac_bin, MAC_MODULE)
    win = module_content(win_bin, WIN_MODULE)

    rename, tm, tw = build_rename_map(mac, win)
    host_map = {k: rename[k] for k in ("B", "A_", "fde", "t4", "Er") if k in rename}
    print(f"rename pairs: {len(rename)}  host_map: {host_map}")

    manifest = json.loads((MAC_PKG / "patch.json").read_text())
    target = manifest["patch"]["targets"][0]
    ops = target["modules"][0]["operations"]

    win_bytes = win_bin.read_bytes()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "payloads").mkdir(exist_ok=True)

    new_ops, patched = [], win
    for idx, op in enumerate(ops, start=1):
        mac_exact = op["exact"]
        win_exact = win_exact_for(mac_exact, mac, win, tm, tw)
        if win.count(win_exact) != 1:
            raise RuntimeError(f"win anchor {idx} not unique: {win_exact[:60]!r}")
        ref = op["replacement"]["path"]
        mac_payload = (MAC_PKG / ref).read_text()
        if idx == 1:
            if not mac_payload.endswith(mac_exact):
                raise RuntimeError("payload 01 does not end with anchor 1's exact")
            win_payload = translate(mac_payload[: -len(mac_exact)], host_map) + win_exact
        else:
            win_payload = translate(mac_payload, rename)
        (OUT / ref).parent.mkdir(parents=True, exist_ok=True)
        (OUT / ref).write_text(win_payload)
        new_ops.append(
            {
                "opId": op["opId"].replace(f"-{VERSION.replace('.', '-')}", f"-win-{VERSION.replace('.', '-')}"),
                "label": op["label"],
                "type": "replace_exact",
                "exact": win_exact,
                "requireWithinRange": [translate(r, rename) for r in op["requireWithinRange"]],
                "oldRangeSha256": hashlib.sha256(win_exact.encode()).hexdigest(),
                "oldRangeLength": len(win_exact.encode()),
                "replacement": {
                    "path": ref,
                    "sha256": hashlib.sha256(win_payload.encode()).hexdigest(),
                },
                "knownBehaviorChange": op.get("knownBehaviorChange", ""),
            }
        )
        if patched.count(win_exact) != 1:
            raise RuntimeError(f"win anchor {idx} not unique in evolving module")
        patched = patched.replace(win_exact, win_payload, 1)

    def xlate(assertions):
        return [
            {"type": a["type"], "modulePath": WIN_MODULE, "value": translate(a["value"], rename)}
            for a in assertions
        ]

    win_post = xlate(target.get("postconditions", []))
    for a in win_post:
        present = a["value"] in patched
        if present != (a["type"] == "module_must_contain"):
            raise RuntimeError(f"postcondition would fail: {a['type']} {a['value'][:70]!r}")

    win_manifest = {
        "schemaVersion": 1,
        "kind": "patch",
        "id": "capybara-onsen-win",
        "label": manifest["label"] + " (Windows)",
        "description": manifest["description"],
        "packageVersion": manifest["packageVersion"] + "-win",
        "compatibility": {"claudeVersions": [VERSION]},
        "patch": {
            "engine": "bun_graph_repack",
            "targets": [
                {
                    "sourceIdentity": {
                        "claudeVersion": VERSION,
                        "versionOutput": VERSION_OUT,
                        "sha256": hashlib.sha256(win_bytes).hexdigest(),
                        "sizeBytes": len(win_bytes),
                        "platform": "win32",
                        "arch": "x64",
                    },
                    "requiredEngine": "bun_graph_repack",
                    "requiredBinaryFormat": "bun_standalone_pe64",
                    "modules": [
                        {
                            "path": WIN_MODULE,
                            "contentSha256": hashlib.sha256(win.encode()).hexdigest(),
                            "contentLength": len(win.encode()),
                            "operations": new_ops,
                        }
                    ],
                    "preconditions": xlate(target.get("preconditions", [])),
                    "postconditions": win_post,
                    "manualSmoke": target.get("manualSmoke", {"required": True, "reason": "visual"}),
                }
            ],
        },
    }
    (OUT / "patch.json").write_text(json.dumps(win_manifest, indent=2) + "\n")
    (OUT / "README.md").write_text(
        "# Capybara Onsen (Windows)\n\n"
        f"Auto-translated from `packages/capybara-onsen` for the win32-x64 Claude Code {VERSION} "
        "bundle by `examples/capybara-onsen-generator/translate_to_windows.py`. The Windows build "
        "minifies the shared source with different identifier names, so every anchor and every "
        "host-identifier reference was realigned via token-position alignment of the two bundles.\n\n"
        "This package **builds through the real PE pipeline** against the pinned Windows binary "
        "(fail-closed pins satisfied, postconditions pass). **Visual rendering is unverified** — it "
        "must be confirmed by launching the patched `claude.exe` in Windows Terminal. See `WINDOWS.md`.\n"
    )
    print(f"wrote {OUT} with {len(new_ops)} operations")
    print(f"patched module length: {len(patched.encode())}  sha256: {hashlib.sha256(patched.encode()).hexdigest()}")


if __name__ == "__main__":
    main()
