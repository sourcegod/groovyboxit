#python3
"""
    File: tests/test_pattern_grid_api.py
    Tests unitaires de la nouvelle API grille de Pattern (get_cell/set_cell/
    clear_grid_pad/clear_grid_box/grid_row/set_grid_row/iter_grid/
    to_dense_grid/copy_from) — façade au-dessus de _tape (etype ETYPE_GRID) qui
    remplace l'ancien _curpattern.
    Date: Thu, 16/07/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH, ETYPE_BEND
from tape_test_utils import tape_at, has_tape_at, set_tape_at, add_tape_at, same_events


def _K(note, vel=100, dur=0):
    return TapeEvent(ETYPE_KIT, dur=dur, payload={"note": note, "vel": vel})


def _P(note, vel=100, dur=0):
    return TapeEvent(ETYPE_PATCH, dur=dur, payload={"note": note, "vel": vel})


# ---------------------------------------------------------------------------
# get_cell / set_cell
# ---------------------------------------------------------------------------

def test_get_cell_empty_returns_zero():
    p = Pattern()
    assert p.get_cell(0, 0, 0, 0) == 0
    print("  get_cell vide → 0 : OK")


def test_set_cell_then_get_cell():
    p = Pattern()
    p.set_cell(0, 3, 0, 5, 100)
    assert p.get_cell(0, 3, 0, 5) == 100
    assert tape_at(p, 0, 0, 5) == [TapeEvent(ETYPE_GRID, payload={"pad": 3, "vel": 100})]
    print("  set_cell → get_cell : OK")


def test_set_cell_clamps_velocity():
    p = Pattern()
    p.set_cell(0, 0, 0, 0, 999)
    assert p.get_cell(0, 0, 0, 0) == 127
    p.set_cell(0, 0, 0, 1, True)
    assert p.get_cell(0, 0, 0, 1) == 100
    p.set_cell(0, 0, 0, 2, False)
    assert p.get_cell(0, 0, 0, 2) == 0
    print("  set_cell clamp/bool : OK")


def test_set_cell_zero_removes_event():
    p = Pattern()
    p.set_cell(0, 0, 0, 0, 100)
    p.set_cell(0, 0, 0, 0, 0)
    assert p.get_cell(0, 0, 0, 0) == 0
    assert not has_tape_at(p, 0, 0, 0)
    print("  set_cell(0) supprime l'event : OK")


def test_set_cell_overwrites_same_pad():
    p = Pattern()
    p.set_cell(0, 0, 0, 0, 100)
    p.set_cell(0, 0, 0, 0, 50)
    assert p.get_cell(0, 0, 0, 0) == 50
    assert len(tape_at(p, 0, 0, 0)) == 1
    print("  set_cell réécrit (pas de doublon) : OK")


def test_multiple_pads_same_offset():
    p = Pattern()
    p.set_cell(0, 2, 0, 4, 80)
    p.set_cell(0, 7, 0, 4, 110)
    assert p.get_cell(0, 2, 0, 4) == 80
    assert p.get_cell(0, 7, 0, 4) == 110
    assert len(tape_at(p, 0, 0, 4)) == 2
    print("  plusieurs pads au même offset : OK")


def test_set_cell_coexists_with_kp_events():
    p = Pattern()
    set_tape_at(p, 0, 0, 4, [_K(60, 90), _P(61, 70, 200)])
    p.set_cell(0, 3, 0, 4, 100)
    assert same_events(tape_at(p, 0, 0, 4), [
        _K(60, 90), _P(61, 70, 200), TapeEvent(ETYPE_GRID, payload={"pad": 3, "vel": 100})
    ])
    # Effacer la note G ne touche pas K/P
    p.set_cell(0, 3, 0, 4, 0)
    assert same_events(tape_at(p, 0, 0, 4), [_K(60, 90), _P(61, 70, 200)])
    print("  set_cell coexiste avec K/P sur la même clé : OK")


# ---------------------------------------------------------------------------
# clear_grid_pad / clear_grid_box
# ---------------------------------------------------------------------------

def test_clear_grid_pad_only_removes_matching_pad():
    p = Pattern()
    p.set_cell(0, 1, 0, 0, 100)
    p.set_cell(0, 2, 0, 0, 100)
    p.set_cell(1, 1, 0, 0, 100)   # autre piste, ne doit pas être touché
    p.clear_grid_pad(0, 1)
    assert p.get_cell(0, 1, 0, 0) == 0
    assert p.get_cell(0, 2, 0, 0) == 100
    assert p.get_cell(1, 1, 0, 0) == 100
    print("  clear_grid_pad cible piste+pad uniquement : OK")


def test_clear_grid_pad_preserves_kp():
    p = Pattern()
    set_tape_at(p, 0, 0, 0, [_K(60, 90)])
    p.set_cell(0, 1, 0, 0, 100)
    p.clear_grid_pad(0, 1)
    assert tape_at(p, 0, 0, 0) == [_K(60, 90)]
    print("  clear_grid_pad préserve K/P : OK")


def test_clear_grid_box_range_and_kp_preserved():
    p = Pattern()
    p.set_cell(0, 0, 0, 0, 100)
    p.set_cell(0, 1, 0, 5, 100)
    p.set_cell(0, 0, 0, 10, 100)   # hors plage
    add_tape_at(p, 0, 0, 5, _K(64, 90))
    p.clear_grid_box(tracks=[0], bars=[0], steps=range(0, 8))
    assert p.get_cell(0, 0, 0, 0) == 0
    assert p.get_cell(0, 1, 0, 5) == 0
    assert p.get_cell(0, 0, 0, 10) == 100   # hors plage : conservé
    assert any(ev.etype == ETYPE_KIT for ev in tape_at(p, 0, 0, 5))
    print("  clear_grid_box respecte la plage et préserve K/P : OK")


# ---------------------------------------------------------------------------
# grid_row / set_grid_row
# ---------------------------------------------------------------------------

def test_grid_row_roundtrip():
    p = Pattern()
    values = [0] * p._num_steps
    values[0] = 100
    values[4] = 50
    values[15] = 127
    p.set_grid_row(0, 3, 0, values)
    assert p.grid_row(0, 3, 0) == values
    print("  set_grid_row / grid_row round-trip : OK")


def test_set_grid_row_clears_absent_steps():
    p = Pattern()
    p.set_cell(0, 3, 0, 2, 100)
    p.set_grid_row(0, 3, 0, [0] * p._num_steps)
    assert p.grid_row(0, 3, 0) == [0] * p._num_steps
    print("  set_grid_row efface les steps à 0 : OK")


# ---------------------------------------------------------------------------
# iter_grid / to_dense_grid
# ---------------------------------------------------------------------------

def test_iter_grid_filters_by_track_and_etype():
    p = Pattern()
    p.set_cell(0, 1, 0, 0, 100)
    p.set_cell(1, 2, 0, 3, 80)
    add_tape_at(p, 0, 0, 0, _K(60, 90))
    all_g = sorted(p.iter_grid())
    assert all_g == [(0, 1, 0, 0, 100), (1, 2, 0, 3, 80)]
    track0_only = sorted(p.iter_grid(track=0))
    assert track0_only == [(0, 1, 0, 0, 100)]
    print("  iter_grid filtre piste + etype G uniquement : OK")


def test_to_dense_grid_matches_iter_grid():
    p = Pattern()
    p.set_cell(0, 1, 0, 0, 100)
    p.set_cell(0, 2, 0, 5, 64)
    p.set_cell(1, 3, 0, 10, 40)
    dense = p.to_dense_grid()
    for t, pad, b, s, vel in p.iter_grid():
        assert dense[t][pad][b][s] == vel
    total_active = sum(
        1
        for track in dense
        for pad in track
        for bar in pad
        for v in bar
        if v
    )
    assert total_active == 3
    print("  to_dense_grid cohérent avec iter_grid : OK")


# ---------------------------------------------------------------------------
# copy_from
# ---------------------------------------------------------------------------

def test_copy_from_copies_dims_tape_bend():
    src = Pattern()
    src.resize(3, 32)
    src.set_cell(0, 1, 2, 10, 90)
    add_tape_at(src, 0, 2, 10, _K(60, 90))
    src._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": 1000}, time=5.0))

    dst = Pattern()
    dst.copy_from(src)

    assert dst._num_bars  == 3
    assert dst._num_steps == 32
    assert dst.get_cell(0, 1, 2, 10) == 90
    assert any(ev.etype == ETYPE_KIT for ev in tape_at(dst, 0, 2, 10))
    assert [(ev.time, ev.payload) for ev in dst._tape[0] if ev.etype == ETYPE_BEND] == \
        [(5.0, {"value": 1000})]
    print("  copy_from copie dims + tape, bends compris (_mod_tape 5h, _bend_tape 6h1 supprimés) : OK")


def test_copy_from_is_independent_copy():
    src = Pattern()
    src.set_cell(0, 0, 0, 0, 100)
    dst = Pattern()
    dst.copy_from(src)

    src.set_cell(0, 0, 0, 0, 0)          # modifie la source après coup
    src._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": 500}, time=1.0))

    assert dst.get_cell(0, 0, 0, 0) == 100   # dst inchangé
    assert [ev for ev in dst._tape[0] if ev.etype == ETYPE_BEND] == []
    print("  copy_from produit une copie indépendante : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import inspect
    mod = sys.modules[__name__]
    for name, fn in sorted(inspect.getmembers(mod, inspect.isfunction)):
        if name.startswith("test_"):
            fn()
    print("Tous les tests test_pattern_grid_api ont réussi.")


# ---------------------------------------------------------------------------
# grid_row en un passage (Phase 7 étape 18d3) : même résultat que get_cell
# case par case
# ---------------------------------------------------------------------------

def test_grid_row_matches_get_cell():
    p = Pattern()
    p._num_bars = 3
    for bar, step, pad, vel in [(0, 0, 2, 90), (0, 15, 2, 40), (1, 3, 2, 70),
                                (0, 4, 5, 100), (2, 15, 2, 20)]:
        p.set_cell(0, pad, bar, step, vel)
    p._tape[0].append(TapeEvent(ETYPE_PATCH, payload={"note": 60, "vel": 1}, time=6))
    p._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": 9}, time=7))
    for pad in range(16):
        for bar in range(3):
            assert p.grid_row(0, pad, bar) == [p.get_cell(0, pad, bar, s) for s in range(16)]
    assert p.grid_row(0, 2, 0)[15] == 40 and p.grid_row(0, 2, 2)[15] == 20


def test_grid_row_first_event_wins_like_get_cell():
    p = Pattern()
    p._tape[0].append(TapeEvent(ETYPE_GRID, payload={"pad": 1, "vel": 30}, time=5))
    p._tape[0].append(TapeEvent(ETYPE_GRID, payload={"pad": 1, "vel": 99}, time=5))
    assert p.grid_row(0, 1, 0)[5] == p.get_cell(0, 1, 0, 5) == 30


def test_grid_row_ignores_fractional_times_and_other_tracks():
    p = Pattern()
    p._tape[0].append(TapeEvent(ETYPE_GRID, payload={"pad": 1, "vel": 30}, time=5.5))
    p.set_cell(1, 1, 0, 5, 80)
    assert p.grid_row(0, 1, 0) == [0] * 16
    assert p.grid_row(99, 1, 0) == [0] * 16


def test_grid_row_is_linear_in_track_size():
    """Une piste de 20 000 notes : une ligne en un passage, pas 16."""
    p = Pattern()
    p._num_bars, p._num_steps = 999, 128
    p._tape[0] = [TapeEvent(ETYPE_PATCH, payload={"note": 60, "vel": 1}, time=t)
                  for t in range(20000)]
    calls = [0]
    real = p._tape[0]
    class Counting(list):
        def __iter__(self):
            calls[0] += 1
            return list.__iter__(self)
    p._tape[0] = Counting(real)
    p.grid_row(0, 0, 0)
    assert calls[0] == 1
