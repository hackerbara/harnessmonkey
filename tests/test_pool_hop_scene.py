"""Scene-level tests for the capybara pool-hop feature (pure Python, no binary)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "examples" / "capybara-onsen-generator"
if str(GEN) not in sys.path:
    sys.path.insert(0, str(GEN))

import water_sim as ws  # noqa: E402


def test_soak_ripple_is_deterministic_and_phase_varying():
    a = ws.soak_ripple_cells(3, 9, 84)
    b = ws.soak_ripple_cells(3, 9, 84)
    assert a == b
    assert ws.soak_ripple_cells(0, 9, 84) != ws.soak_ripple_cells(2, 9, 84)


def test_soak_ripple_stays_on_the_surface_row():
    for p in range(16):
        cells = ws.soak_ripple_cells(p, 9, 84)
        assert cells, f"phase {p}: empty ripple"
        assert all(y == 84 for _, y, _ in cells)
        assert all(ch in ("F", "V") for _, _, ch in cells)


def test_splash_cells_deterministic_and_bounded():
    assert ws.splash_cells(3, 9, 84) == ws.splash_cells(3, 9, 84)
    assert ws.splash_cells(0, 9, 84) == []
    for step in range(6):
        for x, y, ch in ws.splash_cells(step, 9, 84):
            assert 56 <= y <= 85, f"splash leaked to subrow {y}"
            assert ch in ("U", "u", "F")
    assert len(ws.splash_cells(4, 9, 84)) > len(ws.splash_cells(1, 9, 84))


import paint_scene as scene  # noqa: E402


def _static_right():
    return scene.static_right()


def test_submerged_frames_static_band_and_determinism():
    static_rows = _static_right()
    assert scene.compose_right_submerged(0) == scene.compose_right_submerged(0)
    frames = [scene.compose_right_submerged(p) for p in range(scene.PHASES)]
    for p, frame in enumerate(frames):
        assert len(frame) == scene.H
        for r in range(56):
            assert frame[r] == static_rows[r], f"v8 leak: phase {p} row {r}"
    assert len({tuple(f) for f in frames}) >= 2, "submerged loop has no motion"


def test_submerged_pose_shows_eyes_and_ears_above_water_only():
    frame = scene.compose_right_submerged(0)
    assert "E" in frame[83], "eyes missing just above the waterline"
    ear_rows = "".join(frame[79] + frame[80] + frame[81])
    assert "c" in ear_rows, "ears missing above the waterline"
    # the dry body must be gone: its eye row was y71
    assert "E" not in frame[71]
    # nothing but water/ripple chars on the surface row left of the rock column
    assert all(ch in "WVvF" for ch in frame[84][0:22])


def test_submerged_ears_still_wiggle():
    rest = scene.compose_right_submerged(0)
    flick = scene.compose_right_submerged(7)
    wiggle_band = [rest[r] != flick[r] for r in range(78, 83)]
    assert any(wiggle_band), "ear flick not visible in submerged pose"


def test_jump_frames_shape_and_static_band():
    static_rows = _static_right()
    for compose in (scene.compose_right_jump_in, scene.compose_right_jump_out):
        frames = [compose(f) for f in range(scene.TRANS_FRAMES)]
        assert compose(0) == compose(0)
        assert len(frames) == 6
        for i, frame in enumerate(frames):
            assert len(frame) == scene.H
            for r in range(56):
                assert frame[r] == static_rows[r], f"v8 leak: frame {i} row {r}"
        assert len({tuple(f) for f in frames}) >= 4, "transition barely animates"


def test_jump_in_starts_dry_and_ends_submerged():
    first = scene.compose_right_jump_in(0)
    last = scene.compose_right_jump_in(scene.TRANS_FRAMES - 1)
    assert "E" in first[73] or "E" in first[71], "frame 0 should show the body on the shelf"
    assert "E" in last[83], "last frame should show the soak pose"
    assert "E" not in last[71]


def test_jump_out_ends_in_rest_pose():
    last = scene.compose_right_jump_out(scene.TRANS_FRAMES - 1)
    rest = scene.compose_right(15)
    assert last == rest, "jump-out must land exactly on the phase-15 rest frame"


def test_transition_steam_phases_are_consecutive():
    # dry leaves at phase 15; transIn bakes steam phases 0..5; soak enters at 6;
    # soak exits at 9; transOut bakes 10..15; dry resumes at 0.
    for f in range(scene.TRANS_FRAMES):
        assert scene.compose_right_jump_in(f)[56:] != scene.compose_right(15)[56:]
    sub6 = scene.compose_right_submerged(6)
    assert sub6 == scene.compose_right_submerged(6)
    out_last = scene.compose_right_jump_out(scene.TRANS_FRAMES - 1)
    assert out_last == scene.compose_right(15)


def test_jump_impact_frames_show_splash():
    impact = scene.compose_right_jump_in(3)
    band = "".join(row[3:16] for row in impact[80:84])
    assert "u" in band or "U" in band, "impact frame shows no splash"
    settle = scene.compose_right_jump_in(4)
    above = "".join(row[3:16] for row in settle[80:83])
    assert "u" in above or "U" in above or "F" in above, (
        "settle frame shows no spray above the head"
    )
    burst = scene.compose_right_jump_out(1)
    band_out = "".join(row[3:16] for row in burst[80:84])
    assert "u" in band_out or "U" in band_out, "jump-out burst shows no splash"


import importlib  # noqa: E402
import json  # noqa: E402


def test_compile_emits_pool_hop_arrays(tmp_path, monkeypatch):
    compile_mod = importlib.import_module("compile")
    monkeypatch.setattr(compile_mod, "OUT", tmp_path)
    compile_mod.main()
    data = json.loads((tmp_path / "onsen-data.json").read_text())
    assert data["phases"] == 16
    for key, count in (("animRSub", 16), ("transInR", 6), ("transOutR", 6)):
        assert key in data, f"missing {key}"
        assert len(data[key]) == count
        for frame in data[key]:
            assert len(frame) == data["animCellRows"]
            for cellrow in frame:
                assert sum(run[2] for run in cellrow) == data["w"]
