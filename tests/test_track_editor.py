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

def test_select_all():
    te = TrackEditor()
    te.select_all(4)
    assert te._sel_tracks == {0, 1, 2, 3}


def test_select_all_then_clear():
    te = TrackEditor()
    te.select_all(3)
    te.clear_selection()
    assert te._sel_tracks == set()


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


def test_copy_with_lims_extracts_limited_range():
    """Ctrl+C avec limiteurs : clipboard limité à la plage, barres relatives."""
    te = TrackEditor()
    p  = _make_pattern(num_bars=4, num_steps=16)
    _fill_track(p, 0, 3)

    # Limite sur les mesures 1-2 (steps 16..47, bars 1-2)
    te.set_lim_left(16)
    te.set_lim_right(47)
    te.copy(p, 0)

    assert te._clipboard.num_bars == 2        # 2 mesures copiées
    assert te._clipboard.grid[0][0][0][0] == 3  # 1re mesure relative (bar 1 source)
    assert _track_sum(p, 0) > 0              # pattern non modifié


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

def test_erase_grid_fills_clipboard_zeros_steps():
    te = TrackEditor()
    p  = _make_pattern()
    _fill_track(p, 0, 44)
    ev = TapeEvent("K", 36, 100, 0, 0)
    p._tape[(0, 0, 3)] = [ev]

    te.erase_grid(p, 0)

    assert te.has_clipboard()
    assert _track_sum(p, 0) == 0          # grille effacée
    assert (0, 0, 3) in p._tape           # tape préservé


def test_erase_grid_preserves_tape():
    te = TrackEditor()
    p  = _make_pattern()
    _fill_track(p, 0, 10)
    p._tape[(0, 1, 7)] = [TapeEvent("K", 42, 80, 0, 0)]

    te.erase_grid(p, 0)

    assert p._tape  # tape non vidé


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


# ---------------------------------------------------------------------------
# Limiteurs temporels
# ---------------------------------------------------------------------------

def test_lims_initially_none():
    te = TrackEditor()
    assert te._lim_left  is None
    assert te._lim_right is None


def test_set_lim_left():
    te = TrackEditor()
    te.set_lim_left(8)
    assert te._lim_left == 8
    assert te._lim_right is None


def test_set_lim_right():
    te = TrackEditor()
    te.set_lim_right(31)
    assert te._lim_right == 31
    assert te._lim_left is None


def test_set_full_range():
    te = TrackEditor()
    te.set_full_range(64)
    assert te._lim_left  == 0
    assert te._lim_right == 63


def test_set_full_range_one_step():
    te = TrackEditor()
    te.set_full_range(1)
    assert te._lim_left  == 0
    assert te._lim_right == 0


def test_reset_lims():
    te = TrackEditor()
    te.set_lim_left(4)
    te.set_lim_right(20)
    te.reset_lims()
    assert te._lim_left  is None
    assert te._lim_right is None


def test_reset_lims_already_none():
    te = TrackEditor()
    te.reset_lims()
    assert te._lim_left  is None
    assert te._lim_right is None


# ---------------------------------------------------------------------------
# fmt_bbt()
# ---------------------------------------------------------------------------

# Paramètres : 4 mesures × 16 steps, 4 beats/mesure → steps_per_beat=4, total=64

NUM_STEPS      = 16
NUM_BEATS      = 4
STEPS_PER_BEAT = NUM_STEPS // NUM_BEATS   # 4
TOTAL_STEPS    = 4 * NUM_STEPS            # 64


def test_fmt_bbt_origin():
    assert TrackEditor.fmt_bbt(0, NUM_STEPS, STEPS_PER_BEAT, TOTAL_STEPS) == "1:1:1"


def test_fmt_bbt_last():
    assert TrackEditor.fmt_bbt(63, NUM_STEPS, STEPS_PER_BEAT, TOTAL_STEPS) == "4:4:4"


def test_fmt_bbt_step8():
    assert TrackEditor.fmt_bbt(8, NUM_STEPS, STEPS_PER_BEAT, TOTAL_STEPS) == "1:3:1"


def test_fmt_bbt_start_bar2():
    assert TrackEditor.fmt_bbt(NUM_STEPS, NUM_STEPS, STEPS_PER_BEAT, TOTAL_STEPS) == "2:1:1"


def test_fmt_bbt_clamps_below_zero():
    assert TrackEditor.fmt_bbt(-5, NUM_STEPS, STEPS_PER_BEAT, TOTAL_STEPS) == "1:1:1"


def test_fmt_bbt_beyond_total():
    """Un step au-delà de total_steps s'affiche normalement (navigation après la fin)."""
    # TOTAL_STEPS=64 → step 64 = 5:1:1, step 74 = 5:3:3 (rem=10, beat=2, tick=2)
    assert TrackEditor.fmt_bbt(TOTAL_STEPS, NUM_STEPS, STEPS_PER_BEAT, TOTAL_STEPS) == "5:1:1"


# ---------------------------------------------------------------------------
# erase_grid et _erase_tracks — respect des limiteurs
# ---------------------------------------------------------------------------
# Pattern : 2 mesures × 16 steps = 32 steps au total (0..31)

def test_erase_grid_no_lims_clears_all():
    """Sans limiteurs, erase_grid efface toute la grille (comportement existant)."""
    te = TrackEditor()
    p  = _make_pattern(num_tracks=2, num_bars=2, num_steps=16)
    _fill_track(p, 0, 1)
    te.erase_grid(p, 0)
    assert _track_sum(p, 0) == 0


def test_erase_grid_with_lims_clears_only_range():
    """Avec limiteurs, erase_grid n'efface que les steps dans [lim_left, lim_right]."""
    te = TrackEditor()
    p  = _make_pattern(num_tracks=2, num_bars=2, num_steps=16)
    _fill_track(p, 0, 1)
    total_before = _track_sum(p, 0)

    # Limite sur la 2e mesure (steps 16..31)
    te.set_lim_left(16)
    te.set_lim_right(31)
    te.erase_grid(p, 0)

    # 1re mesure (steps 0..15) doit rester intacte
    sum_bar0 = sum(
        p._curpattern[0][pad][0][step]
        for pad in range(p._num_pads)
        for step in range(16)
    )
    sum_bar1 = sum(
        p._curpattern[0][pad][1][step]
        for pad in range(p._num_pads)
        for step in range(16)
    )
    assert sum_bar0 > 0, "La 1re mesure ne devrait pas être effacée"
    assert sum_bar1 == 0, "La 2e mesure devrait être effacée"


def test_erase_grid_with_lims_fills_clipboard_limited_range():
    """Avec limiteurs, le clipboard ne contient que la plage limitée."""
    te = TrackEditor()
    p  = _make_pattern(num_tracks=2, num_bars=2, num_steps=16)
    _fill_track(p, 0, 5)
    # Limite sur la 1re mesure seulement (steps 0..15 = bar 0)
    te.set_lim_left(0)
    te.set_lim_right(15)
    te.erase_grid(p, 0)
    assert te.has_clipboard()
    assert te._clipboard.num_bars == 1   # une seule mesure copiée, pas deux


def test_erase_tracks_no_lims_clears_all():
    """Sans limiteurs, cut efface tout le track."""
    te = TrackEditor()
    p  = _make_pattern(num_tracks=2, num_bars=2, num_steps=16)
    _fill_track(p, 0, 1)
    te.erase(p, 0)
    assert _track_sum(p, 0) == 0


def test_erase_tracks_with_lims_clears_only_range():
    """Avec limiteurs, cut n'efface que les steps dans [lim_left, lim_right]."""
    te = TrackEditor()
    p  = _make_pattern(num_tracks=2, num_bars=2, num_steps=16)
    _fill_track(p, 0, 1)

    # Limite sur la 1re mesure uniquement (steps 0..15)
    te.set_lim_left(0)
    te.set_lim_right(15)
    te.erase(p, 0)

    sum_bar0 = sum(
        p._curpattern[0][pad][0][step]
        for pad in range(p._num_pads)
        for step in range(16)
    )
    sum_bar1 = sum(
        p._curpattern[0][pad][1][step]
        for pad in range(p._num_pads)
        for step in range(16)
    )
    assert sum_bar0 == 0, "La 1re mesure devrait être effacée"
    assert sum_bar1 > 0, "La 2e mesure ne devrait pas être effacée"


def test_paste_merge_grid():
    """Shift+V : max() sur la grille — les notes existantes ne sont pas écrasées."""
    te  = TrackEditor()
    src = _make_pattern(num_bars=1, num_steps=16)
    dst = _make_pattern(num_bars=1, num_steps=16)

    # dst : step 0 vaut 80, step 1 vaut 0
    dst._curpattern[0][0][0][0] = 80
    dst._curpattern[0][0][0][1] = 0
    # src : step 0 vaut 50, step 1 vaut 90
    src._curpattern[0][0][0][0] = 50
    src._curpattern[0][0][0][1] = 90

    te.copy(src, 0)
    te.paste(dst, 0, merge=True)

    assert dst._curpattern[0][0][0][0] == 80   # max(80, 50) = 80 (dst conservé)
    assert dst._curpattern[0][0][0][1] == 90   # max(0, 90)  = 90 (src ajouté)


def test_paste_merge_tape():
    """Shift+V : les événements tape sont fusionnés, non remplacés."""
    te  = TrackEditor()
    src = _make_pattern(num_bars=1, num_steps=16)
    dst = _make_pattern(num_bars=1, num_steps=16)
    ev_dst = TapeEvent("K", 36, 100, 0, 0)
    ev_src = TapeEvent("K", 42,  80, 0, 0)
    dst._tape[(0, 0, 3)] = [ev_dst]
    src._tape[(0, 0, 3)] = [ev_src]

    te.copy(src, 0)
    te.paste(dst, 0, merge=True)

    assert len(dst._tape[(0, 0, 3)]) == 2   # les deux événements coexistent


def test_paste_no_extension_when_fits():
    """Règle 1 : si source ≤ place restante, paste ne rallonge pas le pattern."""
    te  = TrackEditor()
    src = _make_pattern(num_bars=2, num_steps=16)
    dst = _make_pattern(num_bars=4, num_steps=16)
    _fill_track(src, 0, 1)

    te.copy(src, 0)
    te.paste(dst, 0, dest_bar=2)   # 2 + 2 = 4 == num_bars → pas d'extension

    assert dst._num_bars == 4, "Le pattern ne doit pas être étendu"


def test_paste_extends_when_overflow():
    """Règle 2 : si source dépasse la fin, le pattern est rallongé avec des mesures vides."""
    te  = TrackEditor()
    src = _make_pattern(num_bars=3, num_steps=16)
    dst = _make_pattern(num_bars=4, num_steps=16)
    _fill_track(src, 0, 1)

    te.copy(src, 0)
    te.paste(dst, 0, dest_bar=3)   # 3 + 3 = 6 > 4 → extension

    assert dst._num_bars == 6, "Le pattern doit être étendu à 6 mesures"
    # Les 3 premières mesures restent vides (mesures 0-2)
    sum_bars_0_2 = sum(
        dst._curpattern[0][pad][b][s]
        for pad in range(dst._num_pads)
        for b in range(3)
        for s in range(16)
    )
    assert sum_bars_0_2 == 0, "Mesures 0-2 doivent rester vides"


def test_paste_at_dest_bar():
    """paste(dest_bar=2) colle à partir de la mesure 2 sans écraser les premières."""
    te  = TrackEditor()
    src = _make_pattern(num_bars=2, num_steps=16)
    dst = _make_pattern(num_bars=4, num_steps=16)
    _fill_track(src, 0, 7)

    te.copy(src, 0)
    te.paste(dst, 0, dest_bar=2)

    # Mesures 0-1 de dst intactes (vides)
    sum_bar0 = sum(
        dst._curpattern[0][pad][0][s]
        for pad in range(dst._num_pads)
        for s in range(16)
    )
    sum_bar2 = sum(
        dst._curpattern[0][pad][2][s]
        for pad in range(dst._num_pads)
        for s in range(16)
    )
    assert sum_bar0 == 0, "Mesure 0 ne doit pas être modifiée"
    assert sum_bar2 > 0,  "Mesure 2 doit contenir les données collées"


def test_erase_grid_then_paste_at_bar5():
    """Scénario complet : erase_grid sur 4 mesures, coller à partir de la mesure 4 (0-based)."""
    te  = TrackEditor()
    # Pattern 4 mesures, rempli
    p = _make_pattern(num_bars=4, num_steps=16)
    _fill_track(p, 0, 9)

    # Ctrl+X : on efface toute la plage (mesures 0-3, steps 0-63)
    te.set_lim_left(0)
    te.set_lim_right(63)
    te.erase_grid(p, 0)

    assert _track_sum(p, 0) == 0, "Grille doit être vide après erase_grid"
    assert te._clipboard.num_bars == 4

    # On déplace le limiteur gauche à la mesure 4 (step 64)
    te.set_lim_left(64)
    te.set_lim_right(127)
    dest_bar = te._lim_left // p._num_steps   # 64 // 16 = 4

    te.paste(p, 0, dest_bar=dest_bar)

    assert p._num_bars == 8, "Pattern doit être étendu à 8 mesures"

    # Mesures 0-3 vides, mesures 4-7 remplies
    sum_bars_0_3 = sum(
        p._curpattern[0][pad][b][s]
        for pad in range(p._num_pads)
        for b in range(4)
        for s in range(16)
    )
    sum_bars_4_7 = sum(
        p._curpattern[0][pad][b][s]
        for pad in range(p._num_pads)
        for b in range(4, 8)
        for s in range(16)
    )
    assert sum_bars_0_3 == 0, "Mesures 0-3 doivent rester vides"
    assert sum_bars_4_7 > 0,  "Mesures 4-7 doivent contenir les données collées"


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
