"""Tests — MidiEditor.filter_events (Phase 6 étape 8a-1)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from midi.midi_editor import MidiEditor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _events():
    """Liste de dicts imitant get_all_events() : 2 notes, 1 bend, 1 CC#1
    (Mod Wheel — plus de type "mod" séparé depuis l'étape 5f, voir alias
    etype_filter="mod" testé plus bas)."""
    return [
        {"type": "note", "offset": 0,   "pad": 60, "vel": 100},
        {"type": "note", "offset": 4,   "pad": 72, "vel": 30},
        {"type": "bend", "offset": 2,   "value": -200},
        {"type": "cc",   "offset": 1.5, "cc_num": 1, "value": 64},
    ]


def _default_criteria(**overrides):
    c = {
        "active":       True,
        "invert":       False,
        "etype_filter": "all",
        "note_lo": 0, "note_hi": 127,
        "vel_lo":  0, "vel_hi":  127,
        "bend_lo": -8192, "bend_hi": 8191,
        "cc_num_lo": 0, "cc_num_hi": 127,
        "cc_val_lo": 0, "cc_val_hi": 127,
        "pgm_lo": 0, "pgm_hi": 127,
        "pos_from": None, "pos_to": None,
    }
    c.update(overrides)
    return c


def _events_with_cc_pgm():
    """Liste de dicts imitant get_all_events() avec CC générique et Program
    Change (Phase 7 étape 4j) : 1 note, 2 CC, 1 Program Change."""
    return [
        {"type": "note", "offset": 0, "pad": 60, "vel": 100},
        {"type": "cc",   "offset": 2, "cc_num": 74, "value": 90},
        {"type": "cc",   "offset": 4, "cc_num": 7,  "value": 20},
        {"type": "pgm",  "offset": 6, "program": 42},
    ]


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
# Type "mod" — alias de filtre (type=="cc" and cc_num==1), Phase 7 étape 5f
# ---------------------------------------------------------------------------

def test_type_mod_isolates_cc1_no_sub_criteria():
    """"mod" n'est plus un vrai type d'événement : raccourci de filtre
    traduit en type=="cc" and cc_num==1."""
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(etype_filter="mod"))
    assert matched == {3}


def test_type_mod_excludes_other_cc_numbers():
    me = MidiEditor()
    ev = _events() + [{"type": "cc", "offset": 5, "cc_num": 7, "value": 20}]
    matched = me.filter_events(ev, _default_criteria(etype_filter="mod"))
    assert matched == {3}


def test_type_mod_ignores_cc_range_criteria():
    """"mod" n'a pas de sous-critères (comme avant 5f) : les bornes cc_num/
    cc_val, même resserrées, ne filtrent pas le CC#1 isolé."""
    me = MidiEditor()
    ev = _events()
    matched = me.filter_events(ev, _default_criteria(
        etype_filter="mod", cc_num_lo=50, cc_num_hi=60, cc_val_lo=0, cc_val_hi=1))
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


# ---------------------------------------------------------------------------
# CC générique / Program Change (Phase 7 étape 4j)
# ---------------------------------------------------------------------------

def test_type_cc_matches_only_cc_events():
    me = MidiEditor()
    ev = _events_with_cc_pgm()
    assert me.filter_events(ev, _default_criteria(etype_filter="cc")) == {1, 2}


def test_type_pgm_matches_only_program_change_events():
    me = MidiEditor()
    ev = _events_with_cc_pgm()
    assert me.filter_events(ev, _default_criteria(etype_filter="pgm")) == {3}


def test_type_all_includes_cc_and_pgm():
    me = MidiEditor()
    ev = _events_with_cc_pgm()
    assert me.filter_events(ev, _default_criteria()) == {0, 1, 2, 3}


def test_cc_num_range_filters_by_controller_number():
    me = MidiEditor()
    ev = _events_with_cc_pgm()
    matched = me.filter_events(ev, _default_criteria(etype_filter="cc",
                                                     cc_num_lo=70, cc_num_hi=80))
    assert matched == {1}        # CC#74 seul


def test_cc_value_range_filters_by_value():
    me = MidiEditor()
    ev = _events_with_cc_pgm()
    matched = me.filter_events(ev, _default_criteria(etype_filter="cc",
                                                     cc_val_lo=0, cc_val_hi=50))
    assert matched == {2}        # valeur 20 seule


def test_cc_num_and_value_ranges_combined():
    me = MidiEditor()
    ev = _events_with_cc_pgm()
    matched = me.filter_events(ev, _default_criteria(etype_filter="cc",
                                                     cc_num_lo=0, cc_num_hi=10,
                                                     cc_val_lo=0, cc_val_hi=50))
    assert matched == {2}        # CC#7 valeur 20
    matched = me.filter_events(ev, _default_criteria(etype_filter="cc",
                                                     cc_num_lo=0, cc_num_hi=10,
                                                     cc_val_lo=80, cc_val_hi=127))
    assert matched == set()      # CC#7 mais valeur hors plage


def test_pgm_range_filters_by_program_number():
    me = MidiEditor()
    ev = _events_with_cc_pgm()
    assert me.filter_events(ev, _default_criteria(etype_filter="pgm",
                                                   pgm_lo=40, pgm_hi=50)) == {3}
    assert me.filter_events(ev, _default_criteria(etype_filter="pgm",
                                                   pgm_lo=0, pgm_hi=10)) == set()


def test_cc_ranges_ignored_for_other_types():
    """Les bornes cc_num/cc_val ne s'appliquent qu'au type "cc" : en filtre
    "all", un CC hors plage passe quand même (même logique que note/bend)."""
    me = MidiEditor()
    ev = _events_with_cc_pgm()
    matched = me.filter_events(ev, _default_criteria(cc_num_lo=100, cc_num_hi=101))
    assert matched == {0, 1, 2, 3}


def test_cc_position_combined_with_type():
    me = MidiEditor()
    ev = _events_with_cc_pgm()
    matched = me.filter_events(ev, _default_criteria(etype_filter="cc",
                                                     pos_from=3, pos_to=10))
    assert matched == {2}


def test_cc_pgm_defaults_are_permissive():
    """Sans clés cc_*/pgm_* dans les critères, les valeurs par défaut de
    filter_events laissent tout passer."""
    me = MidiEditor()
    ev = _events_with_cc_pgm()
    assert me.filter_events(ev, {"active": True, "etype_filter": "cc"}) == {1, 2}
    assert me.filter_events(ev, {"active": True, "etype_filter": "pgm"}) == {3}
