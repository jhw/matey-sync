import logging

import pytest

from conftest import CLIP, M8, entry
from matey_sync.cache import Cache
from matey_sync.models import (Patch, UnsafePath, safe_segment, safe_term,
                               validate_patch_path)
from matey_sync.sync import MAX_CONSECUTIVE_FAILURES, sync


def test_layout_is_term_user_patch(make):
    client, cache, _ = make([
        entry("LD=STRINGS1.m8i", clip=True, author="ineffable-twaddle")])
    sync("Strings", client, cache)  # term folder is lower-cased
    d = cache.root / "strings" / "ineffable-twaddle"
    assert (d / "LD=STRINGS1.m8i").read_bytes() == M8
    assert (d / "LD=STRINGS1.mp3").read_bytes() == CLIP  # clip sits beside it


def test_downloads_missing_patches_and_clips(make):
    client, cache, _ = make([entry("A=BASS.m8i", clip=True),
                             entry("B=BASS.m8i", clip=False)])
    r = sync("bass", client, cache)
    assert len(r.matched) == 2 and len(r.new_patches) == 2
    assert [p.path for p in r.new_clips] == ["A=BASS.m8i"]
    assert (cache.root / "bass/a/A=BASS.m8i").read_bytes() == M8
    assert not (cache.root / "bass/a/B=BASS.mp3").exists()


def test_second_run_makes_only_the_search_request(make):
    client, cache, session = make([entry("A=BASS.m8i", clip=True)])
    sync("bass", client, cache)
    n = len(session.calls)
    r = sync("bass", client, Cache(cache.root))  # fresh Cache reloads index
    assert r.already_cached == 1 and not r.new_patches and not r.new_clips
    assert len(session.calls) == n + 1


def test_same_patch_under_second_term_is_copied_not_downloaded(make):
    client, cache, session = make([entry("SUB BASS.m8i", clip=True)])
    sync("bass", client, cache)
    n = len(session.calls)
    r = sync("sub", client, cache)
    assert len(session.calls) == n + 1          # just the search
    assert [p.path for p in r.copied_locally] == ["SUB BASS.m8i"]
    assert (cache.root / "sub/a/SUB BASS.m8i").read_bytes() == M8
    assert (cache.root / "sub/a/SUB BASS.mp3").read_bytes() == CLIP


def test_staleness_is_tracked_per_term(make):
    client, cache, session = make([entry("X BASS.m8i")])
    sync("bass", client, cache)
    sync("x", client, cache)                     # copy under a second term
    session.entries[0]["date"] = "2026-06-01T00:00:00+00:00"
    sync("bass", client, cache)                  # refreshes the bass copy
    r = sync("x", client, cache)                 # x copy is now older
    assert [p.path for p in r.updated_patches] == ["X BASS.m8i"]
    # the fresh bass copy is reused, so no extra download for the x refresh
    assert [p.path for p in r.copied_locally] == ["X BASS.m8i"]


def test_search_term_filters(make):
    client, cache, _ = make([entry("A=BASS.m8i"), entry("S=STRINGS.m8i")])
    r = sync("strings", client, cache)
    assert [p.path for p in r.matched] == ["S=STRINGS.m8i"]
    assert not (cache.root / "strings/a/A=BASS.m8i").exists()


def test_changed_date_refetches(make):
    client, cache, session = make([entry("A.m8i", clip=True)])
    sync("", client, cache)
    session.entries[0]["date"] = "2026-01-01T00:00:00+00:00"
    r = sync("", client, cache)
    assert [p.path for p in r.updated_patches] == ["A.m8i"]
    assert [p.path for p in r.new_clips] == ["A.m8i"]
    assert (cache.root / "_all/a/A.m8i").exists()   # empty term -> _all


def test_clip_added_later_is_picked_up(make):
    client, cache, session = make([entry("A.m8i", clip=False)])
    sync("", client, cache)
    session.entries[0]["hasClip"] = True
    r = sync("", client, cache)
    assert not r.new_patches and not r.updated_patches
    assert [p.path for p in r.new_clips] == ["A.m8i"]


def test_only_with_clip(make):
    client, cache, _ = make([entry("A.m8i", clip=True), entry("B.m8i")])
    r = sync("", client, cache, only_with_clip=True)
    assert [p.path for p in r.matched] == ["A.m8i"]
    assert not (cache.root / "_all/a/B.m8i").exists()


def test_dry_run_changes_nothing(make):
    client, cache, session = make([entry("A.m8i", clip=True)])
    r = sync("", client, cache, dry_run=True)
    assert r.dry_run and len(r.new_patches) == 1 and len(r.new_clips) == 1
    assert not cache.root.exists()
    assert len(session.calls) == 1               # only the search


def test_failure_is_reported_and_others_continue(make):
    client, cache, session = make([entry("A.m8i"), entry("B.m8i")])
    session.fail.add("A.m8i")
    r = sync("", client, cache)
    assert [f[0] for f in r.failed] == ["A.m8i"] and not r.aborted
    assert (cache.root / "_all/a/B.m8i").exists()
    assert "A.m8i" not in cache.index            # retried next run


def test_aborts_after_repeated_failures(make):
    names = [f"P{i}.m8i" for i in range(MAX_CONSECUTIVE_FAILURES + 3)]
    client, cache, session = make([entry(n) for n in names])
    session.fail.update(names)
    r = sync("", client, cache)
    assert r.aborted and len(r.failed) == MAX_CONSECUTIVE_FAILURES
    patch_gets = [u for u, _ in session.calls if "/api/P" in u]
    attempts = 1 + client.retries                # initial try + retries
    assert len(patch_gets) == MAX_CONSECUTIVE_FAILURES * attempts


def test_logs_plan_and_each_patch(make, caplog):
    client, cache, _ = make([entry("A BASS.m8i", clip=True, author="bob")])
    with caplog.at_level(logging.INFO, logger="matey_sync"):
        sync("bass", client, cache)
    text = caplog.text
    assert "searching impbox.net/matey for 'bass'" in text
    assert "1 patches match (1 have an audio clip)" in text
    assert "2 downloads" in text
    assert "[1/1] bob/A BASS.m8i: patch" in text and "clip" in text


@pytest.mark.parametrize("bad", ["../evil.m8i", "a/b.m8i", "a\\b.m8i",
                                 ".hidden.m8i", "notapatch.txt", ".m8i", ""])
def test_unsafe_paths_rejected(bad):
    with pytest.raises(UnsafePath):
        validate_patch_path(bad)


def test_unsafe_entries_are_skipped_by_search(make):
    client, cache, _ = make([entry("../evil.m8i"), entry("ok.m8i")])
    r = sync("", client, cache)
    assert [p.path for p in r.matched] == ["ok.m8i"]


def test_hostile_author_and_term_cannot_escape_cache(make):
    client, cache, _ = make([entry("A.m8i", author="../../etc", desc="../..")])
    sync("../..", client, cache)
    inside = [p for p in cache.root.rglob("A.m8i")]
    assert inside and all(cache.root in p.parents for p in inside)


def test_segment_helpers():
    assert safe_term("") == "_all" and safe_term("  Bass  Drum ") == "bass drum"
    assert safe_segment("Dimitri Eugensson") == "Dimitri Eugensson"
    assert safe_segment(".cortx") == "cortx" and safe_segment("") == "_"
    assert "/" not in safe_segment("a/b") and safe_segment("..") == "_"


def test_special_characters_in_names(make):
    names = ["LD=50%SOLO.m8i", "LD=BIG&UGLY.m8i", "BS=SLAPPEN D.m8i"]
    client, cache, _ = make([entry(n, clip=True) for n in names])
    r = sync("", client, cache)
    assert len(r.new_patches) == 3 and len(r.new_clips) == 3
    assert Patch.from_api(entry("X.m8i")).clip_name == "X.mp3"
