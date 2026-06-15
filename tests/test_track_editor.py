#python3
"""
    File: tests/test_track_editor.py
    Tests unitaires — TrackEditor (sélection multi-pistes + copier/couper/coller/effacer)
    Date: Mon, 15/06/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import Pattern, TapeEvent
from track_editor import TrackEditor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pattern(num_tracks=4, num_bars=2, num_steps=16):
    p = Pattern()
    p._num_tracks = num_tracks
    p._num_bars   = num_bars
    p._num_steps  = num_steps
    p._curpattern = [
        [
            [[0] * num_steps for _ in range(num_bars)]
            for _ in range(p._num_pads)
        ]
        for _ in range(num_tracks)
    ]
    p._tape      = {}
    p._bend_tape = [[] for _ in range(num_tracks)]
    p._mod_tape  = [[] for _ in range(num_tracks)]
    return p


def _fill_track(pattern, track_idx, value=100):
    """Met toutes les cellules d'une piste à `value`."""
    for pad in pattern._curpattern[track_idx]:
        for bar in pad:
            for i in range(len(bar)):
                bar[i] = value


def _track_sum(pattern, track_idx):
    return sum(
        v
        for pad in pattern._curpattern[track_idx]
        for bar in pad
        for v in bar
    )


# ---------------------------------------------------------------------------
# Tests sélection
# ---------------------------------------------------------------------------

def test_select_one():
    te = TrackEditor()
    te.select_one(2)
    assert te._sel_tracks == {2}


def test_clear_selection():
    te = TrackEditor()
    te.select_one(1)
    te.clear_selection()
    assert te._sel_tracks == set()


def test_toggle_track_add_remove():
    te = TrackEditor()
    te.toggle_track(3)
    assert 3 in te._sel_tracks
    te.toggle_track(3)
    assert 3 not in te._sel_tracks


def test_is_selected():
    te = TrackEditor()
    te.select_one(0)
    assert te.is_selected(0)
    assert not te.is_selected(1)


def test_has_multi_selection():
    te = TrackEditor()
    assert not te.has_multi_selection()
    te.select_one(0)
    assert not te.has_multi_selection()
    te.toggle_track(1)
    assert te.has_multi_selection()


def test_extend_up_basic():
    te = TrackEditor()
    new = te.extend_up(2)
    assert new == 1
    assert te._sel_tracks == {1, 2}


def test_extend_up_at_top():
    te = TrackEditor()
    new = te.extend_up(0)
    assert new == 0
    assert te._sel_tracks == set()


def test_extend_down_basic():
    te = TrackEditor()
    new = te.extend_down(1, 4)
    assert new == 2
    assert te._sel_tracks == {1, 2}


def test_extend_down_at_bottom():
    te = TrackEditor()
    new = te.extend_down(3, 4)
    assert new == 3
    assert te._sel_tracks == set()


def test_get_effective_tracks_empty():
    te = TrackEditor()
    assert te.get_effective_tracks(2) == [2]


def test_get_effective_tracks_multi():
    te = TrackEditor()
    te.select_one(0)
    te.toggle_track(2)
    assert te.get_effective_tracks(0) == [0, 2]


# ---------------------------------------------------------------------------
# Tests copier / coller
# ---------------------------------------------------------------------------

def test_copy_single_track():
    te = TrackEditor()
    p  = _make_pattern()
    _fill_track(p, 0, 99)

    te.copy(p, 0)
    assert te.has_clipboard()
    assert te._clipboard.num_tracks == 1
    assert te._clipboard.grid[0][0][0][0] == 99


def test_copy_does_not_modify_pattern():
    te = TrackEditor()
    p  = _make_pattern()
    _fill_track(p, 0, 77)

    te.copy(p, 0)
    assert _track_sum(p, 0) > 0   # toujours remplie


def test_paste_single_track():
    te = TrackEditor()
    src = _make_pattern()
    dst = _make_pattern()
    _fill_track(src, 0, 50)

    te.copy(src, 0)
    te.paste(dst, 1)

    assert _track_sum(dst, 1) > 0
    assert _track_sum(dst, 0) == 0   # piste 0 intacte


def test_paste_multi_track():
    te = TrackEditor()
    src = _make_pattern(num_tracks=4)
    dst = _make_pattern(num_tracks=4)
    _fill_track(src, 0, 11)
    _fill_track(src, 1, 22)

    te.select_one(0)
    te.toggle_track(1)
    te.copy(src, 0)
    te.paste(dst, 2)

    assert _track_sum(dst, 2) > 0
    assert _track_sum(dst, 3) > 0
    assert _track_sum(dst, 0) == 0
    assert _track_sum(dst, 1) == 0


def test_paste_empty_clipboard():
    te = TrackEditor()
    p  = _make_pattern()
    assert not te.paste(p, 0)


def test_paste_truncates_to_destination():
    te  = TrackEditor()
    src = _make_pattern(num_tracks=4)
    dst = _make_pattern(num_tracks=2)
    for t in range(4):
        _fill_track(src, t, 1)

    te.select_one(0)
    for t in range(1, 4):
        te.toggle_track(t)
    te.copy(src, 0)
    te.paste(dst, 1)   # seule piste 1 disponible

    assert _track_sum(dst, 1) > 0


def test_copy_includes_tape_events():
    te = TrackEditor()
    p  = _make_pattern()
    ev = TapeEvent("K", 36, 100, 0, 0)
    p._tape[(0, 0, 3)] = [ev]

    te.copy(p, 0)
    assert (0, 0, 3) in te._clipboard.tape


def test_paste_restores_tape_events():
    te  = TrackEditor()
    src = _make_pattern()
    dst = _make_pattern()
    ev  = TapeEvent("K", 42, 80, 0, 0)
    src._tape[(0, 1, 5)] = [ev]

    te.copy(src, 0)
    te.paste(dst, 0)

    assert (0, 1, 5) in dst._tape


# ---------------------------------------------------------------------------
# Tests couper / effacer
# ---------------------------------------------------------------------------

def test_cut_fills_clipboard_and_clears():
    te = TrackEditor()
    p  = _make_pattern()
    _fill_track(p, 0, 33)

    te.cut(p, 0)

    assert te.has_clipboard()
    assert _track_sum(p, 0) == 0


def test_erase_clears_without_clipboard():
    te = TrackEditor()
    p  = _make_pattern()
    _fill_track(p, 0, 55)

    te.erase(p, 0)

    assert not te.has_clipboard()
    assert _track_sum(p, 0) == 0


def test_erase_multi_tracks():
    te = TrackEditor()
    p  = _make_pattern(num_tracks=4)
    _fill_track(p, 0, 10)
    _fill_track(p, 2, 20)
    _fill_track(p, 3, 30)

    te.select_one(0)
    te.toggle_track(2)
    te.erase(p, 0)

    assert _track_sum(p, 0) == 0
    assert _track_sum(p, 2) == 0
    assert _track_sum(p, 3) > 0   # non sélectionnée → intacte


# ---------------------------------------------------------------------------
# Test presse-papier cross-pattern
# ---------------------------------------------------------------------------

def test_clipboard_survives_pattern_change():
    te   = TrackEditor()
    src  = _make_pattern()
    dst  = _make_pattern()
    _fill_track(src, 0, 7)

    te.copy(src, 0)
    # On "change" de pattern (nouveau objet) — le clipboard reste dans te
    te.paste(dst, 0)

    assert _track_sum(dst, 0) > 0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  OK  {fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"FAIL  {fn.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
