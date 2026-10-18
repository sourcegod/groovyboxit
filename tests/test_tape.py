#python3
"""
    File: tests/test_tape.py
    Tests unitaires de _tape (TapeEvent, Pitch Bend compris — ETYPE_BEND depuis 6b1) :
    structure Pattern, lifecycle (new/reset/double/halve/resize),
    sérialisation to_dict/from_dict, enregistrement DrumPlayer,
    et durée note_on→note_off pour les événements patch.
    _mod_tape a existé puis a été supprimé en Phase 7 étape 5h (CC#1 vit
    dans _tape, ETYPE_CC, depuis 5b) — voir la migration .gvp testée plus
    bas (from_dict convertit un ancien 'mod_tape' en ETYPE_CC cc_num=1).
    Date: Fri, 06/06/2026
    Author: Coolbrother
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH, ETYPE_CC, ETYPE_PGM, ETYPE_BEND
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

def _P(note, vel=100, dur=0):
    """Raccourci : TapeEvent patch (sans bend par note depuis la Phase 7 étape 7f1)."""
    return TapeEvent(ETYPE_PATCH, dur=dur, payload={"note": note, "vel": vel})

def _P_old(note, vel=100, dur=0, bend=0):
    """TapeEvent patch au format d'avant la Phase 7 étape 7h1 (champ "bend"
    par note), pour les tests de migration."""
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
    assign_tape(p, {(1, 0, 7): [_P(60, 90, 350)]})
    track1 = p.to_dict()["tape_v2"][1]
    assert len(track1) == 1
    ev_time, etype, dur, channel, payload = track1[0]
    assert ev_time  == p._bar_step_to_time(0, 7)
    assert etype    == ETYPE_PATCH
    assert dur      == 350
    assert channel  == 0
    assert payload  == {"note": 60, "vel": 90}
    print("  to_dict tape_v2 : événement PATCH correctement sérialisé (sans bend) : OK")

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

def test_roundtrip_patch_tape_with_bend_points():
    """Notes PATCH + ETYPE_BEND au même pas : aller-retour à l'identique,
    sans point ajouté par la migration (les notes n'ont pas de champ bend)."""
    src = Pattern()
    assign_tape(src, {
        (0, 0, 0): [TapeEvent(ETYPE_BEND, payload={"value": 4096}),
                    _P(60, 100, 500), _P(62, 90, 300)],
        (1, 0, 4): [_P(67, 80, 200)],
    })
    dst = Pattern()
    dst.from_dict(src.to_dict())
    assert tapes_equal_strict(dst._tape, src._tape)
    print("  to_dict → from_dict notes PATCH + ETYPE_BEND à l'identique : OK")

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
    """Anciens presets sans dur ni bend doivent charger dur=0, sans bend."""
    old = {
        "curpattern": Pattern().to_dense_grid(),
        "patch_tape": [[0, 0, 7, 60, 90]],   # 5 colonnes
    }
    p = Pattern()
    p.from_dict(old)
    assert has_tape_at(p, 0, 0, 7)
    assert tape_at(p, 0, 0, 7) == [_P(60, 90, 0)]
    print("  from_dict patch rétro-compat 5 colonnes → dur=0, sans bend : OK")

def test_from_dict_patch_tape_backward_compat_6_columns():
    """Anciens presets avec dur mais sans bend : note sans bend, aucun ETYPE_BEND."""
    old = {
        "curpattern": Pattern().to_dense_grid(),
        "patch_tape": [[0, 0, 3, 60, 100, 500]],   # 6 colonnes, sans bend
    }
    p = Pattern()
    p.from_dict(old)
    assert tape_at(p, 0, 0, 3) == [_P(60, 100, 500)]
    print("  from_dict patch rétro-compat 6 colonnes → sans bend : OK")

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
# DrumPlayer.record_cc / record_program_change (Phase 7 étape 4e)
# ---------------------------------------------------------------------------

def test_record_cc_stores_event():
    pl = _make_player()
    pl.record_cc(74, 90, channel=3)
    events = pl._pattern._tape[0]
    assert len(events) == 1
    ev = events[0]
    assert ev.etype == ETYPE_CC
    assert ev.payload == {"cc_num": 74, "value": 90}
    assert ev.channel == 3
    assert ev.dur == 0
    print("  record_cc stocke TapeEvent(CC, cc_num=74, value=90) : OK")

def test_record_cc_no_dedup_same_value_same_step():
    """Contrairement à record_kit_note, deux CC identiques au même tick sont
    tous les deux enregistrés (données valides, pas un doublon à filtrer)."""
    pl = _make_player()
    pl.record_cc(1, 64)
    pl.record_cc(1, 64)
    events = [e for e in pl._pattern._tape[0] if e.etype == ETYPE_CC]
    assert len(events) == 2
    print("  record_cc : pas de dédoublonnage, deux CC identiques conservés : OK")

def test_record_cc_returns_bar_step():
    pl = _make_player()
    bar_idx, step_idx = pl.record_cc(7, 100)
    assert isinstance(bar_idx,  int)
    assert isinstance(step_idx, int)
    print("  record_cc retourne (bar_idx, step_idx) valides : OK")

def _player_at_offset(offset_steps):
    """Player dont l'horloge d'enregistrement est à `offset_steps` pas du
    début de la boucle (mesure de référence placée dans le passé)."""
    pl = _make_player()
    pl._measure_start = time.perf_counter() - offset_steps * pl.step_duration
    return pl

def test_record_cc_stores_fractional_time():
    """Phase 7 étape 5b : un CC garde sa position sous-pas, pas d'arrondi
    au pas entier (sinon balayage de molette rejoué en escalier)."""
    pl = _player_at_offset(3.4)
    bar_idx, step_idx = pl.record_cc(1, 64)
    ev = pl._pattern._tape[0][0]
    assert 3.35 < ev.time < 3.6, ev.time
    assert ev.time != int(ev.time)
    assert (bar_idx, step_idx) == (0, 3)   # pas tronqué, pas arrondi à 4
    print("  record_cc stocke une position fractionnaire (≈3.4) : OK")

def test_record_cc_ignores_record_quantization():
    """La quantisation d'enregistrement reste réservée aux notes."""
    pl = _player_at_offset(3.4)
    pl._quant_in_recording = True
    pl.quant_idx = 7   # 1/16 → calerait au pas 3
    pl.record_cc(1, 64)
    pl.record_hit(0)
    cc  = [e for e in pl._pattern._tape[0] if e.etype == ETYPE_CC][0]
    hit = [e for e in pl._pattern._tape[0] if e.etype == ETYPE_GRID][0]
    assert cc.time != int(cc.time)
    assert hit.time == 3                   # la note, elle, est quantifiée
    print("  record_cc ignore la quantisation d'enregistrement (notes : oui) : OK")

def test_record_cc_successive_points_keep_their_order():
    """Plusieurs points d'un même pas restent distincts et croissants."""
    pl = _player_at_offset(5.1)
    pl.record_cc(1, 10)
    pl._measure_start -= 0.3 * pl.step_duration
    pl.record_cc(1, 20)
    t1, t2 = (e.time for e in pl._pattern._tape[0])
    assert int(t1) == int(t2) == 5
    assert t1 < t2
    print("  record_cc : deux points dans le même pas, positions distinctes : OK")

def test_record_cc_count_in_gives_zero():
    """Frappe anticipée (mesure de référence dans le futur) → position 0."""
    pl = _make_player()
    pl._measure_start = time.perf_counter() + 10
    pl.record_cc(7, 100)
    assert pl._pattern._tape[0][0].time == 0.0
    print("  record_cc pendant le count-in → position 0 : OK")

def test_record_program_change_stays_on_integer_step():
    """Program Change reste ponctuel, calé au pas entier (décision 1)."""
    pl = _player_at_offset(3.4)
    pl.record_program_change(5)
    assert pl._pattern._tape[0][0].time == 3
    print("  record_program_change reste au pas entier : OK")

def test_resize_preserves_fractional_time():
    """Phase 7 étape 5b : la fraction de pas suit la nouvelle position."""
    p = Pattern()
    p.resize(2, 16)
    p._tape[0].append(TapeEvent(ETYPE_CC, payload={"cc_num": 1, "value": 64}, time=19.25))
    p.resize(2, 8)    # bar 1 step 3 → 1*8 + 3 = 11, + .25
    assert p._tape[0][0].time == 11.25
    p.resize(4, 8)    # num_steps inchangé → position inchangée
    assert p._tape[0][0].time == 11.25
    print("  resize préserve la fraction de pas d'un CC : OK")

def test_resize_integer_time_stays_int():
    """Non-régression : un événement au pas entier ne devient pas flottant."""
    p = Pattern()
    p.set_cell(0, 3, 1, 5, 100)
    p.resize(2, 32)
    ev = p._tape[0][0]
    assert ev.time == 37 and isinstance(ev.time, int)
    print("  resize : time entier reste un int : OK")

def test_record_program_change_stores_event():
    pl = _make_player()
    pl.record_program_change(42, channel=9)
    events = pl._pattern._tape[0]
    assert len(events) == 1
    ev = events[0]
    assert ev.etype == ETYPE_PGM
    assert ev.payload == {"program": 42}
    assert ev.channel == 9
    assert ev.dur == 0
    print("  record_program_change stocke TapeEvent(PGM, program=42) : OK")

def test_record_program_change_returns_bar_step():
    pl = _make_player()
    bar_idx, step_idx = pl.record_program_change(3)
    assert isinstance(bar_idx,  int)
    assert isinstance(step_idx, int)
    print("  record_program_change retourne (bar_idx, step_idx) valides : OK")

def test_cc_tape_callback_receives_track_cc_and_value():
    received = []
    pl = _make_player()
    pl._on_cc_tape_cb = lambda t, cc, v: received.append((t, cc, v))
    pl._on_cc_tape_cb(2, 74, 90)
    assert received == [(2, 74, 90)]
    print("  on_cc_tape_cb reçoit (track_idx, cc_num, value) : OK")

def test_cc_tape_no_callback_is_safe():
    pl = _make_player()
    pl._on_cc_tape_cb = None
    try:
        if pl._on_cc_tape_cb:
            pl._on_cc_tape_cb(0, 0, 0)
        print("  on_cc_tape_cb=None → no-op sans plantage : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"

def test_program_change_tape_callback_receives_track_and_program():
    received = []
    pl = _make_player()
    pl._on_program_change_tape_cb = lambda t, p: received.append((t, p))
    pl._on_program_change_tape_cb(1, 42)
    assert received == [(1, 42)]
    print("  on_program_change_tape_cb reçoit (track_idx, program) : OK")

def test_program_change_tape_no_callback_is_safe():
    pl = _make_player()
    pl._on_program_change_tape_cb = None
    try:
        if pl._on_program_change_tape_cb:
            pl._on_program_change_tape_cb(0, 0)
        print("  on_program_change_tape_cb=None → no-op sans plantage : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"

def test_run_thread_build_cc_and_pgm_events_mixed_with_patch():
    """Non-régression (Phase 7 étape 4e) : un ETYPE_CC/ETYPE_PGM dans _tape,
    aux côtés d'un ETYPE_PATCH sur la même piste, ne casse plus la
    construction des événements de lecture. Piège identifié en 4a : l'ancien
    `else` catch-all aurait lu le CC/PGM comme un PATCH (note=None, bend=0)."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    pl.record_cc(74, 90)
    pl.record_program_change(5)

    events = []
    for t_idx, note_list in enumerate(pl._pattern._tape):
        for ev in note_list:
            if ev.etype == ETYPE_GRID:
                events.append((pl.GRID_EVENT,
                               (t_idx, ev.payload.get("pad"), ev.dur), ev.payload.get("vel")))
            elif ev.etype == ETYPE_KIT:
                events.append((pl.KIT_TAPE_EVENT,
                               (t_idx, ev.payload.get("note"), ev.dur), ev.payload.get("vel")))
            elif ev.etype == ETYPE_PATCH:
                events.append((pl.PATCH_TAPE_EVENT,
                               (t_idx, ev.payload.get("note"), ev.dur),
                               ev.payload.get("vel")))
            elif ev.etype == ETYPE_CC:
                events.append((pl.CC_TAPE_EVENT,
                               (t_idx, ev.payload.get("cc_num"), ev.payload.get("value")), 0))
            elif ev.etype == ETYPE_PGM:
                events.append((pl.PGM_TAPE_EVENT, (t_idx, ev.payload.get("program")), 0))

    by_type = {e[0]: e for e in events}
    assert len(events) == 3, "GRID/KIT/PATCH/CC/PGM exhaustifs, aucun événement fantôme"

    _, (t_idx, note, dur), vel = by_type[pl.PATCH_TAPE_EVENT]
    assert (note, dur, vel) == (60, 500, 100), \
        "le PATCH voisin d'un CC/PGM garde ses vraies valeurs (pas de note=None)"

    _, (t_idx, cc_num, value), _ = by_type[pl.CC_TAPE_EVENT]
    assert (cc_num, value) == (74, 90)

    _, (t_idx, program), _ = by_type[pl.PGM_TAPE_EVENT]
    assert program == 5
    print("  _run_thread : CC/PGM aux côtés d'un PATCH, catégorisation correcte, pas de note=None : OK")


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

def _patch_notes(pattern, track):
    return [ev for ev in pattern._tape[track] if ev.etype == ETYPE_PATCH]

def test_record_patch_note_payload_has_no_bend():
    """Phase 7 étape 7f1 : la note PATCH ne porte plus de bend, même tenu."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500, bend=4096)
    notes = _patch_notes(pl._pattern, 0)
    assert len(notes) == 1
    assert notes[0].payload == {"note": 60, "vel": 100}
    print("  record_patch_note : payload sans \"bend\" : OK")

def test_record_patch_note_with_held_bend_chases_etype_bend():
    """Bend tenu au note-on (état de piste à 0) → un ETYPE_BEND au temps de
    la note, avec le canal de la note."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500, bend=4096, channel=3)
    note  = _patch_notes(pl._pattern, 0)[0]
    bends = _bends(pl._pattern, 0)
    assert len(bends) == 1
    assert bends[0].time == note.time
    assert bends[0].payload == {"value": 4096}
    assert bends[0].channel == 3
    print("  record_patch_note bend tenu → ETYPE_BEND au temps de la note : OK")

def test_record_patch_note_bend_zero_without_state_adds_nothing():
    """Sans bend actif ni état antérieur : aucun ETYPE_BEND."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500)
    assert _bends(pl._pattern, 0) == []
    assert "bend" not in _patch_notes(pl._pattern, 0)[0].payload
    print("  record_patch_note sans bend → aucun ETYPE_BEND : OK")

def test_record_patch_note_no_duplicate_when_state_already_equal():
    """Bend déjà enregistré à la même valeur avant la note (par
    on_pitch_bend/record_bend) → pas de second point."""
    pl = _make_player()
    pl._pattern._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": 2048}, time=0.0))
    pl.record_patch_note(60, 100, 500, bend=2048)
    assert [ev.payload["value"] for ev in _bends(pl._pattern, 0)] == [2048]
    print("  record_patch_note : pas de doublon si l'état est déjà égal : OK")

def test_record_patch_note_bend_back_to_zero_after_bent_state():
    """État de piste plié (2048) et molette revenue au centre au note-on :
    un ETYPE_BEND 0 remet l'état au centre au temps de la note."""
    pl = _make_player()
    pl._pattern._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": 2048}, time=0.0))
    pl.record_patch_note(60, 100, 500, bend=0)
    note = _patch_notes(pl._pattern, 0)[0]
    bends = _bends(pl._pattern, 0)
    assert len(bends) == 2
    assert (bends[-1].time, bends[-1].payload["value"]) == (note.time, 0)
    assert pl._pattern._bend_state_at(0, note.time) == 0
    print("  record_patch_note : retour au centre → ETYPE_BEND 0 : OK")

def test_record_patch_note_replaced_note_does_not_duplicate_bend():
    """Deux fois la même note au même pas (remplacement) avec le même bend
    tenu : un seul ETYPE_BEND."""
    pl = _make_player()
    pl.record_patch_note(60, 100, 500, bend=1000)
    pl.record_patch_note(60, 110, 500, bend=1000)
    assert len(_patch_notes(pl._pattern, 0)) == 1
    assert len(_bends(pl._pattern, 0)) == 1
    print("  note remplacée au même pas : un seul ETYPE_BEND : OK")

def test_record_patch_note_off_keeps_chased_bend():
    """record_patch_note_off (durée MIDI) ne touche pas au point de bend posé
    au note-on, et la note n'a toujours pas de champ bend."""
    pl = _make_player()
    pl.record_patch_note(60, 100, bend=-8192)   # duration_ms=None → pending
    pl.record_patch_note_off(60)
    note = _patch_notes(pl._pattern, 0)[0]
    assert note.dur > 0, "durée doit être > 0 après note_off"
    assert "bend" not in note.payload
    assert [ev.payload["value"] for ev in _bends(pl._pattern, 0)] == [-8192]
    print("  record_patch_note_off garde le ETYPE_BEND du note-on : OK")

def test_run_thread_replays_chased_bend_before_note_same_time():
    """Vraie boucle _run_thread : au même temps, le ETYPE_BEND posé au
    note-on est rejoué AVANT la note (BEND_TAPE_EVENT=-4 trié avant
    PATCH_TAPE_EVENT=-3), et on_patch_tape_cb reçoit 4 arguments, sans bend."""
    import threading
    pl = _make_player()
    pl.set_bpm(600)
    pl._pattern._tape[0].append(TapeEvent(ETYPE_PATCH, dur=50,
                                          payload={"note": 60, "vel": 100}, time=2.0))
    pl._pattern._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": 3000}, time=2.0))
    order = []
    done  = threading.Event()
    pl._on_bend_tape_cb  = lambda t, v: order.append(("bend", t, v))
    def _note_cb(t, n, v, d):
        order.append(("note", t, n, v, d))
        done.set()
    pl._on_patch_tape_cb = _note_cb
    try:
        pl.play_pattern()
        assert done.wait(2.0), f"note non rejouée : {order}"
    finally:
        pl.stop_pattern()
    assert order[:2] == [("bend", 0, 3000), ("note", 0, 60, 100, 50)]
    print("  _run_thread : bend du note-on rejoué avant la note, callback à 4 args : OK")


# ---------------------------------------------------------------------------
# Pattern._bend_state_at / _chase_bend (Phase 7 étape 7f1)
# ---------------------------------------------------------------------------

def _state_pattern():
    p = Pattern()
    p._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": 100}, time=1.0))
    p._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": 300}, time=4.5))
    p._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": 200}, time=3.0))
    p._tape[0].append(TapeEvent(ETYPE_PATCH, payload={"note": 60, "vel": 100}, time=5.0))
    p._tape[1].append(TapeEvent(ETYPE_BEND, payload={"value": -50}, time=0.0))
    return p

def test_bend_state_at_zero_before_any_bend():
    assert _state_pattern()._bend_state_at(0, 0.5) == 0

def test_bend_state_at_latest_time_not_list_order():
    p = _state_pattern()
    assert p._bend_state_at(0, 1.0) == 100
    assert p._bend_state_at(0, 3.9) == 200     # 3.0 posé après 4.5 dans la liste
    assert p._bend_state_at(0, 4.5) == 300
    assert p._bend_state_at(0, 99.0) == 300

def test_bend_state_at_ignores_future_and_other_tracks():
    p = _state_pattern()
    assert p._bend_state_at(0, 2.9) == 100
    assert p._bend_state_at(1, 5.0) == -50
    assert p._bend_state_at(7, 5.0) == 0       # piste sans bend
    assert p._bend_state_at(42, 5.0) == 0      # piste inexistante

def test_bend_state_at_same_time_last_in_tape_wins():
    p = Pattern()
    p._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": 10}, time=2.0))
    p._tape[0].append(TapeEvent(ETYPE_BEND, payload={"value": 20}, time=2.0))
    assert p._bend_state_at(0, 2.0) == 20

def test_chase_bend_adds_point_when_state_differs():
    p = _state_pattern()
    assert p._chase_bend(0, 5.0, 999, channel=4) is True
    ev = p._tape[0][-1]
    assert (ev.etype, ev.time, ev.payload, ev.channel) == (ETYPE_BEND, 5.0, {"value": 999}, 4)
    assert p._bend_state_at(0, 5.0) == 999

def test_chase_bend_noop_when_state_equal():
    p = _state_pattern()
    n = len(p._tape[0])
    assert p._chase_bend(0, 5.0, 300) is False
    assert p._chase_bend(0, 0.0, 0) is False
    assert len(p._tape[0]) == n

def test_chase_bend_extends_tracks():
    p = Pattern()
    n = len(p._tape)
    assert p._chase_bend(n + 2, 0.0, 512) is True
    assert len(p._tape) == n + 3


# ---------------------------------------------------------------------------
# Automation Pitch Bend — ETYPE_BEND dans _tape (_bend_tape supprimé en 6h1)
# ---------------------------------------------------------------------------

def _bend(value, time, channel=0):
    return TapeEvent(ETYPE_BEND, channel=channel, payload={"value": value}, time=time)

def _bend_pts(pattern, track):
    """(time, value) des ETYPE_BEND d'une piste, triés."""
    return sorted((ev.time, ev.payload["value"])
                  for ev in pattern._tape[track] if ev.etype == ETYPE_BEND)

def test_pattern_has_no_bend_tape_attribute():
    """Phase 7 étape 6h1 : l'attribut _bend_tape a disparu de Pattern."""
    assert not hasattr(Pattern(), "_bend_tape")
    print("  Pattern n'a plus l'attribut _bend_tape : OK")

def test_new_pattern_resets_bends():
    p = Pattern()
    p._tape[0].append(_bend(2048, 4.0))
    p.new_pattern()
    assert _bend_pts(p, 0) == []
    print("  new_pattern efface les ETYPE_BEND : OK")

def test_reset_pattern_clears_bends():
    p = Pattern()
    p._tape[1].append(_bend(-1024, 8.0))
    p.reset_pattern()
    assert _bend_pts(p, 1) == []
    print("  reset_pattern efface les ETYPE_BEND : OK")

def test_clear_track_clears_bends_for_track():
    p = Pattern()
    p.new_pattern(1, 16)
    p._tape[0].append(_bend(4096, 2.0))
    p._tape[1].append(_bend(-2000, 3.0))
    p.clear_track(0)
    assert _bend_pts(p, 0) == [], "piste 0 effacée"
    assert _bend_pts(p, 1) == [(3.0, -2000)], "piste 1 intacte"
    print("  clear_track efface les bends de la piste sans toucher les autres : OK")

def test_double_bars_duplicates_bends():
    p = Pattern()
    p.new_pattern(2, 16)
    p._tape[0] += [_bend(2048, 4.0, channel=3), _bend(-1024, 10.5)]
    p.double_bars()
    assert _bend_pts(p, 0) == [(4.0, 2048), (10.5, -1024), (36.0, 2048), (42.5, -1024)]
    assert [ev.channel for ev in p._tape[0] if ev.payload["value"] == 2048] == [3, 3]
    print("  double_bars duplique les bends (offset + half_steps, canal, fraction) : OK")

def test_halve_bars_filters_bends():
    p = Pattern()
    p.new_pattern(4, 16)
    p._tape[0] += [_bend(1000, 5.0), _bend(-500, 20.0), _bend(2000, 35.0)]
    p.halve_bars()
    assert _bend_pts(p, 0) == [(5.0, 1000), (20.0, -500)]
    print("  halve_bars filtre les bends : OK")

def test_resize_filters_bends():
    p = Pattern()
    p.new_pattern(4, 16)
    p._tape[0] += [_bend(100, 5.0), _bend(-200, 40.0)]
    p.resize(2, 16)
    assert _bend_pts(p, 0) == [(5.0, 100)]
    print("  resize filtre les bends hors pattern : OK")

def test_resize_reencodes_bend_position_when_num_steps_changes():
    """Bug 1 du plan 6a1 : _bend_tape n'était que filtré, jamais ré-encodé.
    Un bend à la mesure 2 pas 1 (time 17.25 en 16 pas/mesure) reste à la
    mesure 2 pas 1 en 32 pas/mesure (time 33.25), fraction comprise."""
    p = Pattern()
    p.new_pattern(2, 16)
    p._tape[0].append(_bend(700, 17.25))
    p.resize(2, 32)
    assert _bend_pts(p, 0) == [(33.25, 700)]
    print("  resize 16→32 pas garde la position musicale d'un bend : OK")

def test_copy_from_copies_bends():
    src = Pattern()
    src._tape[0].append(_bend(1000, 5.5, channel=4))
    dst = Pattern()
    dst.copy_from(src)
    assert _bend_pts(dst, 0) == [(5.5, 1000)]
    assert dst._tape[0][0].channel == 4
    print("  copy_from copie les ETYPE_BEND : OK")

def test_roundtrip_bends():
    src = Pattern()
    src.new_pattern(1, 16)
    src._tape[0] += [_bend(4096, 2.5, channel=1), _bend(-2000, 7.0)]
    src._tape[2].append(_bend(8191, 1.0))
    dst = Pattern()
    dst.from_dict(src.to_dict())
    assert tapes_equal_strict(dst._tape, src._tape)
    print("  to_dict → from_dict des ETYPE_BEND (tape_v2) round-trip : OK")

def test_to_dict_no_longer_writes_bend_tape_key():
    p = Pattern()
    p._tape[0].append(_bend(10, 1.0))
    assert "bend_tape" not in p.to_dict()
    print("  to_dict n'écrit plus la clé bend_tape : OK")

def test_from_dict_without_bend_tape_key_is_noop():
    """Preset sauvé après 6h1 : rien à migrer, ETYPE_BEND de tape_v2 gardés."""
    src = Pattern()
    src._tape[0].append(_bend(10, 1.5))
    p = Pattern()
    p.from_dict(src.to_dict())
    assert _bend_pts(p, 0) == [(1.5, 10)]
    print("  from_dict sans clé bend_tape : rien à migrer : OK")

def test_from_dict_migrates_bend_tape_to_etype_bend():
    """Preset ancien (tape_v2 + bend_tape) : chaque (off, val) devient un
    ETYPE_BEND channel=0, time flottant conservé, aux côtés des événements
    déjà présents (pas de doublon possible : pas de copie avant 6b1)."""
    src = Pattern()
    src.set_cell(0, 2, 0, 3, 100)
    src._tape[0].append(TapeEvent(ETYPE_CC, payload={"cc_num": 7, "value": 90}, time=4))
    d = src.to_dict()
    d["bend_tape"] = [[[2.5, 4096], [7.0, -2000]], [], [[1.0, 8191]]]   # forme JSON
    p = Pattern()
    p.from_dict(d)
    assert _bend_pts(p, 0) == [(2.5, 4096), (7.0, -2000)]
    assert _bend_pts(p, 1) == []
    assert _bend_pts(p, 2) == [(1.0, 8191)]
    bends = [ev for ev in p._tape[0] if ev.etype == ETYPE_BEND]
    assert all(ev.channel == 0 and ev.dur == 0 for ev in bends)
    assert {ev.etype for ev in p._tape[0]} == {ETYPE_GRID, ETYPE_CC, ETYPE_BEND}
    print("  from_dict migre bend_tape en ETYPE_BEND (notes/CC conservés) : OK")

def test_from_dict_migrates_bend_tape_from_legacy_format():
    """Très ancien format (curpattern, sans tape_v2) + bend_tape."""
    d = {"curpattern": Pattern().to_dense_grid(), "bend_tape": [[(3.0, 100)]]}
    p = Pattern()
    p.from_dict(d)
    assert _bend_pts(p, 0) == [(3.0, 100)]
    print("  from_dict migre bend_tape depuis l'ancien format curpattern : OK")

def test_from_dict_bend_tape_beyond_num_tracks_extends_tape():
    src = Pattern()
    d = src.to_dict()
    n = src._num_tracks
    d["bend_tape"] = [[] for _ in range(n)] + [[(1.0, 5)]]
    p = Pattern()
    p.from_dict(d)
    assert _bend_pts(p, n) == [(1.0, 5)]
    print("  from_dict : bend_tape plus long que tape_v2 → piste ajoutée : OK")

def test_migrated_bends_are_replayed_and_resaved():
    """Après migration, re-sauvegarde : plus de clé bend_tape, bends dans tape_v2."""
    d = Pattern().to_dict()
    d["bend_tape"] = [[(2.5, 4096)]]
    p = Pattern()
    p.from_dict(d)
    d2 = p.to_dict()
    assert "bend_tape" not in d2
    p2 = Pattern()
    p2.from_dict(d2)
    assert _bend_pts(p2, 0) == [(2.5, 4096)]
    print("  bends migrés re-sauvés dans tape_v2, sans clé bend_tape : OK")

def _bends(pattern, track):
    """Événements ETYPE_BEND d'une piste de _tape (Phase 7 étape 6b1)."""
    return [ev for ev in pattern._tape[track] if ev.etype == ETYPE_BEND]

def test_record_bend_stores_float_offset_and_value():
    """Phase 7 étape 6b1 : record_bend écrit un TapeEvent ETYPE_BEND dans
    _tape (plus dans _bend_tape), payload {"value": bend}, dur=0."""
    pl = _make_player()
    pl.record_bend(2048)
    bends = _bends(pl._pattern, 0)
    assert len(bends) == 1
    ev = bends[0]
    assert isinstance(ev.time, float)
    assert ev.payload == {"value": 2048}
    assert ev.dur == 0
    assert ev.channel == 0
    print("  record_bend stocke TapeEvent(BEND, value=2048) dans _tape : OK")

def test_record_bend_stores_channel():
    pl = _make_player()
    pl.record_bend(-100, channel=9)
    assert _bends(pl._pattern, 0)[0].channel == 9
    print("  record_bend conserve le canal MIDI d'origine : OK")

def test_record_bend_multiple_points_accumulate():
    pl = _make_player()
    pl.record_bend(0)
    pl.record_bend(4096)
    pl.record_bend(-4096)
    bends = _bends(pl._pattern, 0)
    assert len(bends) == 3
    assert [ev.payload["value"] for ev in bends] == [0, 4096, -4096]
    print("  record_bend accumule plusieurs points sans déduplication : OK")

def test_record_bend_uses_cur_track():
    pl = _make_player()
    pl._cur_track = 3
    pl.record_bend(1234)
    assert _bends(pl._pattern, 3) != []
    assert _bends(pl._pattern, 0) == []
    print("  record_bend enregistre sur la piste courante : OK")

def test_record_bend_returns_bar_step():
    pl = _make_player()
    pl._pattern.resize(2, 16)
    pl._measure_start = time.perf_counter() - 19.4 * pl.step_duration
    bar_idx, step_idx = pl.record_bend(500)
    assert (bar_idx, step_idx) == (1, 3)
    print("  record_bend retourne (bar_idx, step_idx) tronqués : OK")

def test_record_bend_stores_fractional_time():
    """Contrôleur continu : position sous-pas conservée (comme record_cc)."""
    pl = _player_at_offset(3.4)
    pl.record_bend(1000)
    ev = _bends(pl._pattern, 0)[0]
    assert 3.35 < ev.time < 3.6, ev.time
    assert ev.time != int(ev.time)
    print("  record_bend stocke une position fractionnaire (≈3.4) : OK")

def test_record_bend_ignores_record_quantization():
    """La quantisation d'enregistrement reste réservée aux notes."""
    pl = _player_at_offset(3.4)
    pl._quant_in_recording = True
    pl.quant_idx = 7   # 1/16 → calerait au pas 3
    pl.record_bend(1000)
    pl.record_hit(0)
    bend = _bends(pl._pattern, 0)[0]
    hit  = [e for e in pl._pattern._tape[0] if e.etype == ETYPE_GRID][0]
    assert bend.time != int(bend.time)
    assert hit.time == 3
    print("  record_bend ignore la quantisation d'enregistrement : OK")

def test_record_bend_count_in_gives_zero():
    pl = _make_player()
    pl._measure_start = time.perf_counter() + 10
    pl.record_bend(1000)
    assert _bends(pl._pattern, 0)[0].time == 0.0
    print("  record_bend pendant le count-in → position 0 : OK")

def test_compute_float_offset_shared_by_cc_and_bend():
    """record_cc et record_bend tirent leur position du même helper (6b1) :
    à horloge égale, même position."""
    from unittest import mock
    pl = _player_at_offset(7.25)
    with mock.patch("player.dp_recording.time.perf_counter", return_value=time.perf_counter()):
        pl.record_cc(74, 10)
        pl.record_bend(10)
    cc   = [e for e in pl._pattern._tape[0] if e.etype == ETYPE_CC][0]
    bend = _bends(pl._pattern, 0)[0]
    assert cc.time == bend.time
    assert 7.2 < bend.time < 7.4
    print("  record_cc / record_bend : même position via _compute_float_offset : OK")

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

def test_run_thread_replays_bend_from_tape():
    """Phase 7 étape 6b1 : la vraie boucle _run_thread rejoue les ETYPE_BEND
    de _tape vers _on_bend_tape_cb(track, value), dans l'ordre, une seule
    fois par point et par passage (plus de source _bend_tape parallèle)."""
    import threading
    pl = _make_player()
    pl.set_bpm(600)                       # pas = 25 ms, boucle d'1 mesure = 0,4 s
    pl._pattern._tape[1].append(TapeEvent(ETYPE_BEND, channel=2, payload={"value": 100},  time=0.0))
    pl._pattern._tape[1].append(TapeEvent(ETYPE_BEND, channel=2, payload={"value": -200}, time=1.5))
    received = []
    done = threading.Event()
    def _cb(t, v):
        received.append((t, v))
        if len(received) >= 2:
            done.set()
    pl._on_bend_tape_cb = _cb
    try:
        pl.play_pattern()
        assert done.wait(2.0), f"bends non rejoués : {received}"
    finally:
        pl.stop_pattern()
    assert received[:2] == [(1, 100), (1, -200)]
    print("  _run_thread rejoue les ETYPE_BEND de _tape vers on_bend_tape_cb : OK")


# ---------------------------------------------------------------------------
# Régression — flush/apply store
# ---------------------------------------------------------------------------

def _flush_pattern_to_store(pat, player_pattern):
    """Simule _flush_pattern_to_store de MainWindow (bends inclus dans
    _tape depuis la Phase 7 étape 6b1)."""
    flush_tape(pat, player_pattern)

def _apply_pattern_from_store(player_pattern, store_pat):
    """Simule _apply_pattern_from_store de MainWindow."""
    flush_tape(player_pattern, store_pat)

def test_flush_and_apply_preserve_bends():
    pl = _make_player()
    pl.record_bend(2048)
    pl.record_bend(-1000)

    store_pat = Pattern()
    _flush_pattern_to_store(store_pat, pl._pattern)

    assert len(_bends(store_pat, 0)) == 2, "flush doit copier les ETYPE_BEND"

    player2 = _make_player()
    _apply_pattern_from_store(player2._pattern, store_pat)

    assert tapes_equal_strict(player2._pattern._tape, pl._pattern._tape)
    print("  flush+apply store préserve les ETYPE_BEND (régression) : OK")

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

    assert len(_bends(player2._pattern, 0)) == 2
    assert len(_bends(player2._pattern, 3)) == 1
    assert tapes_equal_strict(player2._pattern._tape, pl._pattern._tape)
    print("  cycle complet record→flush→to_dict→from_dict→apply préserve les ETYPE_BEND : OK")


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
        assert False, f"to_dict lève une exception sur ETYPE_BEND runtime : {e}"
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

    try:
        json_str = _json.dumps(store.to_dict(), separators=(',', ':'))
    except Exception as e:
        assert False, f"json.dumps échoue : {e}"

    restored = Pattern()
    restored.from_dict(_json.loads(json_str))

    pl2 = _make_player()
    flush_tape(pl2._pattern, restored)

    assert tapes_equal_strict(pl2._pattern._tape, pl._pattern._tape), "_tape perdu"
    # 2 points record_bend + 2 posés au note-on par les notes pliées (Phase 7
    # étape 7f1 : 0 → 2048 puis 2048 → -1000)
    assert len(_bends(pl2._pattern, 0)) == 4, "ETYPE_BEND perdus"
    assert all("bend" not in ev.payload
               for ev in pl2._pattern._tape[0] if ev.etype == ETYPE_PATCH)
    print("  intégration record→JSON→rechargement préserve _tape (bends compris) : OK")

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

    restored = Pattern()
    restored.from_dict(_json.loads(_json.dumps(store.to_dict(), separators=(',', ':'))))

    pl2 = _make_player()
    flush_tape(pl2._pattern, restored)

    assert tapes_equal_strict(pl2._pattern._tape, pl._pattern._tape)
    assert len(_bends(pl2._pattern, 2)) == 1
    print("  intégration multi-pistes record→JSON→rechargement : OK")


# ---------------------------------------------------------------------------
# _mod_tape — supprimé en Phase 7 étape 5h (CC#1/Mod Wheel vit dans _tape,
# ETYPE_CC, depuis l'étape 5b). Les tests structurels (initialement vide,
# new_pattern/reset_pattern/clear_track/double_bars/halve_bars/resize,
# record_mod, MOD_TAPE_EVENT, _on_mod_tape_cb, flush/apply) ont disparu avec
# la structure elle-même. Place à la migration .gvp (décision 3, 5a) ci-dessous.
# ---------------------------------------------------------------------------

def test_to_dict_no_longer_writes_mod_tape_key():
    p = Pattern()
    assert "mod_tape" not in p.to_dict()
    print("  to_dict n'écrit plus la clé mod_tape : OK")

def test_from_dict_without_mod_tape_key_is_noop():
    """Preset sauvé après 5h (pas de clé mod_tape) : rien à migrer."""
    p = Pattern()
    add_tape_at(p, 0, 0, 1, TapeEvent(ETYPE_CC, payload={"cc_num": 1, "value": 90}))
    d = p.to_dict()
    assert "mod_tape" not in d
    p2 = Pattern()
    p2.from_dict(d)
    cc1 = [ev for ev in p2._tape[0] if ev.etype == ETYPE_CC and ev.payload.get("cc_num") == 1]
    assert len(cc1) == 1 and cc1[0].payload["value"] == 90
    print("  from_dict sans clé mod_tape : rien à migrer, ETYPE_CC conservé : OK")

def test_from_dict_migrates_mod_tape_alone_to_cc1():
    """Preset ancien (pré-4f) : mod_tape seul, aucun doublon ETYPE_CC à retirer."""
    from pattern import ETYPE_CC
    p = Pattern()
    d = p.to_dict()
    d["mod_tape"] = [[(2.0, 64), (10.5, 127)]]
    p2 = Pattern()
    p2.from_dict(d)
    cc1 = sorted((ev.time, ev.payload["value"]) for ev in p2._tape[0]
                 if ev.etype == ETYPE_CC and ev.payload.get("cc_num") == 1)
    assert cc1 == [(2.0, 64), (10.5, 127)]
    assert all(ev.channel == 0 and ev.dur == 0 for ev in p2._tape[0] if ev.etype == ETYPE_CC)
    print("  from_dict migre mod_tape seul en ETYPE_CC cc_num=1 : OK")

def test_from_dict_mod_tape_wins_over_duplicate_cc1_in_tape_v2():
    """Preset sauvé entre 4f et 5h : doublon CC#1 dans tape_v2 (pas entier,
    imprécis) ET dans mod_tape (flottant, précis) — mod_tape doit gagner."""
    from pattern import ETYPE_CC
    p = Pattern()
    add_tape_at(p, 0, 0, 3, TapeEvent(ETYPE_CC, payload={"cc_num": 1, "value": 20}))   # doublon imprécis
    add_tape_at(p, 0, 0, 5, TapeEvent(ETYPE_CC, payload={"cc_num": 7, "value": 50}))   # autre CC, non concerné
    d = p.to_dict()
    d["mod_tape"] = [[(3.4, 64), (3.7, 90)]]   # copie précise, temps flottant
    p2 = Pattern()
    p2.from_dict(d)
    cc1 = sorted((round(ev.time, 6), ev.payload["value"]) for ev in p2._tape[0]
                 if ev.etype == ETYPE_CC and ev.payload.get("cc_num") == 1)
    assert cc1 == [(3.4, 64), (3.7, 90)]   # le doublon imprécis (3, 20) a été retiré
    cc7 = [ev for ev in p2._tape[0] if ev.etype == ETYPE_CC and ev.payload.get("cc_num") == 7]
    assert len(cc7) == 1 and cc7[0].payload["value"] == 50   # CC#7 intact, non concerné
    print("  from_dict : mod_tape remplace le doublon CC#1 imprécis de tape_v2 : OK")

def test_from_dict_empty_mod_tape_keeps_existing_cc1():
    """Piste dont mod_tape est vide (liste vide ou absente pour cette piste) :
    ses ETYPE_CC cc_num=1 existants ne sont pas touchés."""
    from pattern import ETYPE_CC
    p = Pattern()
    add_tape_at(p, 0, 0, 3, TapeEvent(ETYPE_CC, payload={"cc_num": 1, "value": 20}))
    d = p.to_dict()
    d["mod_tape"] = [[]]   # piste 0 : mod_tape vide
    p2 = Pattern()
    p2.from_dict(d)
    cc1 = [ev for ev in p2._tape[0] if ev.etype == ETYPE_CC and ev.payload.get("cc_num") == 1]
    assert len(cc1) == 1 and cc1[0].payload["value"] == 20
    print("  from_dict : mod_tape vide → ETYPE_CC cc_num=1 existant gardé tel quel : OK")

def test_drum_player_has_no_mod_tape_remnants():
    """Garde-fou structurel (Phase 7 étape 5h) : MOD_TAPE_EVENT, record_mod
    et _on_mod_tape_cb ont tous disparu de DrumPlayer."""
    pl = _make_player()
    assert not hasattr(DrumPlayer, "MOD_TAPE_EVENT")
    assert not hasattr(pl, "record_mod")
    assert not hasattr(pl, "_on_mod_tape_cb")
    print("  DrumPlayer n'a plus MOD_TAPE_EVENT/record_mod/_on_mod_tape_cb : OK")

def test_pattern_has_no_mod_tape_attribute():
    p = Pattern()
    assert not hasattr(p, "_mod_tape")
    print("  Pattern n'a plus l'attribut _mod_tape : OK")

def test_from_dict_mod_tape_only_affects_its_own_track():
    """mod_tape d'une piste ne touche pas les ETYPE_CC#1 d'une autre piste."""
    from pattern import ETYPE_CC
    p = Pattern()
    add_tape_at(p, 1, 0, 2, TapeEvent(ETYPE_CC, payload={"cc_num": 1, "value": 20}))
    d = p.to_dict()
    d["mod_tape"] = [[(5.0, 99)]]   # ne concerne que la piste 0
    p2 = Pattern()
    p2.from_dict(d)
    cc1_t1 = [ev for ev in p2._tape[1] if ev.etype == ETYPE_CC and ev.payload.get("cc_num") == 1]
    assert len(cc1_t1) == 1 and cc1_t1[0].payload["value"] == 20   # piste 1 intacte
    cc1_t0 = [ev for ev in p2._tape[0] if ev.etype == ETYPE_CC and ev.payload.get("cc_num") == 1]
    assert len(cc1_t0) == 1 and cc1_t0[0].time == 5.0
    print("  from_dict : migration mod_tape limitée à sa propre piste : OK")


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
                                        TapeEvent(ETYPE_PATCH, dur=400, payload={"note": 60, "vel": 90})])
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
    # Automation Pitch Bend — structure (_bend_tape supprimé en 6h1) + migration .gvp
    test_pattern_has_no_bend_tape_attribute()
    test_new_pattern_resets_bends()
    test_reset_pattern_clears_bends()
    test_clear_track_clears_bends_for_track()
    test_double_bars_duplicates_bends()
    test_halve_bars_filters_bends()
    test_resize_filters_bends()
    test_resize_reencodes_bend_position_when_num_steps_changes()
    test_copy_from_copies_bends()
    test_roundtrip_bends()
    test_to_dict_no_longer_writes_bend_tape_key()
    test_from_dict_without_bend_tape_key_is_noop()
    test_from_dict_migrates_bend_tape_to_etype_bend()
    test_from_dict_migrates_bend_tape_from_legacy_format()
    test_from_dict_bend_tape_beyond_num_tracks_extends_tape()
    test_migrated_bends_are_replayed_and_resaved()
    # Automation Pitch Bend — ETYPE_BEND dans _tape (Phase 7 étape 6b1)
    test_record_bend_stores_float_offset_and_value()
    test_record_bend_stores_channel()
    test_record_bend_multiple_points_accumulate()
    test_record_bend_uses_cur_track()
    test_record_bend_returns_bar_step()
    test_record_bend_stores_fractional_time()
    test_record_bend_ignores_record_quantization()
    test_record_bend_count_in_gives_zero()
    test_compute_float_offset_shared_by_cc_and_bend()
    test_bend_tape_callback_receives_track_and_value()
    test_bend_tape_no_callback_is_safe()
    test_run_thread_replays_bend_from_tape()
    # Régression — flush/apply store
    test_flush_and_apply_preserve_bends()
    test_flush_and_apply_roundtrip_via_todict()
    # Tests préventifs — utilise les méthodes record_* (données runtime réelles)
    test_to_dict_does_not_raise_after_record_patch_note()
    test_to_dict_does_not_raise_after_record_kit_note()
    test_to_dict_does_not_raise_after_record_bend()
    test_integration_record_json_reload()
    test_integration_record_json_reload_all_tracks()
    # _mod_tape supprimé en 5h — migration .gvp vers ETYPE_CC cc_num=1
    test_to_dict_no_longer_writes_mod_tape_key()
    test_from_dict_without_mod_tape_key_is_noop()
    test_from_dict_migrates_mod_tape_alone_to_cc1()
    test_from_dict_mod_tape_wins_over_duplicate_cc1_in_tape_v2()
    test_from_dict_empty_mod_tape_keeps_existing_cc1()
    test_drum_player_has_no_mod_tape_remnants()
    test_pattern_has_no_mod_tape_attribute()
    test_from_dict_mod_tape_only_affects_its_own_track()
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


# ---------------------------------------------------------------------------
# Migration du champ "bend" des notes PATCH → ETYPE_BEND (Phase 7 étape 7i1)
# ---------------------------------------------------------------------------

def _old_tape_v2(*track0_events, bend_points=()):
    """Dict de preset au format tape_v2 d'avant 7h1 : notes PATCH avec champ
    "bend" (ou tout TapeEvent fourni), sur la piste 0."""
    p = Pattern()
    p._tape[0].extend(track0_events)
    p._tape[0].extend(TapeEvent(ETYPE_BEND, payload={"value": v}, time=t)
                      for t, v in bend_points)
    return p.to_dict()

def _loaded(d):
    p = Pattern()
    p.from_dict(d)
    return p

def _bend_points(p, track=0):
    return sorted((ev.time, ev.payload["value"]) for ev in _bends(p, track))

def _old_note(note, time, bend, channel=0):
    ev = _P_old(note, 100, 300, bend)
    ev.time, ev.channel = time, channel
    return ev

def test_migrate_note_bends_become_etype_bend_points():
    """Note pliée → point au temps de la note ; note à 0 qui suit une note
    pliée → retour au centre (avant 7f1, chaque note imposait son bend)."""
    p = _loaded(_old_tape_v2(_old_note(60, 0, 4096), _old_note(62, 4, 0),
                             _old_note(64, 8, -2000), _old_note(65, 12, -2000)))
    assert _bend_points(p) == [(0, 4096), (4, 0), (8, -2000)]
    print("  migration : bends des notes → ETYPE_BEND (retour à 0, sans doublon) : OK")

def test_migrate_note_bends_removes_field_from_payloads():
    p = _loaded(_old_tape_v2(_old_note(60, 0, 4096), _old_note(62, 4, 0)))
    notes = [ev for ev in p._tape[0] if ev.etype == ETYPE_PATCH]
    assert [ev.payload for ev in notes] == [{"note": 60, "vel": 100}, {"note": 62, "vel": 100}]
    print("  migration : champ bend retiré des payloads PATCH : OK")

def test_migrate_all_zero_bends_adds_no_point():
    """Cas courant des anciens fichiers : toutes les notes à bend 0."""
    p = _loaded(_old_tape_v2(_old_note(60, 0, 0), _old_note(62, 4, 0)))
    assert _bends(p, 0) == []
    print("  migration : notes toutes à 0 → aucun ETYPE_BEND : OK")

def test_migrate_uses_note_channel():
    p = _loaded(_old_tape_v2(_old_note(60, 2, 1500, channel=9)))
    assert [(ev.time, ev.channel) for ev in _bends(p, 0)] == [(2, 9)]

def test_migrate_follows_time_not_list_order():
    p = _loaded(_old_tape_v2(_old_note(64, 8, 0), _old_note(60, 0, 4096)))
    assert _bend_points(p) == [(0, 4096), (8, 0)]

def test_migrate_respects_existing_bend_automation():
    """Un ETYPE_BEND déjà présent fixe l'état : note de même valeur → pas de
    doublon ; note à 0 sous un état plié → point de retour à 0."""
    p = _loaded(_old_tape_v2(_old_note(60, 2, 2000), _old_note(62, 6, 0),
                             bend_points=[(0.5, 2000)]))
    assert _bend_points(p) == [(0.5, 2000), (6, 0)]
    print("  migration : tient compte des ETYPE_BEND existants : OK")

def test_migrate_after_old_bend_tape_key():
    """La migration des notes passe après celle de 'bend_tape' (6h1) et tient
    donc compte de ses points."""
    d = _old_tape_v2(_old_note(60, 4, 3000))
    d["bend_tape"] = [[(1.5, 3000)]]
    p = _loaded(d)
    assert _bend_points(p) == [(1.5, 3000)]

def test_migrate_old_patch_tape_format_7_columns():
    old = {
        "curpattern": Pattern().to_dense_grid(),
        "patch_tape": [[0, 0, 3, 60, 100, 500, 4096], [0, 0, 9, 62, 100, 500, 0]],
    }
    p = _loaded(old)
    assert _bend_points(p) == [(3, 4096), (9, 0)]
    assert all("bend" not in ev.payload for ev in p._tape[0] if ev.etype == ETYPE_PATCH)
    print("  migration : ancien format patch_tape (7 colonnes) : OK")

def test_migrate_leaves_new_format_notes_untouched():
    """Note sans champ bend (format 7f1+) sous un état plié : aucun point
    ajouté — seules les notes portant le champ sont migrées."""
    p = _loaded(_old_tape_v2(_P(60, 100, 300), bend_points=[(0, 2048)]))
    assert _bend_points(p) == [(0, 2048)]

def test_migrate_does_not_mutate_caller_dict():
    d = _old_tape_v2(_old_note(60, 0, 4096))
    _loaded(d)
    assert d["tape_v2"][0][0][4] == {"note": 60, "vel": 100, "bend": 4096}

def test_migrate_is_idempotent_through_save_and_reload():
    p1 = _loaded(_old_tape_v2(_old_note(60, 0, 4096), _old_note(62, 4, 0)))
    d  = p1.to_dict()
    assert all("bend" not in rec[4] for rec in d["tape_v2"][0] if rec[1] == ETYPE_PATCH)
    p2 = _loaded(d)
    assert tapes_equal_strict(p2._tape, p1._tape)
    print("  migration : sauvegarde puis rechargement → rien de plus : OK")
