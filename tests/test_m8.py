import pytest

from conftest import M8, entry
from matey_sync.cache import Cache
from matey_sync.m8 import M8NotFound, copy_to_m8, fat_safe
from matey_sync.models import Patch
from matey_sync.sync import sync


@pytest.fixture
def synced(make):
    client, cache, _ = make([entry("A=BASS.m8i", clip=True),
                             entry("B*BASS.m8i")])
    r = sync("bass", client, cache)
    return cache, r.matched


@pytest.fixture
def card(tmp_path):
    root = tmp_path / "M8"
    (root / "Instruments").mkdir(parents=True)
    return root


def test_copies_patches_not_clips_into_term_folder(synced, card):
    cache, patches = synced
    r = copy_to_m8("bass", patches, cache, m8_root=card)
    dest = card / "Instruments" / "Packs" / "matey" / "bass"
    assert sorted(p.name for p in dest.iterdir()) == ["A=BASS.m8i", "B_BASS.m8i"]
    assert (dest / "A=BASS.m8i").read_bytes() == M8
    assert len(r.copied) == 2 and r.destination == dest


def test_second_copy_is_a_noop(synced, card):
    cache, patches = synced
    copy_to_m8("bass", patches, cache, m8_root=card)
    r = copy_to_m8("bass", patches, cache, m8_root=card)
    assert not r.copied and len(r.unchanged) == 2


def test_changed_file_is_overwritten(synced, card):
    cache, patches = synced
    copy_to_m8("bass", patches, cache, m8_root=card)
    (card / "Instruments/Packs/matey/bass/A=BASS.m8i").write_bytes(b"old")
    r = copy_to_m8("bass", patches, cache, m8_root=card)
    assert r.copied == ["A=BASS.m8i"]


def test_dry_run_writes_nothing(synced, card):
    cache, patches = synced
    r = copy_to_m8("bass", patches, cache, m8_root=card, dry_run=True)
    assert len(r.copied) == 2
    assert not (card / "Instruments" / "Packs").exists()


def test_no_subdir_still_uses_term_folder(synced, card):
    cache, patches = synced
    copy_to_m8("bass", patches, cache, m8_root=card, subdir="")
    assert (card / "Instruments/bass/A=BASS.m8i").exists()


def test_uncached_patches_are_reported(card, tmp_path):
    p = Patch.from_api(entry("Z.m8i"))
    r = copy_to_m8("bass", [p], Cache(tmp_path / "empty"), m8_root=card)
    assert r.not_cached == ["Z.m8i"]


def test_missing_volume_and_missing_instruments(synced, tmp_path):
    cache, patches = synced
    with pytest.raises(M8NotFound):
        copy_to_m8("bass", patches, cache, m8_root=tmp_path / "nope")
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(M8NotFound):
        copy_to_m8("bass", patches, cache, m8_root=bare)
    assert not (bare / "Instruments").exists()


def test_fat_safe():
    assert fat_safe('a:b*c?d"e<f>g|h') == "a_b_c_d_e_f_g_h"
    assert fat_safe("name. ") == "name"
    assert fat_safe("LD=50%SOLO.m8i") == "LD=50%SOLO.m8i"
