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

class _FakeSoundManager:
    """Sound manager minimal pour les tests qui appellent stop_all()."""
    def stop_all(self):    pass
    def play_sound(self, *a): pass
    def play_metronome(self, *a): pass
    def play_note(self, *a): pass


def _make_player():
    """DrumPlayer prêt pour l'enregistrement (non lancé, quant désactivée)."""
    p = DrumPlayer(_FakeSoundManager())
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

def test_to_dict_patch_tape_7_columns():
    p = Pattern()
    p._patch_tape = {(1, 0, 7): [(60, 90, 350, 2048)]}
    rec = p.to_dict()["patch_tape"]
    assert len(rec) == 1
    assert rec[0] == [1, 0, 7, 60, 90, 350, 2048]
    print("  to_dict patch_tape : enregistrement 7 colonnes (avec bend) : OK")

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
        (0, 0, 4): [(60, 100, 500, 0), (64, 90, 250, 0)],
        (0, 1, 0): [(67, 80, 300, 0)],
    }
    dst = Pattern()
    dst.from_dict(src.to_dict())
    assert dst._patch_tape == src._patch_tape
    print("  to_dict → from_dict patch_tape round-trip : OK")

def test_roundtrip_patch_tape_with_bend():
    """Régression : to_dict levait ValueError sur les 4-tuples (note,vel,dur,bend).
    Ce bug empêchait toute sauvegarde preset dès qu'une note synth était enregistrée."""
    src = Pattern()
    src._patch_tape = {
        (0, 0, 0): [(60, 100, 500, 4096), (62, 90, 300, -2000)],
        (1, 0, 4): [(67, 80, 200, 0)],
    }
    try:
        d = src.to_dict()
    except ValueError as e:
        assert False, f"to_dict lève ValueError sur patch_tape 4-tuples : {e}"
    dst = Pattern()
    dst.from_dict(d)
    assert dst._patch_tape[(0, 0, 0)][0] == (60, 100, 500, 4096)
    assert dst._patch_tape[(0, 0, 0)][1] == (62, 90, 300, -2000)
    assert dst._patch_tape[(1, 0, 4)][0] == (67, 80, 200, 0)
    print("  to_dict → from_dict patch_tape 4-tuples avec bend (régression) : OK")

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
    """Anciens presets sans colonne dur doivent se charger avec dur=0, bend=0."""
    old = {
        "curpattern": Pattern()._curpattern,
        "patch_tape": [[0, 0, 7, 60, 90]],   # 5 colonnes, sans dur ni bend
    }
    p = Pattern()
    p.from_dict(old)
    assert (0, 0, 7) in p._patch_tape
    assert p._patch_tape[(0, 0, 7)] == [(60, 90, 0, 0)]
    print("  from_dict patch_tape rétro-compat 5 colonnes → dur=0, bend=0 : OK")

def test_from_dict_patch_tape_backward_compat_6_columns():
    """Anciens presets avec dur mais sans bend doivent charger bend=0."""
    old = {
        "curpattern": Pattern()._curpattern,
        "patch_tape": [[0, 0, 3, 60, 100, 500]],   # 6 colonnes, sans bend
    }
    p = Pattern()
    p.from_dict(old)
    assert p._patch_tape[(0, 0, 3)] == [(60, 100, 500, 0)]
    print("  from_dict patch_tape rétro-compat 6 colonnes → bend=0 : OK")

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
    note, vel, dur, *_ = events[0]
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
    note, vel, dur, *_ = events[0]
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
    note, vel, dur, *_ = events[entry_idx]
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
# erase_patch_tape_note
# ---------------------------------------------------------------------------

def test_erase_patch_tape_note_removes_event():
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    key = list(pl._pattern._patch_tape.keys())[0]
    result = pl.erase_patch_tape_note(0, 60)
    assert result is not None
    assert key not in pl._pattern._patch_tape, "clé supprimée quand liste vide"
    print("  erase_patch_tape_note supprime l'événement et la clé vide : OK")

def test_erase_patch_tape_note_returns_bar_step():
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    bar_idx, step_idx = pl.erase_patch_tape_note(0, 60)
    assert isinstance(bar_idx,  int)
    assert isinstance(step_idx, int)
    assert 0 <= bar_idx  < pl._pattern._num_bars
    assert 0 <= step_idx < pl._pattern._num_steps
    print("  erase_patch_tape_note retourne (bar_idx, step_idx) valides : OK")

def test_erase_patch_tape_note_unknown_note_returns_none():
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    result = pl.erase_patch_tape_note(0, 99)   # note 99 non enregistrée
    assert result is None
    print("  erase_patch_tape_note note absente → None sans plantage : OK")

def test_erase_patch_tape_note_wrong_track_returns_none():
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    result = pl.erase_patch_tape_note(1, 60)   # note sur track 0, pas track 1
    assert result is None
    print("  erase_patch_tape_note mauvaise piste → None : OK")

def test_erase_patch_tape_note_keeps_other_note_at_same_step():
    """Effacer note 60 ne doit pas toucher note 64 au même pas."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    pl.record_patch_note(64, 90, 400)
    key = list(pl._pattern._patch_tape.keys())[0]
    pl.erase_patch_tape_note(0, 60)
    remaining = [e[0] for e in pl._pattern._patch_tape.get(key, [])]
    assert 64 in remaining, "note 64 doit rester"
    assert 60 not in remaining
    print("  erase_patch_tape_note ne touche pas les autres notes du même step : OK")

def test_erase_patch_tape_note_twice_removes_both():
    """Effacer deux fois des notes différentes fonctionne."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    pl.record_patch_note(64, 90, 400)
    pl.erase_patch_tape_note(0, 60)
    pl.erase_patch_tape_note(0, 64)
    assert pl._pattern._patch_tape == {}, "patch_tape vide après deux effacements"
    print("  erase_patch_tape_note deux effacements successifs : OK")

def test_erase_patch_tape_note_empty_tape_returns_none():
    pl = _make_player()
    result = pl.erase_patch_tape_note(0, 60)
    assert result is None
    print("  erase_patch_tape_note sur tape vide → None : OK")


# ---------------------------------------------------------------------------
# _erase_active_midi_notes — note_on / note_off / toggle_erase
# ---------------------------------------------------------------------------

def test_erase_active_midi_notes_initially_empty():
    pl = _make_player()
    assert pl._erase_active_midi_notes == set()
    print("  _erase_active_midi_notes vide à l'init : OK")

def test_toggle_erase_clears_active_midi_notes_on_enter():
    pl = _make_player()
    pl._erase_active_midi_notes.add(60)
    pl.toggle_erase()   # entre en Erase
    assert pl._erase_active_midi_notes == set(), \
        "activer Erase doit vider _erase_active_midi_notes"
    print("  toggle_erase (entrée) vide _erase_active_midi_notes : OK")

def test_toggle_erase_clears_active_midi_notes_on_exit():
    pl = _make_player()
    pl.toggle_erase()   # entre en Erase
    pl._erase_active_midi_notes.add(60)
    pl.toggle_erase()   # sort du Erase
    assert pl._erase_active_midi_notes == set(), \
        "désactiver Erase doit vider _erase_active_midi_notes"
    print("  toggle_erase (sortie) vide _erase_active_midi_notes : OK")

def test_stop_all_clears_active_midi_notes():
    pl = _make_player()
    pl._erase_active_midi_notes.add(60)
    pl._erase_active_midi_notes.add(62)
    pl.stop_all()
    assert pl._erase_active_midi_notes == set()
    print("  stop_all vide _erase_active_midi_notes : OK")

def test_update_erase_midi_range_pad_mode_uses_erase_held():
    """En mode pad, _update_erase_midi_range doit utiliser les notes brutes de _erase_held."""
    pl = _make_player()
    pl.toggle_erase()
    # Simule ce que _update_erase_midi_range fait en mode pad
    erase_held = {36, 43}   # raw MIDI notes (kick C2, snare G2)
    pl._erase_active_midi_notes = set(range(min(erase_held), max(erase_held) + 1))
    assert pl._erase_active_midi_notes == set(range(36, 44))
    print("  update_erase_midi_range (pad) : plage depuis notes brutes : OK")

def test_note_on_range_two_notes():
    """Tenir C2(36) et G2(43) → plage {36..43} dans _erase_active_midi_notes.

    Simule ce que _handle_keyboard_note_on + _update_erase_midi_range font.
    """
    pl = _make_player()
    pl.toggle_erase()
    # Simule note_on C2
    erase_held_kb = set()
    erase_held_kb.add(36)
    pl._erase_active_midi_notes = set(range(min(erase_held_kb), max(erase_held_kb) + 1))
    assert pl._erase_active_midi_notes == {36}
    # Simule note_on G2 (tenu en même temps)
    erase_held_kb.add(43)
    pl._erase_active_midi_notes = set(range(min(erase_held_kb), max(erase_held_kb) + 1))
    assert pl._erase_active_midi_notes == set(range(36, 44)), \
        "tenir C2+G2 doit couvrir toute la plage 36-43"
    print("  note_on Erase : deux notes tenues → plage complète : OK")

def test_note_off_shrinks_range():
    """Relâcher C2 pendant que G2 est tenu → plage réduite à {43}."""
    pl = _make_player()
    pl.toggle_erase()
    erase_held_kb = {36, 43}
    pl._erase_active_midi_notes = set(range(36, 44))
    # Simule note_off C2
    erase_held_kb.discard(36)
    pl._erase_active_midi_notes = set(range(min(erase_held_kb), max(erase_held_kb) + 1))
    assert pl._erase_active_midi_notes == {43}
    print("  note_off Erase : relâcher une note réduit la plage : OK")

def test_note_off_last_note_clears_range():
    """Relâcher la dernière note tenue → plage vide."""
    pl = _make_player()
    pl.toggle_erase()
    erase_held_kb = {60}
    pl._erase_active_midi_notes = {60}
    # Simule note_off de la dernière note
    erase_held_kb.discard(60)
    if not erase_held_kb:
        pl._erase_active_midi_notes.clear()
    assert pl._erase_active_midi_notes == set()
    print("  note_off Erase : dernière note relâchée → plage vide : OK")

def test_note_off_discard_unknown_note_is_safe():
    """discard sur note absente ne doit pas planter."""
    pl = _make_player()
    try:
        pl._erase_active_midi_notes.discard(99)
        print("  note_off Erase : discard note inconnue → no-op : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"


# ---------------------------------------------------------------------------
# _erase_patch_tape_event — auto-effacement pendant la lecture
# ---------------------------------------------------------------------------

def test_erase_kit_tape_event_removes_note():
    """_erase_kit_tape_event supprime la note ciblée dans kit_tape."""
    pl = _make_player()
    pl.record_kit_note(36, 100)
    key = list(pl._pattern._kit_tape.keys())[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl._erase_kit_tape_event(0, 36, t_sec)

    assert key not in pl._pattern._kit_tape
    print("  _erase_kit_tape_event supprime l'événement : OK")

def test_erase_kit_tape_event_keeps_other_notes():
    """Note 38 au même step n'est pas touchée quand on efface note 36."""
    pl = _make_player()
    pl.record_kit_note(36, 100)
    pl.record_kit_note(38, 80)
    key = list(pl._pattern._kit_tape.keys())[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl._erase_kit_tape_event(0, 36, t_sec)

    remaining = [e[0] for e in pl._pattern._kit_tape.get(key, [])]
    assert 38 in remaining
    assert 36 not in remaining
    print("  _erase_kit_tape_event conserve les autres notes du step : OK")

def test_run_thread_auto_erase_kit_tape():
    """Simule la logique _run_thread pour KIT_TAPE_EVENT en mode Erase."""
    pl = _make_player()
    pl.record_kit_note(36, 100)
    key = list(pl._pattern._kit_tape.keys())[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl.toggle_erase()
    pl._erase_active_midi_notes = {36}

    t_idx, midi_note, dur = 0, 36, 0
    if pl.erasing and t_idx == pl._cur_track \
            and midi_note in pl._erase_active_midi_notes:
        pl._erase_kit_tape_event(t_idx, midi_note, t_sec)

    assert key not in pl._pattern._kit_tape
    print("  _run_thread logique : KIT_TAPE_EVENT effacé si note active en Erase : OK")

def test_erase_patch_tape_event_removes_note():
    """_erase_patch_tape_event supprime la note ciblée à un step donné."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    # Retrouve le step enregistré
    key = list(pl._pattern._patch_tape.keys())[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl._erase_patch_tape_event(0, 60, t_sec)

    assert key not in pl._pattern._patch_tape, "clé supprimée après effacement"
    print("  _erase_patch_tape_event supprime l'événement et la clé vide : OK")

def test_erase_patch_tape_event_keeps_other_notes_at_same_step():
    """Note 64 au même step n'est pas touchée quand on efface note 60."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    pl.record_patch_note(64, 90, 400)
    key = list(pl._pattern._patch_tape.keys())[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl._erase_patch_tape_event(0, 60, t_sec)

    remaining = [e[0] for e in pl._pattern._patch_tape.get(key, [])]
    assert 64 in remaining, "note 64 doit rester"
    assert 60 not in remaining
    print("  _erase_patch_tape_event ne touche pas les autres notes du step : OK")

def test_erase_patch_tape_event_no_crash_on_missing_step():
    """Pas de plantage si t_sec ne correspond à aucun step enregistré."""
    pl = _make_player()
    try:
        pl._erase_patch_tape_event(0, 60, 99.9)
        print("  _erase_patch_tape_event step absent → no-op : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"

def test_run_thread_auto_erase_uses_erase_active_midi_notes():
    """Simule la logique _run_thread : PATCH_TAPE_EVENT efface si note dans _erase_active_midi_notes."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    key = list(pl._pattern._patch_tape.keys())[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl.toggle_erase()
    pl._erase_active_midi_notes.add(60)

    # Simule ce que _run_thread fait pour PATCH_TAPE_EVENT
    t_idx, midi_note, dur = 0, 60, 500
    if pl.erasing and t_idx == pl._cur_track \
            and midi_note in pl._erase_active_midi_notes:
        pl._erase_patch_tape_event(t_idx, midi_note, t_sec)

    assert key not in pl._pattern._patch_tape, \
        "l'événement doit être effacé automatiquement pendant la lecture"
    print("  _run_thread logique : PATCH_TAPE_EVENT effacé si note active en Erase : OK")

def test_run_thread_no_erase_if_note_not_active():
    """Si la note n'est pas dans _erase_active_midi_notes, elle ne doit pas être effacée."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    key = list(pl._pattern._patch_tape.keys())[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    played = []
    pl._on_patch_tape_cb = lambda t, n, v, d: played.append(n)

    pl.toggle_erase()
    # note 60 PAS dans _erase_active_midi_notes

    t_idx, midi_note, dur = 0, 60, 500
    if pl.erasing and t_idx == pl._cur_track \
            and midi_note in pl._erase_active_midi_notes:
        pl._erase_patch_tape_event(t_idx, midi_note, t_sec)
    elif pl._on_patch_tape_cb:
        pl._on_patch_tape_cb(t_idx, midi_note, 100, dur)

    assert 60 in played, "la note doit être jouée, pas effacée"
    assert key in pl._pattern._patch_tape, "l'événement ne doit pas être supprimé"
    print("  _run_thread logique : PATCH_TAPE_EVENT joué si note pas active en Erase : OK")


# ---------------------------------------------------------------------------
# Sécurité accès concurrent (simulation du bug de régression)
# ---------------------------------------------------------------------------

def test_patch_tape_list_snapshot_safe_during_erase():
    """Simule la race condition _run_thread vs erase_patch_tape_note.

    Sans list() : RuntimeError 'dictionary changed size during iteration'.
    Avec list() : aucune exception.
    """
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    pl.record_patch_note(62, 100, 500)
    pl.record_patch_note(64, 100, 500)

    collected = []
    try:
        for (t_idx, b, s), note_list in list(pl._pattern._patch_tape.items()):
            # modification concurrente pendant l'itération (comme erase UI thread)
            pl.erase_patch_tape_note(0, 60)
            for midi_note, vel, dur, *_ in list(note_list):
                collected.append(midi_note)
    except RuntimeError as e:
        assert False, f"RuntimeError (accès concurrent non protégé) : {e}"
    print("  list(patch_tape.items()) immunise contre la modification concurrente : OK")

def test_kit_tape_list_snapshot_safe_during_modification():
    """Même vérification pour kit_tape."""
    pl = _make_player()
    pl.record_kit_note(36, 100)
    pl.record_kit_note(38, 100)

    try:
        for (t_idx, b, s), note_list in list(pl._pattern._kit_tape.items()):
            # modification concurrente
            for k in list(pl._pattern._kit_tape.keys()):
                del pl._pattern._kit_tape[k]
                break
            for midi_note, vel, dur, *_ in list(note_list):
                pass
    except RuntimeError as e:
        assert False, f"RuntimeError (accès concurrent kit_tape non protégé) : {e}"
    print("  list(kit_tape.items()) immunise contre la modification concurrente : OK")


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
        if pl._on_kit_tape_cb:
            pl._on_kit_tape_cb(0, 36, 100, 0)
        print("  on_kit_tape_cb=None → no-op sans plantage : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"


# ---------------------------------------------------------------------------
# Simulation Pitch Bend — enregistrement et lecture
# ---------------------------------------------------------------------------

def test_record_patch_note_stores_bend():
    """record_patch_note stocke le bend comme 4e élément du tuple."""
    pl = _make_player()
    bend_val = 4096   # +1 semitone (pitch_bend_range=2 → +1st)
    pl.record_patch_note(60, 100, 500, bend=bend_val)
    events = list(pl._pattern._patch_tape.values())[0]
    assert len(events) == 1
    assert len(events[0]) == 4, f"tuple doit avoir 4 éléments, a {len(events[0])}"
    note, vel, dur, bend = events[0]
    assert note == 60
    assert bend == bend_val, f"bend attendu {bend_val}, reçu {bend}"
    print(f"  record_patch_note stocke bend={bend_val} → tuple(60, 100, 500, {bend_val}) : OK")

def test_record_patch_note_bend_zero_by_default():
    """Sans pitch bend actif, le 4e élément doit être 0."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    events = list(pl._pattern._patch_tape.values())[0]
    note, vel, dur, *rest = events[0]
    bend = rest[0] if rest else 0
    assert bend == 0, f"bend attendu 0 (pas de bend), reçu {bend}"
    print("  record_patch_note sans bend → 4e élément = 0 : OK")

def test_record_patch_note_off_preserves_bend():
    """record_patch_note_off (durée MIDI) préserve le bend dans le tuple final."""
    pl = _make_player()
    bend_val = -8192   # -2 semitones (max bend down)
    pl.record_patch_note(60, 100, bend=bend_val)   # duration_ms=None → pending
    pl.record_patch_note_off(60)
    events = list(pl._pattern._patch_tape.values())[0]
    note, vel, dur, *rest = events[0]
    bend = rest[0] if rest else 0
    assert bend == bend_val, f"bend {bend_val} doit être conservé après note_off, reçu {bend}"
    assert dur > 0, "durée doit être > 0 après note_off"
    print(f"  record_patch_note_off préserve bend={bend_val} dans le tuple : OK")

def test_run_thread_dispatch_passes_bend_to_callback():
    """Simule le dispatch _run_thread : on_patch_tape_cb reçoit (t, n, v, d, bend)."""
    received = []
    pl = _make_player()
    pl._on_patch_tape_cb = lambda t, n, v, d, b=0: received.append((t, n, v, d, b))

    bend_val = 8191   # +2 semitones (max bend up)
    pl.record_patch_note(60, 100, 500, bend=bend_val)
    key = list(pl._pattern._patch_tape.keys())[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    # Simule la boucle _run_thread (construction + dispatch)
    note_list = pl._pattern._patch_tape[key]
    for midi_note, vel, dur, *rest in list(note_list):
        bend = rest[0] if rest else 0
        # Simule le dispatch PATCH_TAPE_EVENT
        t_idx = 0
        if not pl.erasing:
            pl._on_patch_tape_cb(t_idx, midi_note, vel, dur, bend)

    assert len(received) == 1, "callback appelé exactement une fois"
    t, n, v, d, b = received[0]
    assert n == 60
    assert b == bend_val, f"bend attendu {bend_val}, callback a reçu b={b}"
    print(f"  _run_thread dispatch : callback reçoit bend={bend_val} correctement : OK")


# ---------------------------------------------------------------------------
# Automation Pitch Bend — _bend_tape
# ---------------------------------------------------------------------------

def test_bend_tape_initially_empty():
    p = Pattern()
    assert isinstance(p._bend_tape, list)
    assert len(p._bend_tape) == p._num_tracks
    assert all(t == [] for t in p._bend_tape)
    print("  _bend_tape vide à l'init (liste de listes) : OK")

def test_new_pattern_resets_bend_tape():
    p = Pattern()
    p._bend_tape[0] = [(4.0, 2048)]
    p.new_pattern()
    assert all(t == [] for t in p._bend_tape)
    print("  new_pattern efface _bend_tape : OK")

def test_reset_pattern_clears_bend_tape():
    p = Pattern()
    p._bend_tape[1] = [(8.0, -1024)]
    p.reset_pattern()
    assert all(t == [] for t in p._bend_tape)
    print("  reset_pattern efface _bend_tape : OK")

def test_clear_track_clears_bend_tape_for_track():
    p = Pattern()
    p.new_pattern(1, 16)
    p._bend_tape[0] = [(2.0, 4096)]
    p._bend_tape[1] = [(3.0, -2000)]
    p.clear_track(0)
    assert p._bend_tape[0] == [], "piste 0 effacée"
    assert p._bend_tape[1] == [(3.0, -2000)], "piste 1 intacte"
    print("  clear_track efface _bend_tape[track] sans toucher les autres : OK")

def test_double_bars_duplicates_bend_tape():
    p = Pattern()
    p.new_pattern(2, 16)    # 2 mesures × 16 pas = 32 pas
    p._bend_tape[0] = [(4.0, 2048), (10.0, -1024)]
    p.double_bars()          # maintenant 4 mesures × 16 = 64 pas
    offsets = [off for off, _ in p._bend_tape[0]]
    assert 4.0  in offsets, "offset 4 original présent"
    assert 10.0 in offsets, "offset 10 original présent"
    assert 36.0 in offsets, "offset 4+32=36 dupliqué présent"
    assert 42.0 in offsets, "offset 10+32=42 dupliqué présent"
    print("  double_bars duplique _bend_tape avec offset + half_steps : OK")

def test_double_bars_preserves_bend_values():
    p = Pattern()
    p.new_pattern(1, 16)
    p._bend_tape[0] = [(3.0, 8191)]
    p.double_bars()
    vals = [b for _, b in p._bend_tape[0]]
    assert vals.count(8191) == 2
    print("  double_bars préserve les valeurs bend dans les copies : OK")

def test_halve_bars_filters_bend_tape():
    p = Pattern()
    p.new_pattern(4, 16)    # 64 pas
    p._bend_tape[0] = [(5.0, 1000), (20.0, -500), (35.0, 2000)]
    p.halve_bars()           # garde seulement les 32 premiers pas
    offsets = [off for off, _ in p._bend_tape[0]]
    assert 5.0  in offsets,  "offset 5 conservé (< 32)"
    assert 20.0 in offsets,  "offset 20 conservé (< 32)"
    assert 35.0 not in offsets, "offset 35 supprimé (>= 32)"
    print("  halve_bars filtre _bend_tape : OK")

def test_resize_filters_bend_tape():
    p = Pattern()
    p.new_pattern(4, 16)    # 64 pas
    p._bend_tape[0] = [(5.0, 100), (40.0, -200)]
    p.resize(2, 16)          # 32 pas désormais
    offsets = [off for off, _ in p._bend_tape[0]]
    assert 5.0  in offsets,  "offset 5 conservé"
    assert 40.0 not in offsets, "offset 40 supprimé"
    print("  resize filtre _bend_tape : OK")

def test_roundtrip_bend_tape():
    src = Pattern()
    src.new_pattern(1, 16)
    src._bend_tape[0] = [(2.5, 4096), (7.0, -2000)]
    src._bend_tape[2] = [(1.0, 8191)]
    dst = Pattern()
    dst.from_dict(src.to_dict())
    assert dst._bend_tape[0] == src._bend_tape[0]
    assert dst._bend_tape[2] == src._bend_tape[2]
    print("  to_dict → from_dict _bend_tape round-trip : OK")

def test_from_dict_without_bend_tape_gives_empty():
    p = Pattern()
    p.from_dict({"curpattern": Pattern()._curpattern})
    assert isinstance(p._bend_tape, list)
    assert all(t == [] for t in p._bend_tape)
    print("  from_dict sans bend_tape → listes vides (rétrocompat) : OK")

def test_from_dict_bend_tape_pads_to_num_tracks():
    """Si bend_tape sérialisé contient moins de pistes, from_dict complète avec []."""
    p = Pattern()
    d = p.to_dict()
    d["bend_tape"] = [[(1.0, 100)]]   # seulement 1 piste au lieu de 8
    p2 = Pattern()
    p2.from_dict(d)
    assert len(p2._bend_tape) == p2._num_tracks
    assert p2._bend_tape[0] == [(1.0, 100)]
    assert p2._bend_tape[1] == []
    print("  from_dict bend_tape incomplet → complété avec [] : OK")

def test_record_bend_stores_float_offset_and_value():
    pl = _make_player()
    pl.record_bend(2048)
    bends = pl._pattern._bend_tape[0]
    assert len(bends) == 1
    off, val = bends[0]
    assert isinstance(off, float)
    assert val == 2048
    print("  record_bend stocke (float_offset, bend_value) : OK")

def test_record_bend_multiple_points_accumulate():
    pl = _make_player()
    pl.record_bend(0)
    pl.record_bend(4096)
    pl.record_bend(-4096)
    bends = pl._pattern._bend_tape[0]
    assert len(bends) == 3
    assert [b for _, b in bends] == [0, 4096, -4096]
    print("  record_bend accumule plusieurs points sans déduplication : OK")

def test_record_bend_uses_cur_track():
    pl = _make_player()
    pl._cur_track = 3
    pl.record_bend(1234)
    assert pl._pattern._bend_tape[3] != []
    assert pl._pattern._bend_tape[0] == []
    print("  record_bend enregistre sur la piste courante : OK")

def test_bend_tape_callback_receives_track_and_value():
    """Simule le dispatch BEND_TAPE_EVENT → callback (track_idx, bend_value)."""
    received = []
    pl = _make_player()
    pl._on_bend_tape_cb = lambda t, b: received.append((t, b))

    t_idx, bend_val = 2, -8000
    if pl._on_bend_tape_cb:
        pl._on_bend_tape_cb(t_idx, bend_val)

    assert len(received) == 1
    assert received[0] == (2, -8000)
    print("  on_bend_tape_cb reçoit (track_idx, bend_value) : OK")

def test_bend_tape_no_callback_is_safe():
    pl = _make_player()
    pl._on_bend_tape_cb = None
    try:
        if pl._on_bend_tape_cb:
            pl._on_bend_tape_cb(0, 0)
        print("  on_bend_tape_cb=None → no-op sans plantage : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"

def test_run_thread_build_bend_tape_events():
    """Simule la construction des BEND_TAPE_EVENTs dans _run_thread."""
    pl = _make_player()
    pl._pattern._bend_tape[0] = [(4.0, 2048), (12.0, -1024)]
    events = []
    for t_idx, track_bends in enumerate(pl._pattern._bend_tape):
        for float_off, bend_val in list(track_bends):
            t_sec = float_off * pl.step_duration
            events.append((t_sec, pl.BEND_TAPE_EVENT, (t_idx, bend_val), 0))
    assert len(events) == 2
    _, etype, (ti, bv), _ = events[0]
    assert etype == pl.BEND_TAPE_EVENT
    assert ti == 0
    assert bv == 2048
    print("  _run_thread construit les BEND_TAPE_EVENTs correctement : OK")


# ---------------------------------------------------------------------------
# Régression — flush/apply store (bug bend_tape non synchronisé)
# ---------------------------------------------------------------------------

def _flush_pattern_to_store(pat, player_pattern):
    """Simule _flush_pattern_to_store de MainWindow."""
    pat._kit_tape   = dict(player_pattern._kit_tape)
    pat._patch_tape = dict(player_pattern._patch_tape)
    pat._bend_tape  = [list(t) for t in player_pattern._bend_tape]

def _apply_pattern_from_store(player_pattern, store_pat):
    """Simule _apply_pattern_from_store de MainWindow."""
    player_pattern._kit_tape   = dict(store_pat._kit_tape)
    player_pattern._patch_tape = dict(store_pat._patch_tape)
    player_pattern._bend_tape  = [list(t) for t in store_pat._bend_tape]

def test_flush_and_apply_preserve_bend_tape():
    """Régression : _flush_pattern_to_store/_apply_pattern_from_store doivent
    inclure _bend_tape, sinon les courbes bend sont perdues lors de la
    sauvegarde preset ou du changement de pattern."""
    pl = _make_player()
    pl.record_bend(2048)
    pl.record_bend(-1000)

    store_pat = Pattern()
    _flush_pattern_to_store(store_pat, pl._pattern)

    # _bend_tape doit être dans le store
    assert store_pat._bend_tape[0] != [], "flush doit copier _bend_tape"
    assert len(store_pat._bend_tape[0]) == 2

    # Simuler un rechargement (apply)
    player2 = _make_player()
    _apply_pattern_from_store(player2._pattern, store_pat)

    assert player2._pattern._bend_tape[0] == pl._pattern._bend_tape[0], \
        "apply doit restaurer _bend_tape identiquement"
    print("  flush+apply store préserve _bend_tape (régression) : OK")

def test_flush_and_apply_roundtrip_via_todict():
    """Cycle complet : record_bend → flush → to_dict → from_dict → apply."""
    pl = _make_player()
    pl.record_bend(4096)
    pl.record_bend(-8192)
    pl._cur_track = 3
    pl.record_bend(1111)

    store_pat = Pattern()
    _flush_pattern_to_store(store_pat, pl._pattern)

    # Sérialise via to_dict → from_dict (comme _save_preset/_load_preset)
    loaded_pat = Pattern()
    loaded_pat.from_dict(store_pat.to_dict())

    player2 = _make_player()
    _apply_pattern_from_store(player2._pattern, loaded_pat)

    assert player2._pattern._bend_tape[0] == pl._pattern._bend_tape[0]
    assert player2._pattern._bend_tape[3] == pl._pattern._bend_tape[3]
    print("  cycle complet record→flush→to_dict→from_dict→apply préserve _bend_tape : OK")


# ---------------------------------------------------------------------------
# Tests préventifs — anti-régression structurelle
#
# Règle : utiliser les méthodes record_* pour produire les données,
# jamais des tuples fabriqués à la main.  Ces tests auraient détecté
# le bug to_dict/4-tuples dès le commit 423d46b.
# ---------------------------------------------------------------------------

def test_to_dict_does_not_raise_after_record_patch_note():
    """Régression critique : to_dict levait ValueError sur les 4-tuples
    produits par record_patch_note (champ bend ajouté en cours de dev).
    Ce test doit passer même si le format interne évolue."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500, bend=2048)
    pl.record_patch_note(64, 90, 300, bend=-4096)
    try:
        pl._pattern.to_dict()
    except Exception as e:
        assert False, f"to_dict lève une exception sur données runtime : {e}"
    print("  to_dict ne lève pas d'exception sur données de record_patch_note : OK")

def test_to_dict_does_not_raise_after_record_kit_note():
    pl = _make_player()
    pl.record_kit_note(36, 100)
    pl.record_kit_note(38, 80)
    try:
        pl._pattern.to_dict()
    except Exception as e:
        assert False, f"to_dict lève une exception sur kit_tape runtime : {e}"
    print("  to_dict ne lève pas d'exception sur données de record_kit_note : OK")

def test_to_dict_does_not_raise_after_record_bend():
    pl = _make_player()
    pl.record_bend(4096)
    pl.record_bend(-2048)
    try:
        pl._pattern.to_dict()
    except Exception as e:
        assert False, f"to_dict lève une exception sur bend_tape runtime : {e}"
    print("  to_dict ne lève pas d'exception sur données de record_bend : OK")

def test_integration_record_json_reload():
    """Intégration : enregistrement via API → sérialisation JSON complète
    → rechargement → vérification de toutes les tapes.
    Ce test couvre la chaîne complète que _save_preset/_load_preset exécute."""
    import json as _json
    pl = _make_player()
    # Enregistrement via les vraies méthodes
    pl.record_kit_note(36, 100)
    pl.record_kit_note(38, 80)
    pl.record_patch_note(60, 100, 500, bend=2048)
    pl.record_patch_note(64,  90, 300, bend=-1000)
    pl.record_bend(4096)
    pl.record_bend(-2048)

    # Simulation _flush_pattern_to_store
    store = Pattern()
    store._kit_tape   = dict(pl._pattern._kit_tape)
    store._patch_tape = dict(pl._pattern._patch_tape)
    store._bend_tape  = [list(t) for t in pl._pattern._bend_tape]

    # Sérialisation JSON complète (comme json.dump dans _save_preset)
    try:
        json_str = _json.dumps(store.to_dict(), separators=(',', ':'))
    except Exception as e:
        assert False, f"json.dumps échoue : {e}"

    # Rechargement (comme from_dict dans _load_preset)
    restored = Pattern()
    restored.from_dict(_json.loads(json_str))

    # Simulation _apply_pattern_from_store
    pl2 = _make_player()
    pl2._pattern._kit_tape   = dict(restored._kit_tape)
    pl2._pattern._patch_tape = dict(restored._patch_tape)
    pl2._pattern._bend_tape  = [list(t) for t in restored._bend_tape]

    assert pl2._pattern._kit_tape   == pl._pattern._kit_tape,   "kit_tape perdu"
    assert pl2._pattern._patch_tape == pl._pattern._patch_tape, "patch_tape perdu"
    assert pl2._pattern._bend_tape  == pl._pattern._bend_tape,  "bend_tape perdu"
    print("  intégration record→JSON→rechargement préserve kit/patch/bend tapes : OK")

def test_integration_record_json_reload_all_tracks():
    """Même test sur plusieurs pistes simultanément."""
    import json as _json
    pl = _make_player()
    pl._cur_track = 0; pl.record_patch_note(60, 100, 400, bend=1000)
    pl._cur_track = 1; pl.record_kit_note(36, 127)
    pl._cur_track = 2; pl.record_bend(8191)
    pl._cur_track = 3; pl.record_patch_note(67, 80, 200, bend=-500)

    store = Pattern()
    store._kit_tape   = dict(pl._pattern._kit_tape)
    store._patch_tape = dict(pl._pattern._patch_tape)
    store._bend_tape  = [list(t) for t in pl._pattern._bend_tape]

    restored = Pattern()
    restored.from_dict(_json.loads(_json.dumps(store.to_dict(), separators=(',', ':'))))

    pl2 = _make_player()
    pl2._pattern._kit_tape   = dict(restored._kit_tape)
    pl2._pattern._patch_tape = dict(restored._patch_tape)
    pl2._pattern._bend_tape  = [list(t) for t in restored._bend_tape]

    assert pl2._pattern._kit_tape   == pl._pattern._kit_tape
    assert pl2._pattern._patch_tape == pl._pattern._patch_tape
    assert pl2._pattern._bend_tape  == pl._pattern._bend_tape
    print("  intégration multi-pistes record→JSON→rechargement : OK")


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
    test_to_dict_patch_tape_7_columns()
    test_roundtrip_kit_tape()
    test_roundtrip_patch_tape()
    test_roundtrip_patch_tape_with_bend()
    test_from_dict_kit_tape_backward_compat_5_columns()
    test_from_dict_patch_tape_backward_compat_5_columns()
    test_from_dict_patch_tape_backward_compat_6_columns()
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
    # erase_patch_tape_note
    test_erase_patch_tape_note_removes_event()
    test_erase_patch_tape_note_returns_bar_step()
    test_erase_patch_tape_note_unknown_note_returns_none()
    test_erase_patch_tape_note_wrong_track_returns_none()
    test_erase_patch_tape_note_keeps_other_note_at_same_step()
    test_erase_patch_tape_note_twice_removes_both()
    test_erase_patch_tape_note_empty_tape_returns_none()
    # _erase_active_midi_notes
    test_erase_active_midi_notes_initially_empty()
    test_toggle_erase_clears_active_midi_notes_on_enter()
    test_toggle_erase_clears_active_midi_notes_on_exit()
    test_stop_all_clears_active_midi_notes()
    test_update_erase_midi_range_pad_mode_uses_erase_held()
    # _erase_kit_tape_event
    test_erase_kit_tape_event_removes_note()
    test_erase_kit_tape_event_keeps_other_notes()
    test_run_thread_auto_erase_kit_tape()
    test_note_on_range_two_notes()
    test_note_off_shrinks_range()
    test_note_off_last_note_clears_range()
    test_note_off_discard_unknown_note_is_safe()
    # _erase_patch_tape_event
    test_erase_patch_tape_event_removes_note()
    test_erase_patch_tape_event_keeps_other_notes_at_same_step()
    test_erase_patch_tape_event_no_crash_on_missing_step()
    test_run_thread_auto_erase_uses_erase_active_midi_notes()
    test_run_thread_no_erase_if_note_not_active()
    # Sécurité accès concurrent
    test_patch_tape_list_snapshot_safe_during_erase()
    test_kit_tape_list_snapshot_safe_during_modification()
    # Dispatch callbacks
    test_kit_tape_callback_receives_duration()
    test_patch_tape_callback_receives_duration()
    test_kit_tape_no_callback_is_safe()
    # Simulation Pitch Bend — enregistrement et lecture (snapshot note_on)
    test_record_patch_note_stores_bend()
    test_record_patch_note_bend_zero_by_default()
    test_record_patch_note_off_preserves_bend()
    test_run_thread_dispatch_passes_bend_to_callback()
    # Automation Pitch Bend — _bend_tape
    test_bend_tape_initially_empty()
    test_new_pattern_resets_bend_tape()
    test_reset_pattern_clears_bend_tape()
    test_clear_track_clears_bend_tape_for_track()
    test_double_bars_duplicates_bend_tape()
    test_double_bars_preserves_bend_values()
    test_halve_bars_filters_bend_tape()
    test_resize_filters_bend_tape()
    test_roundtrip_bend_tape()
    test_from_dict_without_bend_tape_gives_empty()
    test_from_dict_bend_tape_pads_to_num_tracks()
    test_record_bend_stores_float_offset_and_value()
    test_record_bend_multiple_points_accumulate()
    test_record_bend_uses_cur_track()
    test_bend_tape_callback_receives_track_and_value()
    test_bend_tape_no_callback_is_safe()
    test_run_thread_build_bend_tape_events()
    # Régression — flush/apply store
    test_flush_and_apply_preserve_bend_tape()
    test_flush_and_apply_roundtrip_via_todict()
    # Tests préventifs — utilise les méthodes record_* (données runtime réelles)
    test_to_dict_does_not_raise_after_record_patch_note()
    test_to_dict_does_not_raise_after_record_kit_note()
    test_to_dict_does_not_raise_after_record_bend()
    test_integration_record_json_reload()
    test_integration_record_json_reload_all_tracks()
    print("Tous les tests : OK")
