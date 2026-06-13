#python3
"""
    File: tests/test_song_serialization.py
    Tests de la sérialisation/désérialisation des Songs dans le preset JSON :
    round-trip Song.to_dict/from_dict, persistance de cur_song, _save_song_as.
    Date: Sat, 14/06/2026
    Author: Coolbrother
"""
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from song import Song


# ---------------------------------------------------------------------------
# Helpers reproduisant la logique de _save_preset / _load_preset (sans wx)
# ---------------------------------------------------------------------------

def _make_song_list(n=Song.MAX_SONGS):
    return [Song(i) for i in range(n)]


def _serialize_preset(song_list, cur_song_idx):
    """Reproduit exactement le format JSON de _save_preset pour les songs."""
    return {
        "version":  1,
        "songs":    [s.to_dict() for s in song_list],
        "cur_song": cur_song_idx,
    }


def _load_preset_songs(data, song_list):
    """Reproduit exactement la logique de _load_preset pour les songs."""
    for i, s in enumerate(data.get("songs", [])):
        if i < len(song_list):
            song_list[i].from_dict(s)
    cur_song_idx = max(0, min(data.get("cur_song", 0), len(song_list) - 1))
    return cur_song_idx


def _simulate_save_song_as(song_list, cur_song_idx, dst_idx, new_name):
    """Reproduit la logique de _save_song_as sans wx."""
    src = song_list[cur_song_idx]
    dst = song_list[dst_idx]
    dst._sequence = src._sequence[:]
    dst._looping  = src._looping
    dst._name     = new_name
    return dst_idx   # nouveau cur_song_idx


# ---------------------------------------------------------------------------
# Tests round-trip preset JSON — champ "cur_song"
# ---------------------------------------------------------------------------

def test_preset_saves_cur_song():
    songs = _make_song_list()
    data = _serialize_preset(songs, cur_song_idx=5)
    assert data["cur_song"] == 5
    print("  preset sauvegarde cur_song : OK")


def test_preset_restores_cur_song():
    songs = _make_song_list()
    data = _serialize_preset(songs, cur_song_idx=7)
    songs2 = _make_song_list()
    idx = _load_preset_songs(data, songs2)
    assert idx == 7
    print("  preset restaure cur_song : OK")


def test_preset_cur_song_default_zero():
    """Preset sans clé cur_song → valeur par défaut 0."""
    data = {"version": 1, "songs": [s.to_dict() for s in _make_song_list()]}
    songs = _make_song_list()
    idx = _load_preset_songs(data, songs)
    assert idx == 0
    print("  cur_song absent → défaut 0 : OK")


def test_preset_cur_song_clamp_high():
    """cur_song trop grand → clampé à MAX_SONGS-1."""
    songs = _make_song_list()
    data = _serialize_preset(songs, cur_song_idx=999)
    songs2 = _make_song_list()
    idx = _load_preset_songs(data, songs2)
    assert idx == Song.MAX_SONGS - 1
    print("  cur_song clampé (trop grand) : OK")


def test_preset_cur_song_clamp_zero():
    """cur_song négatif → clampé à 0."""
    songs = _make_song_list()
    data = _serialize_preset(songs, cur_song_idx=0)
    data["cur_song"] = -3
    songs2 = _make_song_list()
    idx = _load_preset_songs(data, songs2)
    assert idx == 0
    print("  cur_song clampé (négatif) : OK")


# ---------------------------------------------------------------------------
# Tests round-trip Song.to_dict / from_dict via preset
# ---------------------------------------------------------------------------

def test_preset_all_songs_roundtrip():
    """Les 16 songs survivent au cycle sérialisation → désérialisation."""
    songs = _make_song_list()
    for i, s in enumerate(songs):
        s._name     = f"Song_{i:02d}_test"
        s._sequence = [i % 99, (i + 1) % 99]
        s._looping  = (i % 2 == 0)

    data   = _serialize_preset(songs, cur_song_idx=3)
    songs2 = _make_song_list()
    _load_preset_songs(data, songs2)

    for i, s in enumerate(songs2):
        assert s._name     == f"Song_{i:02d}_test",    f"Song {i} name"
        assert s._sequence == [i % 99, (i + 1) % 99], f"Song {i} sequence"
        assert s._looping  == (i % 2 == 0),            f"Song {i} looping"
    print("  round-trip 16 songs (name, sequence, looping) : OK")


def test_preset_song_sequence_isolation():
    """Modifier la séquence après sérialisation ne doit pas affecter le preset sauvé."""
    songs = _make_song_list()
    songs[0]._sequence = [1, 2, 3]
    data = _serialize_preset(songs, cur_song_idx=0)
    songs[0]._sequence.append(99)
    songs2 = _make_song_list()
    _load_preset_songs(data, songs2)
    assert songs2[0]._sequence == [1, 2, 3]
    print("  isolation séquence après sérialisation : OK")


def test_backward_compat_no_songs():
    """Preset sans clé 'songs' → songs chargés avec les valeurs par défaut."""
    data   = {"version": 1, "cur_song": 2}
    songs  = _make_song_list()
    idx    = _load_preset_songs(data, songs)
    assert idx == 2
    for s in songs:
        assert s._sequence == []
        assert s._name     == ""
        assert s._looping  is False
    print("  backward-compat (clé songs absente) : OK")


def test_backward_compat_partial_songs():
    """Preset avec moins de 16 songs → songs manquants gardent les défauts."""
    songs_src = _make_song_list()
    songs_src[0]._sequence = [0, 1]
    songs_src[0]._name     = "Intro"
    data = {"version": 1, "songs": [songs_src[0].to_dict()], "cur_song": 0}

    songs2 = _make_song_list()
    idx = _load_preset_songs(data, songs2)
    assert idx == 0
    assert songs2[0]._sequence == [0, 1]
    assert songs2[0]._name     == "Intro"
    for i in range(1, Song.MAX_SONGS):
        assert songs2[i]._sequence == []
    print("  backward-compat (songs partiels) : OK")


# ---------------------------------------------------------------------------
# Tests _save_song_as (logique pure, sans wx)
# ---------------------------------------------------------------------------

def test_save_song_as_copies_sequence():
    songs = _make_song_list()
    songs[2]._sequence = [0, 3, 7]
    _simulate_save_song_as(songs, cur_song_idx=2, dst_idx=5, new_name="Copy")
    assert songs[5]._sequence == [0, 3, 7]
    print("  save_song_as copie la séquence : OK")


def test_save_song_as_copies_looping():
    songs = _make_song_list()
    songs[1]._looping = True
    _simulate_save_song_as(songs, cur_song_idx=1, dst_idx=4, new_name="")
    assert songs[4]._looping is True
    print("  save_song_as copie le flag looping : OK")


def test_save_song_as_sets_name():
    songs = _make_song_list()
    songs[0]._sequence = [1, 2]
    _simulate_save_song_as(songs, cur_song_idx=0, dst_idx=3, new_name="Verse")
    assert songs[3]._name == "Verse"
    print("  save_song_as définit le nom : OK")


def test_save_song_as_updates_cur_song_idx():
    songs = _make_song_list()
    new_idx = _simulate_save_song_as(songs, cur_song_idx=0, dst_idx=8, new_name="X")
    assert new_idx == 8
    print("  save_song_as retourne le nouvel index : OK")


def test_save_song_as_does_not_modify_src():
    """La source ne doit pas être modifiée quand la destination est un slot différent."""
    songs = _make_song_list()
    songs[0]._sequence = [5, 6, 7]
    songs[0]._name     = "Orig"
    songs[0]._looping  = True
    _simulate_save_song_as(songs, cur_song_idx=0, dst_idx=1, new_name="Clone")
    assert songs[0]._sequence == [5, 6, 7]
    assert songs[0]._name     == "Orig"
    assert songs[0]._looping  is True
    print("  save_song_as ne modifie pas la source : OK")


def test_save_song_as_sequence_isolation():
    """La séquence copiée doit être indépendante de la source."""
    songs = _make_song_list()
    songs[0]._sequence = [1, 2, 3]
    _simulate_save_song_as(songs, cur_song_idx=0, dst_idx=1, new_name="")
    songs[0]._sequence.append(99)
    assert songs[1]._sequence == [1, 2, 3]
    print("  save_song_as isolation séquence copiée : OK")


# ---------------------------------------------------------------------------
# Test round-trip complet via fichier JSON temporaire
# ---------------------------------------------------------------------------

def test_json_roundtrip_with_songs():
    """Sérialisation complète → fichier temporaire → chargement."""
    songs = _make_song_list()
    songs[0]._name     = "Intro"
    songs[0]._sequence = [0, 1, 2]
    songs[0]._looping  = False
    songs[3]._name     = "Verse"
    songs[3]._sequence = [3, 4, 3, 4]
    songs[3]._looping  = True
    songs[15]._name    = "Outro"
    songs[15]._sequence = [10]

    data = _serialize_preset(songs, cur_song_idx=3)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f, separators=(',', ':'))
        path = f.name

    try:
        with open(path, encoding="utf-8") as f:
            loaded_data = json.load(f)
        songs2  = _make_song_list()
        cur_idx = _load_preset_songs(loaded_data, songs2)

        assert cur_idx              == 3
        assert songs2[0]._name      == "Intro"
        assert songs2[0]._sequence  == [0, 1, 2]
        assert songs2[0]._looping   is False
        assert songs2[3]._name      == "Verse"
        assert songs2[3]._sequence  == [3, 4, 3, 4]
        assert songs2[3]._looping   is True
        assert songs2[15]._name     == "Outro"
        assert songs2[15]._sequence == [10]
    finally:
        os.unlink(path)
    print("  JSON round-trip complet (fichier temporaire) : OK")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def _run(name, fn):
    try:
        fn()
        return True
    except Exception as e:
        print(f"  FAIL {name}: {e}")
        return False


if __name__ == "__main__":
    print("=== test_song_serialization ===")
    tests = [
        ("preset_saves_cur_song",            test_preset_saves_cur_song),
        ("preset_restores_cur_song",         test_preset_restores_cur_song),
        ("preset_cur_song_default_zero",     test_preset_cur_song_default_zero),
        ("preset_cur_song_clamp_high",       test_preset_cur_song_clamp_high),
        ("preset_cur_song_clamp_zero",       test_preset_cur_song_clamp_zero),
        ("preset_all_songs_roundtrip",       test_preset_all_songs_roundtrip),
        ("preset_song_sequence_isolation",   test_preset_song_sequence_isolation),
        ("backward_compat_no_songs",         test_backward_compat_no_songs),
        ("backward_compat_partial_songs",    test_backward_compat_partial_songs),
        ("save_song_as_copies_sequence",     test_save_song_as_copies_sequence),
        ("save_song_as_copies_looping",      test_save_song_as_copies_looping),
        ("save_song_as_sets_name",           test_save_song_as_sets_name),
        ("save_song_as_updates_cur_idx",     test_save_song_as_updates_cur_song_idx),
        ("save_song_as_no_modify_src",       test_save_song_as_does_not_modify_src),
        ("save_song_as_sequence_isolation",  test_save_song_as_sequence_isolation),
        ("json_roundtrip_with_songs",        test_json_roundtrip_with_songs),
    ]

    ok = sum(1 for name, fn in tests if _run(name, fn))
    total = len(tests)
    print(f"\n{ok}/{total} tests OK")
    if ok < total:
        raise SystemExit(1)
