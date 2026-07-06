"""Execution-level test of the pool-hop runtime state machine.

Extracts __coSoak/__coSoakTick/__coOnAssistantText from the shipped payload
and drives them tick-by-tick under Node, asserting the choreography the
baked steam phases rely on. Hop-in and climb-out are both un-gated (start
immediately, on the next tick, regardless of the interrupted phase) as a
user-requested responsiveness tradeoff; only the transIn->soak handoff and
the transOut->landing handoff remain phase-aligned/seamless.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = next((ROOT / "packages/capybara-onsen/payloads").glob("01-*.js"))


def _extract(name: str, source: str) -> str:
    pattern = (
        rf"(function {name}\(.*?\n|function {name}\(.*?)"
        r"(?=function __co|let __co|$)"
    )
    m = re.search(pattern, source, re.S)
    assert m, f"cannot locate {name} in payload"
    return m.group(0)


def test_soak_state_machine_phase_alignment():
    if shutil.which("node") is None:
        pytest.skip("node not available")
    src = PAYLOAD.read_text()
    # pull the trigger list, the state initializer, the shipped hold-tick
    # constant, and both functions out of the payload verbatim --
    # __coOnAssistantText closes over __coTriggers, so it must come along too
    # (not called out explicitly in the original spec, but required for the
    # harness to actually exercise trigger matching). __coSoakHoldTicks is
    # extracted (not hardcoded) so this test can't drift from shipped reality
    # if the hold duration is ever tuned again.
    triggers = re.search(r"let __coTriggers=.*?;", src).group(0)
    init = re.search(r"let __coSoak=\{[^}]*\};", src).group(0)
    hold_ticks_stmt = re.search(r"let __coSoakHoldTicks=\d+;", src).group(0)
    tick = _extract("__coSoakTick", src)
    on_text = _extract("__coOnAssistantText", src)
    harness = f"""
let __coPhases=16;
{hold_ticks_stmt}
let __coTransInR=new Array(6).fill("in");let __coTransOutR=new Array(6).fill("out");
let __coAnimRSub=new Array(16).fill("sub");let __coAnimR=new Array(16).fill("dry");
{triggers}
{init}
{tick}
{on_text}
function frameId(){{
  let s=__coSoak;
  if(s.mode===1)return["in",s.frame];
  if(s.mode===2)return["sub",s.rp];
  if(s.mode===3)return["out",s.frame];
  return["dry",s.rp];
}}
function msg(){{
  let block={{type:"text",text:"we are hopping in the pool today"}};
  return {{message:{{id:"m1",content:[block]}},type:"assistant"}};
}}
let log=[];
// drive some plain dry ticks first -- the hop must now start on the very
// next tick after the trigger regardless of where rp happens to land
// (the old rp===15 entry gate is gone; a small steam discontinuity at
// takeoff is an accepted tradeoff for responsiveness).
for(let t=0;t<7;t++){{__coSoakTick();log.push(frameId())}}
__coOnAssistantText(msg());
// re-render with identical content must not enqueue again
__coOnAssistantText(msg());
for(let t=0;t<400;t++){{__coSoakTick();log.push(frameId())}}
console.log(JSON.stringify({{queue:__coSoak.queue,log:log}}));
"""
    out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    log = data["log"]
    assert data["queue"] == 0, "dedup failed: identical re-render enqueued a second soak"
    # find the mode-1 entry and check the full choreography
    first_in = next(i for i, (kind, _) in enumerate(log) if kind == "in")
    assert first_in == 7, (
        "hop must start on the tick right after the trigger, immediately -- "
        "not gated on any particular rp value"
    )
    assert log[first_in][1] == 0, "hop must start at transIn frame 0"
    assert [f for k, f in log[first_in:first_in + 6] if k == "in"] == [0, 1, 2, 3, 4, 5]
    sub_start = first_in + 6
    assert log[sub_start] == ["sub", 6], "soak must enter at phase 6"
    sub_frames = [f for k, f in log[sub_start:] if k == "sub"]
    out_start = sub_start + len(sub_frames)
    # The soak exit is no longer phase-gated (climb-out is un-gated, same
    # responsiveness tradeoff as the hop-in): soak length is now exactly the
    # hold-tick constant, deterministic, not a phase-aligned range.
    assert len(sub_frames) == 39, "soak must last exactly the 39-tick hold"
    # Incidental (not a contract): with entry fixed at phase 6 and an exact
    # 39-tick hold, the last soak frame lands at (6+38)%16 == 12. Pinned here
    # only so an accidental change to the entry phase or hold length is
    # caught; the runtime does not gate on this value.
    assert sub_frames[-1] == 12, "soak exit phase drifted from the expected (6+38)%16"
    assert [f for k, f in log[out_start:out_start + 6] if k == "out"] == [0, 1, 2, 3, 4, 5]
    assert log[out_start + 6] == ["dry", 0], "landing must resume the dry loop at phase 0"


def test_pool_hop_note_sink_fires_once_per_hop():
    """The injected pool-break note must fire exactly once per hop-in, even

    across queued retrigger cycles. The sink is a module-scope callback slot
    (bridged from the REPL component in the real module); here we stub it
    directly since __coSoakTick calls it unconditionally when present.
    """
    if shutil.which("node") is None:
        pytest.skip("node not available")
    src = PAYLOAD.read_text()
    triggers = re.search(r"let __coTriggers=.*?;", src).group(0)
    init = re.search(r"let __coSoak=\{[^}]*\};", src).group(0)
    hold_ticks_stmt = re.search(r"let __coSoakHoldTicks=\d+;", src).group(0)
    note_sink_decl = re.search(r"let __coCapyNoteSink=null;", src).group(0)
    note_text_decl = re.search(r"let __coCapyNoteText=.*?;", src).group(0)
    tick = _extract("__coSoakTick", src)
    on_text = _extract("__coOnAssistantText", src)
    harness = f"""
let __coPhases=16;
{hold_ticks_stmt}
let __coTransInR=new Array(6).fill("in");let __coTransOutR=new Array(6).fill("out");
let __coAnimRSub=new Array(16).fill("sub");let __coAnimR=new Array(16).fill("dry");
{triggers}
{init}
{note_sink_decl}
{note_text_decl}
{tick}
{on_text}
let notes=[];
__coCapyNoteSink=(t)=>notes.push(t);
function msg(id,text){{
  return {{message:{{id:id,content:[{{type:"text",text:text}}]}},type:"assistant"}};
}}
// first trigger: queue one hop
__coOnAssistantText(msg("m1","we are hopping in the pool today"));
// consuming the queue on the very next tick must fire exactly one note
__coSoakTick();
if(notes.length!==1) throw new Error("expected 1 note right after hop start, got "+notes.length);
if(notes[0].indexOf("Enjoy the break")<0) throw new Error("unexpected note text: "+notes[0]);
// retrigger while the first hop is still in progress (transIn) -- queues a
// second full hop/soak/climb-out cycle
__coOnAssistantText(msg("m2","hop in the pool again"));
// run out the remaining first cycle (5 more transIn + 39 hold + 6 transOut)
// then the full second cycle (1 consume + 5 transIn + 39 hold + 6 transOut)
for(let t=0;t<(5+39+6)+(1+5+39+6);t++){{__coSoakTick()}}
console.log(JSON.stringify({{queue:__coSoak.queue,noteCount:notes.length,notes:notes}}));
"""
    out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    assert data["queue"] == 0, "both queued hops should have fully played out"
    assert data["noteCount"] == 2, (
        f"expected exactly 2 notes total (one per hop, incl. queued retrigger), "
        f"got {data['noteCount']}: {data['notes']}"
    )
    for note in data["notes"]:
        assert "Enjoy the break" in note
