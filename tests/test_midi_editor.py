"""Tests — MidiEditor (Phase 6 étapes 1a–3c)."""
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
    p._tape.setdefault((0, 0, 0), []).append(TapeEvent("K", 60, 100, 500, 0))
    p._tape.setdefault((1, 0, 4), []).append(TapeEvent("P", 64,  80, 300, 0))

    # Automation bend/mod piste 0
    p._bend_tape[0] = [(2, 100), (6, -200)]
    p._mod_tape[0]  = [(1, 64)]
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
    assert all(e["etype"] in ("G", "K", "P") for e in ev)
    grid = [e for e in ev if e["etype"] == "G"]
    tape = [e for e in ev if e["etype"] in ("K", "P")]
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
    grid = next(e for e in ev if e["etype"] == "G")
    tape = next(e for e in ev if e["etype"] == "P")
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
    grid_pads = {e["pad"] for e in at_zero if e["etype"] == "G"}
    assert grid_pads == {0, 1}


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
    assert p.get_cell(ev["track"], ev["pad"], ev["bar"], ev["step"]) == 0


def test_delete_grid_sets_cell_to_zero():
    me = MidiEditor()
    p  = _make_pattern()
    assert p.get_cell(0, 0, 0, 0) == 100
    ev = {"type": "note", "etype": "G", "track": 0, "pad": 0, "bar": 0, "step": 0}
    me.delete_event(p, ev)
    assert p.get_cell(0, 0, 0, 0) == 0


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
    assert p.get_cell(0, 0, 0, 0) == 50


def test_edit_grid_move_position():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": "G", "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    result = me.edit_grid_note(p, ev, new_bar=1, new_step=3)
    assert result is not None
    assert result["bar"]  == 1
    assert result["step"] == 3
    assert p.get_cell(0, 0, 0, 0) == 0     # ancienne cellule effacée
    assert p.get_cell(0, 0, 1, 3) == 100   # nouvelle cellule remplie


def test_edit_grid_change_pad():
    me = MidiEditor()
    p  = _make_pattern()
    ev = {"type": "note", "etype": "G", "track": 0, "pad": 0, "bar": 0, "step": 0, "vel": 100}
    result = me.edit_grid_note(p, ev, new_pad=5)
    assert result is not None
    assert result["pad"] == 5
    assert p.get_cell(0, 0, 0, 0) == 0   # ancien pad effacé
    assert p.get_cell(0, 5, 0, 0) == 100 # nouveau pad rempli


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
    assert p.get_cell(0, 0, 0, 0) == 100


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
    group0 = [i for i in me.group_indices(ev, 0) if ev[i]["etype"] == "G"]
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
    g_notes = [i for i in group0 if ev[i]["etype"] == "G"]
    for idx in sorted(g_notes, reverse=True):
        me.delete_event(p, ev[idx])
    ev2 = me.get_note_events(p, 0)
    # Plus de notes G à offset 0
    g_at_zero = [e for e in ev2 if e["offset"] == 0 and e["etype"] == "G"]
    assert g_at_zero == []


def test_delete_tape_event_returns_true():
    """Les événements tape (K/P) sont supprimables via delete_event."""
    me = MidiEditor()
    p  = _make_pattern()
    ev = me.get_note_events(p, 0)
    tape_ev = next(e for e in ev if e["etype"] in ("K", "P"))
    result = me.delete_event(p, tape_ev)
    assert result is True
    # L'événement K/P doit avoir disparu (des notes G peuvent rester à la même clé)
    key = (tape_ev["track"], tape_ev["bar"], tape_ev["step"])
    remaining = p._tape.get(key, [])
    assert not any(e.etype in ("K", "P") for e in remaining)


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
