"""Tests — MidiEditor (Phase 6 étape 1a)."""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import Pattern, TapeEvent
from midi_editor import MidiEditor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pattern():
    """Pattern 2 mesures × 16 pas avec notes dans la grille et le tape."""
    p = Pattern()
    p.resize(2, 16)   # étend _curpattern à 2 mesures
    # Grille : piste 0, pad 0, mesure 0, pas 0 et 4
    p._curpattern[0][0][0][0]  = 100
    p._curpattern[0][0][0][4]  = 80
    # Grille : piste 0, pad 1, mesure 0, pas 0 (groupe : même offset que pad 0)
    p._curpattern[0][1][0][0]  = 90
    # Grille : piste 0, pad 2, mesure 1, pas 2
    p._curpattern[0][2][1][2]  = 70
    # Grille : piste 1, pad 3, mesure 0, pas 8
    p._curpattern[1][3][0][8]  = 100

    # Tape K/P pour le mode ALL
    p._tape[(0, 0, 0)] = [TapeEvent("K", 60, 100, 500, 0)]
    p._tape[(1, 0, 4)] = [TapeEvent("P", 64,  80, 300, 0)]

    # Automation bend/mod piste 0
    p._bend_tape[0] = [(2, 100), (6, -200)]
    p._mod_tape[0]  = [(1, 64)]
    return p


# ---------------------------------------------------------------------------
# get_note_events — source : _curpattern
# ---------------------------------------------------------------------------

def test_note_events_count_track0():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # pad0:step0, pad0:step4, pad1:step0, pad2:bar1step2 → 4 notes
    assert len(ev) == 4


def test_note_events_only_nonzero_cells():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    assert all(e["vel"] > 0 for e in ev)


def test_note_events_etype_G():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    assert all(e["etype"] == "G" for e in ev)


def test_note_events_sorted_by_offset_then_pad():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    keys = [(e["offset"], e["pad"]) for e in ev]
    assert keys == sorted(keys)


def test_note_events_fields():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    first = next(e for e in ev if e["pad"] == 0 and e["step"] == 0)
    assert first["type"]  == "note"
    assert first["track"] == 0
    assert first["bar"]   == 0
    assert first["step"]  == 0
    assert first["vel"]   == 100
    assert "dur" in first


def test_note_events_correct_offset():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # pad2, bar=1, step=2 → offset = 1*16+2 = 18
    bar1 = next(e for e in ev if e["bar"] == 1)
    assert bar1["offset"] == 18


def test_note_events_track1():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 1)
    assert len(ev) == 1
    assert ev[0]["pad"] == 3
    assert ev[0]["step"] == 8


def test_note_events_empty_track():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 7)
    assert ev == []


def test_note_events_empty_pattern():
    me = MidiEditor()
    p  = Pattern()
    assert me.get_note_events(p, 0) == []


def test_note_events_lim_left():
    me = MidiEditor()
    p  = _make_pattern()
    # À partir de offset 4
    ev = me.get_note_events(p, 0, lim_left=4)
    assert all(e["offset"] >= 4 for e in ev)


def test_note_events_lim_right():
    me = MidiEditor()
    p  = _make_pattern()
    # Jusqu'à offset 3 inclus → seulement offset 0 (2 notes)
    ev = me.get_note_events(p, 0, lim_right=3)
    assert len(ev) == 2
    assert all(e["offset"] <= 3 for e in ev)


def test_note_events_both_limits():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0, lim_left=4, lim_right=4)
    assert len(ev) == 1
    assert ev[0]["step"] == 4


def test_note_events_out_of_range_track():
    me = MidiEditor()
    p  = Pattern()
    ev = me.get_note_events(p, 99)
    assert ev == []


def test_note_events_group_at_same_offset():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # Deux notes à offset 0 : pad 0 et pad 1
    at_zero = [e for e in ev if e["offset"] == 0]
    assert len(at_zero) == 2
    pads = {e["pad"] for e in at_zero}
    assert pads == {0, 1}


# ---------------------------------------------------------------------------
# get_all_events — grille + tape + bend + mod
# ---------------------------------------------------------------------------

def test_all_events_includes_grid_notes():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_all_events(p, [0])
    grid = [e for e in ev if e.get("etype") == "G"]
    assert len(grid) == 4


def test_all_events_includes_tape():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_all_events(p, [0])
    tape = [e for e in ev if e.get("etype") in ("K", "P")]
    assert len(tape) == 1   # tape track 0 only


def test_all_events_includes_bend():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_all_events(p, [0])
    bends = [e for e in ev if e["type"] == "bend"]
    assert len(bends) == 2


def test_all_events_includes_mod():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_all_events(p, [0])
    mods = [e for e in ev if e["type"] == "mod"]
    assert len(mods) == 1


def test_all_events_multi_track():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_all_events(p, [0, 1])
    grid = [e for e in ev if e.get("etype") == "G"]
    # 4 de tr0 + 1 de tr1
    assert len(grid) == 5


def test_all_events_sorted():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_all_events(p, [0, 1])
    offsets = [e["offset"] for e in ev]
    assert offsets == sorted(offsets)


def test_all_events_empty_sel():
    me = MidiEditor()
    p  = _make_pattern()
    assert me.get_all_events(p, []) == []


# ---------------------------------------------------------------------------
# delete_event — grille (etype G)
# ---------------------------------------------------------------------------

def test_delete_grid_event():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)[0]   # premier event grille
    assert me.delete_event(p, ev) is True
    assert p._curpattern[ev["track"]][ev["pad"]][ev["bar"]][ev["step"]] == 0


def test_delete_grid_sets_cell_to_zero():
    me = MidiEditor()
    p  = _make_pattern()
    assert p._curpattern[0][0][0][0] == 100
    ev = {"type": "note", "etype": "G", "track": 0, "pad": 0, "bar": 0, "step": 0}
    me.delete_event(p, ev)
    assert p._curpattern[0][0][0][0] == 0


def test_delete_out_of_bounds_track():
    me = MidiEditor()
    p  = Pattern()
    ev = {"type": "note", "etype": "G", "track": 99, "pad": 0, "bar": 0, "step": 0}
    assert me.delete_event(p, ev) is False


def test_delete_bend_returns_false():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "bend"}
    assert me.delete_event(p, ev) is False


def test_delete_mod_returns_false():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "mod"}
    assert me.delete_event(p, ev) is False


# ---------------------------------------------------------------------------
# edit_grid_note
# ---------------------------------------------------------------------------

def test_edit_grid_velocity():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": "G", "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    result = me.edit_grid_note(p, ev, new_vel=50)
    assert result is not None
    assert result["vel"] == 50
    assert p._curpattern[0][0][0][0] == 50


def test_edit_grid_move_position():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": "G", "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    result = me.edit_grid_note(p, ev, new_bar=1, new_step=3)
    assert result is not None
    assert result["bar"]  == 1
    assert result["step"] == 3
    assert p._curpattern[0][0][0][0] == 0     # ancienne cellule effacée
    assert p._curpattern[0][0][1][3] == 100   # nouvelle cellule remplie


def test_edit_grid_change_pad():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": "G", "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    result = me.edit_grid_note(p, ev, new_pad=5)
    assert result is not None
    assert result["pad"] == 5
    assert p._curpattern[0][0][0][0] == 0   # ancien pad effacé
    assert p._curpattern[0][5][0][0] == 100 # nouveau pad rempli


def test_edit_grid_updated_offset():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": "G", "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    result = me.edit_grid_note(p, ev, new_bar=1, new_step=4)
    assert result["offset"] == 1 * p._num_steps + 4


def test_edit_grid_no_change():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": "G", "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    result = me.edit_grid_note(p, ev)
    assert result["vel"] == 100
    assert p._curpattern[0][0][0][0] == 100


def test_edit_grid_wrong_etype_returns_none():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": "K", "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    assert me.edit_grid_note(p, ev) is None


def test_edit_grid_out_of_bounds_returns_none():
    me = MidiEditor()
    p  = Pattern()
    ev = {"type": "note", "etype": "G", "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100,
          "new_bar": 999}
    result = me.edit_grid_note(p, ev, new_bar=999)
    assert result is None


# ---------------------------------------------------------------------------
# Constantes et état initial
# ---------------------------------------------------------------------------

def test_view_constants():
    assert MidiEditor.VIEW_NOTES == 0
    assert MidiEditor.VIEW_ALL   == 1


def test_default_state():
    me = MidiEditor()
    assert me._view_mode == MidiEditor.VIEW_NOTES
    assert me._cur_idx   == 0
