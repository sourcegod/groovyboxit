#python3
"""
    File: tests/test_song.py
    Tests unitaires du Mode Song : Song data model + DrumPlayer song mode.
    Date: Mon, 08/06/2026
    Author: Coolbrother
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from song import Song
from pattern import Pattern
from drum_player import DrumPlayer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_pattern(bpm=100, num_bars=1, name=""):
    p = Pattern()
    p._bpm = bpm
    p._num_bars = num_bars
    p._name = name
    p._looping = True
    return p


class FakePlayer(DrumPlayer):
    """DrumPlayer sans son pour les tests."""
    def __init__(self, pattern_list=None):
        super().__init__(sound_manager=None)
        self._pattern_list_ref = pattern_list
        self._advances = []

    def play_pattern(self):
        self.playing = True
        self.start_thread()

    def _setup_advance_cb(self):
        self._on_song_advance_cb = lambda idx: self._advances.append(idx)


# ---------------------------------------------------------------------------
# Song — modèle données
# ---------------------------------------------------------------------------

def test_song_default_name():
    s = Song(0)
    assert s._name == ""
    assert s._idx == 0
    assert s.label() == "Song_01"

def test_song_label_with_sequence():
    s = Song(2)
    s._sequence = [0, 1, 5]
    assert s.label() == "Song_03 (3)"

def test_song_label_with_name():
    s = Song(0)
    s._name = "Intro"
    s._sequence = [0, 1]
    assert s.label() == "Intro (2)"

def test_song_to_dict():
    s = Song(1)
    s._name = "Test"
    s._sequence = [0, 3, 7]
    d = s.to_dict()
    assert d["name"] == "Test"
    assert d["sequence"] == [0, 3, 7]

def test_song_to_dict_isolation():
    s = Song(0)
    s._sequence = [1, 2]
    d = s.to_dict()
    d["sequence"].append(99)
    assert s._sequence == [1, 2]

def test_song_from_dict():
    s = Song(3)
    s.from_dict({"name": "Verse", "sequence": [0, 1, 0]})
    assert s._name == "Verse"
    assert s._sequence == [0, 1, 0]

def test_song_from_dict_defaults():
    s = Song(0)
    s._name = "old"
    s._sequence = [1, 2]
    s.from_dict({})
    assert s._name == ""
    assert s._sequence == []

def test_song_from_dict_coerces_int():
    s = Song(0)
    s.from_dict({"sequence": ["3", "7", "0"]})
    assert s._sequence == [3, 7, 0]

def test_song_max_songs():
    assert Song.MAX_SONGS == 16

def test_song_roundtrip():
    s = Song(5)
    s._name = "Coda"
    s._sequence = [0, 2, 4, 99]
    s2 = Song(5)
    s2.from_dict(s.to_dict())
    assert s2._name == s._name
    assert s2._sequence == s._sequence


# ---------------------------------------------------------------------------
# Song — DrumPlayer.play_song
# ---------------------------------------------------------------------------

def test_play_song_sets_song_mode():
    pats = [make_pattern(bpm=120) for _ in range(3)]
    player = FakePlayer(pats)
    player.load_pattern(pats[0].to_dense_grid())
    player.play_song([0, 1, 2], pats)
    assert player._song_mode is True
    assert player._song_sequence == [0, 1, 2]
    assert player._song_pos == 0
    player.stop_pattern()

def test_play_song_empty_sequence_noop():
    pats = [make_pattern()]
    player = FakePlayer(pats)
    player.play_song([], pats)
    assert player._song_mode is False
    assert player.playing is False

def test_stop_pattern_clears_song_mode():
    pats = [make_pattern()]
    player = FakePlayer(pats)
    player.load_pattern(pats[0].to_dense_grid())
    player.play_song([0], pats)
    player.stop_pattern()
    assert player._song_mode is False

def test_play_song_sets_looping_false():
    pats = [make_pattern()]
    pats[0]._looping = True
    player = FakePlayer(pats)
    player.load_pattern(pats[0].to_dense_grid())
    player.play_song([0], pats)
    assert player._pattern._looping is False
    player.stop_pattern()


# ---------------------------------------------------------------------------
# Song — transition automatique (test temps réel court)
# ---------------------------------------------------------------------------

def _run_song_advance_test(num_patterns, bpm=600, num_bars=1):
    """Joue un song et attend les N-1 transitions + fin."""
    pats = [make_pattern(bpm=bpm, num_bars=num_bars) for _ in range(num_patterns)]
    for p in pats:
        p._looping = False
    advances = []
    player = FakePlayer(pats)
    player._on_song_advance_cb = lambda idx: advances.append(idx)
    player.load_pattern(pats[0].to_dense_grid())
    player.play_song(list(range(num_patterns)), pats)

    # Attendre la fin du song (avec timeout)
    timeout = (num_patterns * num_bars * 4 * 60.0 / bpm) + 2.0
    deadline = time.perf_counter() + timeout
    while player.playing and time.perf_counter() < deadline:
        time.sleep(0.05)
    player.stop_pattern()
    return advances


def test_song_single_pattern_ends():
    advances = _run_song_advance_test(1, bpm=600)
    assert advances == [-1]

def test_song_two_patterns_advance_then_end():
    advances = _run_song_advance_test(2, bpm=600)
    assert advances == [1, -1]

def test_song_three_patterns_all_advances():
    advances = _run_song_advance_test(3, bpm=600)
    assert advances == [1, 2, -1]


# ---------------------------------------------------------------------------
# Song — bouclage
# ---------------------------------------------------------------------------

def test_song_looping_default_false():
    s = Song(0)
    assert s._looping is False

def test_song_looping_to_dict():
    s = Song(0)
    s._looping = True
    assert s.to_dict()["looping"] is True

def test_song_looping_from_dict():
    s = Song(0)
    s.from_dict({"looping": True})
    assert s._looping is True

def test_song_looping_from_dict_default():
    s = Song(0)
    s.from_dict({})
    assert s._looping is False

def test_play_song_sets_looping_flag():
    pats = [make_pattern()]
    player = FakePlayer(pats)
    player.load_pattern(pats[0].to_dense_grid())
    player.play_song([0], pats, looping=True)
    assert player._song_looping is True
    player.stop_pattern()

def test_song_looping_loops_back():
    """Avec looping=True, le callback reçoit l'indice du 1er pattern au lieu de -1."""
    pats = [make_pattern(bpm=600) for _ in range(2)]
    for p in pats:
        p._looping = False
    advances = []
    player = FakePlayer(pats)
    player._on_song_advance_cb = lambda idx: advances.append(idx)
    player.load_pattern(pats[0].to_dense_grid())
    player.play_song([0, 1], pats, looping=True)

    # Attendre 2 cycles complets (chaque pattern = ~0.1 s à 600 BPM)
    deadline = time.perf_counter() + 3.0
    while len(advances) < 4 and time.perf_counter() < deadline:
        time.sleep(0.05)
    player.stop_pattern()

    # On doit voir la séquence : 1, 0, 1, 0, ... (jamais -1)
    assert -1 not in advances[:4], f"Got -1 (stop) in looping song: {advances}"
    assert 1 in advances, "Premier avancement vers pat 1 manquant"
    assert advances.count(0) >= 1, "Retour au pat 0 manquant (boucle)"


# ---------------------------------------------------------------------------

def _run(name, fn):
    try:
        fn()
        print(f"  OK  {name}")
        return True
    except Exception as e:
        print(f"  FAIL {name}: {e}")
        return False


if __name__ == "__main__":
    tests = [
        ("song_default_name",            test_song_default_name),
        ("song_label_with_sequence",     test_song_label_with_sequence),
        ("song_label_with_name",         test_song_label_with_name),
        ("song_to_dict",                 test_song_to_dict),
        ("song_to_dict_isolation",       test_song_to_dict_isolation),
        ("song_from_dict",               test_song_from_dict),
        ("song_from_dict_defaults",      test_song_from_dict_defaults),
        ("song_from_dict_coerces_int",   test_song_from_dict_coerces_int),
        ("song_max_songs",               test_song_max_songs),
        ("song_roundtrip",               test_song_roundtrip),
        ("play_song_sets_song_mode",     test_play_song_sets_song_mode),
        ("play_song_empty_noop",         test_play_song_empty_sequence_noop),
        ("stop_pattern_clears_mode",     test_stop_pattern_clears_song_mode),
        ("play_song_looping_false",      test_play_song_sets_looping_false),
        ("song_single_ends",             test_song_single_pattern_ends),
        ("song_two_advance_end",         test_song_two_patterns_advance_then_end),
        ("song_three_all_advances",      test_song_three_patterns_all_advances),
        ("song_looping_default_false",   test_song_looping_default_false),
        ("song_looping_to_dict",         test_song_looping_to_dict),
        ("song_looping_from_dict",       test_song_looping_from_dict),
        ("song_looping_from_dict_default", test_song_looping_from_dict_default),
        ("play_song_sets_looping_flag",  test_play_song_sets_looping_flag),
        ("song_looping_loops_back",      test_song_looping_loops_back),
    ]

    ok = sum(1 for name, fn in tests if _run(name, fn))
    total = len(tests)
    print(f"\n{ok}/{total} tests OK")
    if ok < total:
        raise SystemExit(1)
