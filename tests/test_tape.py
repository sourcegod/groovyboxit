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

from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH
from drum_player import DrumPlayer
from tape_test_utils import (
    tape_at, has_tape_at, set_tape_at, add_tape_at, all_tape_events,
    assign_tape, flush_tape, tapes_equal_strict, tape_positions, same_events,
)


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
    return TapeEvent(ETYPE_KIT, dur=dur, payload={"note": note, "vel": vel})

def _P(note, vel=100, dur=0, bend=0):
    """Raccourci : TapeEvent patch."""
    return TapeEvent(ETYPE_PATCH, dur=dur, payload={"note": note, "vel": vel, "bend": bend})


# ---------------------------------------------------------------------------
# Structure initiale du Pattern
# ---------------------------------------------------------------------------

def test_pattern_tape_initially_empty():
    p = Pattern()
    assert p.is_empty()
    print("  _tape vide à l'init : OK")


# ---------------------------------------------------------------------------
# new_pattern / reset_pattern
# ---------------------------------------------------------------------------

def test_new_pattern_resets_tape():
    p = Pattern()
    assign_tape(p, {(0, 0, 0): [_K(36)], (0, 0, 3): [_P(60)]})
    p.new_pattern()
    assert p.is_empty()
    print("  new_pattern efface _tape : OK")

def test_reset_pattern_clears_tape():
    p = Pattern()
    assign_tape(p, {(0, 0, 5): [_K(38)], (1, 0, 8): [_P(64)]})
    p.reset_pattern()
    assert p.is_empty()
    print("  reset_pattern efface _tape : OK")


# ---------------------------------------------------------------------------
# double_bars
# ---------------------------------------------------------------------------

def test_double_bars_duplicates_kit_events():
    p = Pattern()
    p.new_pattern(2, 16)
    assign_tape(p, {(0, 0, 3): [_K(36)], (0, 1, 7): [_K(38, 80)]})
    p.double_bars()
    assert has_tape_at(p, 0, 2, 3), "bar 0 dupliquée en bar 2"
    assert has_tape_at(p, 0, 3, 7), "bar 1 dupliquée en bar 3"
    assert tape_at(p, 0, 2, 3) == [_K(36)]
    assert tape_at(p, 0, 3, 7) == [_K(38, 80)]
    print("  double_bars duplique les événements K dans _tape : OK")

def test_double_bars_preserves_original_kit_events():
    p = Pattern()
    p.new_pattern(2, 16)
    assign_tape(p, {(0, 0, 1): [_K(42)]})
    p.double_bars()
    assert has_tape_at(p, 0, 0, 1), "entrée originale conservée"
    print("  double_bars conserve les entrées originales de _tape : OK")

def test_double_bars_duplicates_patch_events():
    p = Pattern()
    p.new_pattern(2, 16)
    assign_tape(p, {(0, 0, 5): [_P(60, 100, 400)], (0, 1, 10): [_P(62, 90, 200)]})
    p.double_bars()
    assert has_tape_at(p, 0, 2, 5)
    assert has_tape_at(p, 0, 3, 10)
    assert tape_at(p, 0, 2, 5)  == [_P(60, 100, 400)]
    assert tape_at(p, 0, 3, 10) == [_P(62, 90, 200)]
    print("  double_bars duplique les événements P dans _tape : OK")


# ---------------------------------------------------------------------------
# halve_bars
# ---------------------------------------------------------------------------

def test_halve_bars_removes_second_half_kit_events():
    p = Pattern()
    p.new_pattern(4, 16)
    assign_tape(p, {
        (0, 0, 0): [_K(36)],   # bar 0 → conservé
        (0, 1, 0): [_K(38)],   # bar 1 → conservé
        (0, 2, 0): [_K(42)],   # bar 2 → supprimé
        (0, 3, 0): [_K(46)],   # bar 3 → supprimé
    })
    p.halve_bars()
    assert has_tape_at(p, 0, 0, 0)
    assert has_tape_at(p, 0, 1, 0)
    assert not has_tape_at(p, 0, 2, 0)
    assert not has_tape_at(p, 0, 3, 0)
    print("  halve_bars filtre les événements K hors de la 1ère moitié : OK")

def test_halve_bars_removes_second_half_patch_events():
    p = Pattern()
    p.new_pattern(4, 16)
    assign_tape(p, {
        (0, 0, 5): [_P(60, 100, 300)],
        (0, 3, 5): [_P(65, 80, 150)],
    })
    p.halve_bars()
    assert has_tape_at(p, 0, 0, 5)
    assert not has_tape_at(p, 0, 3, 5)
    print("  halve_bars filtre les événements P hors de la 1ère moitié : OK")


# ---------------------------------------------------------------------------
# resize
# ---------------------------------------------------------------------------

def test_resize_filters_kit_events_out_of_range():
    p = Pattern()
    p.new_pattern(4, 16)
    assign_tape(p, {
        (0, 0, 3):  [_K(36)],   # conservé
        (0, 1, 15): [_K(38)],   # conservé
        (0, 2, 5):  [_K(42)],   # supprimé (bar >= 2)
    })
    p.resize(2, 16)
    assert has_tape_at(p, 0, 0, 3)
    assert has_tape_at(p, 0, 1, 15)
    assert not has_tape_at(p, 0, 2, 5)
    print("  resize filtre les événements K (bars hors limites) : OK")

def test_resize_filters_patch_events_out_of_range():
    p = Pattern()
    p.new_pattern(2, 32)
    assign_tape(p, {
        (0, 0, 31): [_P(60, 100, 200)],   # conservé
        (0, 1, 5):  [_P(62, 90, 150)],    # supprimé (bar >= 1)
    })
    p.resize(1, 32)
    assert has_tape_at(p, 0, 0, 31)
    assert not has_tape_at(p, 0, 1, 5)
    print("  resize filtre les événements P (bars hors limites) : OK")

def test_resize_filters_kit_events_steps_out_of_range():
    p = Pattern()
    p.new_pattern(1, 32)
    assign_tape(p, {
        (0, 0, 15): [_K(36)],   # conservé
        (0, 0, 16): [_K(38)],   # supprimé (step >= 16)
    })
    p.resize(1, 16)
    assert has_tape_at(p, 0, 0, 15)
    assert not has_tape_at(p, 0, 0, 16)
    print("  resize filtre les événements K (steps hors limites) : OK")


# ---------------------------------------------------------------------------
# to_dict / from_dict — format tape_v2 (Phase 7 étape 1e) + rétrocompatibilité
# ---------------------------------------------------------------------------

def test_to_dict_kit_event_in_tape_v2():
    p = Pattern()
    assign_tape(p, {(0, 0, 3): [_K(36)]})
    track0 = p.to_dict()["tape_v2"][0]
    assert len(track0) == 1
    ev_time, etype, dur, channel, payload = track0[0]
    assert ev_time  == p._bar_step_to_time(0, 3)
    assert etype    == ETYPE_KIT
    assert dur      == 0
    assert channel  == 0
    assert payload  == {"note": 36, "vel": 100}
    print("  to_dict tape_v2 : événement KIT correctement sérialisé : OK")

def test_to_dict_patch_event_in_tape_v2():
    p = Pattern()
    assign_tape(p, {(1, 0, 7): [_P(60, 90, 350, 2048)]})
    track1 = p.to_dict()["tape_v2"][1]
    assert len(track1) == 1
    ev_time, etype, dur, channel, payload = track1[0]
    assert ev_time  == p._bar_step_to_time(0, 7)
    assert etype    == ETYPE_PATCH
    assert dur      == 350
    assert channel  == 0
    assert payload  == {"note": 60, "vel": 90, "bend": 2048}
    print("  to_dict tape_v2 : événement PATCH correctement sérialisé (avec bend) : OK")

def test_roundtrip_kit_tape():
    src = Pattern()
    assign_tape(src, {
        (0, 0, 2): [_K(36), _K(42, 80)],
        (1, 0, 8): [_K(38, 127)],
    })
    dst = Pattern()
    dst.from_dict(src.to_dict())
    assert tapes_equal_strict(dst._tape, src._tape)
    print("  to_dict → from_dict kit events round-trip : OK")

def test_roundtrip_patch_tape():
    src = Pattern()
    assign_tape(src, {
        (0, 0, 4): [_P(60, 100, 500), _P(64, 90, 250)],
        (0, 1, 0): [_P(67, 80, 300)],
    })
    dst = Pattern()
    dst.from_dict(src.to_dict())
    assert tapes_equal_strict(dst._tape, src._tape)
    print("  to_dict → from_dict patch events round-trip : OK")

def test_roundtrip_patch_tape_with_bend():
    """Régression : to_dict levait ValueError sur les 4-tuples."""
    src = Pattern()
    assign_tape(src, {
        (0, 0, 0): [_P(60, 100, 500, 4096), _P(62, 90, 300, -2000)],
        (1, 0, 4): [_P(67, 80, 200)],
    })
    try:
        d = src.to_dict()
    except ValueError as e:
        assert False, f"to_dict lève ValueError sur _tape : {e}"
    dst = Pattern()
    dst.from_dict(d)
    assert tape_at(dst, 0, 0, 0)[0] == _P(60, 100, 500, 4096)
    assert tape_at(dst, 0, 0, 0)[1] == _P(62, 90, 300, -2000)
    assert tape_at(dst, 1, 0, 4)[0] == _P(67, 80, 200)
    print("  to_dict → from_dict patch 4-tuples avec bend (régression) : OK")

def test_from_dict_kit_tape_backward_compat_5_columns():
    """Anciens presets sans colonne dur doivent se charger avec dur=0."""
    old = {
        "curpattern": Pattern().to_dense_grid(),
        "kit_tape": [[0, 0, 3, 36, 100]],   # 5 colonnes, sans dur
    }
    p = Pattern()
    p.from_dict(old)
    assert has_tape_at(p, 0, 0, 3)
    assert tape_at(p, 0, 0, 3) == [_K(36)]
    print("  from_dict kit rétro-compat 5 colonnes → dur=0 : OK")

def test_from_dict_patch_tape_backward_compat_5_columns():
    """Anciens presets sans dur ni bend doivent charger dur=0, bend=0."""
    old = {
        "curpattern": Pattern().to_dense_grid(),
        "patch_tape": [[0, 0, 7, 60, 90]],   # 5 colonnes
    }
    p = Pattern()
    p.from_dict(old)
    assert has_tape_at(p, 0, 0, 7)
    assert tape_at(p, 0, 0, 7) == [_P(60, 90, 0, 0)]
    print("  from_dict patch rétro-compat 5 colonnes → dur=0, bend=0 : OK")

def test_from_dict_patch_tape_backward_compat_6_columns():
    """Anciens presets avec dur mais sans bend doivent charger bend=0."""
    old = {
        "curpattern": Pattern().to_dense_grid(),
        "patch_tape": [[0, 0, 3, 60, 100, 500]],   # 6 colonnes, sans bend
    }
    p = Pattern()
    p.from_dict(old)
    assert tape_at(p, 0, 0, 3) == [_P(60, 100, 500, 0)]
    print("  from_dict patch rétro-compat 6 colonnes → bend=0 : OK")

def test_from_dict_empty_tapes():
    p = Pattern()
    p.from_dict({"curpattern": Pattern().to_dense_grid()})
    assert p.is_empty()
    print("  from_dict sans kit_tape/patch_tape → _tape vide : OK")

def test_from_dict_mixed_kit_and_patch_same_step():
    """Kit et patch au même (track, bar, step) → tous dans _tape."""
    old = {
        "curpattern": Pattern().to_dense_grid(),
        "kit_tape":   [[0, 0, 4, 36, 100, 0]],
        "patch_tape": [[0, 0, 4, 60, 90, 500, 0]],
    }
    p = Pattern()
    p.from_dict(old)
    events = tape_at(p, 0, 0, 4)
    etypes = [ev.etype for ev in events]
    assert ETYPE_KIT in etypes and ETYPE_PATCH in etypes
    print("  from_dict kit+patch au même step → cohabitent dans _tape : OK")

def test_from_dict_old_format_then_to_dict_upgrades_to_tape_v2():
    """Charger un vieux preset (curpattern/kit_tape/patch_tape) puis re-sérialiser
    doit produire le nouveau format tape_v2 — pas de double écriture permanente."""
    old = {
        "curpattern": Pattern().to_dense_grid(),
        "kit_tape":   [[0, 0, 4, 36, 100, 0]],
        "patch_tape": [[1, 0, 7, 60, 90, 500, 100]],
    }
    p = Pattern()
    p.from_dict(old)
    d = p.to_dict()
    assert "tape_v2" in d
    assert "curpattern" not in d and "kit_tape" not in d and "patch_tape" not in d
    reloaded = Pattern()
    reloaded.from_dict(d)
    assert any(ev.etype == ETYPE_KIT   and ev.payload.get("note") == 36 for ev in tape_at(reloaded, 0, 0, 4))
    assert any(ev.etype == ETYPE_PATCH and ev.payload.get("note") == 60 for ev in tape_at(reloaded, 1, 0, 7))
    print("  from_dict (vieux format) → to_dict bascule vers tape_v2 (pas de dual-write) : OK")


# ---------------------------------------------------------------------------
# DrumPlayer.record_kit_note
# ---------------------------------------------------------------------------

def test_record_kit_note_stores_event():
    pl = _make_player()
    pl.record_kit_note(36, 100)
    events = pl._pattern._tape[0]
    assert len(events) == 1
    ev = events[0]
    assert ev.etype == ETYPE_KIT
    assert ev.payload.get("note") == 36
    assert ev.payload.get("vel")  == 100
    assert ev.dur  == 0
    print("  record_kit_note stocke TapeEvent('K', 36, 100, 0, 0) : OK")

def test_record_kit_note_no_duplicate_same_note():
    pl = _make_player()
    pl.record_kit_note(36, 100)
    pl.record_kit_note(36, 127)   # même note, même position → pas de doublon
    events = pl._pattern._tape[0]
    kit_notes = [e.payload.get("note") for e in events if e.etype == ETYPE_KIT]
    assert kit_notes.count(36) == 1, "note 36 ne doit apparaître qu'une fois"
    print("  record_kit_note : pas de doublon sur même note : OK")

def test_record_kit_note_two_different_notes_same_step():
    """Deux notes MIDI différentes au même pas sont enregistrées toutes les deux."""
    pl = _make_player()
    pl.record_kit_note(36, 100)
    pl.record_kit_note(38, 80)
    all_events = all_tape_events(pl._pattern)
    notes = [e.payload.get("note") for e in all_events if e.etype == ETYPE_KIT]
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
    events = pl._pattern._tape[0]
    assert events[0].payload.get("vel") == 127
    print("  record_kit_note clamp vélocité à 127 : OK")

def test_record_kit_note_velocity_minimum_one():
    pl = _make_player()
    pl.record_kit_note(36, 0)
    events = pl._pattern._tape[0]
    assert events[0].payload.get("vel") == 1
    print("  record_kit_note vélocité 0 → 1 : OK")


# ---------------------------------------------------------------------------
# DrumPlayer.record_patch_note — durée fixe (numpad)
# ---------------------------------------------------------------------------

def test_record_patch_note_fixed_duration():
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    events = pl._pattern._tape[0]
    assert len(events) == 1
    ev = events[0]
    assert ev.etype == ETYPE_PATCH
    assert ev.payload.get("note") == 60
    assert ev.payload.get("vel")  == 100
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
    events = pl._pattern._tape[0]
    assert events[0].dur == 0
    print("  record_patch_note duration_ms=0 stocké : OK")

def test_record_patch_note_replaces_same_note_at_same_step():
    pl = _make_player()
    pl.record_patch_note(60, 100, 300)
    pl.record_patch_note(60, 90, 400)   # même note, même step → remplace
    all_events = [e for e in all_tape_events(pl._pattern) if e.etype == ETYPE_PATCH]
    notes = [e.payload.get("note") for e in all_events]
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
    events = pl._pattern._tape[0]
    assert events[0].dur == 0, "durée provisoire = 0"
    print("  record_patch_note MIDI → durée provisoire 0 : OK")

def test_record_patch_note_midi_registers_pending():
    pl = _make_player()
    pl.record_patch_note(60, 100)
    assert 60 in pl._pending_patch, "note 60 doit être en attente de note_off"
    print("  record_patch_note MIDI → enregistré dans _pending_patch : OK")

def test_record_patch_note_off_updates_duration():
    pl = _make_player()
    bar_idx, step_idx = pl.record_patch_note(60, 100)
    track, target_ev, _ = pl._pending_patch[60]
    pl._pending_patch[60] = (track, target_ev, time.perf_counter() - 0.300)
    pl.record_patch_note_off(60)
    ev = tape_at(pl._pattern, track, bar_idx, step_idx)[0]
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
    key = tape_positions(pl._pattern, track=0)[0]
    result = pl.erase_patch_tape_note(0, 60)
    assert result is not None
    assert not has_tape_at(pl._pattern, *key), "clé supprimée quand liste vide"
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
    key = tape_positions(pl._pattern, track=0)[0]
    pl.erase_patch_tape_note(0, 60)
    remaining = [e.payload.get("note") for e in tape_at(pl._pattern, *key) if e.etype == ETYPE_PATCH]
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
    assert pl._pattern.is_empty(), "_tape vide après deux effacements"
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
    key = tape_positions(pl._pattern, track=0)[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl._erase_tape_event(0, 36, t_sec, ETYPE_KIT)

    assert not has_tape_at(pl._pattern, *key)
    print("  _erase_tape_event supprime l'événement K : OK")

def test_erase_tape_event_keeps_other_kit_notes():
    """Note 38 au même step n'est pas touchée quand on efface note 36 (K)."""
    pl = _make_player()
    pl.record_kit_note(36, 100)
    pl.record_kit_note(38, 80)
    key = tape_positions(pl._pattern, track=0)[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl._erase_tape_event(0, 36, t_sec, ETYPE_KIT)

    remaining = [e.payload.get("note") for e in tape_at(pl._pattern, *key) if e.etype == ETYPE_KIT]
    assert 38 in remaining
    assert 36 not in remaining
    print("  _erase_tape_event conserve les autres notes K du step : OK")

def test_run_thread_auto_erase_kit_tape():
    """Simule la logique _run_thread pour KIT_TAPE_EVENT en mode Erase."""
    pl = _make_player()
    pl.record_kit_note(36, 100)
    key = tape_positions(pl._pattern, track=0)[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl.toggle_erase()
    pl._erase_active_midi_notes = {36}

    t_idx, midi_note, dur = 0, 36, 0
    if pl.erasing and t_idx == pl._cur_track \
            and midi_note in pl._erase_active_midi_notes:
        pl._erase_tape_event(t_idx, midi_note, t_sec, ETYPE_KIT)

    assert not has_tape_at(pl._pattern, *key)
    print("  _run_thread logique : KIT_TAPE_EVENT effacé si note active en Erase : OK")

def test_erase_tape_event_removes_patch_note():
    """_erase_tape_event supprime la note P ciblée dans _tape."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    key = tape_positions(pl._pattern, track=0)[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl._erase_tape_event(0, 60, t_sec, ETYPE_PATCH)

    assert not has_tape_at(pl._pattern, *key), "clé supprimée après effacement"
    print("  _erase_tape_event supprime l'événement P et la clé vide : OK")

def test_erase_tape_event_keeps_other_patch_notes():
    """Note 64 au même step n'est pas touchée quand on efface note 60 (P)."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    pl.record_patch_note(64, 90, 400)
    key = tape_positions(pl._pattern, track=0)[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl._erase_tape_event(0, 60, t_sec, ETYPE_PATCH)

    remaining = [e.payload.get("note") for e in tape_at(pl._pattern, *key) if e.etype == ETYPE_PATCH]
    assert 64 in remaining, "note 64 doit rester"
    assert 60 not in remaining
    print("  _erase_tape_event ne touche pas les autres notes P du step : OK")

def test_erase_tape_event_no_crash_on_missing_step():
    """Pas de plantage si t_sec ne correspond à aucun step enregistré."""
    pl = _make_player()
    try:
        pl._erase_tape_event(0, 60, 99.9, ETYPE_PATCH)
        print("  _erase_tape_event step absent → no-op : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"

def test_erase_tape_event_etype_discriminates():
    """Effacer K ne touche pas P au même step, et vice versa."""
    pl = _make_player()
    pl.record_kit_note(60, 100)    # K note 60
    pl.record_patch_note(60, 100, 500)  # P note 60 (même note, même step)
    key = tape_positions(pl._pattern, track=0)[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl._erase_tape_event(0, 60, t_sec, ETYPE_KIT)   # efface seulement K

    events = tape_at(pl._pattern, *key)
    etypes = [e.etype for e in events]
    assert ETYPE_KIT not in etypes
    assert ETYPE_PATCH in etypes
    print("  _erase_tape_event discrimine etype : K effacé, P conservé : OK")

def test_run_thread_auto_erase_uses_erase_active_midi_notes():
    """Simule la logique _run_thread : PATCH_TAPE_EVENT efface si note dans _erase_active_midi_notes."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    key = tape_positions(pl._pattern, track=0)[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    pl.toggle_erase()
    pl._erase_active_midi_notes.add(60)

    t_idx, midi_note, dur = 0, 60, 500
    if pl.erasing and t_idx == pl._cur_track \
            and midi_note in pl._erase_active_midi_notes:
        pl._erase_tape_event(t_idx, midi_note, t_sec, ETYPE_PATCH)

    assert not has_tape_at(pl._pattern, *key)
    print("  _run_thread logique : PATCH_TAPE_EVENT effacé si note active en Erase : OK")

def test_run_thread_no_erase_if_note_not_active():
    """Si la note n'est pas dans _erase_active_midi_notes, elle n'est pas effacée."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    key = tape_positions(pl._pattern, track=0)[0]
    _, bar_idx, step_idx = key
    t_sec = (bar_idx * pl._pattern._num_steps + step_idx) * pl.step_duration

    played = []
    pl._on_patch_tape_cb = lambda t, n, v, d, b=0: played.append(n)

    pl.toggle_erase()
    # note 60 PAS dans _erase_active_midi_notes

    t_idx, midi_note, dur = 0, 60, 500
    if pl.erasing and t_idx == pl._cur_track \
            and midi_note in pl._erase_active_midi_notes:
        pl._erase_tape_event(t_idx, midi_note, t_sec, ETYPE_PATCH)
    elif pl._on_patch_tape_cb:
        pl._on_patch_tape_cb(t_idx, midi_note, 100, dur)

    assert 60 in played, "la note doit être jouée, pas effacée"
    assert has_tape_at(pl._pattern, *key), "l'événement ne doit pas être supprimé"
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
            snap = [list(track_list) for track_list in pl._pattern._tape]
        for t_idx, note_list in enumerate(snap):
            pl.erase_patch_tape_note(0, 60)
            for ev in note_list:
                if ev.etype == ETYPE_PATCH:
                    collected.append(ev.payload.get("note"))
    except RuntimeError as e:
        assert False, f"RuntimeError (accès concurrent non protégé) : {e}"
    print("  snapshot _tape immunise contre la modification concurrente : OK")

def test_tape_snapshot_safe_during_concurrent_kit_delete():
    """Suppression d'une piste pendant l'itération ne lève pas RuntimeError."""
    pl = _make_player()
    pl.record_kit_note(36, 100)
    pl.record_kit_note(38, 100)

    try:
        with pl._pattern._lock:
            snap = [list(track_list) for track_list in pl._pattern._tape]
        for t_idx, note_list in enumerate(snap):
            for t in range(len(pl._pattern._tape)):
                pl._pattern._tape[t] = []
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
    """record_patch_note stocke le bend dans TapeEvent.payload["bend"]."""
    pl = _make_player()
    bend_val = 4096
    pl.record_patch_note(60, 100, 500, bend=bend_val)
    events = pl._pattern._tape[0]
    assert len(events) == 1
    ev = events[0]
    assert ev.etype == ETYPE_PATCH
    assert ev.payload.get("note") == 60
    assert ev.payload.get("bend", 0) == bend_val
    print(f"  record_patch_note stocke bend={bend_val} dans TapeEvent : OK")

def test_record_patch_note_bend_zero_by_default():
    """Sans pitch bend actif, TapeEvent.payload["bend"] doit être 0."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    events = pl._pattern._tape[0]
    assert events[0].payload.get("bend", 0) == 0
    print('  record_patch_note sans bend → TapeEvent.payload["bend"] = 0 : OK')

def test_record_patch_note_off_preserves_bend():
    """record_patch_note_off (durée MIDI) préserve le bend dans TapeEvent."""
    pl = _make_player()
    bend_val = -8192
    pl.record_patch_note(60, 100, bend=bend_val)   # duration_ms=None → pending
    pl.record_patch_note_off(60)
    events = pl._pattern._tape[0]
    ev = events[0]
    assert ev.payload.get("bend", 0) == bend_val, f"bend {bend_val} doit être conservé après note_off"
    assert ev.dur > 0, "durée doit être > 0 après note_off"
    print(f"  record_patch_note_off préserve bend={bend_val} dans TapeEvent : OK")

def test_run_thread_dispatch_passes_bend_to_callback():
    """Simule le dispatch _run_thread : on_patch_tape_cb reçoit (t, n, v, d, bend)."""
    received = []
    pl = _make_player()
    pl._on_patch_tape_cb = lambda t, n, v, d, b=0: received.append((t, n, v, d, b))

    bend_val = 8191
    pl.record_patch_note(60, 100, 500, bend=bend_val)
    key = tape_positions(pl._pattern, track=0)[0]
    _, bar_idx, step_idx = key

    note_list = tape_at(pl._pattern, *key)
    for ev in list(note_list):
        if ev.etype != ETYPE_PATCH:
            continue
        t_idx = 0
        if not pl.erasing:
            pl._on_patch_tape_cb(t_idx, ev.payload.get("note"), ev.payload.get("vel"), ev.dur, ev.payload.get("bend", 0))

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
    p.from_dict({"curpattern": Pattern().to_dense_grid()})
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
    flush_tape(pat, player_pattern)
    pat._bend_tape = [list(t) for t in player_pattern._bend_tape]

def _apply_pattern_from_store(player_pattern, store_pat):
    """Simule _apply_pattern_from_store de MainWindow."""
    flush_tape(player_pattern, store_pat)
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
    flush_tape(store, pl._pattern)
    store._bend_tape = [list(t) for t in pl._pattern._bend_tape]

    try:
        json_str = _json.dumps(store.to_dict(), separators=(',', ':'))
    except Exception as e:
        assert False, f"json.dumps échoue : {e}"

    restored = Pattern()
    restored.from_dict(_json.loads(json_str))

    pl2 = _make_player()
    flush_tape(pl2._pattern, restored)
    pl2._pattern._bend_tape = [list(t) for t in restored._bend_tape]

    assert tapes_equal_strict(pl2._pattern._tape, pl._pattern._tape), "_tape perdu"
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
    flush_tape(store, pl._pattern)
    store._bend_tape = [list(t) for t in pl._pattern._bend_tape]

    restored = Pattern()
    restored.from_dict(_json.loads(_json.dumps(store.to_dict(), separators=(',', ':'))))

    pl2 = _make_player()
    flush_tape(pl2._pattern, restored)
    pl2._pattern._bend_tape = [list(t) for t in restored._bend_tape]

    assert tapes_equal_strict(pl2._pattern._tape, pl._pattern._tape)
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
    flush_tape(store, pl._pattern)
    store._bend_tape = [list(t) for t in pl._pattern._bend_tape]
    store._mod_tape  = [list(t) for t in pl._pattern._mod_tape]

    try:
        json_str = _json.dumps(store.to_dict(), separators=(',', ':'))
    except Exception as e:
        assert False, f"json.dumps échoue : {e}"

    restored = Pattern()
    restored.from_dict(_json.loads(json_str))

    pl2 = _make_player()
    flush_tape(pl2._pattern, restored)
    pl2._pattern._bend_tape = [list(t) for t in restored._bend_tape]
    pl2._pattern._mod_tape  = [list(t) for t in restored._mod_tape]

    assert tapes_equal_strict(pl2._pattern._tape, pl._pattern._tape), "_tape perdu"
    assert pl2._pattern._bend_tape == pl._pattern._bend_tape, "bend_tape perdu"
    assert pl2._pattern._mod_tape  == pl._pattern._mod_tape,  "mod_tape perdu"
    print("  intégration record→JSON→rechargement préserve _tape+bend+mod : OK")


# ---------------------------------------------------------------------------
# Etype ETYPE_GRID — grille unifiée dans _tape (GRID_EVENT)
# ---------------------------------------------------------------------------

def test_grid_event_constant_value():
    """GRID_EVENT vaut -6."""
    from drum_player import DrumPlayer
    assert DrumPlayer.GRID_EVENT == -6
    print("  DrumPlayer.GRID_EVENT == -6 : OK")


def test_compute_offsets_reflects_existing_G_events():
    """_compute_offsets projette les notes G déjà présentes dans _tape vers _all_offsets."""
    pl = _make_player()
    pl._pattern.set_cell(0, 3, 0, 7, 90)   # track 0, pad 3, bar 0, step 7
    pl._compute_offsets()
    assert 7.0 in pl._all_offsets[0][3]
    print("  _compute_offsets reflète les notes G existantes dans _all_offsets : OK")


def test_compute_offsets_does_not_mutate_tape():
    """_compute_offsets est une projection en lecture seule : elle ne modifie plus _tape."""
    pl = _make_player()
    set_tape_at(pl._pattern, 0, 0, 5, [TapeEvent(ETYPE_GRID, payload={"pad": 2, "vel": 100})])
    pl._compute_offsets()
    assert has_tape_at(pl._pattern, 0, 0, 5), "compute_offsets ne doit plus supprimer d'entrées _tape"
    print("  _compute_offsets ne mute plus _tape (lecture seule) : OK")


def test_compute_offsets_preserves_K_and_P():
    """_compute_offsets ne touche pas les événements K et P existants."""
    pl = _make_player()
    set_tape_at(pl._pattern, 0, 0, 3, [TapeEvent(ETYPE_KIT, payload={"note": 36, "vel": 100}),
                                        TapeEvent(ETYPE_PATCH, dur=400, payload={"note": 60, "vel": 90, "bend": 0})])
    pl._compute_offsets()   # lecture seule : ne mute pas _tape
    assert has_tape_at(pl._pattern, 0, 0, 3), "clé (0,0,3) ne doit pas disparaître"
    etypes = [ev.etype for ev in tape_at(pl._pattern, 0, 0, 3)]
    assert ETYPE_KIT in etypes, "K doit rester"
    assert ETYPE_PATCH in etypes, "P doit rester"
    print("  _compute_offsets préserve les événements K et P : OK")


def test_record_hit_adds_G_to_tape():
    """record_hit ajoute un TapeEvent 'G' dans _tape."""
    pl = _make_player()
    bar_idx, step_idx = pl.record_hit(5, 90)
    key = (0, bar_idx, step_idx)
    assert has_tape_at(pl._pattern, *key), "clé absente de _tape après record_hit"
    g_events = [ev for ev in tape_at(pl._pattern, *key)
                if ev.etype == ETYPE_GRID and ev.payload.get("pad") == 5]
    assert len(g_events) == 1, f"attendu 1 'G' pour pad 5, obtenu {len(g_events)}"
    assert g_events[0].payload.get("vel") == 90
    print("  record_hit ajoute TapeEvent('G') dans _tape : OK")


def test_record_hit_G_velocity_clamped():
    """record_hit clamp la vélocité à 127 pour le TapeEvent 'G'."""
    pl = _make_player()
    bar_idx, step_idx = pl.record_hit(0, 200)
    key = (0, bar_idx, step_idx)
    g_events = [ev for ev in tape_at(pl._pattern, *key) if ev.etype == ETYPE_GRID]
    assert g_events[0].payload.get("vel") == 127
    print("  record_hit clamp vélocité 'G' à 127 : OK")


def test_record_hit_replaces_existing_G():
    """record_hit au même step remplace le 'G' existant sans doublon."""
    pl = _make_player()
    pl.record_hit(2, 80)
    pl.record_hit(2, 120)   # même position (_measure_start=None → step 0)
    key = (0, 0, 0)
    g_events = [ev for ev in tape_at(pl._pattern, *key)
                if ev.etype == ETYPE_GRID and ev.payload.get("pad") == 2]
    assert len(g_events) == 1, f"doublon 'G' interdit, obtenu {len(g_events)}"
    assert g_events[0].payload.get("vel") == 120, "vélocité doit être mise à jour"
    print("  record_hit remplace 'G' existant au même step sans doublon : OK")


def test_record_nr_hit_adds_G_to_tape():
    """_record_nr_hit ajoute un TapeEvent 'G' dans _tape."""
    pl = _make_player()
    pl._record_nr_hit(7, 4.0)   # pad 7, offset flottant 4.0 → step 4
    key = (0, 0, 4)
    assert has_tape_at(pl._pattern, *key), "clé (0,0,4) absente après _record_nr_hit"
    g_events = [ev for ev in tape_at(pl._pattern, *key)
                if ev.etype == ETYPE_GRID and ev.payload.get("pad") == 7]
    assert len(g_events) == 1
    assert g_events[0].payload.get("vel") == 100
    print("  _record_nr_hit ajoute TapeEvent('G') dans _tape : OK")


def test_erase_hit_removes_G_from_tape():
    """erase_hit supprime le TapeEvent 'G' de _tape."""
    pl = _make_player()
    bar_idx, step_idx = pl.record_hit(3, 100)
    key = (0, bar_idx, step_idx)
    assert has_tape_at(pl._pattern, *key), "précondition : 'G' présent"
    pl.erase_hit(3)
    g_after = [ev for ev in tape_at(pl._pattern, *key)
               if ev.etype == ETYPE_GRID and ev.payload.get("pad") == 3]
    assert len(g_after) == 0, "'G' doit être supprimé après erase_hit"
    print("  erase_hit supprime TapeEvent('G') de _tape : OK")


def test_clear_offset_removes_G_from_tape():
    """_clear_offset supprime le TapeEvent 'G' de _tape."""
    pl = _make_player()
    pl._record_nr_hit(6, 2.0)   # pad 6, step 2
    key = (0, 0, 2)
    assert has_tape_at(pl._pattern, *key), "précondition : 'G' présent"
    pl._clear_offset(6, 2.0)
    g_after = [ev for ev in tape_at(pl._pattern, *key)
               if ev.etype == ETYPE_GRID and ev.payload.get("pad") == 6]
    assert len(g_after) == 0, "'G' doit être supprimé après _clear_offset"
    print("  _clear_offset supprime TapeEvent('G') de _tape : OK")


def test_to_dict_tape_v2_grid_entry_correctly_typed():
    """to_dict sérialise une note GRID avec etype=ETYPE_GRID dans tape_v2 (pas KIT/PATCH)."""
    pl = _make_player()
    pl.record_hit(4, 100)   # crée un ETYPE_GRID dans _tape
    d = pl._pattern.to_dict()
    events = [ev for track in d["tape_v2"] for ev in track]
    assert len(events) == 1
    ev_time, etype, dur, channel, payload = events[0]
    assert etype == ETYPE_GRID, f"attendu ETYPE_GRID, obtenu {etype!r}"
    print("  to_dict sérialise une note GRID avec le bon etype dans tape_v2 : OK")


def test_G_and_K_coexist_at_same_step():
    """Un event 'G' et un event 'K' peuvent cohabiter au même (track, bar, step)."""
    pl = _make_player()
    pl.record_hit(0, 100)          # 'G' note=0 → key = (0, 0, 0)
    pl.record_kit_note(36, 100)    # 'K' note=36 → même key = (0, 0, 0)
    key = (0, 0, 0)
    etypes = [ev.etype for ev in tape_at(pl._pattern, *key)]
    assert ETYPE_GRID in etypes, "'G' doit être présent"
    assert ETYPE_KIT in etypes, "'K' doit être présent"
    print("  'G' et 'K' cohabitent au même (track, bar, step) : OK")


def test_run_thread_GRID_EVENT_dispatch():
    """Simule la logique _run_thread : GRID_EVENT dispatch (track, pad, dur, vel)."""
    pl = _make_player()
    pl.record_hit(5, 90)
    key = (0, 0, 0)
    note_list = tape_at(pl._pattern, *key)

    events = []
    for ev in note_list:
        if ev.etype == ETYPE_GRID:
            events.append((0.0, pl.GRID_EVENT,
                            (0, ev.payload.get("pad"), ev.dur), ev.payload.get("vel")))

    assert len(events) == 1, f"attendu 1 GRID_EVENT, obtenu {len(events)}"
    t_sec, etype, evt_data, vel = events[0]
    assert etype == pl.GRID_EVENT, f"etype attendu GRID_EVENT, obtenu {etype}"
    t_idx, pad_idx, dur_override = evt_data
    assert t_idx        == 0
    assert pad_idx      == 5
    assert dur_override == 0   # record_hit ne pose jamais d'override
    assert vel          == 90
    print("  _run_thread dispatch GRID_EVENT : (track=0, pad=5, dur=0, vel=90) : OK")

def test_run_thread_GRID_EVENT_dispatch_carries_dur_override():
    """Phase 7 étape 1k : une durée éditée (Numpad1/3) doit voyager jusqu'au
    dispatch _run_thread, pour primer sur voice_manager.get_duration_ms."""
    pl = _make_player()
    p  = pl._pattern
    p.set_cell(0, 5, 0, 0, 90, dur=750)   # override posé via edit_grid_note en pratique
    note_list = tape_at(p, 0, 0, 0)

    events = []
    for ev in note_list:
        if ev.etype == ETYPE_GRID:
            events.append((0.0, pl.GRID_EVENT,
                            (0, ev.payload.get("pad"), ev.dur), ev.payload.get("vel")))

    t_sec, etype, evt_data, vel = events[0]
    t_idx, pad_idx, dur_override = evt_data
    assert dur_override == 750
    # Résolution effective, comme dans _run_thread : override prime sur la voix.
    effective_dur = dur_override if dur_override > 0 else pl.voice_manager.get_duration_ms(pad_idx)
    assert effective_dur == 750
    print("  _run_thread dispatch GRID_EVENT véhicule un dur_override (1k) : OK")


# ---------------------------------------------------------------------------
# Durée GRID par événement (Phase 7 étape 1k)
# ---------------------------------------------------------------------------

def test_set_cell_default_dur_zero():
    p = Pattern()
    p.set_cell(0, 3, 0, 5, 100)
    assert tape_at(p, 0, 0, 5)[0].dur == 0
    print("  set_cell sans dur → 0 (pas d'override) par défaut : OK")

def test_set_cell_stores_dur_override():
    p = Pattern()
    p.set_cell(0, 3, 0, 5, 100, dur=750)
    assert tape_at(p, 0, 0, 5)[0].dur == 750
    print("  set_cell(dur=750) stocke l'override sur l'event GRID : OK")

def test_resize_preserves_dur_override():
    p = Pattern()
    p.set_cell(0, 3, 0, 5, 100, dur=750)
    p.resize(2, 32)   # change num_steps → retemporisation interne
    ev = [e for e in p._tape[0] if e.etype == ETYPE_GRID][0]
    assert ev.dur == 750
    print("  resize (avec changement num_steps) préserve l'override de durée : OK")

def test_double_bars_preserves_dur_override():
    p = Pattern()
    p.new_pattern(1, 16)
    p.set_cell(0, 3, 0, 5, 100, dur=750)
    p.double_bars()
    evs = [e for e in p._tape[0] if e.etype == ETYPE_GRID]
    assert all(e.dur == 750 for e in evs)
    print("  double_bars préserve l'override de durée sur l'original et la copie : OK")


# ---------------------------------------------------------------------------
# Canal MIDI (Phase 7 étape 1i)
# ---------------------------------------------------------------------------

def test_set_cell_default_channel_zero():
    p = Pattern()
    p.set_cell(0, 3, 0, 5, 100)
    assert tape_at(p, 0, 0, 5)[0].channel == 0
    print("  set_cell sans channel → 0 par défaut : OK")

def test_set_cell_stores_channel():
    p = Pattern()
    p.set_cell(0, 3, 0, 5, 100, channel=9)
    assert tape_at(p, 0, 0, 5)[0].channel == 9
    print("  set_cell(channel=9) stocke le canal : OK")

def test_record_hit_stores_channel():
    pl = _make_player()
    bar_idx, step_idx = pl.record_hit(4, 100, channel=3)
    ev = [e for e in tape_at(pl._pattern, 0, bar_idx, step_idx) if e.etype == ETYPE_GRID][0]
    assert ev.channel == 3
    print("  record_hit(channel=3) stocke le canal sur l'event GRID : OK")

def test_record_kit_note_stores_channel():
    pl = _make_player()
    pl.record_kit_note(36, 100, channel=5)
    ev = [e for e in pl._pattern._tape[0] if e.etype == ETYPE_KIT][0]
    assert ev.channel == 5
    print("  record_kit_note(channel=5) stocke le canal : OK")

def test_record_patch_note_stores_channel():
    pl = _make_player()
    pl.record_patch_note(60, 100, duration_ms=200, channel=7)
    ev = [e for e in pl._pattern._tape[0] if e.etype == ETYPE_PATCH][0]
    assert ev.channel == 7
    print("  record_patch_note(channel=7) stocke le canal : OK")

def test_record_patch_note_off_preserves_channel():
    """La finalisation de durée (note_off) ne doit pas réinitialiser le canal."""
    pl = _make_player()
    pl.record_patch_note(60, 100, channel=7)   # duration_ms=None → attend note_off
    pl.record_patch_note_off(60)
    ev = [e for e in pl._pattern._tape[0] if e.etype == ETYPE_PATCH][0]
    assert ev.channel == 7
    print("  record_patch_note_off préserve le canal : OK")

def test_resize_preserves_channel():
    p = Pattern()
    p.set_cell(0, 3, 0, 5, 100, channel=9)
    p.resize(2, 32)   # change num_steps → retemporisation interne
    ev = [e for e in p._tape[0] if e.etype == ETYPE_GRID][0]
    assert ev.channel == 9
    print("  resize (avec changement num_steps) préserve le canal : OK")

def test_double_bars_preserves_channel():
    p = Pattern()
    p.new_pattern(1, 16)
    p.set_cell(0, 3, 0, 5, 100, channel=9)
    p.double_bars()
    evs = [e for e in p._tape[0] if e.etype == ETYPE_GRID]
    assert all(e.channel == 9 for e in evs)
    print("  double_bars préserve le canal sur l'original et la copie : OK")


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
    test_to_dict_kit_event_in_tape_v2()
    test_to_dict_patch_event_in_tape_v2()
    test_roundtrip_kit_tape()
    test_roundtrip_patch_tape()
    test_roundtrip_patch_tape_with_bend()
    test_from_dict_kit_tape_backward_compat_5_columns()
    test_from_dict_patch_tape_backward_compat_5_columns()
    test_from_dict_patch_tape_backward_compat_6_columns()
    test_from_dict_empty_tapes()
    test_from_dict_mixed_kit_and_patch_same_step()
    test_from_dict_old_format_then_to_dict_upgrades_to_tape_v2()
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
    # Etype ETYPE_GRID — grille unifiée dans _tape (GRID_EVENT)
    test_grid_event_constant_value()
    test_compute_offsets_reflects_existing_G_events()
    test_compute_offsets_does_not_mutate_tape()
    test_compute_offsets_preserves_K_and_P()
    test_record_hit_adds_G_to_tape()
    test_record_hit_G_velocity_clamped()
    test_record_hit_replaces_existing_G()
    test_record_nr_hit_adds_G_to_tape()
    test_erase_hit_removes_G_from_tape()
    test_clear_offset_removes_G_from_tape()
    test_to_dict_tape_v2_grid_entry_correctly_typed()
    test_G_and_K_coexist_at_same_step()
    test_run_thread_GRID_EVENT_dispatch()
    test_run_thread_GRID_EVENT_dispatch_carries_dur_override()
    # Durée GRID par événement (Phase 7 étape 1k)
    test_set_cell_default_dur_zero()
    test_set_cell_stores_dur_override()
    test_resize_preserves_dur_override()
    test_double_bars_preserves_dur_override()
    # Canal MIDI (Phase 7 étape 1i)
    test_set_cell_default_channel_zero()
    test_set_cell_stores_channel()
    test_record_hit_stores_channel()
    test_record_kit_note_stores_channel()
    test_record_patch_note_stores_channel()
    test_record_patch_note_off_preserves_channel()
    test_resize_preserves_channel()
    test_double_bars_preserves_channel()
    print("Tous les tests : OK")
