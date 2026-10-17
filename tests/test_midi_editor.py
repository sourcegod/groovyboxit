"""Tests — MidiEditor (Phase 6 étapes 1a–3c)."""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH, ETYPE_CC, ETYPE_PGM, ETYPE_BEND
from tape_test_utils import tape_at, has_tape_at, set_tape_at, add_tape_at
from midi.midi_editor import MidiEditor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pattern():
    """Pattern 2 mesures × 16 pas avec notes dans la grille et le tape."""
    p = Pattern()
    p.resize(2, 16)   # étend la grille à 2 mesures
    # Grille : piste 0, pad 0, mesure 0, pas 0 et 4
    p.set_cell(0, 0, 0, 0, 100)
    p.set_cell(0, 0, 0, 4, 80)
    # Grille : piste 0, pad 1, mesure 0, pas 0 (groupe : même offset que pad 0)
    p.set_cell(0, 1, 0, 0, 90)
    # Grille : piste 0, pad 2, mesure 1, pas 2
    p.set_cell(0, 2, 1, 2, 70)
    # Grille : piste 1, pad 3, mesure 0, pas 8
    p.set_cell(1, 3, 0, 8, 100)

    # Tape K/P pour le mode ALL (ajoutés aux entrées G déjà posées par set_cell)
    add_tape_at(p, 0, 0, 0, TapeEvent(ETYPE_KIT, dur=500, payload={"note": 60, "vel": 100}))
    add_tape_at(p, 1, 0, 4, TapeEvent(ETYPE_PATCH, dur=300, payload={"note": 64, "vel": 80}))

    # Automation bend piste 0 — ETYPE_BEND dans _tape depuis la Phase 7
    # étape 6d1 (_mod_tape supprimé en 5h, _bend_tape plus lu par l'éditeur)
    p._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": 100},  time=2))
    p._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": -200}, time=6))
    return p


# ---------------------------------------------------------------------------
# get_note_events — source unifiée : _tape (etype G/K/P)
# ---------------------------------------------------------------------------

def test_note_events_count_track0():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # Grille : pad0:step0, pad0:step4, pad1:step0, pad2:bar1step2 → 4
    # Tape K : (0,0,0) → 1
    assert len(ev) == 5


def test_note_events_only_nonzero_cells():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    assert all(e["vel"] > 0 for e in ev)


def test_note_events_etypes():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # Grille → G, tape K/P également inclus
    assert all(e["etype"] in (ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH) for e in ev)
    grid = [e for e in ev if e["etype"] == ETYPE_GRID]
    tape = [e for e in ev if e["etype"] in (ETYPE_KIT, ETYPE_PATCH)]
    assert len(grid) == 4
    assert len(tape) == 1


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
    # Grille : pad3 step8 → 1 ; tape P : note64 step4 → 1
    assert len(ev) == 2
    grid = next(e for e in ev if e["etype"] == ETYPE_GRID)
    tape = next(e for e in ev if e["etype"] == ETYPE_PATCH)
    assert grid["pad"] == 3 and grid["step"] == 8
    assert tape["pad"] == 64 and tape["step"] == 4


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
    # Jusqu'à offset 3 inclus → offset 0 : pad0(G), pad1(G), K(note=60) → 3 notes
    ev = me.get_note_events(p, 0, lim_right=3)
    assert len(ev) == 3
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
    # Offset 0 : pad0(G), pad1(G), tape K note=60 → 3 événements
    at_zero = [e for e in ev if e["offset"] == 0]
    assert len(at_zero) == 3
    grid_pads = {e["pad"] for e in at_zero if e["etype"] == ETYPE_GRID}
    assert grid_pads == {0, 1}


# ---------------------------------------------------------------------------
# get_all_events — grille + tape + bend + mod
# ---------------------------------------------------------------------------

def test_all_events_includes_grid_notes():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_all_events(p, [0])
    grid = [e for e in ev if e.get("etype") == ETYPE_GRID]
    assert len(grid) == 4


def test_all_events_includes_tape():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_all_events(p, [0])
    tape = [e for e in ev if e.get("etype") in (ETYPE_KIT, ETYPE_PATCH)]
    assert len(tape) == 1   # tape track 0 only


def test_all_events_includes_bend():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_all_events(p, [0])
    bends = [e for e in ev if e["type"] == "bend"]
    assert len(bends) == 2
    assert [(e["offset"], e["value"]) for e in bends] == [(2, 100), (6, -200)]
    assert all(e["etype"] == ETYPE_BEND and e["channel"] == 0 for e in bends)


def test_bend_excluded_from_note_events():
    me = MidiEditor()
    p  = _make_pattern()
    assert all(e["type"] == "note" for e in me.get_note_events(p, 0))


def test_all_events_bend_respects_limiters():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_all_events(p, [0], lim_left=4, lim_right=10)
    assert [e["value"] for e in ev if e["type"] == "bend"] == [-200]


def test_all_events_no_longer_includes_mod_type():
    """Phase 7 étape 5f/5h : "mod" n'est plus un type d'événement réel —
    get_all_events ne le produit plus (CC#1 remonte comme "cc")."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_all_events(p, [0])
    assert [e for e in ev if e["type"] == "mod"] == []


def test_all_events_cc1_shows_as_cc_not_mod():
    me = MidiEditor()
    p  = _make_pattern()
    add_tape_at(p, 0, 0, 1, TapeEvent(ETYPE_CC, channel=0, payload={"cc_num": 1, "value": 64}))
    ev  = me.get_all_events(p, [0])
    cc1 = [e for e in ev if e["type"] == "cc" and e["cc_num"] == 1]
    assert len(cc1) == 1
    assert cc1[0]["value"] == 64


def test_all_events_multi_track():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_all_events(p, [0, 1])
    grid = [e for e in ev if e.get("etype") == ETYPE_GRID]
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
    assert p.get_cell(ev["track"], ev["pad"], ev["bar"], ev["step"]) == 0


def test_delete_grid_sets_cell_to_zero():
    me = MidiEditor()
    p  = _make_pattern()
    assert p.get_cell(0, 0, 0, 0) == 100
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0, "step": 0}
    me.delete_event(p, ev)
    assert p.get_cell(0, 0, 0, 0) == 0


def test_delete_out_of_bounds_track():
    me = MidiEditor()
    p  = Pattern()
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 99, "pad": 0, "bar": 0, "step": 0}
    assert me.delete_event(p, ev) is False


def test_delete_bend_not_found_returns_false():
    """Phase 7 étape 6d1 : un bend est supprimable (dans _tape), mais un
    event_idx qui ne résout rien est refusé sans rien toucher."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = dict(_bend_ev(p), event_idx=99)
    assert me.delete_event(p, ev) is False
    assert _bend_points(p) == [(2, 100), (6, -200)]


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
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    result = me.edit_grid_note(p, ev, new_vel=50)
    assert result is not None
    assert result["vel"] == 50
    assert p.get_cell(0, 0, 0, 0) == 50


def test_edit_grid_move_position():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    result = me.edit_grid_note(p, ev, new_bar=1, new_step=3)
    assert result is not None
    assert result["bar"]  == 1
    assert result["step"] == 3
    assert p.get_cell(0, 0, 0, 0) == 0     # ancienne cellule effacée
    assert p.get_cell(0, 0, 1, 3) == 100   # nouvelle cellule remplie


def test_edit_grid_change_pad():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    result = me.edit_grid_note(p, ev, new_pad=5)
    assert result is not None
    assert result["pad"] == 5
    assert p.get_cell(0, 0, 0, 0) == 0   # ancien pad effacé
    assert p.get_cell(0, 5, 0, 0) == 100 # nouveau pad rempli


def test_edit_grid_updated_offset():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    result = me.edit_grid_note(p, ev, new_bar=1, new_step=4)
    assert result["offset"] == 1 * p._num_steps + 4


def test_edit_grid_no_change():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    result = me.edit_grid_note(p, ev)
    assert result["vel"] == 100
    assert p.get_cell(0, 0, 0, 0) == 100


def test_edit_grid_wrong_etype_returns_none():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": ETYPE_KIT, "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    assert me.edit_grid_note(p, ev) is None


def test_edit_grid_out_of_bounds_returns_none():
    me = MidiEditor()
    p  = Pattern()
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100,
          "new_bar": 999}
    result = me.edit_grid_note(p, ev, new_bar=999)
    assert result is None


# ---------------------------------------------------------------------------
# Canal MIDI (Phase 7 étape 1i)
# ---------------------------------------------------------------------------

def test_edit_grid_channel_preserved_by_default():
    me = MidiEditor()
    p  = Pattern()
    p.set_cell(0, 0, 0, 0, 100, channel=5)
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0, "step": 0,
          "vel": 100, "channel": 5}
    result = me.edit_grid_note(p, ev, new_vel=50)
    assert result["channel"] == 5
    assert tape_at(p, 0, 0, 0)[0].channel == 5

def test_edit_grid_channel_can_be_changed():
    me = MidiEditor()
    p  = Pattern()
    p.set_cell(0, 0, 0, 0, 100, channel=5)
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0, "step": 0,
          "vel": 100, "channel": 5}
    result = me.edit_grid_note(p, ev, new_channel=9)
    assert result["channel"] == 9
    assert tape_at(p, 0, 0, 0)[0].channel == 9

def test_edit_tape_note_basic():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    kit_ev = next(e for e in ev if e["etype"] == ETYPE_KIT)
    result = me.edit_tape_note(p, kit_ev, new_vel=42, new_dur=333)
    assert result is not None
    assert result["vel"] == 42
    assert result["dur"] == 333
    assert result["etype"] == ETYPE_KIT

def test_edit_tape_note_channel_preserved_by_default():
    me = MidiEditor()
    p  = Pattern()
    p._tape[0].append(TapeEvent(ETYPE_KIT, dur=500, channel=6, payload={"note": 60, "vel": 100}, time=0))
    ev = me.get_note_events(p, 0)[0]
    result = me.edit_tape_note(p, ev, new_vel=80)
    assert result["channel"] == 6

def test_edit_tape_note_channel_can_be_changed():
    me = MidiEditor()
    p  = Pattern()
    p._tape[0].append(TapeEvent(ETYPE_PATCH, dur=500, channel=6, payload={"note": 60, "vel": 100}, time=0))
    ev = me.get_note_events(p, 0)[0]
    result = me.edit_tape_note(p, ev, new_channel=2)
    assert result["channel"] == 2
    assert "bend" not in result        # plus de bend par note (Phase 7 étape 7h1)
    assert p._tape[0][0].payload == {"note": 60, "vel": 100}

def test_get_note_events_exposes_channel():
    p = Pattern()
    p.set_cell(0, 0, 0, 0, 100, channel=4)
    me = MidiEditor()
    ev = me.get_note_events(p, 0)[0]
    assert ev["channel"] == 4

def test_duplicate_event_grid_preserves_channel():
    me = MidiEditor()
    p  = Pattern()
    p.set_cell(0, 0, 0, 0, 100, channel=3)
    ev = me.get_note_events(p, 0)[0]
    result = me.duplicate_event(p, ev)
    assert result["channel"] == 3

def test_duplicate_event_tape_preserves_channel():
    me = MidiEditor()
    p  = Pattern()
    p._tape[0].append(TapeEvent(ETYPE_KIT, dur=500, channel=8, payload={"note": 60, "vel": 100}, time=0))
    ev = me.get_note_events(p, 0)[0]
    result = me.duplicate_event(p, ev)
    assert result["channel"] == 8

def test_insert_note_grid_stores_channel():
    me = MidiEditor()
    p  = Pattern()
    result = me.insert_note(p, ETYPE_GRID, 0, 0, 2, 5, vel=90, channel=11)
    assert result["channel"] == 11
    assert tape_at(p, 0, 0, 2)[0].channel == 11

def test_insert_note_patch_stores_channel():
    me = MidiEditor()
    p  = Pattern()
    result = me.insert_note(p, ETYPE_PATCH, 0, 0, 2, 64, vel=100, dur=250, channel=11)
    assert result["channel"] == 11
    assert tape_at(p, 0, 0, 2)[0].channel == 11

def test_insert_note_default_channel_zero():
    me = MidiEditor()
    p  = Pattern()
    result = me.insert_note(p, ETYPE_GRID, 0, 0, 0, 5)
    assert result["channel"] == 0


# ---------------------------------------------------------------------------
# edit_bend_event (edit_mod_event a disparu en 5f — CC#1/Mod Wheel s'édite
# désormais via edit_cc_event comme n'importe quel CC générique, voir
# test_edit_cc_event_* plus bas, qui couvrent déjà cette logique)
# ---------------------------------------------------------------------------

def _bend_ev(p, offset=2, value=100):
    """Relit l'event_info d'un bend depuis le pattern (event_idx à jour)."""
    me = MidiEditor()
    return [e for e in me.get_cc_pgm_events(p, 0)
            if e["type"] == "bend" and e["offset"] == offset and e["value"] == value][0]


def _bend_points(p, track=0):
    return sorted((e.time, e.payload["value"]) for e in p._tape[track] if e.etype == ETYPE_BEND)


def test_edit_bend_value():
    me = MidiEditor()
    p  = _make_pattern()
    ev = _bend_ev(p)
    result = me.edit_bend_event(p, ev, new_value=500)
    assert result is not None
    assert result["value"] == 500
    assert result["etype"] == ETYPE_BEND
    assert _bend_points(p) == [(2, 500), (6, -200)]


def test_edit_bend_move_position():
    me = MidiEditor()
    p  = _make_pattern()
    ev = _bend_ev(p)
    result = me.edit_bend_event(p, ev, new_bar=1, new_step=3)
    assert result["bar"]    == 1
    assert result["step"]   == 3
    assert result["offset"] == 1 * p._num_steps + 3
    assert _bend_points(p) == [(6, -200), (result["offset"], 100)]


def test_edit_bend_value_keeps_fractional_time():
    """Phase 7 étape 6d1 : valeur seule → time fractionnaire conservé
    (l'ancienne version sur _bend_tape le ramenait au pas entier)."""
    me = MidiEditor()
    p  = Pattern()
    p._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": 10}, time=5.37))
    ev = me.get_cc_pgm_events(p, 0)[0]
    res = me.edit_bend_event(p, ev, new_value=20)
    assert res["offset"] == 5.37
    assert _bend_points(p) == [(5.37, 20)]


def test_edit_bend_move_lands_on_integer_step():
    me = MidiEditor()
    p  = Pattern()
    p._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": 10}, time=5.37))
    ev = me.get_cc_pgm_events(p, 0)[0]
    me.edit_bend_event(p, ev, new_step=9)
    assert _bend_points(p) == [(9, 10)]


def test_edit_bend_keeps_channel():
    me = MidiEditor()
    p  = Pattern()
    p._tape[0].append(TapeEvent(ETYPE_BEND, channel=4, payload={"value": 10}, time=1))
    res = me.edit_bend_event(p, me.get_cc_pgm_events(p, 0)[0], new_value=-10)
    assert res["channel"] == 4
    assert [e.channel for e in p._tape[0]] == [4]


def test_edit_bend_value_clamped():
    me = MidiEditor()
    p  = _make_pattern()
    ev = _bend_ev(p)
    result = me.edit_bend_event(p, ev, new_value=999999)
    assert result["value"] == 8191
    result2 = me.edit_bend_event(p, result, new_value=-999999)
    assert result2["value"] == -8192


def test_edit_bend_out_of_bounds_returns_none():
    me = MidiEditor()
    p  = _make_pattern()
    ev = _bend_ev(p)
    assert me.edit_bend_event(p, ev, new_bar=999) is None
    assert (2, 100) in _bend_points(p)   # inchangé


def test_edit_bend_not_found_returns_none():
    me = MidiEditor()
    p  = _make_pattern()
    ev = dict(_bend_ev(p), event_idx=99)
    assert me.edit_bend_event(p, ev, new_value=50) is None
    assert _bend_points(p) == [(2, 100), (6, -200)]


# ---------------------------------------------------------------------------
# move_event (étape 7d — Numpad 4/6)
# ---------------------------------------------------------------------------

def test_move_event_grid_forward_within_pattern():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    result = me.move_event(p, ev, 8)
    assert result is not None
    assert (result["bar"], result["step"]) == (0, 8)
    assert p.get_cell(0, 0, 0, 0) == 0
    assert p.get_cell(0, 0, 0, 8) == 100


def test_move_event_grid_backward():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 2, "bar": 1, "step": 2, "vel": 70}
    result = me.move_event(p, ev, -2)
    assert result is not None
    assert (result["bar"], result["step"]) == (1, 0)


def test_move_event_backward_past_start_returns_none():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    assert me.move_event(p, ev, -1) is None
    assert p.get_cell(0, 0, 0, 0) == 100   # inchangé


def test_move_event_extends_pattern_when_past_end():
    me = MidiEditor()
    p  = Pattern()   # 1 mesure × 16 pas par défaut
    p.set_cell(0, 0, 0, 12, 100)
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0, "step": 12, "vel": 100}
    assert p._num_bars == 1
    result = me.move_event(p, ev, 8)   # offset 12 + 8 = 20 → bar 1, step 4
    assert result is not None
    assert p._num_bars == 2
    assert (result["bar"], result["step"]) == (1, 4)
    assert p.get_cell(0, 0, 1, 4) == 100


def test_move_event_tape_note():
    me = MidiEditor()
    p  = Pattern()
    p.resize(2, 16)
    add_tape_at(p, 0, 0, 4, TapeEvent(ETYPE_PATCH, dur=300, payload={"note": 64, "vel": 100}))
    ev = {"type": "note", "etype": ETYPE_PATCH, "track": 0, "bar": 0, "step": 4,
          "pad": 64, "vel": 100, "dur": 300, "event_idx": 0}
    result = me.move_event(p, ev, 4)
    assert result is not None
    assert (result["bar"], result["step"]) == (0, 8)
    assert not has_tape_at(p, 0, 0, 4)
    assert tape_at(p, 0, 0, 8)[0].payload.get("note") == 64


# ---------------------------------------------------------------------------
# change_duration (étape 7d — Numpad 1/3)
# ---------------------------------------------------------------------------

def test_change_duration_grid_lengthens_from_voice_default():
    """Phase 7 étape 1k : Numpad1/3 fonctionne désormais aussi sur GRID —
    la durée devient propre à cette occurrence (dur_override), elle prime
    sur voice_manager.get_duration_ms(pad)."""
    me = MidiEditor()
    p  = _make_pattern()   # voix par défaut : duration_ms=500
    ev = me.get_note_events(p, 0)[0]
    assert ev["etype"] == ETYPE_GRID and ev["pad"] == 0
    assert ev["dur"] == 500
    assert ev["dur_override"] == 0
    result = me.change_duration(p, ev, 50)
    assert result is not None
    assert result["dur"] == 550
    assert result["dur_override"] == 550

def test_change_duration_grid_no_change_returns_none():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)[0]
    assert me.change_duration(p, ev, 0) is None

def test_change_duration_grid_override_persists_after_other_edits():
    """Une fois posé, l'override de durée doit survivre à un edit_grid_note
    qui ne le touche pas explicitement (vélocité, canal, déplacement...)."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)[0]
    overridden = me.change_duration(p, ev, 50)
    moved = me.edit_grid_note(p, overridden, new_vel=77, new_channel=4)
    assert moved["dur"]          == 550
    assert moved["dur_override"] == 550
    assert moved["vel"]          == 77
    assert moved["channel"]      == 4

def test_edit_grid_note_new_dur_sets_override():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)[0]
    result = me.edit_grid_note(p, ev, new_dur=1200)
    assert result["dur"]          == 1200
    assert result["dur_override"] == 1200

def test_duplicate_event_grid_preserves_dur_override():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)[0]
    overridden = me.change_duration(p, ev, 50)
    dup = me.duplicate_event(p, overridden)
    assert dup["dur"]          == 550
    assert dup["dur_override"] == 550

def test_insert_note_grid_never_sets_dur_override():
    """Contrairement à l'édition, l'insertion GRID ne pose jamais d'override
    (comportement inchangé : toujours la voix, dur passé pour KIT/PATCH
    uniquement — voir insert_note)."""
    me = MidiEditor()
    p  = _make_pattern()
    result = me.insert_note(p, ETYPE_GRID, 0, 1, 0, 5, vel=90, dur=1234)
    assert result["dur_override"] == 0


def test_change_duration_lengthen_tape_note():
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 0, TapeEvent(ETYPE_PATCH, dur=300, payload={"note": 64, "vel": 100}))
    ev = {"type": "note", "etype": ETYPE_PATCH, "track": 0, "bar": 0, "step": 0,
          "pad": 64, "vel": 100, "dur": 300, "event_idx": 0}
    result = me.change_duration(p, ev, 50)
    assert result is not None
    assert result["dur"] == 350


def test_change_duration_shorten_clamped_to_10ms():
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 0, TapeEvent(ETYPE_KIT, dur=15, payload={"note": 3, "vel": 100}))
    ev = {"type": "note", "etype": ETYPE_KIT, "track": 0, "bar": 0, "step": 0,
          "pad": 3, "vel": 100, "dur": 15, "event_idx": 0}
    result = me.change_duration(p, ev, -50)
    assert result["dur"] == 10


def test_change_duration_no_change_at_floor_returns_none():
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 0, TapeEvent(ETYPE_KIT, dur=10, payload={"note": 3, "vel": 100}))
    ev = {"type": "note", "etype": ETYPE_KIT, "track": 0, "bar": 0, "step": 0,
          "pad": 3, "vel": 100, "dur": 10, "event_idx": 0}
    assert me.change_duration(p, ev, -50) is None


# ---------------------------------------------------------------------------
# change_velocity (étape 7d — Numpad 7/9)
# ---------------------------------------------------------------------------

def test_change_velocity_increase_grid():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    result = me.change_velocity(p, ev, 1)
    assert result["vel"] == 101
    assert p.get_cell(0, 0, 0, 0) == 101


def test_change_velocity_decrease_tape():
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 0, TapeEvent(ETYPE_PATCH, dur=300, payload={"note": 64, "vel": 50}))
    ev = {"type": "note", "etype": ETYPE_PATCH, "track": 0, "bar": 0, "step": 0,
          "pad": 64, "vel": 50, "dur": 300, "event_idx": 0}
    result = me.change_velocity(p, ev, -1)
    assert result["vel"] == 49


def test_change_velocity_clamped_at_127_returns_none():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 127}
    assert me.change_velocity(p, ev, 1) is None


def test_change_velocity_clamped_at_1_returns_none():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 1}
    assert me.change_velocity(p, ev, -1) is None


# ---------------------------------------------------------------------------
# shift_pitch (étape 7d — Numpad 2/8, Ctrl+Numpad 2/8)
# ---------------------------------------------------------------------------

def test_shift_pitch_grid_semitone():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    result = me.shift_pitch(p, ev, 1)
    assert result["pad"] == 1
    assert p.get_cell(0, 1, 0, 0) == 100
    assert p.get_cell(0, 0, 0, 0) == 0


def test_shift_pitch_grid_clamped_to_num_pads():
    me = MidiEditor()
    p  = Pattern()
    p.set_cell(0, p._num_pads - 1, 0, 0, 100)
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": p._num_pads - 1,
          "bar": 0, "step": 0, "vel": 100}
    assert me.shift_pitch(p, ev, 1) is None


def test_shift_pitch_grid_octave_clamped_to_num_pads():
    me = MidiEditor()
    p  = Pattern()
    p.set_cell(0, 10, 0, 0, 100)
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 10, "bar": 0, "step": 0, "vel": 100}
    result = me.shift_pitch(p, ev, 12)   # 10 + 12 = 22, borné à num_pads-1 = 15
    assert result["pad"] == p._num_pads - 1


def test_shift_pitch_patch_semitone():
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 0, TapeEvent(ETYPE_PATCH, dur=300, payload={"note": 64, "vel": 100}))
    ev = {"type": "note", "etype": ETYPE_PATCH, "track": 0, "bar": 0, "step": 0,
          "pad": 64, "vel": 100, "dur": 300, "event_idx": 0}
    result = me.shift_pitch(p, ev, 1)
    assert result["pad"] == 65


def test_shift_pitch_patch_octave():
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 0, TapeEvent(ETYPE_PATCH, dur=300, payload={"note": 64, "vel": 100}))
    ev = {"type": "note", "etype": ETYPE_PATCH, "track": 0, "bar": 0, "step": 0,
          "pad": 64, "vel": 100, "dur": 300, "event_idx": 0}
    result = me.shift_pitch(p, ev, -12)
    assert result["pad"] == 52


def test_shift_pitch_patch_clamped_to_127():
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 0, TapeEvent(ETYPE_PATCH, dur=300, payload={"note": 127, "vel": 100}))
    ev = {"type": "note", "etype": ETYPE_PATCH, "track": 0, "bar": 0, "step": 0,
          "pad": 127, "vel": 100, "dur": 300, "event_idx": 0}
    assert me.shift_pitch(p, ev, 1) is None


def test_shift_pitch_kit_goes_beyond_num_pads():
    # KIT est une note MIDI brute en aval (TrackRouter.on_kit_tape), pas un
    # index de pad — ne doit pas être borné à num_pads-1 comme GRID.
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 0, TapeEvent(ETYPE_KIT, dur=500, payload={"note": p._num_pads - 1, "vel": 100}))
    ev = {"type": "note", "etype": ETYPE_KIT, "track": 0, "bar": 0, "step": 0,
          "pad": p._num_pads - 1, "vel": 100, "dur": 500, "event_idx": 0}
    result = me.shift_pitch(p, ev, 1)
    assert result["pad"] == p._num_pads


def test_shift_pitch_kit_clamped_to_127():
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 0, TapeEvent(ETYPE_KIT, dur=500, payload={"note": 127, "vel": 100}))
    ev = {"type": "note", "etype": ETYPE_KIT, "track": 0, "bar": 0, "step": 0,
          "pad": 127, "vel": 100, "dur": 500, "event_idx": 0}
    assert me.shift_pitch(p, ev, 1) is None


# ---------------------------------------------------------------------------
# group_indices
# ---------------------------------------------------------------------------

def test_group_indices_single_note():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # pad0:step4 est seul à offset 4
    idx = next(i for i, e in enumerate(ev) if e["step"] == 4 and e["pad"] == 0)
    assert me.group_indices(ev, idx) == [idx]


def test_group_indices_chord():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # offset 0 : pad0(G), pad1(G), tape K(note=60) → 3 événements
    at_zero = [i for i, e in enumerate(ev) if e["offset"] == 0]
    assert len(at_zero) == 3
    for i in at_zero:
        assert me.group_indices(ev, i) == at_zero


def test_group_indices_empty():
    me = MidiEditor()
    assert me.group_indices([], 0) == []


def test_group_indices_out_of_range():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    assert me.group_indices(ev, 999) == []


# ---------------------------------------------------------------------------
# first_of_next_group
# ---------------------------------------------------------------------------

def test_first_of_next_group_basic():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # Premier groupe à offset 0, le suivant commence à offset 4
    idx0 = next(i for i, e in enumerate(ev) if e["offset"] == 0)
    nxt  = me.first_of_next_group(ev, idx0)
    assert nxt >= 0
    assert ev[nxt]["offset"] > ev[idx0]["offset"]


def test_first_of_next_group_from_chord():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # Depuis le 2e élément du groupe 0 (pad1 à offset 0)
    at_zero = [i for i, e in enumerate(ev) if e["offset"] == 0]
    nxt = me.first_of_next_group(ev, at_zero[-1])
    assert ev[nxt]["offset"] > 0


def test_first_of_next_group_at_last():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    last = len(ev) - 1
    assert me.first_of_next_group(ev, last) == -1


def test_first_of_next_group_empty():
    me = MidiEditor()
    assert me.first_of_next_group([], 0) == -1


# ---------------------------------------------------------------------------
# first_of_prev_group
# ---------------------------------------------------------------------------

def test_first_of_prev_group_basic():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # Trouver un index dans le groupe à offset 4
    idx4 = next(i for i, e in enumerate(ev) if e["offset"] == 4)
    prv  = me.first_of_prev_group(ev, idx4)
    assert prv >= 0
    assert ev[prv]["offset"] < ev[idx4]["offset"]


def test_first_of_prev_group_returns_first_of_group():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # Depuis offset 4, le groupe précédent (offset 0) a 2 notes → doit retourner index 0
    idx4 = next(i for i, e in enumerate(ev) if e["offset"] == 4)
    prv  = me.first_of_prev_group(ev, idx4)
    assert ev[prv]["offset"] == 0
    # Doit être le premier élément du groupe 0
    group0 = me.group_indices(ev, prv)
    assert prv == group0[0]


def test_first_of_prev_group_at_first():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    assert me.first_of_prev_group(ev, 0) == -1


def test_first_of_prev_group_empty():
    me = MidiEditor()
    assert me.first_of_prev_group([], 0) == -1


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


# ---------------------------------------------------------------------------
# Navigation séquentielle (simule ←/→ successifs)
# ---------------------------------------------------------------------------

def test_nav_right_sequence():
    """Trois appuis → avance note par note à travers les groupes."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    cur = 0
    visited_offsets = [ev[cur]["offset"]]
    for _ in range(3):
        nxt = me.first_of_next_group(ev, cur)
        if nxt < 0:
            break
        cur = nxt
        visited_offsets.append(ev[cur]["offset"])
    assert visited_offsets == sorted(set(visited_offsets))


def test_nav_left_sequence():
    """Depuis le dernier groupe, ← revient en arrière à chaque appui."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # Partir du dernier événement
    cur = len(ev) - 1
    last_offset = ev[cur]["offset"]
    prv = me.first_of_prev_group(ev, cur)
    assert prv >= 0
    assert ev[prv]["offset"] < last_offset


def test_nav_right_then_left_returns_to_start():
    """→ puis ← revient au premier groupe."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    nxt = me.first_of_next_group(ev, 0)
    assert nxt >= 0
    prv = me.first_of_prev_group(ev, nxt)
    assert ev[prv]["offset"] == ev[0]["offset"]


# ---------------------------------------------------------------------------
# group_entry — comportement ↑/↓ simulé via group_indices
# ---------------------------------------------------------------------------

def test_group_entry_first_note_is_lowest_index():
    """Quand on arrive sur un groupe, group[0] est le premier à jouer."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    nxt = me.first_of_next_group(ev, 0)   # groupe à offset 0 est déjà le début
    # Simuler ←/→ arrivant sur un groupe : first_of_next_group donne le 1er index
    group = me.group_indices(ev, nxt)
    assert group[0] == nxt            # first_of_*_group renvoie toujours group[0]


def test_group_entry_down_plays_first_then_second():
    """Séquence group_entry : 1er ↓ → group[0], 2e ↓ → group[1]."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # Groupe à offset 0 : 3 notes
    group = me.group_indices(ev, 0)
    assert len(group) >= 2
    # 1er appui ↓ (group_entry=True) → joue group[0], cur reste group[0]
    target_first = group[0]
    # 2e appui ↓ (group_entry=False) → avance à group[1]
    pos = group.index(target_first)
    target_second = group[pos + 1]
    assert ev[target_second]["offset"] == ev[target_first]["offset"]   # même accord
    assert target_second > target_first


def test_group_entry_up_plays_first_note():
    """↑ en group_entry joue aussi group[0] (même comportement que ↓)."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    group = me.group_indices(ev, 0)
    assert len(group) >= 2
    # Simuler group_entry=True, ↑ → group[0]
    target = group[0]
    assert ev[target]["offset"] == 0


def test_group_entry_single_note_group():
    """Sur un groupe d'une seule note, group_entry n'a pas d'effet visible."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # offset 4 : une seule note (pad0)
    idx4 = next(i for i, e in enumerate(ev) if e["offset"] == 4)
    group = me.group_indices(ev, idx4)
    assert len(group) == 1
    # group_entry=True → target = group[0] = idx4 (inchangé)
    assert group[0] == idx4


# ---------------------------------------------------------------------------
# first_of_next/prev_group depuis l'intérieur d'un accord
# ---------------------------------------------------------------------------

def test_next_group_from_second_note_in_chord():
    """→ depuis la 2e note d'un accord saute bien au groupe suivant."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    group0 = me.group_indices(ev, 0)
    assert len(group0) >= 2
    # Depuis la 2e note du groupe 0
    nxt_from_second = me.first_of_next_group(ev, group0[1])
    nxt_from_first  = me.first_of_next_group(ev, group0[0])
    # Les deux doivent atterrir sur le même prochain groupe
    assert nxt_from_second == nxt_from_first


def test_prev_group_from_second_note_in_chord():
    """← depuis la 2e note d'un accord revient au groupe précédent."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # offset 4 a un groupe précédent à offset 0
    idx4  = next(i for i, e in enumerate(ev) if e["offset"] == 4)
    group = me.group_indices(ev, 0)
    # Depuis la 2e note du groupe à offset 0, ← doit renvoyer -1 (premier groupe)
    prv = me.first_of_prev_group(ev, group[0])
    assert prv == -1
    # Depuis offset 4, ← revient à group[0]
    prv4 = me.first_of_prev_group(ev, idx4)
    assert ev[prv4]["offset"] == 0
    assert prv4 == group[0]


# ---------------------------------------------------------------------------
# Sélection — toggle_group_selection (logique simulée)
# ---------------------------------------------------------------------------

def _sim_toggle_group(selected, events, me, idx):
    """Simule _toggle_group_selection sur un set Python."""
    group = me.group_indices(events, idx)
    if all(i in selected for i in group):
        for i in group:
            selected.discard(i)
    else:
        for i in group:
            selected.add(i)


def test_toggle_group_selects_all():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    sel = set()
    # groupe à offset 0 : 3 notes
    _sim_toggle_group(sel, ev, me, 0)
    group0 = me.group_indices(ev, 0)
    assert sel == set(group0)


def test_toggle_group_deselects_when_all_selected():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    sel = set()
    _sim_toggle_group(sel, ev, me, 0)   # sélectionner
    _sim_toggle_group(sel, ev, me, 0)   # désélectionner
    assert sel == set()


def test_toggle_group_partial_becomes_full():
    """Si une partie du groupe est sélectionnée, le toggle complète la sélection."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    sel = set()
    group0 = me.group_indices(ev, 0)
    sel.add(group0[0])                  # sélection partielle
    _sim_toggle_group(sel, ev, me, 0)   # doit sélectionner tout
    assert sel == set(group0)


def test_toggle_group_single_note():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    sel = set()
    idx4 = next(i for i, e in enumerate(ev) if e["offset"] == 4)
    _sim_toggle_group(sel, ev, me, idx4)
    assert sel == {idx4}
    _sim_toggle_group(sel, ev, me, idx4)
    assert sel == set()


# ---------------------------------------------------------------------------
# Sélection — select_all / deselect_all
# ---------------------------------------------------------------------------

def test_select_all_covers_all_indices():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    sel = set(range(len(ev)))
    assert sel == set(range(len(ev)))


def test_deselect_all_clears():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    sel = set(range(len(ev)))
    sel.clear()
    assert sel == set()


# ---------------------------------------------------------------------------
# Sélection — toggle_note (individuelle)
# ---------------------------------------------------------------------------

def test_toggle_note_adds():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    sel = set()
    sel.add(0)
    assert 0 in sel


def test_toggle_note_removes():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    sel = {0, 1}
    sel.discard(0)
    assert 0 not in sel
    assert 1 in sel


# ---------------------------------------------------------------------------
# Sélection — delete simulé (logique delete_event)
# ---------------------------------------------------------------------------

def test_delete_selected_removes_grid_notes():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # Sélectionner les notes G à offset 0
    group0 = [i for i in me.group_indices(ev, 0) if ev[i]["etype"] == ETYPE_GRID]
    for idx in sorted(group0, reverse=True):
        assert me.delete_event(p, ev[idx]) is True
    # Vérifier que les cellules sont à 0
    assert p.get_cell(0, 0, 0, 0) == 0
    assert p.get_cell(0, 1, 0, 0) == 0


def test_delete_group_removes_all_at_offset():
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    group0 = me.group_indices(ev, 0)
    # Supprimer uniquement les notes G du groupe
    g_notes = [i for i in group0 if ev[i]["etype"] == ETYPE_GRID]
    for idx in sorted(g_notes, reverse=True):
        me.delete_event(p, ev[idx])
    ev2 = me.get_note_events(p, 0)
    # Plus de notes G à offset 0
    g_at_zero = [e for e in ev2 if e["offset"] == 0 and e["etype"] == ETYPE_GRID]
    assert g_at_zero == []


def test_delete_tape_event_returns_true():
    """Les événements tape (K/P) sont supprimables via delete_event."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    tape_ev = next(e for e in ev if e["etype"] in (ETYPE_KIT, ETYPE_PATCH))
    result = me.delete_event(p, tape_ev)
    assert result is True
    # L'événement K/P doit avoir disparu (des notes G peuvent rester à la même clé)
    remaining = tape_at(p, tape_ev["track"], tape_ev["bar"], tape_ev["step"])
    assert not any(e.etype in (ETYPE_KIT, ETYPE_PATCH) for e in remaining)


# ---------------------------------------------------------------------------
# _source_events — priorité sélection / limiteurs / groupe courant
# ---------------------------------------------------------------------------

class _FakeLims:
    def __init__(self, lim_l=None, lim_r=None):
        self._lim_left  = lim_l
        self._lim_right = lim_r
    def reset_lims(self):
        self._lim_left = self._lim_right = None
    def set_lim_left(self, v):
        self._lim_left = v
    def set_lim_right(self, v):
        self._lim_right = v


def _sim_source_events(events, selected_indices, lim_l, lim_r, cur_idx):
    """Simule _source_events() sans wx."""
    if selected_indices:
        return [events[i] for i in sorted(selected_indices)
                if events[i].get("type") == "note"]
    if lim_l is not None or lim_r is not None:
        lo = lim_l if lim_l is not None else 0
        hi = lim_r if lim_r is not None else float("inf")
        notes = [e for e in events
                 if e.get("type") == "note" and lo <= e["offset"] <= hi]
        if notes:
            return notes
    if not events:
        return []
    me    = MidiEditor()
    group = me.group_indices(events, cur_idx)
    return [events[i] for i in group if events[i].get("type") == "note"]


def test_source_events_selection_priority():
    """Sélection manuelle prend le dessus sur les limiteurs."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)   # 5 notes
    # Sélectionner uniquement idx=2, limiteurs couvrant tout
    src = _sim_source_events(ev, {2}, lim_l=0, lim_r=100, cur_idx=0)
    assert len(src) == 1
    assert src[0] is ev[2]


def test_source_events_lims_over_group():
    """Limiteurs actifs retournent tous les événements dans la plage."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # Limiteurs : offsets 0 à 4 → grille pad0:0, pad1:0, pad0:4 + tape K:0 = 4 notes
    src = _sim_source_events(ev, set(), lim_l=0, lim_r=4, cur_idx=3)
    offsets = {e["offset"] for e in src}
    assert offsets <= {0, 4}
    assert len(src) == 4


def test_source_events_group_fallback():
    """Sans sélection ni limiteurs, retourne le groupe courant."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # Curseur sur idx=0 (offset 0) → groupe de 3 notes (pad0, pad1, tape K)
    src = _sim_source_events(ev, set(), lim_l=None, lim_r=None, cur_idx=0)
    assert all(e["offset"] == 0 for e in src)
    assert len(src) == 3


def test_source_events_empty_lims_falls_to_group():
    """Limiteurs posés mais aucun événement dans la plage → groupe courant."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    # Limiteurs dans une zone vide (offset 100–200)
    src = _sim_source_events(ev, set(), lim_l=100, lim_r=200, cur_idx=0)
    assert all(e["offset"] == 0 for e in src)


# ---------------------------------------------------------------------------
# _sync_lims_from_selection
# ---------------------------------------------------------------------------

def _sim_sync_lims(events, selected_indices, fake_te):
    """Simule _sync_lims_from_selection() sans wx."""
    if not selected_indices:
        fake_te.reset_lims()
        return
    offsets = [events[i]["offset"] for i in selected_indices if i < len(events)]
    if offsets:
        fake_te.set_lim_left(min(offsets))
        fake_te.set_lim_right(max(offsets))


def test_sync_lims_single_event():
    me  = MidiEditor()
    p   = _make_pattern()
    ev  = me.get_note_events(p, 0)
    te  = _FakeLims()
    # Sélectionner idx=3 (offset 4)
    idx = next(i for i, e in enumerate(ev) if e["offset"] == 4)
    _sim_sync_lims(ev, {idx}, te)
    assert te._lim_left  == 4
    assert te._lim_right == 4


def test_sync_lims_span():
    me  = MidiEditor()
    p   = _make_pattern()
    ev  = me.get_note_events(p, 0)
    te  = _FakeLims()
    # Sélectionner offset 0 et offset 4
    sel = {i for i, e in enumerate(ev) if e["offset"] in (0, 4)}
    _sim_sync_lims(ev, sel, te)
    assert te._lim_left  == 0
    assert te._lim_right == 4


def test_sync_lims_empty_resets():
    te = _FakeLims(lim_l=5, lim_r=10)
    _sim_sync_lims([], set(), te)
    assert te._lim_left  is None
    assert te._lim_right is None


# ---------------------------------------------------------------------------
# duplicate_event (étape 7i)
# ---------------------------------------------------------------------------

def test_duplicate_event_kit_stacks_at_same_position():
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 0, TapeEvent(ETYPE_KIT, dur=500, payload={"note": 60, "vel": 100}))
    ev = {"type": "note", "etype": ETYPE_KIT, "track": 0, "bar": 0, "step": 0,
          "offset": 0, "pad": 60, "vel": 100, "dur": 500, "event_idx": 0}
    result = me.duplicate_event(p, ev)
    assert result is not None
    assert result["bar"] == 0 and result["step"] == 0
    assert result["pad"] == 60
    assert len(tape_at(p, 0, 0, 0)) == 2


def test_duplicate_event_patch_stacks_at_same_position():
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 0, TapeEvent(ETYPE_PATCH, dur=300, payload={"note": 64, "vel": 100}))
    ev = {"type": "note", "etype": ETYPE_PATCH, "track": 0, "bar": 0, "step": 0,
          "offset": 0, "pad": 64, "vel": 100, "dur": 300, "event_idx": 0}
    result = me.duplicate_event(p, ev)
    assert result["pad"] == 64
    assert len(tape_at(p, 0, 0, 0)) == 2


def test_duplicate_event_grid_goes_to_adjacent_pad():
    me = MidiEditor()
    p  = Pattern()
    p.set_cell(0, 0, 0, 0, 100)
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0,
          "step": 0, "offset": 0, "vel": 100}
    result = me.duplicate_event(p, ev)
    assert result["pad"] == 1
    assert p.get_cell(0, 0, 0, 0) == 100   # original intact
    assert p.get_cell(0, 1, 0, 0) == 100   # doublon sur pad adjacent


def test_duplicate_event_grid_falls_back_to_pad_minus_one_at_last_pad():
    me = MidiEditor()
    p  = Pattern()
    last = p._num_pads - 1
    p.set_cell(0, last, 0, 0, 100)
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": last, "bar": 0,
          "step": 0, "offset": 0, "vel": 100}
    result = me.duplicate_event(p, ev)
    assert result["pad"] == last - 1


def test_duplicate_event_grid_single_pad_impossible():
    me = MidiEditor()
    p  = Pattern()
    p._num_pads = 1
    p.set_cell(0, 0, 0, 0, 100)
    ev = {"type": "note", "etype": ETYPE_GRID, "track": 0, "pad": 0, "bar": 0,
          "step": 0, "offset": 0, "vel": 100}
    assert me.duplicate_event(p, ev) is None


# ---------------------------------------------------------------------------
# insert_note (étape 7i)
# ---------------------------------------------------------------------------

def test_insert_note_grid():
    me = MidiEditor()
    p  = Pattern()
    result = me.insert_note(p, ETYPE_GRID, 0, 0, 2, 5, vel=90)
    assert result["pad"] == 5
    assert p.get_cell(0, 5, 0, 2) == 90


def test_insert_note_patch():
    me = MidiEditor()
    p  = Pattern()
    result = me.insert_note(p, ETYPE_PATCH, 0, 0, 2, 64, vel=100, dur=250)
    assert result["pad"] == 64
    assert result["dur"] == 250
    tape = tape_at(p, 0, 0, 2)
    assert len(tape) == 1 and tape[0].etype == ETYPE_PATCH and tape[0].payload.get("note") == 64


def test_insert_note_kit_clamps_note_to_127():
    me = MidiEditor()
    p  = Pattern()
    result = me.insert_note(p, ETYPE_KIT, 0, 0, 0, 200)
    assert result["pad"] == 127


def test_insert_note_grid_clamps_pad_to_num_pads():
    me = MidiEditor()
    p  = Pattern()
    result = me.insert_note(p, ETYPE_GRID, 0, 0, 0, 999)
    assert result["pad"] == p._num_pads - 1


def test_insert_note_out_of_bounds_bar():
    me = MidiEditor()
    p  = Pattern()
    assert me.insert_note(p, ETYPE_GRID, 0, p._num_bars, 0, 5) is None


def test_insert_note_out_of_bounds_track():
    me = MidiEditor()
    p  = Pattern()
    assert me.insert_note(p, ETYPE_GRID, p._num_tracks, 0, 0, 5) is None


def test_insert_note_clamps_velocity():
    me = MidiEditor()
    p  = Pattern()
    result = me.insert_note(p, ETYPE_PATCH, 0, 0, 0, 64, vel=200)
    assert result["vel"] == 127


# ---------------------------------------------------------------------------
# insert_between_offset (étape 7n)
# ---------------------------------------------------------------------------

def test_insert_between_offset_even_gap():
    me = MidiEditor()
    assert me.insert_between_offset(0, 4) == 2


def test_insert_between_offset_odd_gap():
    me = MidiEditor()
    mid = me.insert_between_offset(0, 3)
    assert mid in (1, 2)


def test_insert_between_offset_adjacent_impossible():
    me = MidiEditor()
    assert me.insert_between_offset(0, 1) is None


def test_insert_between_offset_equal_impossible():
    me = MidiEditor()
    assert me.insert_between_offset(5, 5) is None


def test_insert_between_offset_single_gap_impossible():
    me = MidiEditor()
    # écart de 2 mais round() tombe pile sur une borne : toujours résolu (1)
    assert me.insert_between_offset(0, 2) == 1


# ---------------------------------------------------------------------------
# CC générique / Program Change dans _tape (Phase 7 étape 4j)
# ---------------------------------------------------------------------------

def _pattern_with_cc_pgm():
    """Pattern 2×16 : au pas 4 une note GRID + un CC + un Program Change
    (même position, pour éprouver le partage d'event_idx), plus un CC isolé
    au pas 12."""
    p = Pattern()
    p.resize(2, 16)
    p.set_cell(0, 3, 0, 4, 100)
    add_tape_at(p, 0, 0, 4, TapeEvent(ETYPE_CC,  channel=1, payload={"cc_num": 74, "value": 90}))
    add_tape_at(p, 0, 0, 4, TapeEvent(ETYPE_PGM, channel=1, payload={"program": 5}))
    add_tape_at(p, 0, 0, 12, TapeEvent(ETYPE_CC, channel=2, payload={"cc_num": 7, "value": 40}))
    return p


def _cc_ev(me, p, cc_num=74):
    """Relit l'event_info d'un CC depuis le pattern (event_idx à jour)."""
    return [e for e in me.get_cc_pgm_events(p, 0)
            if e["type"] == "cc" and e["cc_num"] == cc_num][0]


def _pgm_ev(me, p):
    return [e for e in me.get_cc_pgm_events(p, 0) if e["type"] == "pgm"][0]


def test_cc_pgm_excluded_from_note_events():
    """CC/PGM ne sont pas des notes : absents de get_note_events (mode Notes)."""
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    ev = me.get_note_events(p, 0)
    assert len(ev) == 1
    assert ev[0]["etype"] == ETYPE_GRID


def test_note_events_sort_unaffected_by_cc_pgm():
    """Le tri de get_note_events (clé e["pad"]) ne lève plus de TypeError :
    les CC/PGM, sans champ "pad", n'entrent plus dans la liste (piège 4a)."""
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    p.set_cell(0, 1, 0, 4, 80)   # 2e note GRID au même offset → force une comparaison
    ev = me.get_note_events(p, 0)
    assert [e["pad"] for e in ev] == [1, 3]


def test_get_cc_pgm_events_fields():
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    cc = _cc_ev(me, p)
    assert cc["type"]    == "cc"
    assert cc["etype"]   == ETYPE_CC
    assert cc["track"]   == 0
    assert cc["bar"]     == 0
    assert cc["step"]    == 4
    assert cc["offset"]  == 4
    assert cc["value"]   == 90
    assert cc["channel"] == 1

    pgm = _pgm_ev(me, p)
    assert pgm["type"]    == "pgm"
    assert pgm["etype"]   == ETYPE_PGM
    assert pgm["program"] == 5
    assert pgm["channel"] == 1
    assert pgm["offset"]  == 4


def test_cc_pgm_event_idx_shared_with_notes_at_same_offset():
    """event_idx compte parmi TOUS les etypes d'une même position : la note
    GRID posée en premier prend 0, le CC 1, le Program Change 2."""
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    note = [e for e in me.get_note_events(p, 0) if e["offset"] == 4][0]
    assert note["event_idx"] == 0
    assert _cc_ev(me, p)["event_idx"]  == 1
    assert _pgm_ev(me, p)["event_idx"] == 2


def test_get_cc_pgm_events_respects_limiters():
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    assert len(me.get_cc_pgm_events(p, 0, lim_left=5)) == 1      # seul le CC du pas 12
    assert me.get_cc_pgm_events(p, 0, lim_left=5)[0]["cc_num"] == 7
    assert len(me.get_cc_pgm_events(p, 0, lim_right=4)) == 2     # CC + PGM du pas 4
    assert me.get_cc_pgm_events(p, 0, lim_left=20) == []


def test_get_cc_pgm_events_unknown_track_returns_empty():
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    assert me.get_cc_pgm_events(p, 99) == []


def test_all_events_includes_cc_and_pgm():
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    ev = me.get_all_events(p, [0])
    assert len([e for e in ev if e["type"] == "cc"])  == 2
    assert len([e for e in ev if e["type"] == "pgm"]) == 1
    assert len([e for e in ev if e["type"] == "note"]) == 1


# --- delete_event ---------------------------------------------------------

def test_delete_event_cc_removes_the_cc_not_its_neighbours():
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    assert me.delete_event(p, _cc_ev(me, p)) is True
    at4 = tape_at(p, 0, 0, 4)
    assert [e.etype for e in at4] == [ETYPE_GRID, ETYPE_PGM]


def test_delete_event_pgm_removes_the_pgm_not_its_neighbours():
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    assert me.delete_event(p, _pgm_ev(me, p)) is True
    at4 = tape_at(p, 0, 0, 4)
    assert [e.etype for e in at4] == [ETYPE_GRID, ETYPE_CC]


def test_delete_event_bend():
    """Phase 7 étape 6d1 : un bend vit dans _tape, delete_event le supprime
    (comme CC/PGM depuis 4i) sans toucher la note/CC/PGM de la même position."""
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    add_tape_at(p, 0, 0, 4, TapeEvent(ETYPE_BEND, payload={"value": 300}))
    bend = [e for e in me.get_cc_pgm_events(p, 0) if e["type"] == "bend"][0]
    assert me.delete_event(p, bend) is True
    assert [e.etype for e in tape_at(p, 0, 0, 4)] == [ETYPE_GRID, ETYPE_CC, ETYPE_PGM]


def test_bend_event_idx_shared_with_note_cc_pgm():
    """event_idx du bend compté parmi tous les etypes de sa position : il
    résout bien le bend (pas la note/CC/PGM voisins) à l'édition."""
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    add_tape_at(p, 0, 0, 4, TapeEvent(ETYPE_BEND, payload={"value": 300}))
    bend = [e for e in me.get_cc_pgm_events(p, 0) if e["type"] == "bend"][0]
    assert bend["event_idx"] == 3            # GRID, CC, PGM, BEND
    res = me.edit_bend_event(p, bend, new_value=-300)
    assert res is not None
    at4 = tape_at(p, 0, 0, 4)
    assert [e.etype for e in at4] == [ETYPE_GRID, ETYPE_CC, ETYPE_PGM, ETYPE_BEND]
    assert at4[3].payload == {"value": -300}
    assert at4[1].payload == {"cc_num": 74, "value": 90}   # CC intact


def test_delete_fractional_bend():
    me = MidiEditor()
    p  = Pattern()
    p._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": 1}, time=3.4))
    p._tape[0].append(TapeEvent(ETYPE_CC, payload={"cc_num": 1, "value": 5}, time=3))
    bend = [e for e in me.get_cc_pgm_events(p, 0) if e["type"] == "bend"][0]
    assert me.delete_event(p, bend) is True
    assert [e.etype for e in p._tape[0]] == [ETYPE_CC]


def test_filter_bend_on_real_events():
    """Le filtre "bend" et ses bornes s'appliquent aux bends lus dans _tape."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_all_events(p, [0])
    crit = {"active": True, "etype_filter": "bend", "bend_lo": -8192, "bend_hi": 0}
    assert [ev[i]["value"] for i in me.filter_events(ev, crit)] == [-200]


# --- edit_cc_event --------------------------------------------------------

def test_edit_cc_event_value():
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    res = me.edit_cc_event(p, _cc_ev(me, p), new_value=20)
    assert res is not None
    assert res["value"]  == 20
    assert res["cc_num"] == 74      # cc_num non éditable, préservé
    assert res["channel"] == 1      # canal d'origine préservé
    ev = [e for e in tape_at(p, 0, 0, 4) if e.etype == ETYPE_CC][0]
    assert ev.payload == {"cc_num": 74, "value": 20}
    assert ev.dur == 0


def test_edit_cc_event_value_clamped():
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    assert me.edit_cc_event(p, _cc_ev(me, p), new_value=999)["value"] == 127
    assert me.edit_cc_event(p, _cc_ev(me, p), new_value=-5)["value"]  == 0


def test_edit_cc_event_move_position():
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    res = me.edit_cc_event(p, _cc_ev(me, p), new_bar=1, new_step=3)
    assert (res["bar"], res["step"], res["offset"]) == (1, 3, p._num_steps + 3)
    assert not [e for e in tape_at(p, 0, 0, 4) if e.etype == ETYPE_CC]
    moved = [e for e in tape_at(p, 0, 1, 3) if e.etype == ETYPE_CC]
    assert moved and moved[0].payload == {"cc_num": 74, "value": 90}


def test_edit_cc_event_out_of_bounds_returns_none():
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    assert me.edit_cc_event(p, _cc_ev(me, p), new_bar=999) is None
    assert me.edit_cc_event(p, _cc_ev(me, p), new_step=999) is None
    assert [e for e in tape_at(p, 0, 0, 4) if e.etype == ETYPE_CC]   # inchangé


def test_edit_cc_event_wrong_event_idx_etype_returns_none():
    """Garde-fou : si event_idx désigne un événement d'un autre etype (ici la
    note GRID), l'édition échoue sans rien toucher dans _tape."""
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    bad = dict(_cc_ev(me, p), event_idx=0)   # 0 = la note GRID
    assert me.edit_cc_event(p, bad, new_value=1) is None
    assert [e.etype for e in tape_at(p, 0, 0, 4)] == [ETYPE_GRID, ETYPE_CC, ETYPE_PGM]


def test_edit_cc_event_unknown_event_idx_returns_none():
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    bad = dict(_cc_ev(me, p), event_idx=99)
    assert me.edit_cc_event(p, bad, new_value=1) is None


# --- CC à position fractionnaire (Phase 7 étape 5b) -----------------------

def _pattern_with_fractional_cc():
    """Piste 0 : note KIT et CC#1 au pas entier 3, CC#1 à 3.4 (même pas
    affiché, autre position exacte)."""
    p = Pattern()
    p.resize(2, 16)
    p._tape[0] += [
        TapeEvent(ETYPE_KIT, payload={"note": 1, "vel": 100}, time=3),
        TapeEvent(ETYPE_CC,  payload={"cc_num": 1, "value": 10}, time=3),
        TapeEvent(ETYPE_CC,  channel=2, payload={"cc_num": 1, "value": 20}, time=3.4),
    ]
    return p


def _frac_cc_ev(me, p):
    return [e for e in me.get_cc_pgm_events(p, 0) if e["offset"] == 3.4][0]


def test_fractional_cc_event_info():
    me = MidiEditor()
    p  = _pattern_with_fractional_cc()
    ev = _frac_cc_ev(me, p)
    assert (ev["bar"], ev["step"], ev["value"]) == (0, 3, 20)
    assert ev["event_idx"] == 0   # seul événement à la position exacte 3.4


def test_delete_fractional_cc_targets_exact_position():
    """bar/step (0,3) désignent aussi la note et le CC au pas entier :
    seul le CC à 3.4 doit partir."""
    me = MidiEditor()
    p  = _pattern_with_fractional_cc()
    assert me.delete_event(p, _frac_cc_ev(me, p)) is True
    left = [(e.etype, e.time, e.payload.get("value")) for e in p._tape[0]]
    assert left == [(ETYPE_KIT, 3, None), (ETYPE_CC, 3, 10)]


def test_delete_integer_cc_leaves_fractional_neighbour():
    me = MidiEditor()
    p  = _pattern_with_fractional_cc()
    ev = [e for e in me.get_cc_pgm_events(p, 0) if e["offset"] == 3][0]
    assert me.delete_event(p, ev) is True
    assert [(e.etype, e.time) for e in p._tape[0]] == [(ETYPE_KIT, 3), (ETYPE_CC, 3.4)]


def test_edit_fractional_cc_value_keeps_position():
    me = MidiEditor()
    p  = _pattern_with_fractional_cc()
    res = me.edit_cc_event(p, _frac_cc_ev(me, p), new_value=99)
    assert res["offset"] == 3.4
    assert res["channel"] == 2
    cc = [e for e in p._tape[0] if e.etype == ETYPE_CC and e.time == 3.4]
    assert len(cc) == 1 and cc[0].payload == {"cc_num": 1, "value": 99}
    # le CC au pas entier n'a pas bougé
    assert [e for e in p._tape[0] if e.etype == ETYPE_CC and e.time == 3][0].payload["value"] == 10


def test_edit_fractional_cc_move_snaps_to_integer_step():
    me = MidiEditor()
    p  = _pattern_with_fractional_cc()
    res = me.edit_cc_event(p, _frac_cc_ev(me, p), new_step=8)
    assert (res["bar"], res["step"], res["offset"]) == (0, 8, 8)
    assert not any(e.time == 3.4 for e in p._tape[0])
    assert [e.payload["value"] for e in p._tape[0] if e.time == 8] == [20]


def test_event_time_falls_back_to_bar_step_when_offset_stale():
    """Un dict dont offset ne correspond plus à bar/step est résolu par
    bar/step (comportement d'avant 5b)."""
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    ev = dict(_cc_ev(me, p, cc_num=7), offset=0.5)   # bar/step = (0,12)
    assert me._event_time(p, ev) == 12
    assert me.delete_event(p, ev) is True
    assert not [e for e in tape_at(p, 0, 0, 12) if e.etype == ETYPE_CC]


# --- edit_pgm_event -------------------------------------------------------

def test_edit_pgm_event_value():
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    res = me.edit_pgm_event(p, _pgm_ev(me, p), new_value=42)
    assert res["program"] == 42
    assert res["channel"] == 1
    ev = [e for e in tape_at(p, 0, 0, 4) if e.etype == ETYPE_PGM][0]
    assert ev.payload == {"program": 42}
    assert ev.dur == 0


def test_edit_pgm_event_value_clamped():
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    assert me.edit_pgm_event(p, _pgm_ev(me, p), new_value=200)["program"] == 127
    assert me.edit_pgm_event(p, _pgm_ev(me, p), new_value=-1)["program"]  == 0


def test_edit_pgm_event_move_position():
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    res = me.edit_pgm_event(p, _pgm_ev(me, p), new_step=9)
    assert (res["bar"], res["step"], res["offset"]) == (0, 9, 9)
    assert [e.etype for e in tape_at(p, 0, 0, 4)] == [ETYPE_GRID, ETYPE_CC]
    assert [e.etype for e in tape_at(p, 0, 0, 9)] == [ETYPE_PGM]


def test_edit_pgm_event_out_of_bounds_returns_none():
    me = MidiEditor()
    p  = _pattern_with_cc_pgm()
    assert me.edit_pgm_event(p, _pgm_ev(me, p), new_bar=999) is None
    assert [e for e in tape_at(p, 0, 0, 4) if e.etype == ETYPE_PGM]   # inchangé


# ---------------------------------------------------------------------------
# Limiteur droit / filtre pos_to inclusifs sur le pas entier (Phase 7 étape 6g2)
# ---------------------------------------------------------------------------

def _pattern_fractional_edge():
    """CC et bend fractionnaires sur le pas 5 (5.4), un CC au pas 6 pile."""
    p = Pattern()
    p.resize(2, 16)
    p._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": 1}, time=5.4))
    p._tape[0].append(TapeEvent(ETYPE_CC, payload={"cc_num": 1, "value": 2}, time=5.4))
    p._tape[0].append(TapeEvent(ETYPE_CC, payload={"cc_num": 7, "value": 3}, time=6))
    return p


def test_all_events_right_limiter_includes_fraction_of_its_step():
    """Limiteur droit sur le pas 5 : un CC/bend à 5.4 est dans la plage
    (avant 6g2 : comparé à 5.4 > 5, il était exclu) ; le pas 6 ne l'est pas."""
    me = MidiEditor()
    ev = me.get_all_events(_pattern_fractional_edge(), [0], lim_left=2, lim_right=5)
    assert sorted((e["type"], e["offset"]) for e in ev) == [("bend", 5.4), ("cc", 5.4)]


def test_filter_pos_to_includes_fraction_of_its_step():
    me = MidiEditor()
    ev = me.get_all_events(_pattern_fractional_edge(), [0])
    crit = {"active": True, "etype_filter": "all", "pos_from": 0, "pos_to": 5}
    assert sorted(ev[i]["offset"] for i in me.filter_events(ev, crit)) == [5.4, 5.4]


# ---------------------------------------------------------------------------
# delete_events — suppression multiple dans l'ordre event_idx (Phase 7 étape 7c1)
# ---------------------------------------------------------------------------

def _patch(note):
    return TapeEvent(ETYPE_PATCH, payload={"note": note, "vel": 100})


def test_delete_events_chord_recorded_high_then_low_fully_removed():
    """Bug A (7a1) : affichage trié par pad (60 avant 67) ≠ ordre _tape
    (67 puis 60). Supprimer à l'envers de l'affichage décalait event_idx et
    laissait la note 60 ; delete_events supprime tout l'accord."""
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 0, _patch(67))
    add_tape_at(p, 0, 0, 0, _patch(60))
    ev = me.get_note_events(p, 0)
    assert [e["pad"] for e in ev] == [60, 67]
    assert [e["event_idx"] for e in ev] == [1, 0]
    assert me.delete_events(p, ev) == 2
    assert p._tape[0] == []


def test_delete_events_mixed_grid_patch_bend_same_step():
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 2, _patch(72))
    p.set_cell(0, 3, 0, 2, 100)
    add_tape_at(p, 0, 0, 2, TapeEvent(ETYPE_BEND, payload={"value": 500}))
    add_tape_at(p, 0, 0, 2, _patch(48))
    ev = me.get_all_events(p, [0])
    assert len(ev) == 4
    assert me.delete_events(p, ev) == 4
    assert tape_at(p, 0, 0, 2) == []


def test_delete_events_keeps_unselected_neighbours():
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 2, _patch(72))
    add_tape_at(p, 0, 0, 2, TapeEvent(ETYPE_BEND, payload={"value": 500}))
    add_tape_at(p, 0, 0, 2, _patch(48))
    ev = me.get_all_events(p, [0])
    targets = [e for e in ev if e["type"] == "note"]
    assert me.delete_events(p, targets) == 2
    remaining = tape_at(p, 0, 0, 2)
    assert [(e.etype, e.payload["value"]) for e in remaining] == [(ETYPE_BEND, 500)]


def test_delete_events_order_of_input_does_not_matter():
    me = MidiEditor()
    p  = Pattern()
    for n in (64, 67, 60):
        add_tape_at(p, 0, 0, 0, _patch(n))
    ev = me.get_note_events(p, 0)
    shuffled = [ev[1], ev[0], ev[2]]
    assert me.delete_events(p, shuffled) == 3
    assert p._tape[0] == []


def test_delete_events_across_tracks_and_steps():
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 1, _patch(60))
    add_tape_at(p, 0, 0, 1, _patch(62))
    add_tape_at(p, 1, 0, 1, _patch(64))
    add_tape_at(p, 1, 0, 3, TapeEvent(ETYPE_CC, payload={"cc_num": 7, "value": 90}))
    ev = me.get_all_events(p, [0, 1])
    assert me.delete_events(p, ev) == 4
    assert p._tape[0] == [] and p._tape[1] == []


def test_delete_events_counts_only_successful_deletions():
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 0, _patch(60))
    ev = me.get_note_events(p, 0)
    ghost = dict(ev[0], event_idx=5)
    assert me.delete_events(p, [ev[0], ghost]) == 1


def test_delete_events_empty_list_returns_zero():
    assert MidiEditor().delete_events(Pattern(), []) == 0



# ---------------------------------------------------------------------------
# Plus de champ "bend" par note PATCH dans l'éditeur (Phase 7 étape 7i1)
# ---------------------------------------------------------------------------

def test_get_note_events_patch_has_no_bend_key():
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 0, _patch(60))
    assert "bend" not in me.get_note_events(p, 0)[0]


def test_insert_note_patch_payload_has_no_bend():
    me = MidiEditor()
    p  = Pattern()
    res = me.insert_note(p, ETYPE_PATCH, 0, 0, 2, 60, vel=90, dur=300)
    assert "bend" not in res
    assert tape_at(p, 0, 0, 2)[0].payload == {"note": 60, "vel": 90}


def test_insert_note_takes_no_bend_parameter():
    with pytest.raises(TypeError):
        MidiEditor().insert_note(Pattern(), ETYPE_PATCH, 0, 0, 2, 60, bend=100)


def test_duplicate_event_patch_payload_has_no_bend():
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 0, _patch(60))
    res = me.duplicate_event(p, me.get_note_events(p, 0)[0])
    assert "bend" not in res
    assert all(ev.payload == {"note": 60, "vel": 100} for ev in p._tape[0])


def test_edit_tape_note_does_not_touch_bend_points():
    """Déplacer une note PATCH ne déplace pas le bend posé à son temps : le
    bend est un état de canal, indépendant de la note."""
    me = MidiEditor()
    p  = Pattern()
    add_tape_at(p, 0, 0, 0, TapeEvent(ETYPE_BEND, payload={"value": 4096}))
    add_tape_at(p, 0, 0, 0, _patch(60))
    note = me.get_note_events(p, 0)[0]
    me.edit_tape_note(p, note, new_step=5)
    bends = [ev for ev in p._tape[0] if ev.etype == ETYPE_BEND]
    assert [(ev.time, ev.payload["value"]) for ev in bends] == [(0, 4096)]
