from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from harnessmonkey import repair as repair_module
from harnessmonkey import source_discovery
from harnessmonkey.install import (
    _unlock_target,
    current_target_is_installed_shim,
    install_shim_transaction,
    resolve_cached_source,
    restore_install_transaction,
)
from harnessmonkey.paths import StatePaths
from harnessmonkey.repair import (
    CacheSourceRefused,
    RepairRefused,
    cache_source_action,
    repair_shim_action,
)

# docs/superpowers/specs/2026-07-04-harnessmonkey-shim-update-resilience.md
# Sec2 (cache official source) / Sec3 (repair existing shim) / Refinements
# R1-R4, R6, R8, R9. Stage 2: cache-source + repair-shim.


@pytest.fixture(autouse=True)
def _tiny_plausible_official_size_floor(monkeypatch):
    """This file's fake "official"/replacement binaries are tiny shell-script
    fixtures, not real ~230MB Claude binaries. Patch the CMux-incident size
    floor (`source_discovery.MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES`) down to 0
    (no floor) so those fixtures keep classifying as "plausible official"
    here, exactly as they did before Fix 1 -- the real, unpatched 50MB floor
    is exercised end-to-end by tests/test_plausible_official_size_floor.py.
    """
    monkeypatch.setattr(source_discovery, "MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES", 0)


def make_executable(path: Path, text: str = "#!/bin/sh\necho '2.1.199 (Claude Code)'\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | 0o111)
    return path


def seed_shim_target(tmp_path: Path) -> tuple[Path, Path]:
    """Install a real managed shim over an existing binary at an external
    target path, mirroring test_status_v3.py's stage-1 helper and the
    spec's observed failure mode.
    """
    state = tmp_path / ".harnessmonkey"
    target = tmp_path / "local-bin" / "claude"
    make_executable(target, "#!/bin/sh\necho '2.1.199 (Claude Code)'\n")
    install_shim_transaction(target, state, dry_run=False)
    return state, target


def replace_target_with_official(
    target: Path, tmp_path: Path, *, version: str = "2.1.201", name: str = "official-source"
) -> Path:
    """Simulate an official Claude updater clobbering the shim in place with
    a symlink to a newly installed official binary.

    The official binary lives under a `versions/<version>` path segment,
    mirroring the real official installer's own versioned-directory layout
    (spec "Observed failure mode": `.../claude/versions/2.1.201`) -- this is
    also what `repair._version_from_path` (C1) now parses instead of
    executing the binary for `--version`.
    """
    official = make_executable(
        tmp_path / name / "versions" / version / "claude",
        f"#!/bin/sh\necho '{version} (Claude Code)'\n",
    )
    # Shim lock feature: a real locked shim can't actually be clobbered by
    # an external actor (that's the whole point -- see
    # tests/test_shim_lock.py) so lift the flag first here to keep
    # simulating "already replaced" directly, exactly like these
    # pre-existing tests always have.
    _unlock_target(target)
    target.unlink()
    target.symlink_to(official)
    return official


# -- repair-shim: happy path --------------------------------------------


def test_repair_shim_happy_path_caches_swaps_and_rewrites_record(tmp_path):
    state, target = seed_shim_target(tmp_path)
    official = replace_target_with_official(target, tmp_path)
    official_sha = hashlib.sha256(official.read_bytes()).hexdigest()
    paths = StatePaths(state)

    result = repair_shim_action(target, state, paths)

    assert result["repaired"] is True
    assert result["newOfficialSha256"] == official_sha
    assert result["newOfficialVersion"] == "2.1.201"
    assert result["previousOfficialSha256"] == official_sha

    # 1. cached
    cache_path = Path(result["cachedSourcePath"])
    assert cache_path.is_file()
    assert cache_path.read_bytes() == official.read_bytes()

    # 2. swapped: target is the HarnessMonkey shim again
    assert "HarnessMonkey" in target.read_text()
    assert not target.is_symlink()

    # 3. record rewritten to point at the NEW official source (R4), not the
    # stale 2.1.199 the shim was originally installed over.
    record = json.loads((state / "install-record.json").read_text())
    assert record["previousSourceSha256"] == official_sha
    assert record["previousType"] == "symlink"
    assert record["previousTarget"] == str(official)
    assert record["installedShimSha256"]


# -- Fix 1: bounded post-swap revert re-check -----------------------------
#
# Field evidence (verified twice on a real machine): the official
# installer's own self-heal mechanism re-detects and re-overwrites the
# target within ~12-45s of a successful `repair-shim` swap. The CLI's
# `"repaired": true` is truthful in the moment but then goes silently stale.
# `repair_shim_action` now waits `REPAIR_REVERT_RECHECK_DELAY_SECONDS`
# (module-level constant, monkeypatched to 0 in these tests) after the swap
# and re-hashes `target_path` exactly once (read+hash only, never executes
# the target) to report whether it was already clobbered again.


def test_repair_shim_revert_recheck_reports_false_when_not_reverted(tmp_path, monkeypatch):
    state, target = seed_shim_target(tmp_path)
    replace_target_with_official(target, tmp_path)
    paths = StatePaths(state)
    monkeypatch.setattr(repair_module, "REPAIR_REVERT_RECHECK_DELAY_SECONDS", 0)

    result = repair_shim_action(target, state, paths)

    assert result["repaired"] is True
    assert result["revertedImmediately"] is False
    assert "HarnessMonkey" in target.read_text()


def test_repair_shim_revert_recheck_reports_true_when_target_clobbered_after_swap(
    tmp_path, monkeypatch
):
    state, target = seed_shim_target(tmp_path)
    replace_target_with_official(target, tmp_path)
    paths = StatePaths(state)
    monkeypatch.setattr(repair_module, "REPAIR_REVERT_RECHECK_DELAY_SECONDS", 0)

    clobber_bytes = b"#!/bin/sh\necho reclobbered-by-official-updater\n"

    def fake_sleep(seconds: float) -> None:
        # Simulate the official updater's self-heal landing during the
        # bounded post-swap wait window, immediately before the re-hash.
        target.unlink()
        target.write_bytes(clobber_bytes)
        target.chmod(target.stat().st_mode | 0o111)

    monkeypatch.setattr(repair_module, "sleep", fake_sleep)

    result = repair_shim_action(target, state, paths)

    # The swap itself genuinely succeeded -- "repaired" stays truthful about
    # that -- but "revertedImmediately" now also tells the truth about what
    # happened microseconds later.
    assert result["repaired"] is True
    assert result["revertedImmediately"] is True
    assert target.read_bytes() == clobber_bytes


# -- R9: concurrent clobber ----------------------------------------------


def test_repair_shim_aborts_on_concurrent_clobber_after_cache(tmp_path, monkeypatch):
    state, target = seed_shim_target(tmp_path)
    replace_target_with_official(target, tmp_path)
    paths = StatePaths(state)

    real_cache_source = repair_module.cache_source
    clobber_bytes = b"#!/bin/sh\necho newer-official-landed-mid-repair\n"

    def clobbering_cache_source(resolved_source, state_dir, **kwargs):
        result = real_cache_source(resolved_source, state_dir, **kwargs)
        # A concurrent official updater replaces the target again, after we
        # cached the (now-stale) bytes but before the swap -- exactly the
        # window R3 requires a re-verify to close.
        target.unlink()
        target.write_bytes(clobber_bytes)
        target.chmod(target.stat().st_mode | 0o111)
        return result

    monkeypatch.setattr(repair_module, "cache_source", clobbering_cache_source)

    with pytest.raises(RepairRefused) as exc_info:
        repair_shim_action(target, state, paths)

    assert exc_info.value.code == "target_changed"
    # No partial write: target holds exactly the clobbering bytes, not the
    # shim and not reverted to anything else.
    assert target.read_bytes() == clobber_bytes
    assert "HarnessMonkey" not in target.read_text()


# -- Adjudication: old-cache gate loosened ----------------------------------
#
# Controller decision (findings.md "Adjudication"): the pre-repair
# old-cache-must-verify gate is removed. `restore_install_transaction`
# (install.py:368-439) never reads previousSourceCachePath/
# previousSourceSha256 -- it restores from previousType/previousTarget/
# previousContentBase64/previousMode, and repair (R4) overwrites all of
# those fields on success anyway. The old cache is not load-bearing in any
# path of this transaction, so a corrupt OLD cache must not block an
# otherwise-healthy repair (this replaces the old
# test_repair_shim_refuses_when_previous_source_cache_is_corrupt, which
# asserted the pre-adjudication "cache_invalid" refusal).


def test_repair_shim_succeeds_despite_corrupt_old_source_cache(tmp_path):
    state, target = seed_shim_target(tmp_path)
    official = replace_target_with_official(target, tmp_path)
    paths = StatePaths(state)

    record_path = state / "install-record.json"
    record = json.loads(record_path.read_text())
    cache_path = Path(record["previousSourceCachePath"])
    cache_path.write_bytes(b"corrupted-cache-bytes")

    result = repair_shim_action(target, state, paths)

    assert result["repaired"] is True
    assert "HarnessMonkey" in target.read_text()
    assert not target.is_symlink()
    new_record = json.loads(record_path.read_text())
    official_sha = hashlib.sha256(official.read_bytes()).hexdigest()
    assert new_record["previousSourceSha256"] == official_sha


def test_cache_source_action_succeeds_despite_corrupt_old_source_cache(tmp_path):
    state, target = seed_shim_target(tmp_path)
    official = replace_target_with_official(target, tmp_path)
    paths = StatePaths(state)

    record_path = state / "install-record.json"
    record = json.loads(record_path.read_text())
    cache_path = Path(record["previousSourceCachePath"])
    cache_path.write_bytes(b"corrupted-cache-bytes")

    result = cache_source_action(target, state, paths)

    official_sha = hashlib.sha256(official.read_bytes()).hexdigest()
    assert result["sha256"] == official_sha


# -- C1: already-installed refusal ------------------------------------------
#
# findings.md C1: repairing/caching from an untouched, still-correctly-
# installed managed shim classified it as "plausible official" (it lives
# outside HarnessMonkey's own bin/versions roots), which would cache the
# shim's own bytes as "the official source" and rewrite the record's true
# pre-HarnessMonkey rollback data to describe the shim itself -- permanently
# destroying the real rollback content. Both actions must refuse outright,
# before touching the record or the source cache, and must never execute
# the target for version metadata.


def test_repair_shim_refuses_already_installed_intact_shim(tmp_path, monkeypatch):
    state, target = seed_shim_target(tmp_path)
    paths = StatePaths(state)
    record_path = state / "install-record.json"
    record_before = record_path.read_text()
    sources_dir = state / "sources"
    sources_before = set(sources_dir.iterdir()) if sources_dir.exists() else set()

    def must_not_execute(argv, **kwargs):
        raise AssertionError(f"must never execute the target for metadata: {argv}")

    monkeypatch.setattr("harnessmonkey.smoke.run_command", must_not_execute)

    with pytest.raises(RepairRefused) as exc_info:
        repair_shim_action(target, state, paths)

    assert exc_info.value.code == "already_installed"
    assert record_path.read_text() == record_before
    sources_after = set(sources_dir.iterdir()) if sources_dir.exists() else set()
    assert sources_after == sources_before
    assert "HarnessMonkey" in target.read_text()


def test_cache_source_refuses_already_installed_intact_shim(tmp_path, monkeypatch):
    state, target = seed_shim_target(tmp_path)
    paths = StatePaths(state)
    sources_dir = state / "sources"
    sources_before = set(sources_dir.iterdir()) if sources_dir.exists() else set()

    def must_not_execute(argv, **kwargs):
        raise AssertionError(f"must never execute the target for metadata: {argv}")

    monkeypatch.setattr("harnessmonkey.smoke.run_command", must_not_execute)

    with pytest.raises(CacheSourceRefused) as exc_info:
        cache_source_action(target, state, paths)

    assert exc_info.value.code == "already_installed"
    sources_after = set(sources_dir.iterdir()) if sources_dir.exists() else set()
    assert sources_after == sources_before
    assert "HarnessMonkey" in target.read_text()


# -- I1: crash-window consistency between record write and swap -------------
#
# findings.md I1: repair now writes the new install record BEFORE the swap,
# not after (see repair.py's docstring for the full trace). If the process
# crashes between the record write and the swap, the target must be left
# untouched, and the record -- even though it already describes the *new*
# official source -- must never be treated as applicable, because the only
# gate anything uses before trusting a record's rollback fields
# (`current_target_is_installed_shim`) re-reads the target's actual bytes,
# not the record's claims.


def test_repair_shim_crash_between_record_write_and_swap_is_self_consistent(
    tmp_path, monkeypatch
):
    state, target = seed_shim_target(tmp_path)
    official = replace_target_with_official(target, tmp_path)
    paths = StatePaths(state)
    record_path = state / "install-record.json"

    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash before swap")

    monkeypatch.setattr(repair_module, "write_shim", boom)

    with pytest.raises(RuntimeError, match="simulated crash before swap"):
        repair_shim_action(target, state, paths)

    # The swap never got a chance to run: target is completely untouched.
    assert target.is_symlink()
    assert target.resolve() == official.resolve()

    # But the record has ALREADY been rewritten to describe the new official
    # source (I1's reorder) -- this is expected and, per the trace above,
    # harmless.
    record = json.loads(record_path.read_text())
    official_sha = hashlib.sha256(official.read_bytes()).hexdigest()
    assert record["previousSourceSha256"] == official_sha
    assert record["previousType"] == "symlink"
    assert record["previousTarget"] == str(official)

    # Nothing acts on that record's rollback fields: the target is still not
    # the installed shim (actual bytes checked, not the record's claims), so
    # uninstall correctly refuses instead of "restoring" onto an
    # unrepaired target.
    assert current_target_is_installed_shim(target, record) is False
    restored = restore_install_transaction(target, record_path, force=False)
    assert restored is False
    assert target.is_symlink()
    assert target.resolve() == official.resolve()

    # Self-healing: the record this crash left behind still backs a valid
    # repair on the next round (R3's "abort is a fresh detection round, not
    # an error" framing applies equally to a crash).
    assert resolve_cached_source(record, state) is not None
    monkeypatch.undo()
    # `monkeypatch.undo()` above reverts every patch made via this test's
    # `monkeypatch` fixture instance, including this file's autouse
    # `_tiny_plausible_official_size_floor` -- reapply it so the tiny fixture
    # binaries above keep classifying as "plausible official" for the
    # self-healing repair call below.
    monkeypatch.setattr(source_discovery, "MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES", 0)
    result = repair_shim_action(target, state, paths)
    assert result["repaired"] is True
    assert "HarnessMonkey" in target.read_text()


# -- R9: repair-then-uninstall ----------------------------------------------


def test_repair_then_uninstall_restores_new_official_not_stale_one(tmp_path):
    state, target = seed_shim_target(tmp_path)
    official = replace_target_with_official(target, tmp_path)
    paths = StatePaths(state)

    repair_shim_action(target, state, paths)
    assert "HarnessMonkey" in target.read_text()

    record_path = state / "install-record.json"
    restored = restore_install_transaction(target, record_path, force=False)

    assert restored is True
    assert target.is_symlink()
    assert target.resolve() == official.resolve()


# -- never-managed / preconditions ------------------------------------------


def test_repair_shim_refuses_never_managed_target(tmp_path):
    state = tmp_path / ".harnessmonkey"
    state.mkdir(parents=True)
    target = tmp_path / "local-bin" / "claude"
    make_executable(target)
    paths = StatePaths(state)

    with pytest.raises(RepairRefused) as exc_info:
        repair_shim_action(target, state, paths)

    assert exc_info.value.code == "no_install_record"
    assert target.read_text().startswith("#!/bin/sh")


def test_repair_shim_refuses_authorization_required_target_before_any_write(
    tmp_path, monkeypatch
):
    state, target = seed_shim_target(tmp_path)
    replace_target_with_official(target, tmp_path)
    paths = StatePaths(state)

    monkeypatch.setattr(repair_module, "target_needs_authorization", lambda path: True)

    sources_before = set((state / "sources").iterdir()) if (state / "sources").exists() else set()

    with pytest.raises(RepairRefused) as exc_info:
        repair_shim_action(target, state, paths)

    assert exc_info.value.code == "authorization_required"
    # No write attempted: target untouched, and no new cache entry created.
    assert target.is_symlink()
    sources_after = set((state / "sources").iterdir()) if (state / "sources").exists() else set()
    assert sources_after == sources_before


# -- cache-source ------------------------------------------------------------


def test_cache_source_action_happy_path(tmp_path):
    state, target = seed_shim_target(tmp_path)
    official = replace_target_with_official(target, tmp_path)
    official_sha = hashlib.sha256(official.read_bytes()).hexdigest()
    paths = StatePaths(state)

    result = cache_source_action(target, state, paths)

    assert result["sha256"] == official_sha
    cache_path = Path(result["cachedSourcePath"])
    assert cache_path.is_file()
    assert cache_path.read_bytes() == official.read_bytes()
    source_record = json.loads(
        (cache_path.parent / "source-record.json").read_text()
    )
    assert source_record["sha256"] == official_sha
    assert source_record["version"] == "2.1.201"
    # Never touches the target itself.
    assert target.is_symlink()
    assert target.resolve() == official.resolve()


def test_cache_source_refuses_managed_path(tmp_path):
    state = tmp_path / ".harnessmonkey"
    paths = StatePaths(state)
    managed = paths.bin_dir / "claude"
    make_executable(managed)

    with pytest.raises(CacheSourceRefused) as exc_info:
        cache_source_action(managed, state, paths)

    assert exc_info.value.code == "managed_path_refused"


def test_cache_source_aborts_when_target_changes_before_copy(tmp_path, monkeypatch):
    state, target = seed_shim_target(tmp_path)
    replace_target_with_official(target, tmp_path)
    paths = StatePaths(state)

    real_classify = repair_module.classify_plausible_official_source
    calls = {"n": 0}

    def flaky_classify(target_path, paths_arg):
        calls["n"] += 1
        if calls["n"] == 1:
            return real_classify(target_path, paths_arg)
        # Simulate the target having changed between the initial
        # classify/hash and the pre-copy re-verify.
        return tmp_path / "unrelated-does-not-exist"

    monkeypatch.setattr(repair_module, "classify_plausible_official_source", flaky_classify)

    with pytest.raises(CacheSourceRefused) as exc_info:
        cache_source_action(target, state, paths)

    assert exc_info.value.code == "target_changed"


# -- R6: cache retention -----------------------------------------------------


def test_cache_source_retention_keeps_active_and_two_newest(tmp_path, monkeypatch):
    counter = iter(range(1, 10_000))
    monkeypatch.setattr("harnessmonkey.install.time", lambda: next(counter))

    state, target = seed_shim_target(tmp_path)
    paths = StatePaths(state)
    record_path = state / "install-record.json"
    active_digest = json.loads(record_path.read_text())["previousSourceSha256"]

    digests = []
    for index in range(3):
        official = replace_target_with_official(
            target, tmp_path, version=f"2.1.20{index}", name=f"official-{index}"
        )
        digests.append(hashlib.sha256(official.read_bytes()).hexdigest())
        cache_source_action(target, state, paths)

    sources_dir = state / "sources"
    remaining = {entry.name for entry in sources_dir.iterdir() if entry.is_dir()}

    # The active install record's rollback digest is never GC'd...
    assert active_digest in remaining
    # ...and only the 2 most recently captured *other* distinct digests
    # survive: the oldest of the three newly cached sources is removed.
    assert digests[0] not in remaining
    assert digests[1] in remaining
    assert digests[2] in remaining
