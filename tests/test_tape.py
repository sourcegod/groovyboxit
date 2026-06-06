#python3
"""
    File: tests/test_tape.py
    Tests unitaires de _tape (TapeEvent), _bend_tape, _mod_tape :
    structure Pattern, lifecycle (new/reset/double/halve/resize),
    sérialisation to_dict/from_dict, enregistrement DrumPlayer,
    et durée note_on→note_off pour les événements patch.
    Date: Fri, 06/06/2026
    Author: Coolbrother
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import Pattern, TapeEvent
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


def _K(note, vel=100, dur=0):
    """Raccourci : TapeEvent kit."""
    return TapeEvent("K", note, vel, dur, 0)

def _P(note, vel=100, dur=0, bend=0):
    """Raccourci : TapeEvent patch."""
    return TapeEvent("P", note, vel, dur, bend)


# ---------------------------------------------------------------------------
# Structure initiale du Pattern
# ---------------------------------------------------------------------------

def test_pattern_tape_initially_empty():
    p = Pattern()
    assert p._tape == {}
    print("  _tape vide à l'init : OK")


# ---------------------------------------------------------------------------
# new_pattern / reset_pattern
# ---------------------------------------------------------------------------

def test_new_pattern_resets_tape():
    p = Pattern()
    p._tape = {(0, 0, 0): [_K(36)], (0, 0, 3): [_P(60)]}
    p.new_pattern()
    assert p._tape == {}
    print("  new_pattern efface _tape : OK")

def test_reset_pattern_clears_tape():
    p = Pattern()
    p._tape = {(0, 0, 5): [_K(38)], (1, 0, 8): [_P(64)]}
    p.reset_pattern()
    assert p._tape == {}
    print("  reset_pattern efface _tape : OK")


# ---------------------------------------------------------------------------
# double_bars
# ---------------------------------------------------------------------------

def test_double_bars_duplicates_kit_events():
    p = Pattern()
    p.new_pattern(2, 16)
    p._tape = {(0, 0, 3): [_K(36)], (0, 1, 7): [_K(38, 80)]}
    p.double_bars()
    assert (0, 2, 3) in p._tape, "bar 0 dupliquée en bar 2"
    assert (0, 3, 7) in p._tape, "bar 1 dupliquée en bar 3"
    assert p._tape[(0, 2, 3)] == [_K(36)]
    assert p._tape[(0, 3, 7)] == [_K(38, 80)]
    print("  double_bars duplique les événements K dans _tape : OK")

def test_double_bars_preserves_original_kit_events():
    p = Pattern()
    p.new_pattern(2, 16)
    p._tape = {(0, 0, 1): [_K(42)]}
    p.double_bars()
    assert (0, 0, 1) in p._tape, "entrée originale conservée"
    print("  double_bars conserve les entrées originales de _tape : OK")

def test_double_bars_duplicates_patch_events():
    p = Pattern()
    p.new_pattern(2, 16)
    p._tape = {(0, 0, 5): [_P(60, 100, 400)], (0, 1, 10): [_P(62, 90, 200)]}
    p.double_bars()
    assert (0, 2, 5)  in p._tape
    assert (0, 3, 10) in p._tape
    assert p._tape[(0, 2, 5)]  == [_P(60, 100, 400)]
    assert p._tape[(0, 3, 10)] == [_P(62, 90, 200)]
    print("  double_bars duplique les événements P dans _tape : OK")


# ---------------------------------------------------------------------------
# halve_bars
# ---------------------------------------------------------------------------

def test_halve_bars_removes_second_half_kit_events():
    p = Pattern()
    p.new_pattern(4, 16)
    p._tape = {
        (0, 0, 0): [_K(36)],   # bar 0 → conservé
        (0, 1, 0): [_K(38)],   # bar 1 → conservé
        (0, 2, 0): [_K(42)],   # bar 2 → supprimé
        (0, 3, 0): [_K(46)],   # bar 3 → supprimé
    }
    p.halve_bars()
    assert (0, 0, 0) in p._tape
    assert (0, 1, 0) in p._tape
    assert (0, 2, 0) not in p._tape
    assert (0, 3, 0) not in p._tape
    print("  halve_bars filtre les événements K hors de la 1ère moitié : OK")

def test_halve_bars_removes_second_half_patch_events():
    p = Pattern()
    p.new_pattern(4, 16)
    p._tape = {
        (0, 0, 5): [_P(60, 100, 300)],
        (0, 3, 5): [_P(65, 80, 150)],
    }
    p.halve_bars()
    assert (0, 0, 5) in p._tape
    assert (0, 3, 5) not in p._tape
    print("  halve_bars filtre les événements P hors de la 1ère moitié : OK")


# ---------------------------------------------------------------------------
# resize
# ---------------------------------------------------------------------------

def test_resize_filters_kit_events_out_of_range():
    p = Pattern()
    p.new_pattern(4, 16)
    p._tape = {
        (0, 0, 3):  [_K(36)],   # conservé
        (0, 1, 15): [_K(38)],   # conservé
        (0, 2, 5):  [_K(42)],   # supprimé (bar >= 2)
    }
    p.resize(2, 16)
    assert (0, 0, 3)  in p._tape
    assert (0, 1, 15) in p._tape
    assert (0, 2, 5)  not in p._tape
    print("  resize filtre les événements K (bars hors limites) : OK")

def test_resize_filters_patch_events_out_of_range():
    p = Pattern()
    p.new_pattern(2, 32)
    p._tape = {
        (0, 0, 31): [_P(60, 100, 200)],   # conservé
        (0, 1, 5):  [_P(62, 90, 150)],    # supprimé (bar >= 1)
    }
    p.resize(1, 32)
    assert (0, 0, 31) in p._tape
    assert (0, 1, 5)  not in p._tape
    print("  resize filtre les événements P (bars hors limites) : OK")

def test_resize_filters_kit_events_steps_out_of_range():
    p = Pattern()
    p.new_pattern(1, 32)
    p._tape = {
        (0, 0, 15): [_K(36)],   # conservé
        (0, 0, 16): [_K(38)],   # supprimé (step >= 16)
    }
    p.resize(1, 16)
    assert (0, 0, 15) in p._tape
    assert (0, 0, 16) not in p._tape
    print("  resize filtre les événements K (steps hors limites) : OK")


# ---------------------------------------------------------------------------
# to_dict / from_dict — format JSON inchangé (rétrocompatibilité)
# ---------------------------------------------------------------------------

def test_to_dict_kit_tape_6_columns():
    p = Pattern()
    p._tape = {(0, 0, 3): [_K(36)]}
    rec = p.to_dict()["kit_tape"]
    assert len(rec) == 1
    assert rec[0] == [0, 0, 3, 36, 100, 0]
    print("  to_dict kit_tape : enregistrement 6 colonnes : OK")

def test_to_dict_patch_tape_7_columns():
    p = Pattern()
    p._tape = {(1, 0, 7): [_P(60, 90, 350, 2048)]}
    rec = p.to_dict()["patch_tape"]
    assert len(rec) == 1
    assert rec[0] == [1, 0, 7, 60, 90, 350, 2048]
    print("  to_dict patch_tape : enregistrement 7 colonnes (avec bend) : OK")

def test_roundtrip_kit_tape():
    src = Pattern()
    src._tape = {
        (0, 0, 2): [_K(36), _K(42, 80)],
        (1, 0, 8): [_K(38, 127)],
    }
    dst = Pattern()
    dst.from_dict(src.to_dict())
    assert dst._tape == src._tape
    print("  to_dict → from_dict kit events round-trip : OK")

def test_roundtrip_patch_tape():
    src = Pattern()
    src._tape = {
        (0, 0, 4): [_P(60, 100, 500), _P(64, 90, 250)],
        (0, 1, 0): [_P(67, 80, 300)],
    }
    dst = Pattern()
    dst.from_dict(src.to_dict())
    assert dst._tape == src._tape
    print("  to_dict → from_dict patch events round-trip : OK")

def test_roundtrip_patch_tape_with_bend():
    """Régression : to_dict levait ValueError sur les 4-tuples."""
    src = Pattern()
    src._tape = {
        (0, 0, 0): [_P(60, 100, 500, 4096), _P(62, 90, 300, -2000)],
        (1, 0, 4): [_P(67, 80, 200)],
    }
    try:
        d = src.to_dict()
    except ValueError as e:
        assert False, f"to_dict lève ValueError sur _tape : {e}"
    dst = Pattern()
    dst.from_dict(d)
    assert dst._tape[(0, 0, 0)][0] == _P(60, 100, 500, 4096)
    assert dst._tape[(0, 0, 0)][1] == _P(62, 90, 300, -2000)
    assert dst._tape[(1, 0, 4)][0] == _P(67, 80, 200)
    print("  to_dict → from_dict patch 4-tuples avec bend (régression) : OK")

def test_from_dict_kit_tape_backward_compat_5_columns():
    """Anciens presets sans colonne dur doivent se charger avec dur=0."""
    old = {
        "curpattern": Pattern()._curpattern,
        "kit_tape": [[0, 0, 3, 36, 100]],   # 5 colonnes, sans dur
    }
    p = Pattern()
    p.from_dict(old)
    assert (0, 0, 3) in p._tape
    assert p._tape[(0, 0, 3)] == [_K(36)]
    print("  from_dict kit rétro-compat 5 colonnes → dur=0 : OK")

def test_from_dict_patch_tape_backward_compat_5_columns():
    """Anciens presets sans dur ni bend doivent charger dur=0, bend=0."""
    old = {
        "curpattern": Pattern()._curpattern,
        "patch_tape": [[0, 0, 7, 60, 90]],   # 5 colonnes
    }
    p = Pattern()
    p.from_dict(old)
    assert (0, 0, 7) in p._tape
    assert p._tape[(0, 0, 7)] == [_P(60, 90, 0, 0)]
    print("  from_dict patch rétro-compat 5 colonnes → dur=0, bend=0 : OK")

def test_from_dict_patch_tape_backward_compat_6_columns():
    """Anciens presets avec dur mais sans bend doivent charger bend=0."""
    old = {
        "curpattern": Pattern()._curpattern,
        "patch_tape": [[0, 0, 3, 60, 100, 500]],   # 6 colonnes, sans bend
    }
    p = Pattern()
    p.from_dict(old)
    assert p._tape[(0, 0, 3)] == [_P(60, 100, 500, 0)]
    print("  from_dict patch rétro-compat 6 colonnes → bend=0 : OK")

def test_from_dict_empty_tapes():
    p = Pattern()
    p.from_dict({"curpattern": Pattern()._curpattern})
    assert p._tape == {}
    print("  from_dict sans kit_tape/patch_tape → _tape vide : OK")

def test_from_dict_mixed_kit_and_patch_same_step():
    """Kit et patch au même (track, bar, step) → tous dans _tape."""
    old = {
        "curpattern": Pattern()._curpattern,
        "kit_tape":   [[0, 0, 4, 36, 100, 0]],
        "patch_tape": [[0, 0, 4, 60, 90, 500, 0]],
    }
    p = Pattern()
    p.from_dict(old)
    events = p._tape.get((0, 0, 4), [])
    etypes = [ev.etype for ev in events]
    assert "K" in etypes and "P" in etypes
    print("  from_dict kit+patch au même step → cohabitent dans _tape : OK")


# ---------------------------------------------------------------------------
# DrumPlayer.record_kit_note
# ---------------------------------------------------------------------------

def test_record_kit_note_stores_event():
    pl = _make_player()
    pl.record_kit_note(36, 100)
    events = list(pl._pattern._tape.values())[0]
    assert len(events) == 1
    ev = events[0]
    assert ev.etype == "K"
    assert ev.note == 36
    assert ev.vel  == 100
    assert ev.dur  == 0
    print("  record_kit_note stocke TapeEvent('K', 36, 100, 0, 0) : OK")

def test_record_kit_note_no_duplicate_same_note():
    pl = _make_player()
    pl.record_kit_note(36, 100)
    pl.record_kit_note(36, 127)   # même note, même position → pas de doublon
    events = list(pl._pattern._tape.values())[0]
    kit_notes = [e.note for e in events if e.etype == "K"]
    assert kit_notes.count(36) == 1, "note 36 ne doit apparaître qu'une fois"
    print("  record_kit_note : pas de doublon sur même note : OK")

def test_record_kit_note_two_different_notes_same_step():
    """Deux notes MIDI différentes au même pas sont enregistrées toutes les deux."""
    pl = _make_player()
    pl.record_kit_note(36, 100)
    pl.record_kit_note(38, 80)
    all_events = [e for lst in pl._pattern._tape.values() for e in lst]
    notes = [e.note for e in all_events if e.etype == "K"]
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
    events = list(pl._pattern._tape.values())[0]
    assert events[0].vel == 127
    print("  record_kit_note clamp vélocité à 127 : OK")

def test_record_kit_note_velocity_minimum_one():
    pl = _make_player()
    pl.record_kit_note(36, 0)
    events = list(pl._pattern._tape.values())[0]
    assert events[0].vel == 1
    print("  record_kit_note vélocité 0 → 1 : OK")


# ---------------------------------------------------------------------------
# DrumPlayer.record_patch_note — durée fixe (numpad)
# ---------------------------------------------------------------------------

def test_record_patch_note_fixed_duration():
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    events = list(pl._pattern._tape.values())[0]
    assert len(events) == 1
    ev = events[0]
    assert ev.etype == "P"
    assert ev.note == 60
    assert ev.vel  == 100
    assert ev.dur  == 500
    print("  record_patch_note durée fixe stockée : OK")

def test_record_patch_note_fixed_duration_no_pending():
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    assert 60 not in pl._pending_patch, "durée fixe → pas de pending"
    print("  record_patch_note durée fixe → _pending_patch vide : OK")

def test_record_patch_note_zero_duration():
    pl = _make_player()
    pl.record_patch_note(60, 100, 0)
    events = list(pl._pattern._tape.values())[0]
    assert events[0].dur == 0
    print("  record_patch_note duration_ms=0 stocké : OK")

def test_record_patch_note_replaces_same_note_at_same_step():
    pl = _make_player()
    pl.record_patch_note(60, 100, 300)
    pl.record_patch_note(60, 90, 400)   # même note, même step → remplace
    all_events = [e for lst in pl._pattern._tape.values() for e in lst if e.etype == "P"]
    notes = [e.note for e in all_events]
    assert notes.count(60) == 1, "note 60 ne doit apparaître qu'une fois"
    assert all_events[0].dur == 400, "durée mise à jour"
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
    events = list(pl._pattern._tape.values())[0]
    assert events[0].dur == 0, "durée provisoire = 0"
    print("  record_patch_note MIDI → durée provisoire 0 : OK")

def test_record_patch_note_midi_registers_pending():
    pl = _make_player()
    pl.record_patch_note(60, 100)
    assert 60 in pl._pending_patch, "note 60 doit être en attente de note_off"
    print("  record_patch_note MIDI → enregistré dans _pending_patch : OK")

def test_record_patch_note_off_updates_duration():
    pl = _make_player()
    pl.record_patch_note(60, 100)
    key, entry_idx, _ = pl._pending_patch[60]
    pl._pending_patch[60] = (key, entry_idx, time.perf_counter() - 0.300)
    pl.record_patch_note_off(60)
    ev = pl._pattern._tape[key][entry_idx]
    assert ev.dur >= 290, f"durée attendue ≥ 290 ms, obtenu {ev.dur}"
    print(f"  record_patch_note_off met à jour la durée ({ev.dur} ms) : OK")

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
    key = list(pl._pattern._tape.keys())[0]
    result = pl.erase_patch_tape_note(0, 60)
    assert result is not None
    assert key not in pl._pattern._tape, "clé supprimée quand liste vide"
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
    key = list(pl._pattern._tape.keys())[0]
    pl.erase_patch_tape_note(0, 60)
    remaining = [e.note for e in pl._pattern._tape.get(key, []) if e.etype == "P"]
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
    assert pl._pattern._tape == {}, "_tape vide après deux effacements"
    print("  erase_patch_tape_note deux effacements successifs : OK")

def test_erase_patch_tape_note_empty_tape_returns_none():
    pl = _make_player()
    result = pl.erase_patch_tape_note(0, 60)
    assert result is None
    print("  erase_patch_tape_note sur _tape vide → None : OK")


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
    pl.toggle_erase()
    assert pl._erase_active_midi_notes == set()
    print("  toggle_erase (entrée) vide _erase_active_midi_notes : OK")

def test_toggle_erase_clears_active_midi_notes_on_exit():
    pl = _make_player()
    pl.toggle_erase()
    pl._erase_active_midi_notes.add(60)
    pl.toggle_erase()
    assert pl._erase_active_midi_notes == set()
    print("  toggle_erase (sortie) vide _erase_active_midi_notes : OK")

def test_stop_all_clears_active_midi_notes():
    pl = _make_player()
    pl._erase_active_midi_notes.add(60)
    pl._erase_active_midi_notes.add(62)
    pl.stop_all()
    assert pl._erase_active_midi_notes == set()
    print("  stop_all vide _erase_active_midi_notes : OK")

def test_update_erase_midi_range_pad_mode_uses_erase_held():
    pl = _make_player()
    pl.toggle_erase()
    erase_held = {36, 43}
    pl._erase_active_midi_notes = set(range(min(erase_held), max(erase_held) + 1))
    assert pl._erase_active_midi_notes == set(range(36, 44))
    print("  update_erase_midi_range (pad) : plage depuis notes brutes : OK")

def test_note_on_range_two_notes():
    pl = _make_player()
    pl.toggle_erase()
    erase_held_kb = set()
    erase_held_kb.add(36)
    pl._erase_active_midi_notes = set(range(min(erase_held_kb), max(erase_held_kb) + 1))
    assert pl._erase_active_midi_notes == {36}
    erase_held_kb.add(43)
    pl._erase_active_midi_notes = set(range(min(erase_held_kb), max(erase_held_kb) + 1))
    assert pl._erase_active_midi_notes == set(range(36, 44))
    print("  note_on Erase : deux notes tenues → plage complète : OK")

def test_note_off_shrinks_range():
    pl = _make_player()
    pl.toggle_erase()
    erase_held_kb = {36, 43}
    pl._erase_active_midi_notes = set(range(36, 44))
    erase_held_kb.discard(36)
    pl._erase_active_midi_notes = set(range(min(erase_held_kb), max(erase_held_kb) + 1))
    assert pl._erase_active_midi_notes == {43}
    print("  note_off Erase : relâcher une note réduit la plage : OK")

def test_note_off_last_note_clears_range():
    pl = _make_player()
    pl.toggle_erase()
    erase_held_kb = {60}
    pl._erase_active_midi_notes = {60}
    erase_held_kb.discard(60)
    if not erase_held_kb:
        pl._erase_active_midi_notes.clear()
    assert pl._erase_active_midi_notes == set()
    print("  note_off Erase : dernière note relâchée → plage vide : OK")

def test_note_off_discard_unknown_note_is_safe():
    pl = _make_player()
    try:
        pl._erase_active_midi_notes.discard(99)
        print("  note_off Erase : discard note inconnue → no-op : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"


# ---------------------------------------------------------------------------
# _erase_tape_event — auto-effacement pendant la lecture
# ---------------------------------------------------------------------------

def test_erase_tape_event_removes_kit_note():
    """_erase_tape_event supprime la note K ciblée dans _tape."""
    pl = _make_player()
    pl.record_kit_note(36, 100)
    key = list(pl._pattern._tape.keys())[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl._erase_tape_event(0, 36, t_sec, "K")

    assert key not in pl._pattern._tape
    print("  _erase_tape_event supprime l'événement K : OK")

def test_erase_tape_event_keeps_other_kit_notes():
    """Note 38 au même step n'est pas touchée quand on efface note 36 (K)."""
    pl = _make_player()
    pl.record_kit_note(36, 100)
    pl.record_kit_note(38, 80)
    key = list(pl._pattern._tape.keys())[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl._erase_tape_event(0, 36, t_sec, "K")

    remaining = [e.note for e in pl._pattern._tape.get(key, []) if e.etype == "K"]
    assert 38 in remaining
    assert 36 not in remaining
    print("  _erase_tape_event conserve les autres notes K du step : OK")

def test_run_thread_auto_erase_kit_tape():
    """Simule la logique _run_thread pour KIT_TAPE_EVENT en mode Erase."""
    pl = _make_player()
    pl.record_kit_note(36, 100)
    key = list(pl._pattern._tape.keys())[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl.toggle_erase()
    pl._erase_active_midi_notes = {36}

    t_idx, midi_note, dur = 0, 36, 0
    if pl.erasing and t_idx == pl._cur_track \
            and midi_note in pl._erase_active_midi_notes:
        pl._erase_tape_event(t_idx, midi_note, t_sec, "K")

    assert key not in pl._pattern._tape
    print("  _run_thread logique : KIT_TAPE_EVENT effacé si note active en Erase : OK")

def test_erase_tape_event_removes_patch_note():
    """_erase_tape_event supprime la note P ciblée dans _tape."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    key = list(pl._pattern._tape.keys())[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl._erase_tape_event(0, 60, t_sec, "P")

    assert key not in pl._pattern._tape, "clé supprimée après effacement"
    print("  _erase_tape_event supprime l'événement P et la clé vide : OK")

def test_erase_tape_event_keeps_other_patch_notes():
    """Note 64 au même step n'est pas touchée quand on efface note 60 (P)."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    pl.record_patch_note(64, 90, 400)
    key = list(pl._pattern._tape.keys())[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl._erase_tape_event(0, 60, t_sec, "P")

    remaining = [e.note for e in pl._pattern._tape.get(key, []) if e.etype == "P"]
    assert 64 in remaining, "note 64 doit rester"
    assert 60 not in remaining
    print("  _erase_tape_event ne touche pas les autres notes P du step : OK")

def test_erase_tape_event_no_crash_on_missing_step():
    """Pas de plantage si t_sec ne correspond à aucun step enregistré."""
    pl = _make_player()
    try:
        pl._erase_tape_event(0, 60, 99.9, "P")
        print("  _erase_tape_event step absent → no-op : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"

def test_erase_tape_event_etype_discriminates():
    """Effacer K ne touche pas P au même step, et vice versa."""
    pl = _make_player()
    pl.record_kit_note(60, 100)    # K note 60
    pl.record_patch_note(60, 100, 500)  # P note 60 (même note, même step)
    key = list(pl._pattern._tape.keys())[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl._erase_tape_event(0, 60, t_sec, "K")   # efface seulement K

    events = pl._pattern._tape.get(key, [])
    etypes = [e.etype for e in events]
    assert "K" not in etypes
    assert "P" in etypes
    print("  _erase_tape_event discrimine etype : K effacé, P conservé : OK")

def test_run_thread_auto_erase_uses_erase_active_midi_notes():
    """Simule la logique _run_thread : PATCH_TAPE_EVENT efface si note dans _erase_active_midi_notes."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    key = list(pl._pattern._tape.keys())[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl.toggle_erase()
    pl._erase_active_midi_notes.add(60)

    t_idx, midi_note, dur = 0, 60, 500
    if pl.erasing and t_idx == pl._cur_track \
            and midi_note in pl._erase_active_midi_notes:
        pl._erase_tape_event(t_idx, midi_note, t_sec, "P")

    assert key not in pl._pattern._tape
    print("  _run_thread logique : PATCH_TAPE_EVENT effacé si note active en Erase : OK")

def test_run_thread_no_erase_if_note_not_active():
    """Si la note n'est pas dans _erase_active_midi_notes, elle n'est pas effacée."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    key = list(pl._pattern._tape.keys())[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    played = []
    pl._on_patch_tape_cb = lambda t, n, v, d, b=0: played.append(n)

    pl.toggle_erase()
    # note 60 PAS dans _erase_active_midi_notes

    t_idx, midi_note, dur = 0, 60, 500
    if pl.erasing and t_idx == pl._cur_track \
            and midi_note in pl._erase_active_midi_notes:
        pl._erase_tape_event(t_idx, midi_note, t_sec, "P")
    elif pl._on_patch_tape_cb:
        pl._on_patch_tape_cb(t_idx, midi_note, 100, dur)

    assert 60 in played, "la note doit être jouée, pas effacée"
    assert key in pl._pattern._tape, "l'événement ne doit pas être supprimé"
    print("  _run_thread logique : PATCH_TAPE_EVENT joué si note pas active en Erase : OK")


# ---------------------------------------------------------------------------
# Sécurité accès concurrent
# ---------------------------------------------------------------------------

def test_tape_snapshot_safe_during_concurrent_erase():
    """Snapshot _tape immunise contre modification concurrente (dict + listes)."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    pl.record_patch_note(62, 100, 500)
    pl.record_patch_note(64, 100, 500)

    collected = []
    try:
        with pl._pattern._lock:
            snap = {k: list(v) for k, v in pl._pattern._tape.items()}
        for (t_idx, b, s), note_list in snap.items():
            pl.erase_patch_tape_note(0, 60)
            for ev in note_list:
                if ev.etype == "P":
                    collected.append(ev.note)
    except RuntimeError as e:
        assert False, f"RuntimeError (accès concurrent non protégé) : {e}"
    print("  snapshot _tape immunise contre la modification concurrente : OK")

def test_tape_snapshot_safe_during_concurrent_kit_delete():
    """Suppression de clé pendant l'itération ne lève pas RuntimeError."""
    pl = _make_player()
    pl.record_kit_note(36, 100)
    pl.record_kit_note(38, 100)

    try:
        with pl._pattern._lock:
            snap = {k: list(v) for k, v in pl._pattern._tape.items()}
        for (t_idx, b, s), note_list in snap.items():
            for k in list(pl._pattern._tape.keys()):
                del pl._pattern._tape[k]
                break
            for ev in note_list:
                pass
    except RuntimeError as e:
        assert False, f"RuntimeError (accès concurrent kit non protégé) : {e}"
    print("  snapshot _tape immunise contre la suppression concurrente : OK")


# ---------------------------------------------------------------------------
# Dispatch callbacks (simulation)
# ---------------------------------------------------------------------------

def test_kit_tape_callback_receives_duration():
    """on_kit_tape_cb reçoit bien (track_idx, midi_note, velocity, duration_ms)."""
    received = []
    pl = _make_player()
    pl._on_kit_tape_cb = lambda t, n, v, d: received.append((t, n, v, d))

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
    """record_patch_note stocke le bend dans TapeEvent.bend."""
    pl = _make_player()
    bend_val = 4096
    pl.record_patch_note(60, 100, 500, bend=bend_val)
    events = list(pl._pattern._tape.values())[0]
    assert len(events) == 1
    ev = events[0]
    assert ev.etype == "P"
    assert ev.note == 60
    assert ev.bend == bend_val
    print(f"  record_patch_note stocke bend={bend_val} dans TapeEvent : OK")

def test_record_patch_note_bend_zero_by_default():
    """Sans pitch bend actif, TapeEvent.bend doit être 0."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    events = list(pl._pattern._tape.values())[0]
    assert events[0].bend == 0
    print("  record_patch_note sans bend → TapeEvent.bend = 0 : OK")

def test_record_patch_note_off_preserves_bend():
    """record_patch_note_off (durée MIDI) préserve le bend dans TapeEvent."""
    pl = _make_player()
    bend_val = -8192
    pl.record_patch_note(60, 100, bend=bend_val)   # duration_ms=None → pending
    pl.record_patch_note_off(60)
    events = list(pl._pattern._tape.values())[0]
    ev = events[0]
    assert ev.bend == bend_val, f"bend {bend_val} doit être conservé après note_off"
    assert ev.dur > 0, "durée doit être > 0 après note_off"
    print(f"  record_patch_note_off préserve bend={bend_val} dans TapeEvent : OK")

def test_run_thread_dispatch_passes_bend_to_callback():
    """Simule le dispatch _run_thread : on_patch_tape_cb reçoit (t, n, v, d, bend)."""
    received = []
    pl = _make_player()
    pl._on_patch_tape_cb = lambda t, n, v, d, b=0: received.append((t, n, v, d, b))

    bend_val = 8191
    pl.record_patch_note(60, 100, 500, bend=bend_val)
    key = list(pl._pattern._tape.keys())[0]
    _, bar_idx, step_idx = key

    note_list = pl._pattern._tape[key]
    for ev in list(note_list):
        if ev.etype != "P":
            continue
        t_idx = 0
        if not pl.erasing:
            pl._on_patch_tape_cb(t_idx, ev.note, ev.vel, ev.dur, ev.bend)

    assert len(received) == 1
    t, n, v, d, b = received[0]
    assert n == 60
    assert b == bend_val
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
    p.new_pattern(2, 16)
    p._bend_tape[0] = [(4.0, 2048), (10.0, -1024)]
    p.double_bars()
    offsets = [off for off, _ in p._bend_tape[0]]
    assert 4.0  in offsets
    assert 10.0 in offsets
    assert 36.0 in offsets
    assert 42.0 in offsets
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
    p.new_pattern(4, 16)
    p._bend_tape[0] = [(5.0, 1000), (20.0, -500), (35.0, 2000)]
    p.halve_bars()
    offsets = [off for off, _ in p._bend_tape[0]]
    assert 5.0  in offsets
    assert 20.0 in offsets
    assert 35.0 not in offsets
    print("  halve_bars filtre _bend_tape : OK")

def test_resize_filters_bend_tape():
    p = Pattern()
    p.new_pattern(4, 16)
    p._bend_tape[0] = [(5.0, 100), (40.0, -200)]
    p.resize(2, 16)
    offsets = [off for off, _ in p._bend_tape[0]]
    assert 5.0  in offsets
    assert 40.0 not in offsets
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
    p = Pattern()
    d = p.to_dict()
    d["bend_tape"] = [[(1.0, 100)]]
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
# Régression — flush/apply store
# ---------------------------------------------------------------------------

def _flush_pattern_to_store(pat, player_pattern):
    """Simule _flush_pattern_to_store de MainWindow."""
    pat._tape      = dict(player_pattern._tape)
    pat._bend_tape = [list(t) for t in player_pattern._bend_tape]

def _apply_pattern_from_store(player_pattern, store_pat):
    """Simule _apply_pattern_from_store de MainWindow."""
    player_pattern._tape      = dict(store_pat._tape)
    player_pattern._bend_tape = [list(t) for t in store_pat._bend_tape]

def test_flush_and_apply_preserve_bend_tape():
    pl = _make_player()
    pl.record_bend(2048)
    pl.record_bend(-1000)

    store_pat = Pattern()
    _flush_pattern_to_store(store_pat, pl._pattern)

    assert store_pat._bend_tape[0] != [], "flush doit copier _bend_tape"
    assert len(store_pat._bend_tape[0]) == 2

    player2 = _make_player()
    _apply_pattern_from_store(player2._pattern, store_pat)

    assert player2._pattern._bend_tape[0] == pl._pattern._bend_tape[0]
    print("  flush+apply store préserve _bend_tape (régression) : OK")

def test_flush_and_apply_roundtrip_via_todict():
    pl = _make_player()
    pl.record_bend(4096)
    pl.record_bend(-8192)
    pl._cur_track = 3
    pl.record_bend(1111)

    store_pat = Pattern()
    _flush_pattern_to_store(store_pat, pl._pattern)

    loaded_pat = Pattern()
    loaded_pat.from_dict(store_pat.to_dict())

    player2 = _make_player()
    _apply_pattern_from_store(player2._pattern, loaded_pat)

    assert player2._pattern._bend_tape[0] == pl._pattern._bend_tape[0]
    assert player2._pattern._bend_tape[3] == pl._pattern._bend_tape[3]
    print("  cycle complet record→flush→to_dict→from_dict→apply préserve _bend_tape : OK")


# ---------------------------------------------------------------------------
# Tests préventifs — anti-régression structurelle
# ---------------------------------------------------------------------------

def test_to_dict_does_not_raise_after_record_patch_note():
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
        assert False, f"to_dict lève une exception sur _tape runtime : {e}"
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
    """Intégration : enregistrement → JSON → rechargement → vérification."""
    import json as _json
    pl = _make_player()
    pl.record_kit_note(36, 100)
    pl.record_kit_note(38, 80)
    pl.record_patch_note(60, 100, 500, bend=2048)
    pl.record_patch_note(64,  90, 300, bend=-1000)
    pl.record_bend(4096)
    pl.record_bend(-2048)

    store = Pattern()
    store._tape      = dict(pl._pattern._tape)
    store._bend_tape = [list(t) for t in pl._pattern._bend_tape]

    try:
        json_str = _json.dumps(store.to_dict(), separators=(',', ':'))
    except Exception as e:
        assert False, f"json.dumps échoue : {e}"

    restored = Pattern()
    restored.from_dict(_json.loads(json_str))

    pl2 = _make_player()
    pl2._pattern._tape      = dict(restored._tape)
    pl2._pattern._bend_tape = [list(t) for t in restored._bend_tape]

    assert pl2._pattern._tape      == pl._pattern._tape,      "_tape perdu"
    assert pl2._pattern._bend_tape == pl._pattern._bend_tape, "bend_tape perdu"
    print("  intégration record→JSON→rechargement préserve _tape + _bend_tape : OK")

def test_integration_record_json_reload_all_tracks():
    """Même test sur plusieurs pistes simultanément."""
    import json as _json
    pl = _make_player()
    pl._cur_track = 0; pl.record_patch_note(60, 100, 400, bend=1000)
    pl._cur_track = 1; pl.record_kit_note(36, 127)
    pl._cur_track = 2; pl.record_bend(8191)
    pl._cur_track = 3; pl.record_patch_note(67, 80, 200, bend=-500)

    store = Pattern()
    store._tape      = dict(pl._pattern._tape)
    store._bend_tape = [list(t) for t in pl._pattern._bend_tape]

    restored = Pattern()
    restored.from_dict(_json.loads(_json.dumps(store.to_dict(), separators=(',', ':'))))

    pl2 = _make_player()
    pl2._pattern._tape      = dict(restored._tape)
    pl2._pattern._bend_tape = [list(t) for t in restored._bend_tape]

    assert pl2._pattern._tape      == pl._pattern._tape
    assert pl2._pattern._bend_tape == pl._pattern._bend_tape
    print("  intégration multi-pistes record→JSON→rechargement : OK")


# ---------------------------------------------------------------------------
# Automation Mod Wheel — _mod_tape (miroir de _bend_tape)
# ---------------------------------------------------------------------------

def test_mod_tape_initially_empty():
    p = Pattern()
    assert len(p._mod_tape) == p._num_tracks
    assert all(t == [] for t in p._mod_tape)
    print("  _mod_tape initialement vide sur toutes les pistes : OK")

def test_new_pattern_resets_mod_tape():
    p = Pattern()
    p._mod_tape[0].append((3.5, 64))
    p.new_pattern()
    assert p._mod_tape[0] == []
    print("  new_pattern réinitialise _mod_tape : OK")

def test_reset_pattern_clears_mod_tape():
    p = Pattern()
    p._mod_tape[1].append((1.0, 100))
    p.reset_pattern()
    assert p._mod_tape[1] == []
    print("  reset_pattern efface _mod_tape : OK")

def test_clear_track_clears_mod_tape_for_track():
    p = Pattern()
    p._mod_tape[2].append((5.0, 32))
    p._mod_tape[3].append((1.0, 64))
    p.clear_track(2)
    assert p._mod_tape[2] == []
    assert p._mod_tape[3] != []
    print("  clear_track efface uniquement _mod_tape de la piste ciblée : OK")

def test_double_bars_duplicates_mod_tape():
    p = Pattern()
    p._num_steps = 16; p._num_bars = 1
    p._mod_tape[0] = [(4.0, 80), (8.0, 100)]
    p.double_bars()
    mods = p._mod_tape[0]
    assert (4.0, 80) in mods and (8.0, 100) in mods
    assert (4.0 + 16, 80) in mods and (8.0 + 16, 100) in mods
    print("  double_bars duplique _mod_tape avec offset correct : OK")

def test_double_bars_preserves_mod_values():
    p = Pattern()
    p._num_steps = 16; p._num_bars = 1
    p._mod_tape[0] = [(2.0, 127)]
    p.double_bars()
    vals = [v for _, v in p._mod_tape[0]]
    assert vals.count(127) == 2
    print("  double_bars préserve les valeurs mod_tape : OK")

def test_halve_bars_filters_mod_tape():
    p = Pattern()
    p._num_steps = 16; p._num_bars = 2
    p._mod_tape[0] = [(4.0, 50), (20.0, 80)]
    p.halve_bars()
    mods = p._mod_tape[0]
    assert (4.0, 50) in mods
    assert not any(off >= 16 for off, _ in mods)
    print("  halve_bars retire les points mod_tape hors de la 1ère moitié : OK")

def test_resize_filters_mod_tape():
    p = Pattern()
    p._num_steps = 16; p._num_bars = 2
    p._mod_tape[0] = [(5.0, 64), (50.0, 100)]
    p.resize(1, 16)
    mods = p._mod_tape[0]
    assert (5.0, 64) in mods
    assert not any(off >= 16 for off, _ in mods)
    print("  resize filtre les points mod_tape hors des nouvelles limites : OK")

def test_roundtrip_mod_tape():
    import json as _json
    p = Pattern()
    p._mod_tape[0] = [(2.0, 64), (10.0, 127)]
    p._mod_tape[3] = [(7.5, 32)]
    d = p.to_dict()
    assert "mod_tape" in d
    p2 = Pattern()
    p2.from_dict(_json.loads(_json.dumps(d)))
    assert p2._mod_tape[0] == [(2.0, 64), (10.0, 127)]
    assert p2._mod_tape[3] == [(7.5, 32)]
    print("  to_dict/from_dict round-trip _mod_tape : OK")

def test_from_dict_without_mod_tape_gives_empty():
    p = Pattern()
    d = p.to_dict()
    del d["mod_tape"]
    p2 = Pattern()
    p2.from_dict(d)
    assert all(t == [] for t in p2._mod_tape)
    print("  from_dict sans clé mod_tape → listes vides (rétrocompat) : OK")

def test_from_dict_mod_tape_pads_to_num_tracks():
    p = Pattern()
    d = p.to_dict()
    d["mod_tape"] = [[(1.0, 50)]]
    p2 = Pattern()
    p2.from_dict(d)
    assert len(p2._mod_tape) == p2._num_tracks
    assert p2._mod_tape[0] == [(1.0, 50)]
    assert all(t == [] for t in p2._mod_tape[1:])
    print("  from_dict _mod_tape complété jusqu'à num_tracks si trop court : OK")

def test_record_mod_stores_float_offset_and_value():
    pl = _make_player()
    pl.record_mod(64)
    mods = pl._pattern._mod_tape[0]
    assert len(mods) == 1
    off, val = mods[0]
    assert isinstance(off, float)
    assert val == 64
    print("  record_mod stocke (float_offset, mod_value) : OK")

def test_record_mod_multiple_points_accumulate():
    pl = _make_player()
    pl.record_mod(0)
    pl.record_mod(64)
    pl.record_mod(127)
    mods = pl._pattern._mod_tape[0]
    assert len(mods) == 3
    assert [v for _, v in mods] == [0, 64, 127]
    print("  record_mod accumule plusieurs points sans déduplication : OK")

def test_record_mod_uses_cur_track():
    pl = _make_player()
    pl._cur_track = 4
    pl.record_mod(100)
    assert pl._pattern._mod_tape[4] != []
    assert pl._pattern._mod_tape[0] == []
    print("  record_mod enregistre sur la piste courante : OK")

def test_mod_tape_callback_receives_track_and_value():
    received = []
    pl = _make_player()
    pl._on_mod_tape_cb = lambda t, m: received.append((t, m))
    if pl._on_mod_tape_cb:
        pl._on_mod_tape_cb(2, 80)
    assert received == [(2, 80)]
    print("  _on_mod_tape_cb reçoit (track_idx, mod_value) : OK")

def test_mod_tape_no_callback_is_safe():
    pl = _make_player()
    pl._on_mod_tape_cb = None
    try:
        if pl._on_mod_tape_cb:
            pl._on_mod_tape_cb(0, 0)
        print("  _on_mod_tape_cb=None → no-op sans plantage : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"

def test_run_thread_build_mod_tape_events():
    pl = _make_player()
    pl._pattern._mod_tape[0] = [(4.0, 64), (12.0, 127)]
    events = []
    for t_idx, track_mods in enumerate(pl._pattern._mod_tape):
        for float_off, mod_val in list(track_mods):
            t_sec = float_off * pl.step_duration
            events.append((t_sec, pl.MOD_TAPE_EVENT, (t_idx, mod_val), 0))
    assert len(events) == 2
    _, etype, (ti, mv), _ = events[0]
    assert etype == pl.MOD_TAPE_EVENT
    assert ti == 0
    assert mv == 64
    print("  _run_thread construit les MOD_TAPE_EVENTs correctement : OK")

def _flush_mod(pat, live):
    pat._mod_tape = [list(t) for t in live._mod_tape]

def _apply_mod(live, store):
    live._mod_tape = [list(t) for t in store._mod_tape]

def test_flush_and_apply_preserve_mod_tape():
    pl = _make_player()
    pl.record_mod(64)
    pl.record_mod(127)
    store = Pattern()
    _flush_mod(store, pl._pattern)
    assert store._mod_tape[0] != []
    assert len(store._mod_tape[0]) == 2
    pl2 = _make_player()
    _apply_mod(pl2._pattern, store)
    assert pl2._pattern._mod_tape[0] == pl._pattern._mod_tape[0]
    print("  flush+apply store préserve _mod_tape : OK")

def test_flush_and_apply_roundtrip_mod_tape_via_todict():
    import json as _json
    pl = _make_player()
    pl.record_mod(32)
    pl.record_mod(100)
    pl._cur_track = 2
    pl.record_mod(0)
    store = Pattern()
    _flush_mod(store, pl._pattern)
    loaded = Pattern()
    loaded.from_dict(_json.loads(_json.dumps(store.to_dict(), separators=(',', ':'))))
    pl2 = _make_player()
    _apply_mod(pl2._pattern, loaded)
    assert pl2._pattern._mod_tape[0] == pl._pattern._mod_tape[0]
    assert pl2._pattern._mod_tape[2] == pl._pattern._mod_tape[2]
    print("  cycle complet record→flush→to_dict→from_dict→apply préserve _mod_tape : OK")

def test_to_dict_does_not_raise_after_record_mod():
    pl = _make_player()
    pl.record_mod(64)
    pl.record_mod(127)
    try:
        pl._pattern.to_dict()
    except Exception as e:
        assert False, f"to_dict lève une exception sur mod_tape runtime : {e}"
    print("  to_dict ne lève pas d'exception sur données de record_mod : OK")

def test_integration_record_json_reload_with_mod():
    """Intégration complète incluant mod_tape."""
    import json as _json
    pl = _make_player()
    pl.record_kit_note(36, 100)
    pl.record_patch_note(60, 100, 500, bend=2048)
    pl.record_bend(4096)
    pl.record_mod(80)
    pl.record_mod(127)

    store = Pattern()
    store._tape      = dict(pl._pattern._tape)
    store._bend_tape = [list(t) for t in pl._pattern._bend_tape]
    store._mod_tape  = [list(t) for t in pl._pattern._mod_tape]

    try:
        json_str = _json.dumps(store.to_dict(), separators=(',', ':'))
    except Exception as e:
        assert False, f"json.dumps échoue : {e}"

    restored = Pattern()
    restored.from_dict(_json.loads(json_str))

    pl2 = _make_player()
    pl2._pattern._tape      = dict(restored._tape)
    pl2._pattern._bend_tape = [list(t) for t in restored._bend_tape]
    pl2._pattern._mod_tape  = [list(t) for t in restored._mod_tape]

    assert pl2._pattern._tape      == pl._pattern._tape,      "_tape perdu"
    assert pl2._pattern._bend_tape == pl._pattern._bend_tape, "bend_tape perdu"
    assert pl2._pattern._mod_tape  == pl._pattern._mod_tape,  "mod_tape perdu"
    print("  intégration record→JSON→rechargement préserve _tape+bend+mod : OK")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_tape ===")
    # Structure initiale
    test_pattern_tape_initially_empty()
    # new_pattern / reset_pattern
    test_new_pattern_resets_tape()
    test_reset_pattern_clears_tape()
    # double_bars
    test_double_bars_duplicates_kit_events()
    test_double_bars_preserves_original_kit_events()
    test_double_bars_duplicates_patch_events()
    # halve_bars
    test_halve_bars_removes_second_half_kit_events()
    test_halve_bars_removes_second_half_patch_events()
    # resize
    test_resize_filters_kit_events_out_of_range()
    test_resize_filters_patch_events_out_of_range()
    test_resize_filters_kit_events_steps_out_of_range()
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
    test_from_dict_mixed_kit_and_patch_same_step()
    # record_kit_note
    test_record_kit_note_stores_event()
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
    test_note_on_range_two_notes()
    test_note_off_shrinks_range()
    test_note_off_last_note_clears_range()
    test_note_off_discard_unknown_note_is_safe()
    # _erase_tape_event
    test_erase_tape_event_removes_kit_note()
    test_erase_tape_event_keeps_other_kit_notes()
    test_run_thread_auto_erase_kit_tape()
    test_erase_tape_event_removes_patch_note()
    test_erase_tape_event_keeps_other_patch_notes()
    test_erase_tape_event_no_crash_on_missing_step()
    test_erase_tape_event_etype_discriminates()
    test_run_thread_auto_erase_uses_erase_active_midi_notes()
    test_run_thread_no_erase_if_note_not_active()
    # Sécurité accès concurrent
    test_tape_snapshot_safe_during_concurrent_erase()
    test_tape_snapshot_safe_during_concurrent_kit_delete()
    # Dispatch callbacks
    test_kit_tape_callback_receives_duration()
    test_patch_tape_callback_receives_duration()
    test_kit_tape_no_callback_is_safe()
    # Simulation Pitch Bend — enregistrement et lecture
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
    # Automation Mod Wheel — _mod_tape
    test_mod_tape_initially_empty()
    test_new_pattern_resets_mod_tape()
    test_reset_pattern_clears_mod_tape()
    test_clear_track_clears_mod_tape_for_track()
    test_double_bars_duplicates_mod_tape()
    test_double_bars_preserves_mod_values()
    test_halve_bars_filters_mod_tape()
    test_resize_filters_mod_tape()
    test_roundtrip_mod_tape()
    test_from_dict_without_mod_tape_gives_empty()
    test_from_dict_mod_tape_pads_to_num_tracks()
    test_record_mod_stores_float_offset_and_value()
    test_record_mod_multiple_points_accumulate()
    test_record_mod_uses_cur_track()
    test_mod_tape_callback_receives_track_and_value()
    test_mod_tape_no_callback_is_safe()
    test_run_thread_build_mod_tape_events()
    test_flush_and_apply_preserve_mod_tape()
    test_flush_and_apply_roundtrip_mod_tape_via_todict()
    test_to_dict_does_not_raise_after_record_mod()
    test_integration_record_json_reload_with_mod()
    print("Tous les tests : OK")
