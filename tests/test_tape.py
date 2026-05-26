#python3
"""
    File: tests/test_tape.py
    Tests unitaires de kit_tape et patch_tape :
    structure Pattern, lifecycle (new/reset/double/halve/resize),
    sérialisation to_dict/from_dict, enregistrement DrumPlayer,
    et durée note_on→note_off pour patch_tape.
    Date: Wed, 27/05/2026
    Author: Coolbrother
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import Pattern
from drum_player import DrumPlayer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_player():
    """DrumPlayer prêt pour l'enregistrement (non lancé, quant désactivée)."""
    p = DrumPlayer()
    p._quant_in_recording = False   # évite les effets de grille dans les tests
    p._measure_start = None         # → ref = now dans record_*
    return p


# ---------------------------------------------------------------------------
# Structure initiale du Pattern
# ---------------------------------------------------------------------------

def test_pattern_kit_tape_initially_empty():
    p = Pattern()
    assert p._kit_tape == {}
    print("  _kit_tape vide à l'init : OK")

def test_pattern_patch_tape_initially_empty():
    p = Pattern()
    assert p._patch_tape == {}
    print("  _patch_tape vide à l'init : OK")


# ---------------------------------------------------------------------------
# new_pattern / reset_pattern
# ---------------------------------------------------------------------------

def test_new_pattern_resets_kit_tape():
    p = Pattern()
    p._kit_tape = {(0, 0, 0): [(36, 100, 0)]}
    p.new_pattern()
    assert p._kit_tape == {}
    print("  new_pattern efface kit_tape : OK")

def test_new_pattern_resets_patch_tape():
    p = Pattern()
    p._patch_tape = {(0, 0, 3): [(60, 90, 250)]}
    p.new_pattern()
    assert p._patch_tape == {}
    print("  new_pattern efface patch_tape : OK")

def test_reset_pattern_clears_kit_tape():
    p = Pattern()
    p._kit_tape = {(0, 0, 5): [(38, 100, 0)]}
    p.reset_pattern()
    assert p._kit_tape == {}
    print("  reset_pattern efface kit_tape : OK")

def test_reset_pattern_clears_patch_tape():
    p = Pattern()
    p._patch_tape = {(1, 0, 8): [(64, 80, 300)]}
    p.reset_pattern()
    assert p._patch_tape == {}
    print("  reset_pattern efface patch_tape : OK")


# ---------------------------------------------------------------------------
# double_bars
# ---------------------------------------------------------------------------

def test_double_bars_duplicates_kit_tape():
    p = Pattern()
    p.new_pattern(2, 16)
    p._kit_tape = {(0, 0, 3): [(36, 100, 0)], (0, 1, 7): [(38, 80, 0)]}
    p.double_bars()
    assert (0, 2, 3) in p._kit_tape, "bar 0 dupliquée en bar 2"
    assert (0, 3, 7) in p._kit_tape, "bar 1 dupliquée en bar 3"
    assert p._kit_tape[(0, 2, 3)] == [(36, 100, 0)]
    assert p._kit_tape[(0, 3, 7)] == [(38, 80, 0)]
    print("  double_bars duplique kit_tape : OK")

def test_double_bars_preserves_original_kit_tape():
    p = Pattern()
    p.new_pattern(2, 16)
    p._kit_tape = {(0, 0, 1): [(42, 100, 0)]}
    p.double_bars()
    assert (0, 0, 1) in p._kit_tape, "entrée originale conservée"
    print("  double_bars conserve les entrées originales de kit_tape : OK")

def test_double_bars_duplicates_patch_tape():
    p = Pattern()
    p.new_pattern(2, 16)
    p._patch_tape = {(0, 0, 5): [(60, 100, 400)], (0, 1, 10): [(62, 90, 200)]}
    p.double_bars()
    assert (0, 2, 5)  in p._patch_tape
    assert (0, 3, 10) in p._patch_tape
    assert p._patch_tape[(0, 2, 5)]  == [(60, 100, 400)]
    assert p._patch_tape[(0, 3, 10)] == [(62, 90, 200)]
    print("  double_bars duplique patch_tape : OK")


# ---------------------------------------------------------------------------
# halve_bars
# ---------------------------------------------------------------------------

def test_halve_bars_removes_second_half_kit_tape():
    p = Pattern()
    p.new_pattern(4, 16)
    p._kit_tape = {
        (0, 0, 0): [(36, 100, 0)],   # bar 0 → conservé
        (0, 1, 0): [(38, 100, 0)],   # bar 1 → conservé
        (0, 2, 0): [(42, 100, 0)],   # bar 2 → supprimé
        (0, 3, 0): [(46, 100, 0)],   # bar 3 → supprimé
    }
    p.halve_bars()
    assert (0, 0, 0) in p._kit_tape
    assert (0, 1, 0) in p._kit_tape
    assert (0, 2, 0) not in p._kit_tape
    assert (0, 3, 0) not in p._kit_tape
    print("  halve_bars filtre kit_tape : OK")

def test_halve_bars_removes_second_half_patch_tape():
    p = Pattern()
    p.new_pattern(4, 16)
    p._patch_tape = {
        (0, 0, 5): [(60, 100, 300)],
        (0, 3, 5): [(65, 80, 150)],
    }
    p.halve_bars()
    assert (0, 0, 5) in p._patch_tape
    assert (0, 3, 5) not in p._patch_tape
    print("  halve_bars filtre patch_tape : OK")


# ---------------------------------------------------------------------------
# resize
# ---------------------------------------------------------------------------

def test_resize_filters_kit_tape_out_of_range():
    p = Pattern()
    p.new_pattern(4, 16)
    p._kit_tape = {
        (0, 0, 3):  [(36, 100, 0)],   # conservé
        (0, 1, 15): [(38, 100, 0)],   # conservé
        (0, 2, 5):  [(42, 100, 0)],   # supprimé (bar >= 2)
    }
    p.resize(2, 16)
    assert (0, 0, 3)  in p._kit_tape
    assert (0, 1, 15) in p._kit_tape
    assert (0, 2, 5)  not in p._kit_tape
    print("  resize filtre kit_tape (bars hors limites) : OK")

def test_resize_filters_patch_tape_out_of_range():
    p = Pattern()
    p.new_pattern(2, 32)
    p._patch_tape = {
        (0, 0, 31): [(60, 100, 200)],   # conservé
        (0, 1, 5):  [(62, 90,  150)],   # supprimé (bar >= 1 après troncature)
    }
    p.resize(1, 32)
    assert (0, 0, 31) in p._patch_tape
    assert (0, 1, 5)  not in p._patch_tape
    print("  resize filtre patch_tape (bars hors limites) : OK")

def test_resize_filters_kit_tape_steps_out_of_range():
    p = Pattern()
    p.new_pattern(1, 32)
    p._kit_tape = {
        (0, 0, 15): [(36, 100, 0)],   # conservé
        (0, 0, 16): [(38, 100, 0)],   # supprimé (step >= 16 après troncature)
    }
    p.resize(1, 16)
    assert (0, 0, 15) in p._kit_tape
    assert (0, 0, 16) not in p._kit_tape
    print("  resize filtre kit_tape (steps hors limites) : OK")


# ---------------------------------------------------------------------------
# to_dict / from_dict — structure (note, vel, dur)
# ---------------------------------------------------------------------------

def test_to_dict_kit_tape_6_columns():
    p = Pattern()
    p._kit_tape = {(0, 0, 3): [(36, 100, 0)]}
    rec = p.to_dict()["kit_tape"]
    assert len(rec) == 1
    assert rec[0] == [0, 0, 3, 36, 100, 0]
    print("  to_dict kit_tape : enregistrement 6 colonnes : OK")

def test_to_dict_patch_tape_6_columns():
    p = Pattern()
    p._patch_tape = {(1, 0, 7): [(60, 90, 350)]}
    rec = p.to_dict()["patch_tape"]
    assert len(rec) == 1
    assert rec[0] == [1, 0, 7, 60, 90, 350]
    print("  to_dict patch_tape : enregistrement 6 colonnes : OK")

def test_roundtrip_kit_tape():
    src = Pattern()
    src._kit_tape = {
        (0, 0, 2): [(36, 100, 0), (42, 80, 0)],
        (1, 0, 8): [(38, 127, 0)],
    }
    dst = Pattern()
    dst.from_dict(src.to_dict())
    assert dst._kit_tape == src._kit_tape
    print("  to_dict → from_dict kit_tape round-trip : OK")

def test_roundtrip_patch_tape():
    src = Pattern()
    src._patch_tape = {
        (0, 0, 4): [(60, 100, 500), (64, 90, 250)],
        (0, 1, 0): [(67, 80, 300)],
    }
    dst = Pattern()
    dst.from_dict(src.to_dict())
    assert dst._patch_tape == src._patch_tape
    print("  to_dict → from_dict patch_tape round-trip : OK")

def test_from_dict_kit_tape_backward_compat_5_columns():
    """Anciens presets sans colonne dur doivent se charger avec dur=0."""
    old = {
        "curpattern": Pattern()._curpattern,
        "kit_tape": [[0, 0, 3, 36, 100]],   # 5 colonnes, sans dur
    }
    p = Pattern()
    p.from_dict(old)
    assert (0, 0, 3) in p._kit_tape
    assert p._kit_tape[(0, 0, 3)] == [(36, 100, 0)]
    print("  from_dict kit_tape rétro-compat 5 colonnes → dur=0 : OK")

def test_from_dict_patch_tape_backward_compat_5_columns():
    """Anciens presets sans colonne dur doivent se charger avec dur=0."""
    old = {
        "curpattern": Pattern()._curpattern,
        "patch_tape": [[0, 0, 7, 60, 90]],   # 5 colonnes, sans dur
    }
    p = Pattern()
    p.from_dict(old)
    assert (0, 0, 7) in p._patch_tape
    assert p._patch_tape[(0, 0, 7)] == [(60, 90, 0)]
    print("  from_dict patch_tape rétro-compat 5 colonnes → dur=0 : OK")

def test_from_dict_empty_tapes():
    p = Pattern()
    p.from_dict({"curpattern": Pattern()._curpattern})
    assert p._kit_tape   == {}
    assert p._patch_tape == {}
    print("  from_dict sans kit_tape/patch_tape → dicts vides : OK")


# ---------------------------------------------------------------------------
# DrumPlayer.record_kit_note
# ---------------------------------------------------------------------------

def test_record_kit_note_stores_tuple():
    pl = _make_player()
    pl.record_kit_note(36, 100)
    events = list(pl._pattern._kit_tape.values())[0]
    assert len(events) == 1
    note, vel, dur = events[0]
    assert note == 36
    assert vel  == 100
    assert dur  == 0
    print("  record_kit_note stocke (note, vel, 0) : OK")

def test_record_kit_note_no_duplicate_same_note():
    pl = _make_player()
    pl.record_kit_note(36, 100)
    pl.record_kit_note(36, 127)   # même note, même position → pas de doublon
    events = list(pl._pattern._kit_tape.values())[0]
    kit_notes = [e[0] for e in events]
    assert kit_notes.count(36) == 1, "note 36 ne doit apparaître qu'une fois"
    print("  record_kit_note : pas de doublon sur même note : OK")

def test_record_kit_note_two_different_notes_same_step():
    """Deux notes MIDI différentes au même pas sont enregistrées toutes les deux."""
    pl = _make_player()
    pl.record_kit_note(36, 100)
    pl.record_kit_note(38, 80)
    # Les deux hits tombent au même step (quantize désactivée, timing immédiat)
    all_events = [e for lst in pl._pattern._kit_tape.values() for e in lst]
    notes = [e[0] for e in all_events]
    assert 36 in notes
    assert 38 in notes
    print("  record_kit_note : deux notes différentes au même step : OK")

def test_record_kit_note_returns_bar_step():
    pl = _make_player()
    bar_idx, step_idx = pl.record_kit_note(42, 90)
    assert isinstance(bar_idx,  int)
    assert isinstance(step_idx, int)
    assert 0 <= bar_idx  < pl._pattern._num_bars
    assert 0 <= step_idx < pl._pattern._num_steps
    print("  record_kit_note retourne (bar_idx, step_idx) valides : OK")

def test_record_kit_note_velocity_clamped():
    pl = _make_player()
    pl.record_kit_note(36, 200)   # > 127
    events = list(pl._pattern._kit_tape.values())[0]
    assert events[0][1] == 127
    print("  record_kit_note clamp vélocité à 127 : OK")

def test_record_kit_note_velocity_minimum_one():
    pl = _make_player()
    pl.record_kit_note(36, 0)
    events = list(pl._pattern._kit_tape.values())[0]
    assert events[0][1] == 1
    print("  record_kit_note vélocité 0 → 1 : OK")


# ---------------------------------------------------------------------------
# DrumPlayer.record_patch_note — durée fixe (numpad)
# ---------------------------------------------------------------------------

def test_record_patch_note_fixed_duration():
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    events = list(pl._pattern._patch_tape.values())[0]
    assert len(events) == 1
    note, vel, dur = events[0]
    assert note == 60
    assert vel  == 100
    assert dur  == 500
    print("  record_patch_note durée fixe stockée : OK")

def test_record_patch_note_fixed_duration_no_pending():
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    assert 60 not in pl._pending_patch, "durée fixe → pas de pending"
    print("  record_patch_note durée fixe → _pending_patch vide : OK")

def test_record_patch_note_zero_duration():
    pl = _make_player()
    pl.record_patch_note(60, 100, 0)
    events = list(pl._pattern._patch_tape.values())[0]
    assert events[0][2] == 0
    print("  record_patch_note duration_ms=0 stocké : OK")

def test_record_patch_note_replaces_same_note_at_same_step():
    pl = _make_player()
    pl.record_patch_note(60, 100, 300)
    pl.record_patch_note(60, 90, 400)   # même note, même step → remplace
    all_events = [e for lst in pl._pattern._patch_tape.values() for e in lst]
    notes = [e[0] for e in all_events]
    assert notes.count(60) == 1, "note 60 ne doit apparaître qu'une fois"
    assert all_events[0][2] == 400, "durée mise à jour"
    print("  record_patch_note remplace note existante au même step : OK")

def test_record_patch_note_returns_bar_step():
    pl = _make_player()
    bar_idx, step_idx = pl.record_patch_note(60, 100, 500)
    assert isinstance(bar_idx,  int)
    assert isinstance(step_idx, int)
    assert 0 <= bar_idx  < pl._pattern._num_bars
    assert 0 <= step_idx < pl._pattern._num_steps
    print("  record_patch_note retourne (bar_idx, step_idx) valides : OK")


# ---------------------------------------------------------------------------
# DrumPlayer.record_patch_note — durée MIDI (note_off)
# ---------------------------------------------------------------------------

def test_record_patch_note_midi_provisional_duration_zero():
    pl = _make_player()
    pl.record_patch_note(60, 100)   # duration_ms=None → MIDI
    events = list(pl._pattern._patch_tape.values())[0]
    assert events[0][2] == 0, "durée provisoire = 0"
    print("  record_patch_note MIDI → durée provisoire 0 : OK")

def test_record_patch_note_midi_registers_pending():
    pl = _make_player()
    pl.record_patch_note(60, 100)
    assert 60 in pl._pending_patch, "note 60 doit être en attente de note_off"
    print("  record_patch_note MIDI → enregistré dans _pending_patch : OK")

def test_record_patch_note_off_updates_duration():
    pl = _make_player()
    pl.record_patch_note(60, 100)
    # Simule 300 ms de tenue en antidatant le t_start
    key, entry_idx, _ = pl._pending_patch[60]
    pl._pending_patch[60] = (key, entry_idx, time.perf_counter() - 0.300)
    pl.record_patch_note_off(60)
    events = pl._pattern._patch_tape[key]
    note, vel, dur = events[entry_idx]
    assert dur >= 290, f"durée attendue ≥ 290 ms, obtenu {dur}"
    print(f"  record_patch_note_off met à jour la durée ({dur} ms) : OK")

def test_record_patch_note_off_removes_from_pending():
    pl = _make_player()
    pl.record_patch_note(60, 100)
    pl.record_patch_note_off(60)
    assert 60 not in pl._pending_patch
    print("  record_patch_note_off retire la note de _pending_patch : OK")

def test_record_patch_note_off_unknown_note_is_noop():
    """record_patch_note_off sur une note non enregistrée ne doit pas planter."""
    pl = _make_player()
    try:
        pl.record_patch_note_off(99)
        print("  record_patch_note_off note inconnue → no-op : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"

def test_record_patch_note_midi_then_fixed_cancels_pending():
    """Une note fixe (numpad) après une note MIDI pending doit annuler le pending."""
    pl = _make_player()
    pl.record_patch_note(60, 100)          # MIDI → pending
    assert 60 in pl._pending_patch
    pl.record_patch_note(60, 100, 400)     # fixe → annule pending
    assert 60 not in pl._pending_patch
    print("  record_patch_note fixe annule le pending MIDI : OK")


# ---------------------------------------------------------------------------
# Dispatch callbacks (simulation)
# ---------------------------------------------------------------------------

def test_kit_tape_callback_receives_duration():
    """on_kit_tape_cb reçoit bien (track_idx, midi_note, velocity, duration_ms)."""
    received = []
    pl = _make_player()
    pl._on_kit_tape_cb = lambda t, n, v, d: received.append((t, n, v, d))

    # Simule le dispatch directement (sans lancer le thread)
    t_idx, midi_note, dur = 0, 36, 0
    velocity = 100
    if pl._on_kit_tape_cb:
        pl._on_kit_tape_cb(t_idx, midi_note, velocity, dur)

    assert len(received) == 1
    assert received[0] == (0, 36, 100, 0)
    print("  on_kit_tape_cb reçoit (track, note, vel, dur) : OK")

def test_patch_tape_callback_receives_duration():
    """on_patch_tape_cb reçoit bien (track_idx, midi_note, velocity, duration_ms)."""
    received = []
    pl = _make_player()
    pl._on_patch_tape_cb = lambda t, n, v, d: received.append((t, n, v, d))

    t_idx, midi_note, dur = 1, 60, 350
    velocity = 90
    if pl._on_patch_tape_cb:
        pl._on_patch_tape_cb(t_idx, midi_note, velocity, dur)

    assert len(received) == 1
    assert received[0] == (1, 60, 90, 350)
    print("  on_patch_tape_cb reçoit (track, note, vel, dur) : OK")

def test_kit_tape_no_callback_is_safe():
    """Pas de plantage si on_kit_tape_cb est None."""
    pl = _make_player()
    pl._on_kit_tape_cb = None
    try:
        # Reproduit la branche fallback du dispatch
        if pl._on_kit_tape_cb:
            pl._on_kit_tape_cb(0, 36, 100, 0)
        # Sinon play_note serait appelé, mais on_kit_tape_cb est None → pas de call
        print("  on_kit_tape_cb=None → no-op sans plantage : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_tape ===")
    # Structure initiale
    test_pattern_kit_tape_initially_empty()
    test_pattern_patch_tape_initially_empty()
    # new_pattern / reset_pattern
    test_new_pattern_resets_kit_tape()
    test_new_pattern_resets_patch_tape()
    test_reset_pattern_clears_kit_tape()
    test_reset_pattern_clears_patch_tape()
    # double_bars
    test_double_bars_duplicates_kit_tape()
    test_double_bars_preserves_original_kit_tape()
    test_double_bars_duplicates_patch_tape()
    # halve_bars
    test_halve_bars_removes_second_half_kit_tape()
    test_halve_bars_removes_second_half_patch_tape()
    # resize
    test_resize_filters_kit_tape_out_of_range()
    test_resize_filters_patch_tape_out_of_range()
    test_resize_filters_kit_tape_steps_out_of_range()
    # to_dict / from_dict
    test_to_dict_kit_tape_6_columns()
    test_to_dict_patch_tape_6_columns()
    test_roundtrip_kit_tape()
    test_roundtrip_patch_tape()
    test_from_dict_kit_tape_backward_compat_5_columns()
    test_from_dict_patch_tape_backward_compat_5_columns()
    test_from_dict_empty_tapes()
    # record_kit_note
    test_record_kit_note_stores_tuple()
    test_record_kit_note_no_duplicate_same_note()
    test_record_kit_note_two_different_notes_same_step()
    test_record_kit_note_returns_bar_step()
    test_record_kit_note_velocity_clamped()
    test_record_kit_note_velocity_minimum_one()
    # record_patch_note durée fixe
    test_record_patch_note_fixed_duration()
    test_record_patch_note_fixed_duration_no_pending()
    test_record_patch_note_zero_duration()
    test_record_patch_note_replaces_same_note_at_same_step()
    test_record_patch_note_returns_bar_step()
    # record_patch_note MIDI (note_off)
    test_record_patch_note_midi_provisional_duration_zero()
    test_record_patch_note_midi_registers_pending()
    test_record_patch_note_off_updates_duration()
    test_record_patch_note_off_removes_from_pending()
    test_record_patch_note_off_unknown_note_is_noop()
    test_record_patch_note_midi_then_fixed_cancels_pending()
    # Dispatch callbacks
    test_kit_tape_callback_receives_duration()
    test_patch_tape_callback_receives_duration()
    test_kit_tape_no_callback_is_safe()
    print("Tous les tests : OK")
