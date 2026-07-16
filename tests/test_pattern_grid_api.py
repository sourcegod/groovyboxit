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

from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH


def _K(note, vel=100, dur=0):
    return TapeEvent(ETYPE_KIT, note, vel, dur, 0)


def _P(note, vel=100, dur=0, bend=0):
    return TapeEvent(ETYPE_PATCH, note, vel, dur, bend)


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
    assert p._tape[(0, 0, 5)] == [TapeEvent(ETYPE_GRID, 3, 100, 0, 0)]
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
    assert (0, 0, 0) not in p._tape
    print("  set_cell(0) supprime l'event : OK")


def test_set_cell_overwrites_same_pad():
    p = Pattern()
    p.set_cell(0, 0, 0, 0, 100)
    p.set_cell(0, 0, 0, 0, 50)
    assert p.get_cell(0, 0, 0, 0) == 50
    assert len(p._tape[(0, 0, 0)]) == 1
    print("  set_cell réécrit (pas de doublon) : OK")


def test_multiple_pads_same_offset():
    p = Pattern()
    p.set_cell(0, 2, 0, 4, 80)
    p.set_cell(0, 7, 0, 4, 110)
    assert p.get_cell(0, 2, 0, 4) == 80
    assert p.get_cell(0, 7, 0, 4) == 110
    assert len(p._tape[(0, 0, 4)]) == 2
    print("  plusieurs pads au même offset : OK")


def test_set_cell_coexists_with_kp_events():
    p = Pattern()
    key = (0, 0, 4)
    p._tape[key] = [_K(60, 90), _P(61, 70, 200, 50)]
    p.set_cell(0, 3, 0, 4, 100)
    assert set(p._tape[key]) == {
        _K(60, 90), _P(61, 70, 200, 50), TapeEvent(ETYPE_GRID, 3, 100, 0, 0)
    }
    # Effacer la note G ne touche pas K/P
    p.set_cell(0, 3, 0, 4, 0)
    assert set(p._tape[key]) == {_K(60, 90), _P(61, 70, 200, 50)}
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
    key = (0, 0, 0)
    p._tape[key] = [_K(60, 90)]
    p.set_cell(0, 1, 0, 0, 100)
    p.clear_grid_pad(0, 1)
    assert p._tape[key] == [_K(60, 90)]
    print("  clear_grid_pad préserve K/P : OK")


def test_clear_grid_box_range_and_kp_preserved():
    p = Pattern()
    p.set_cell(0, 0, 0, 0, 100)
    p.set_cell(0, 1, 0, 5, 100)
    p.set_cell(0, 0, 0, 10, 100)   # hors plage
    p._tape.setdefault((0, 0, 5), []).append(_K(64, 90))
    p.clear_grid_box(tracks=[0], bars=[0], steps=range(0, 8))
    assert p.get_cell(0, 0, 0, 0) == 0
    assert p.get_cell(0, 1, 0, 5) == 0
    assert p.get_cell(0, 0, 0, 10) == 100   # hors plage : conservé
    assert any(ev.etype == ETYPE_KIT for ev in p._tape.get((0, 0, 5), []))
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
    p._tape.setdefault((0, 0, 0), []).append(_K(60, 90))
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

def test_copy_from_copies_dims_tape_bend_mod():
    src = Pattern()
    src.resize(3, 32)
    src.set_cell(0, 1, 2, 10, 90)
    src._tape.setdefault((0, 2, 10), []).append(_K(60, 90))
    src._bend_tape[0].append((5.0, 1000))
    src._mod_tape[0].append((5.0, 64))

    dst = Pattern()
    dst.copy_from(src)

    assert dst._num_bars  == 3
    assert dst._num_steps == 32
    assert dst.get_cell(0, 1, 2, 10) == 90
    assert any(ev.etype == ETYPE_KIT for ev in dst._tape[(0, 2, 10)])
    assert dst._bend_tape[0] == [(5.0, 1000)]
    assert dst._mod_tape[0]  == [(5.0, 64)]
    print("  copy_from copie dims + tape + bend + mod : OK")


def test_copy_from_is_independent_copy():
    src = Pattern()
    src.set_cell(0, 0, 0, 0, 100)
    dst = Pattern()
    dst.copy_from(src)

    src.set_cell(0, 0, 0, 0, 0)          # modifie la source après coup
    src._bend_tape[0].append((1.0, 500))

    assert dst.get_cell(0, 0, 0, 0) == 100   # dst inchangé
    assert dst._bend_tape[0] == []
    print("  copy_from produit une copie indépendante : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import inspect
    mod = sys.modules[__name__]
    for name, fn in sorted(inspect.getmembers(mod, inspect.isfunction)):
        if name.startswith("test_"):
            fn()
    print("Tous les tests test_pattern_grid_api ont réussi.")
