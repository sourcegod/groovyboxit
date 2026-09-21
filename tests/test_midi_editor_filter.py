"""Tests — MidiEditor.filter_events (Phase 6 étape 8a-1)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from midi.midi_editor import MidiEditor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _events():
    """Liste de dicts imitant get_all_events() : 2 notes, 1 bend, 1 mod."""
    return [
        {"type": "note", "offset": 0,   "pad": 60, "vel": 100},
        {"type": "note", "offset": 4,   "pad": 72, "vel": 30},
        {"type": "bend", "offset": 2,   "value": -200},
        {"type": "mod",  "offset": 1.5, "value": 64},
    ]


def _default_criteria(**overrides):
    c = {
        "active":       True,
        "invert":       False,
        "etype_filter": "all",
        "note_lo": 0, "note_hi": 127,
        "vel_lo":  0, "vel_hi":  127,
        "bend_lo": -8192, "bend_hi": 8191,
        "pos_from": None, "pos_to": None,
    }
    c.update(overrides)
    return c


# ---------------------------------------------------------------------------
# Switch maître / inversion
# ---------------------------------------------------------------------------

def test_active_false_matches_everything():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(active=False, etype_filter="note", note_lo=60, note_hi=60))
    assert matched == set(range(len(ev)))


def test_active_true_all_type_matches_everything():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria())
    assert matched == set(range(len(ev)))


def test_invert_returns_complement():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(etype_filter="note"))
    inverted = me.filter_events(ev, _default_criteria(etype_filter="note", invert=True))
    assert inverted == set(range(len(ev))) - matched


def test_invert_with_active_false_is_empty():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(active=False, invert=True))
    assert matched == set()


def test_empty_events_returns_empty_set():
    me = MidiEditor()
    assert me.filter_events([], _default_criteria()) == set()


# ---------------------------------------------------------------------------
# Type "note" — bornes note/vélocité
# ---------------------------------------------------------------------------

def test_type_note_isolates_notes():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(etype_filter="note"))
    assert matched == {0, 1}


def test_note_bounds_inclusive():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(etype_filter="note", note_lo=60, note_hi=60))
    assert matched == {0}


def test_note_bounds_exclude_out_of_range():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(etype_filter="note", note_lo=61, note_hi=71))
    assert matched == set()


def test_velocity_bounds_inclusive_equal_lo_hi():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(etype_filter="note", vel_lo=100, vel_hi=100))
    assert matched == {0}


def test_velocity_bounds_exclude():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(etype_filter="note", vel_lo=50, vel_hi=127))
    assert matched == {0}


def test_note_and_velocity_combined():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(etype_filter="note", note_lo=70, note_hi=127, vel_lo=0, vel_hi=50))
    assert matched == {1}


# ---------------------------------------------------------------------------
# Type "bend" — bornes de valeur
# ---------------------------------------------------------------------------

def test_type_bend_isolates_bend():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(etype_filter="bend"))
    assert matched == {2}


def test_bend_bounds_inclusive():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(etype_filter="bend", bend_lo=-200, bend_hi=-200))
    assert matched == {2}


def test_bend_bounds_exclude():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(etype_filter="bend", bend_lo=0, bend_hi=8191))
    assert matched == set()


# ---------------------------------------------------------------------------
# Type "mod" — aucun sous-critère
# ---------------------------------------------------------------------------

def test_type_mod_isolates_mod_no_sub_criteria():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(etype_filter="mod"))
    assert matched == {3}


# ---------------------------------------------------------------------------
# Type "all" — sous-critères ignorés même resserrés
# ---------------------------------------------------------------------------

def test_type_all_ignores_note_and_vel_bounds():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(etype_filter="all", note_lo=60, note_hi=60, vel_lo=100, vel_hi=100))
    assert matched == set(range(len(ev)))


# ---------------------------------------------------------------------------
# Position — bornes incluses, offsets fractionnaires (bend/mod)
# ---------------------------------------------------------------------------

def test_position_bounds_inclusive():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(pos_from=1, pos_to=2))
    # offset 1.5 (mod) et 2 (bend) sont dans [1, 2] ; 0 et 4 sont hors bornes
    assert matched == {2, 3}


def test_position_from_only():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(pos_from=2))
    assert matched == {1, 2}


def test_position_to_only():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(pos_to=1.5))
    assert matched == {0, 3}


def test_position_combined_with_type():
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(pos_from=0, pos_to=2, etype_filter="note"))
    assert matched == {0}
