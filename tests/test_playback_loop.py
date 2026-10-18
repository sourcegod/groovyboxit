#python3
"""
    File: tests/test_playback_loop.py
    Tests unitaires des trois méthodes extraites de _run_thread en Phase 7
    étape 8e1 (player/dp_playback.py) : _build_measure_events,
    _dispatch_event et _on_measure_end. Appelées directement, sans lancer
    le thread de lecture.
    Date: Sun, 18/10/2026
    Author: Coolbrother
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import Pattern, TapeEvent, ETYPE_KIT, ETYPE_PATCH, ETYPE_CC, ETYPE_PGM, ETYPE_BEND
from metronome import Metronome
from drum_player import DrumPlayer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _RecordingSoundManager:
    """Sound manager qui note les appels reçus."""
    def __init__(self):
        self.calls = []
    def stop_all(self):                 self.calls.append(("stop_all",))
    def play_sound(self, *a):           self.calls.append(("play_sound",) + a)
    def play_note(self, *a):            self.calls.append(("play_note",) + a)
    def play_metronome(self, *a):       self.calls.append(("play_metronome",) + a)


def _make_player():
    """DrumPlayer non lancé : 1 mesure de 16 pas, 0.15 s par pas (100 BPM)."""
    return DrumPlayer(_RecordingSoundManager())


def _add(pl, track, etype, time_val, payload, dur=0):
    pl._pattern._ensure_track_count(track + 1)
    pl._pattern._tape[track].append(
        TapeEvent(etype, dur=dur, payload=payload, time=time_val))


def _build(pl, lp_start=0, lp_end=15, total_steps=16, loop_bars=1, elapsed=0.0):
    return pl._build_measure_events(lp_start, lp_end, total_steps, loop_bars, elapsed)


def _past_measure(pl):
    """measure_start et measure_secs d'une mesure déjà finie : l'attente de
    fin de mesure de _on_measure_end ne bloque pas."""
    measure_secs = 16 * pl.step_duration
    return time.perf_counter() - 2 * measure_secs, measure_secs


def _make_song_player(bpms=(100, 120), looping=False):
    pl = _make_player()
    patterns = []
    for bpm in bpms:
        p = Pattern()
        p._bpm = bpm
        patterns.append(p)
    pl._pattern_list_ref = patterns
    pl._song_sequence    = list(range(len(patterns)))
    pl._song_pos         = 0
    pl._song_mode        = True
    pl._song_looping     = looping
    pl._pattern._looping = False
    pl.playing           = True
    pl._advances = []
    pl._on_song_advance_cb = pl._advances.append
    return pl


# ---------------------------------------------------------------------------
# _build_measure_events
# ---------------------------------------------------------------------------

def test_build_maps_each_etype_to_its_marker():
    pl = _make_player()
    pl.playing = True
    pl._pattern.set_cell(0, 3, 0, 0, 90, dur=250)
    _add(pl, 1, ETYPE_KIT,   1.0, {"note": 36, "vel": 80}, dur=10)
    _add(pl, 2, ETYPE_PATCH, 2.0, {"note": 60, "vel": 70}, dur=20)
    _add(pl, 3, ETYPE_CC,    3.0, {"cc_num": 74, "value": 64})
    _add(pl, 4, ETYPE_PGM,   4.0, {"program": 5})
    _add(pl, 5, ETYPE_BEND,  5.0, {"value": -1000})
    sd = pl.step_duration
    assert _build(pl) == [
        (0.0,    DrumPlayer.GRID_EVENT,       (0, 3, 250),   90),
        (1 * sd, DrumPlayer.KIT_TAPE_EVENT,   (1, 36, 10),   80),
        (2 * sd, DrumPlayer.PATCH_TAPE_EVENT, (2, 60, 20),   70),
        (3 * sd, DrumPlayer.CC_TAPE_EVENT,    (3, 74, 64),   0),
        (4 * sd, DrumPlayer.PGM_TAPE_EVENT,   (4, 5),        0),
        (5 * sd, DrumPlayer.BEND_TAPE_EVENT,  (5, -1000),    0),
    ]
    print("  _build_measure_events : un marqueur par etype, données et vélocité : OK")

def test_build_ignores_tape_when_not_playing():
    pl = _make_player()
    pl._pattern.set_cell(0, 0, 0, 0, 100)
    assert pl.playing is False
    assert _build(pl) == []
    print("  _build_measure_events : tape ignorée hors lecture : OK")

def test_build_keeps_only_loop_window_relative_to_lp_start():
    pl = _make_player()
    pl.playing = True
    for t in (3.0, 4.0, 8.0, 9.0):
        _add(pl, 0, ETYPE_CC, t, {"cc_num": 1, "value": int(t)})
    events = _build(pl, lp_start=4, lp_end=8, total_steps=5)
    sd = pl.step_duration
    assert [(e[0], e[2][2]) for e in events] == [(0.0, 4), (4 * sd, 8)]
    print("  _build_measure_events : fenêtre de boucle, temps relatif à lp_start : OK")

def test_build_skips_events_already_past_with_tolerance():
    pl = _make_player()
    pl.playing = True
    sd = pl.step_duration
    _add(pl, 0, ETYPE_CC, 1.0, {"cc_num": 1, "value": 1})
    _add(pl, 0, ETYPE_CC, 2.0, {"cc_num": 1, "value": 2})
    _add(pl, 0, ETYPE_CC, 3.0, {"cc_num": 1, "value": 3})
    # elapsed juste après le pas 2 (moins de 2 ms) : le pas 2 est encore joué
    events = _build(pl, elapsed=2 * sd + 0.001)
    assert [e[2][2] for e in events] == [2, 3]
    events = _build(pl, elapsed=2 * sd + 0.003)
    assert [e[2][2] for e in events] == [3]
    print("  _build_measure_events : événements passés exclus (tolérance 2 ms) : OK")

def test_build_sorts_bend_before_patch_note_at_same_time():
    """Phase 7 étape 7f1 : un bend au même temps qu'une note PATCH est
    rejoué avant elle (BEND_TAPE_EVENT=-4 < PATCH_TAPE_EVENT=-3)."""
    pl = _make_player()
    pl.playing = True
    _add(pl, 0, ETYPE_PATCH, 2.0, {"note": 60, "vel": 100})
    _add(pl, 0, ETYPE_BEND,  2.0, {"value": 4096})
    _add(pl, 0, ETYPE_PATCH, 1.0, {"note": 62, "vel": 100})
    markers = [e[1] for e in _build(pl)]
    assert markers == [DrumPlayer.PATCH_TAPE_EVENT,
                       DrumPlayer.BEND_TAPE_EVENT, DrumPlayer.PATCH_TAPE_EVENT]
    print("  _build_measure_events : tri par temps, bend avant note au même temps : OK")

def test_build_adds_note_repeat_events():
    pl = _make_player()
    pl._note_repeat_active = True
    pl._nr_quant_idx = Pattern.QUANT_STEPS.index(4)   # noire = 4 pas
    sd = pl.step_duration
    assert _build(pl) == [(i * 4 * sd, DrumPlayer.NR_EVENT, 0, 100) for i in range(4)]
    # Les répétitions déjà passées ne sont plus proposées
    assert len(_build(pl, elapsed=5 * sd)) == 2
    print("  _build_measure_events : Note Repeat au taux demandé : OK")

def test_build_adds_metronome_events_when_clicking():
    pl = _make_player()
    pl.clicking = True
    events = _build(pl)
    assert len(events) == 4
    assert all(e[1] == Metronome.METRO_EVENT for e in events)
    print("  _build_measure_events : clicks du métronome : OK")


# ---------------------------------------------------------------------------
# _dispatch_event
# ---------------------------------------------------------------------------

def test_dispatch_grid_calls_track_play_cb_with_voice_duration():
    pl = _make_player()
    got = []
    pl._on_track_play_cb = lambda *a: got.append(a)
    pl._dispatch_event(DrumPlayer.GRID_EVENT, (2, 5, 0), 50, 0.0)
    dur = pl.voice_manager.get_duration_ms(5)
    assert got == [(2, 5, 0.5, 0, dur)]
    assert pl.sound_man.calls == []
    print("  _dispatch_event GRID : callback piste, durée de la voix : OK")

def test_dispatch_grid_duration_override_wins():
    pl = _make_player()
    got = []
    pl._on_track_play_cb = lambda *a: got.append(a)
    pl._dispatch_event(DrumPlayer.GRID_EVENT, (0, 1, 123), 100, 0.0)
    assert got[0][4] == 123
    print("  _dispatch_event GRID : durée propre à l'événement prioritaire : OK")

def test_dispatch_grid_without_cb_plays_sound_manager():
    pl = _make_player()
    pl._dispatch_event(DrumPlayer.GRID_EVENT, (0, 1, 0), 100, 0.0)
    assert pl.sound_man.calls == [("play_sound", 1, 1.0, 0)]
    print("  _dispatch_event GRID : sans callback → sound manager : OK")

def test_dispatch_grid_erase_clears_offset_instead_of_playing():
    pl = _make_player()
    pl._pattern.set_cell(0, 4, 0, 2, 100)
    pl._compute_offsets()
    replaced = []
    pl._on_replaced_cb = lambda *a: replaced.append(a)
    pl._erase_active_pads.add(4)
    pl._dispatch_event(DrumPlayer.GRID_EVENT, (0, 4, 0), 100, 2 * pl.step_duration)
    assert pl.sound_man.calls == []
    assert pl.float_offsets[4] == []
    assert list(pl._pattern.iter_grid()) == []
    assert replaced == [(4, 0, 2)]
    print("  _dispatch_event GRID : pad tenu en Erase → effacé, pas joué : OK")

def test_dispatch_grid_replace_recording_plays_then_clears():
    pl = _make_player()
    pl._pattern.set_cell(0, 4, 0, 2, 100)
    pl._compute_offsets()
    pl.replace_recording = True
    pl._dispatch_event(DrumPlayer.GRID_EVENT, (0, 4, 0), 100, 2 * pl.step_duration)
    assert pl.sound_man.calls == [("play_sound", 4, 1.0, 0)]
    assert pl.float_offsets[4] == []
    print("  _dispatch_event GRID : Replace → joué puis effacé : OK")

def test_dispatch_kit_cb_or_sound_manager():
    pl = _make_player()
    pl._dispatch_event(DrumPlayer.KIT_TAPE_EVENT, (0, 36, 0), 127, 0.0)
    assert pl.sound_man.calls == [("play_note", 36, 1.0)]
    got = []
    pl._on_kit_tape_cb = lambda *a: got.append(a)
    pl._dispatch_event(DrumPlayer.KIT_TAPE_EVENT, (1, 38, 40), 90, 0.0)
    assert got == [(1, 38, 90, 40)]
    print("  _dispatch_event KIT : callback, sinon play_note : OK")

def test_dispatch_kit_and_patch_erase_remove_tape_event():
    for etype, marker in ((ETYPE_KIT, DrumPlayer.KIT_TAPE_EVENT),
                          (ETYPE_PATCH, DrumPlayer.PATCH_TAPE_EVENT)):
        pl = _make_player()
        _add(pl, 0, etype, 3.0, {"note": 60, "vel": 100})
        got = []
        pl._on_kit_tape_cb = pl._on_patch_tape_cb = lambda *a: got.append(a)
        pl.erasing = True
        pl._erase_active_midi_notes.add(60)
        pl._dispatch_event(marker, (0, 60, 0), 100, 3 * pl.step_duration)
        assert pl._pattern._tape[0] == []
        assert got == []
    print("  _dispatch_event KIT/PATCH : note tenue en Erase → retirée de _tape : OK")

def test_dispatch_patch_bend_cc_pgm_callbacks():
    pl = _make_player()
    got = []
    pl._on_patch_tape_cb         = lambda *a: got.append(("patch",) + a)
    pl._on_bend_tape_cb          = lambda *a: got.append(("bend",) + a)
    pl._on_cc_tape_cb            = lambda *a: got.append(("cc",) + a)
    pl._on_program_change_tape_cb = lambda *a: got.append(("pgm",) + a)
    pl._dispatch_event(DrumPlayer.PATCH_TAPE_EVENT, (1, 60, 300), 70, 0.0)
    pl._dispatch_event(DrumPlayer.BEND_TAPE_EVENT,  (1, 2048), 0, 0.0)
    pl._dispatch_event(DrumPlayer.CC_TAPE_EVENT,    (1, 74, 10), 0, 0.0)
    pl._dispatch_event(DrumPlayer.PGM_TAPE_EVENT,   (1, 7), 0, 0.0)
    assert got == [("patch", 1, 60, 70, 300), ("bend", 1, 2048),
                   ("cc", 1, 74, 10), ("pgm", 1, 7)]
    print("  _dispatch_event PATCH/BEND/CC/PGM : callbacks : OK")

def test_dispatch_without_callbacks_is_silent():
    pl = _make_player()
    for marker, data in ((DrumPlayer.PATCH_TAPE_EVENT, (0, 60, 0)),
                         (DrumPlayer.BEND_TAPE_EVENT,  (0, 0)),
                         (DrumPlayer.CC_TAPE_EVENT,    (0, 1, 0)),
                         (DrumPlayer.PGM_TAPE_EVENT,   (0, 0))):
        pl._dispatch_event(marker, data, 0, 0.0)
    assert pl.sound_man.calls == []
    print("  _dispatch_event : sans callback, rien n'est joué : OK")

def test_dispatch_note_repeat_plays_and_records():
    pl = _make_player()
    played = []
    pl._nr_get_pad = lambda: 6
    pl._nr_play_cb = played.append
    pl.recording = True
    pl._dispatch_event(DrumPlayer.NR_EVENT, 0, 100, 4 * pl.step_duration)
    assert played == [6]
    assert [(t, pad, step) for t, pad, bar, step, vel in pl._pattern.iter_grid()] == [(0, 6, 4)]
    print("  _dispatch_event NR : pad joué via callback et enregistré : OK")

def test_dispatch_note_repeat_without_pad_does_nothing():
    pl = _make_player()
    pl._dispatch_event(DrumPlayer.NR_EVENT, 0, 100, 0.0)
    assert pl.sound_man.calls == []
    print("  _dispatch_event NR : aucun pad joué → rien : OK")

def test_dispatch_metronome():
    pl = _make_player()
    pl._dispatch_event(Metronome.METRO_EVENT, 2, 0, 0.0)
    assert pl.sound_man.calls == [("play_metronome", 2)]
    print("  _dispatch_event METRO : click joué : OK")


# ---------------------------------------------------------------------------
# _on_measure_end
# ---------------------------------------------------------------------------

def test_measure_end_last_count_in_arms_recording():
    pl = _make_player()
    done = []
    pl._on_count_in_done_cb = lambda: done.append(1)
    pl._count_in = 1
    ms, secs = _past_measure(pl)
    new_ms = pl._on_measure_end(ms, secs, 0)
    assert (pl.playing, pl.recording, pl._count_in) == (True, True, 0)
    assert done == [1]   # une seule fois (pré-armement), pas après l'attente
    assert new_ms == ms + secs
    print("  _on_measure_end : dernier count-in → Rec armé, mesure suivante : OK")

def test_measure_end_count_in_resume_offset_shifts_start():
    pl = _make_player()
    pl._count_in = 1
    pl._count_in_resume_offset = 4.0
    ms, secs = _past_measure(pl)
    new_ms = pl._on_measure_end(ms, secs, 0)
    assert abs(new_ms - (ms + secs - 4 * pl.step_duration)) < 1e-9
    assert pl._count_in_resume_offset is None
    print("  _on_measure_end : count-in repris au milieu du pattern : OK")

def test_measure_end_count_in_not_last_only_decrements():
    pl = _make_player()
    pl._count_in = 2
    ms, secs = _past_measure(pl)
    assert pl._on_measure_end(ms, secs, 0) == ms
    assert (pl._count_in, pl.recording, pl.playing) == (1, False, False)
    print("  _on_measure_end : count-in non terminé → décompte seul : OK")

def test_measure_end_loop_counter_stops_at_lp_start():
    pl = _make_player()
    pl.playing = True
    pl._lm._remaining = 1
    ms, secs = _past_measure(pl)
    assert pl._on_measure_end(ms, secs, 4) == ms
    assert pl.playing is False
    assert pl._resume_offset == 4.0
    print("  _on_measure_end : compteur de boucle épuisé → arrêt au début de boucle : OK")

def test_measure_end_loop_counter_not_exhausted_keeps_playing():
    pl = _make_player()
    pl.playing = True
    pl._lm._remaining = 3
    ms, secs = _past_measure(pl)
    pl._on_measure_end(ms, secs, 0)
    assert pl.playing is True and pl._lm.remaining == 2
    print("  _on_measure_end : compteur de boucle décrémenté : OK")

def test_measure_end_looping_pattern_changes_nothing():
    pl = _make_player()
    pl.playing = True
    ms, secs = _past_measure(pl)
    assert pl._on_measure_end(ms, secs, 0) == ms
    assert pl.playing is True and pl._resume_offset is None
    print("  _on_measure_end : pattern en boucle → continue : OK")

def test_measure_end_song_advances_to_next_pattern():
    pl = _make_song_player(bpms=(100, 120))
    ms, secs = _past_measure(pl)
    assert pl._on_measure_end(ms, secs, 0) == ms + secs
    assert pl._song_pos == 1 and pl._advances == [1]
    assert pl.bpm == 120 and pl.step_duration == 60.0 / 120 / 4
    assert pl._pattern._looping is False and pl.playing is True
    print("  _on_measure_end : song → pattern suivant, BPM repris : OK")

def test_measure_end_song_loops_back_to_first():
    pl = _make_song_player(bpms=(90, 120), looping=True)
    pl._song_pos = 1
    pl.bpm = 120
    ms, secs = _past_measure(pl)
    assert pl._on_measure_end(ms, secs, 0) == ms + secs
    assert pl._song_pos == 0 and pl._advances == [0] and pl.bpm == 90
    print("  _on_measure_end : song en boucle → retour au premier pattern : OK")

def test_measure_end_song_end_pauses_on_last_tick():
    pl = _make_song_player(bpms=(100, 100))
    pl._song_pos = 1
    ms, secs = _past_measure(pl)
    assert pl._on_measure_end(ms, secs, 0) == ms
    assert pl.playing is False and pl._song_mode is False
    assert pl._advances == [-1]
    assert pl._resume_offset == 15.0
    print("  _on_measure_end : fin de song → pause sur le dernier tick : OK")

def test_measure_end_non_looping_pattern_pauses_on_last_tick():
    pl = _make_player()
    pl.playing = True
    pl._pattern._looping = False
    ms, secs = _past_measure(pl)
    pl._on_measure_end(ms, secs, 0)
    assert pl.playing is False and pl._resume_offset == 15.0
    print("  _on_measure_end : pattern sans boucle → pause sur le dernier tick : OK")

def test_measure_end_wakeup_skips_decision():
    """_wakeup posé (état changé) : ni décompte ni décision, la mesure sera
    reconstruite par _run_thread."""
    pl = _make_player()
    pl._count_in = 2
    pl._wakeup.set()
    ms, secs = _past_measure(pl)
    assert pl._on_measure_end(ms, secs, 0) == ms
    assert pl._count_in == 2
    print("  _on_measure_end : _wakeup → pas de décision : OK")

def test_measure_end_waits_until_end_of_measure():
    pl = _make_player()
    pl.playing = True
    secs = 0.05
    ms = time.perf_counter()
    pl._on_measure_end(ms, secs, 0)
    assert time.perf_counter() >= ms + secs
    print("  _on_measure_end : attend la fin de mesure : OK")
