#python3
"""
    File: tests/test_tempo_playback.py
    Tests du player sur la carte de tempo (Phase 7 étape 19e1, docs/DESIGN.md
    § 19a1 T4, T5, T10 et avenant § 19d2 R1, R2 ; avancement 19d1, 19d3) :
    carte en cache, tempo en vigueur, tempo changé à la position ou partout
    dans la même proportion, position dans la fenêtre, minutage de la mesure
    (événements, métronome, Note Repeat, décompte), tempos franchis signalés,
    pause, déplacements, position gardée quand le tempo change en lecture,
    song, ms par pas au tempo local, dialogue Aller à en secondes, champ BPM
    de la fenêtre principale ; lecture réelle courte, chronométrée.
    Date: Thu, 29/10/2026
    Author: Coolbrother
"""
import sys
import os
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

import ui.main_window as main_window
from pattern import Pattern, TapeEvent, ETYPE_PATCH, ETYPE_CC
from metronome import Metronome
from player.drum_player import DrumPlayer
from ui.dialogs_temporal import GotoDialog
from tempo_map import TempoMap


class _Silent:
    def stop_all(self):           pass
    def play_sound(self, *a):     pass
    def play_note(self, *a):      pass
    def play_metronome(self, *a): pass


def _player(bpm=120, changes=(), bars=4, steps=16):
    """Player non lancé ; 120 BPM, 16 pas par mesure : 0,125 s par pas."""
    pl = DrumPlayer(_Silent())
    pat = pl._pattern
    pat._num_bars, pat._num_steps = bars, steps
    pl.set_bpm(bpm)
    pat.set_tempo_changes(changes)
    return pl


def _freeze(pl, monkeypatch):
    """Lecture simulée sans thread."""
    monkeypatch.setattr(pl, "start_thread", lambda: None)
    monkeypatch.setattr(pl, "stop_thread", lambda: None)


# ---------------------------------------------------------------------------
# Carte du player, tempo en vigueur
# ---------------------------------------------------------------------------

def test_tempo_map_cached_until_something_changes():
    pl = _player(changes=[(16, 60)])
    m = pl.tempo_map()
    assert pl.tempo_map() is m
    pl.set_bpm(100)
    m2 = pl.tempo_map()
    assert m2 is not m and m2.start_bpm == 100
    pl._pattern._tempo_changes = [(16, 90)]
    assert pl.tempo_map().changes == [(16, 90)]
    pl._pattern._num_steps = 32
    assert pl.tempo_map().steps_per_beat == 8


def test_tempo_map_start_is_player_bpm():
    pl = _player(bpm=90)
    pl._pattern._bpm = 50                  # pattern pas à jour : le player prime
    pl._tmap_key = None
    assert pl.tempo_map().start_bpm == 90


def test_set_bpm_keeps_live_pattern_bpm():
    """19d1 : le pattern du player restait à 100 BPM."""
    pl = _player(bpm=137)
    assert pl._pattern._bpm == 137


def test_tempo_at_position():
    pl = _player(changes=[(16, 60), (32, 90)])
    assert [pl.tempo_at(p) for p in (0, 16, 31.9, 32)] == [120, 60, 60, 90]
    pl._resume_offset = 20.0
    assert pl.tempo_at() == 60                  # position courante


def test_set_tempo_at_start_segment_changes_start_tempo():
    pl = _player(changes=[(16, 60)])
    assert pl.set_tempo_at(100, pos=4) == 100
    assert pl.bpm == 100 and pl._pattern._bpm == 100
    assert pl._pattern._tempo_changes == [(16, 60)]


def test_set_tempo_at_later_segment_changes_that_change_only():
    pl = _player(changes=[(16, 60), (32, 90)])
    pl.set_tempo_at(70, pos=20)
    assert pl.bpm == 120
    assert pl._pattern._tempo_changes == [(16, 70), (32, 90)]


def test_set_tempo_at_drops_redundant_change():
    pl = _player(changes=[(16, 60)])
    pl.set_tempo_at(120, pos=16)
    assert pl._pattern._tempo_changes == []


def test_set_tempo_at_out_of_range():
    pl = _player(changes=[(16, 60)])
    assert pl.set_tempo_at(0, pos=0) is None and pl.set_tempo_at(601, pos=0) is None
    assert pl.bpm == 120


# ---------------------------------------------------------------------------
# Tous les tempos dans la même proportion (§ 19d2 R2)
# ---------------------------------------------------------------------------

def test_scale_tempos_multiplies_all():
    pl = _player(bpm=92, changes=[(16, 94), (32, 40)])
    pl.scale_tempos(0.5)
    assert pl.bpm == 46 and pl._pattern._bpm == 46
    assert pl._pattern._tempo_changes == [(16, 47), (32, 20)]


def test_scale_tempos_keeps_two_decimals():
    pl = _player(bpm=92, changes=[(16, 93)])
    pl.scale_tempos(0.5)
    assert pl._pattern._tempo_changes == [(16, 46.5)]


def test_scale_tempos_clamps_each_tempo():
    pl = _player(bpm=300, changes=[(16, 10)])
    pl.scale_tempos(3)
    assert pl.bpm == 600 and pl._pattern._tempo_changes == [(16, 30)]
    pl.scale_tempos(0.01)
    assert pl.bpm == 6 and pl._pattern._tempo_changes == [(16, 1)]


def test_set_tempo_scaled_from_tempo_at_position():
    pl = _player(bpm=100, changes=[(16, 50)])
    assert pl.set_tempo_scaled(25, pos=20) == 25      # 50 → 25 : tout à moitié
    assert pl.bpm == 50 and pl._pattern._tempo_changes == [(16, 25)]


def test_set_tempo_scaled_out_of_range():
    pl = _player(bpm=100)
    assert pl.set_tempo_scaled(0) is None and pl.set_tempo_scaled(700) is None
    assert pl.bpm == 100


def test_scaling_round_trip_is_exact():
    """Tempos à 0,01 : plus lent, ±5 en série, puis retour au départ (R1)."""
    changes = [(10, 94), (15, 92), (25, 93), (500, 85), (530, 60), (540, 40)]
    pl = _player(bpm=92, changes=changes, bars=36)
    pl.set_tempo_scaled(46, pos=0)
    for step in (5, 5, 5, -5, -5, -5, 7, -7):
        pl.set_tempo_scaled(round(pl.tempo_at(0)) + step, pos=0)
    pl.set_tempo_scaled(92, pos=0)
    assert pl.bpm == 92
    assert pl._pattern._tempo_changes == changes


def test_scaled_map_lengthens_proportionally():
    pl = _player(bpm=92, changes=[(16, 60)])
    before = pl.tempo_map().secs(64)
    pl.set_tempo_scaled(46, pos=0)
    assert pl.tempo_map().secs(64) == pytest.approx(2 * before)


# ---------------------------------------------------------------------------
# Position dans la fenêtre, fin de fenêtre en secondes
# ---------------------------------------------------------------------------

def test_position_at_constant_tempo_matches_linear():
    pl = _player(bpm=120)
    pl._measure_start = 100.0
    pl._cur_lp_start, pl._cur_loop_steps = 0, 0
    sd = pl.step_duration
    for elapsed in (0.0, 0.3, 7.9):
        assert pl._position_at(100.0 + elapsed) == pytest.approx((elapsed % (64 * sd)) / sd)


def test_position_at_follows_map():
    pl = _player(bpm=120, changes=[(16, 60)])            # 0,125 s puis 0,25 s par pas
    pl._measure_start = 10.0
    pl._cur_lp_start, pl._cur_loop_steps = 0, 0
    assert pl._position_at(12.0) == pytest.approx(16)
    assert pl._position_at(13.0) == pytest.approx(20)
    total = pl.tempo_map().secs(64)                      # retour au début
    assert pl._position_at(10.0 + total + 0.25) == pytest.approx(2)


def test_position_at_inside_loop_window():
    pl = _player(bpm=120, changes=[(16, 60)])
    pl._measure_start = 0.0
    pl._cur_lp_start, pl._cur_loop_steps = 12, 8         # pas 12..19
    assert pl._position_at(0.5) == pytest.approx(16)     # 4 pas à 0,125 s
    assert pl._position_at(1.5) == pytest.approx(20 - 8)  # fin de fenêtre : retour à 12


def test_t_to_offset_counts_from_window_start():
    """19d1 : t_sec / step_duration oubliait le début de la boucle."""
    pl = _player(bpm=120, changes=[(16, 60)])
    pl._cur_lp_start = 12
    assert pl._t_to_offset(0.5) == pytest.approx(16)
    assert pl._t_to_offset(0.75) == pytest.approx(17)


def test_time_str_by_map():
    pl = _player(bpm=120, changes=[(16, 60)], bars=2)
    pl._resume_offset = 20.0
    assert pl.time_str() == "3.000 / 6.000"


def test_move_by_seconds_by_map(monkeypatch):
    pl = _player(bpm=120, changes=[(16, 60)])
    pl._resume_offset = 16.0                              # 2 s
    pl.move_by_seconds(1)
    assert pl._resume_offset == pytest.approx(20)         # 3 s


# ---------------------------------------------------------------------------
# Minutage de la mesure
# ---------------------------------------------------------------------------

def test_measure_clock_constant_matches_linear():
    pl = _player(bpm=120)
    clock = pl._measure_clock(0)
    assert clock(10) == pytest.approx(10 * pl.step_duration)


def test_measure_clock_from_window_start():
    pl = _player(bpm=120, changes=[(16, 60)])
    clock = pl._measure_clock(12)
    assert clock(4) == pytest.approx(0.5) and clock(8) == pytest.approx(1.5)


def test_measure_clock_count_in_at_resume_tempo():
    pl = _player(bpm=120, changes=[(16, 60)])
    pl._count_in = 1
    pl._count_in_resume_offset = 20.0
    assert pl._measure_clock(0)(16) == pytest.approx(4.0)     # mesure à 60 BPM
    pl._count_in_resume_offset = 0.0
    assert pl._measure_clock(0)(16) == pytest.approx(2.0)


def test_count_in_offset_secs_by_map():
    pl = _player(bpm=120, changes=[(16, 60)])
    pl._count_in_resume_offset = 20.0
    assert pl._count_in_offset_secs() == pytest.approx(3.0)


def _build(pl, lp_start=0, lp_end=63, total=64, bars=4, elapsed=0.0):
    return pl._build_measure_events(lp_start, lp_end, total, bars, elapsed)


def test_build_tape_events_timed_by_map():
    pl = _player(bpm=120, changes=[(16, 60)])
    pl.playing = True
    for t in (0, 16, 20):
        pl._pattern._tape[0].append(TapeEvent(ETYPE_PATCH, dur=100,
                                              payload={"note": 60, "vel": 90}, time=t))
    times = [e[0] for e in _build(pl) if e[1] == DrumPlayer.PATCH_TAPE_EVENT]
    assert times == pytest.approx([0.0, 2.0, 3.0])


def test_build_metronome_and_note_repeat_by_map():
    pl = _player(bpm=120, changes=[(16, 60)], bars=2)
    pl.playing = True
    pl.clicking = True
    beats = [e[0] for e in _build(pl, lp_end=31, total=32, bars=2)
             if e[1] == Metronome.METRO_EVENT]
    assert beats == pytest.approx([0, 0.5, 1, 1.5, 2, 3, 4, 5])
    pl.clicking = False
    pl._note_repeat_active = True
    pl._nr_quant_idx = 3                                   # 1/4 : un par temps
    nr = [e[0] for e in _build(pl, lp_end=31, total=32, bars=2)
          if e[1] == DrumPlayer.NR_EVENT]
    assert nr == pytest.approx([0, 0.5, 1, 1.5, 2, 3, 4, 5])


def test_metronome_accepts_function_or_step_duration():
    m = Metronome()
    m.active = True
    lin = [e[0] for e in m.build_events(1, 16, 4, 0.125, 0.0)]
    fn  = [e[0] for e in m.build_events(1, 16, 4, lambda s: s * 0.125, 0.0)]
    assert lin == fn == pytest.approx([0, 0.5, 1, 1.5])


def test_build_tempo_marks_only_with_changes():
    pl = _player(bpm=120)
    pl.playing = True
    assert not [e for e in _build(pl) if e[1] == DrumPlayer.TEMPO_EVENT]
    pl._pattern.set_tempo_changes([(16, 60), (40.5, 90)])
    marks = [(e[0], e[2]) for e in _build(pl) if e[1] == DrumPlayer.TEMPO_EVENT]
    assert marks == [(0.0, 120), (2.0, 60), pytest.approx((8.125, 90))]


def test_build_tempo_marks_in_window_and_not_during_count_in():
    pl = _player(bpm=120, changes=[(16, 60), (63.5, 90)])
    pl.playing = True
    marks = [e[2] for e in _build(pl, lp_start=8, lp_end=63, total=56)
             if e[1] == DrumPlayer.TEMPO_EVENT]
    assert marks == [120, 60, 90]                    # 63,5 : dans la dernière case
    marks = [e[2] for e in _build(pl, lp_start=20, lp_end=30, total=11)
             if e[1] == DrumPlayer.TEMPO_EVENT]
    assert marks == [60]                             # début de fenêtre seulement
    pl._count_in = 1
    assert not [e for e in _build(pl) if e[1] == DrumPlayer.TEMPO_EVENT]


def test_dispatch_tempo_event_calls_callback():
    pl = _player()
    got = []
    pl._dispatch_event(DrumPlayer.TEMPO_EVENT, 60, 0, 0.0)      # sans rappel : rien
    pl._on_tempo_cb = got.append
    pl._dispatch_event(DrumPlayer.TEMPO_EVENT, 46.5, 0, 0.0)
    assert got == [46.5]


# ---------------------------------------------------------------------------
# Pause, déplacements, position gardée, song
# ---------------------------------------------------------------------------

def test_pause_keeps_position_by_map(monkeypatch):
    pl = _player(bpm=120, changes=[(16, 60)])
    _freeze(pl, monkeypatch)
    pl.playing = True
    pl._cur_lp_start, pl._cur_loop_steps = 0, 0
    pl._measure_start = time.perf_counter() - 3.0
    pl.pause_pattern()
    assert pl._resume_offset == pytest.approx(20, abs=0.05)


def test_stopped_move_calls_callback_playing_does_not(monkeypatch):
    pl = _player()
    _freeze(pl, monkeypatch)
    moves = []
    pl._on_stopped_move_cb = lambda: moves.append(pl._resume_offset)
    pl._go_to_offset(16.0)
    pl.goto_start()
    assert moves == [16.0, None]
    pl.playing = True
    pl._go_to_offset(8.0)
    assert moves == [16.0, None]


def test_keep_position_only_while_playing():
    pl = _player(changes=[(16, 60)])
    pl.set_tempo_scaled(60)                                # à l'arrêt : 120 → 60
    assert pl._resync_offset is None
    pl.playing = True
    pl._cur_lp_start, pl._cur_loop_steps = 0, 0
    pl._measure_start = time.perf_counter() - 1.0          # pas 4 à 60 BPM
    pl.set_tempo_scaled(30)
    assert pl._resync_offset == pytest.approx(4, abs=0.05)


def test_set_bpm_keeps_position_while_playing():
    """19d1 : changer le tempo de départ en lecture ne fait plus sauter la
    position, le thread se recale sur _resync_offset."""
    pl = _player(bpm=120)
    pl.playing = True
    pl._cur_lp_start, pl._cur_loop_steps = 0, 0
    pl._measure_start = time.perf_counter() - 1.0          # pas 8 à 120 BPM
    pl.set_bpm(60)
    assert pl._resync_offset == pytest.approx(8, abs=0.05)


def test_note_repeat_recorded_at_window_position(monkeypatch):
    """19d1 : un coup de Note Repeat est enregistré à sa position dans une
    boucle qui ne commence pas à 1.1.1, par la carte."""
    pl = _player(bpm=120, changes=[(16, 60)])
    got = []
    monkeypatch.setattr(pl, "_record_nr_hit", lambda pad, off: got.append((pad, off)))
    pl._nr_get_pad = lambda: 2
    pl.recording = True
    pl._cur_lp_start = 12
    pl._dispatch_event(DrumPlayer.NR_EVENT, 0, 100, 0.75)
    assert got == [(2, pytest.approx(17))]


def test_song_advance_takes_next_pattern_map():
    pl = _player(bpm=100)
    nxt = Pattern()
    nxt._bpm = 80
    nxt.set_tempo_changes([(8, 40)])
    pl._pattern_list_ref = [Pattern(), nxt]
    pl._song_sequence, pl._song_pos, pl._song_mode = [0, 1], 0, True
    pl._pattern._looping = False
    pl.playing = True
    pl._wakeup.clear()                       # posé par set_bpm : pas de décision sinon
    secs = 16 * pl.step_duration
    pl._on_measure_end(time.perf_counter() - 2 * secs, secs, 0)
    assert pl.bpm == 80 and pl._pattern._bpm == 80
    assert pl.tempo_map().changes == [(8, 40)]


# ---------------------------------------------------------------------------
# Millisecondes par pas au tempo local (T5)
# ---------------------------------------------------------------------------

def test_ms_per_step_at():
    p = Pattern()
    p._bpm = 120
    p.set_tempo_changes([(16, 60)])
    assert p.ms_per_step_at(0) == pytest.approx(125)
    assert p.ms_per_step_at(16) == pytest.approx(250)


# ---------------------------------------------------------------------------
# Dialogue Aller à en secondes (19d1)
# ---------------------------------------------------------------------------

def test_goto_to_offset_seconds_by_map():
    tm = TempoMap(120, [(16, 60)], 4)
    assert GotoDialog.to_offset(3, 3, 4, 4, 16, 0.125, tm) == pytest.approx(20)
    assert GotoDialog.to_offset(3, 3, 4, 4, 16, 0.125) == pytest.approx(24)   # sans carte
    assert GotoDialog.to_offset(0, 2, 4, 4, 16, 0.125, tm) == 16.0           # mesures : inchangé


def test_goto_secs_and_steps_by_map():
    fake = SimpleNamespace(_tempo_map=TempoMap(120, [(16, 60)], 4), _step_duration=0.125)
    assert GotoDialog._secs(fake, 20) == pytest.approx(3.0)
    assert GotoDialog._steps(fake, 3.0) == pytest.approx(20)
    fake._tempo_map = None
    assert GotoDialog._secs(fake, 20) == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# Champ BPM de la fenêtre principale (§ 19d2 R2)
# ---------------------------------------------------------------------------

class _Ctrl:
    def __init__(self, value=0): self.value = value
    def SetValue(self, v):       self.value = v
    def GetValue(self):          return self.value


def test_update_bpm_display_rounds_tempo_at_position():
    pl = _player(bpm=92, changes=[(16, 46.6)])
    pl._resume_offset = 20.0
    win = SimpleNamespace(_player=pl, _bpm_ctrl=_Ctrl())
    main_window.MainWindow._update_bpm_display(win)
    assert win._bpm_ctrl.value == 47 and isinstance(win._bpm_ctrl.value, int)


def test_bpm_spin_scales_all_tempos():
    pl = _player(bpm=100, changes=[(16, 50)])
    win = SimpleNamespace(_player=pl, _bpm_ctrl=_Ctrl(50), statuses=[])
    win._show_status = win.statuses.append
    pl._resume_offset = 20.0
    win._bpm_ctrl.value = 25
    main_window.MainWindow._on_bpm_spin(win, None)
    assert pl.bpm == 50 and pl._pattern._tempo_changes == [(16, 25)]
    assert win.statuses == ["BPM: 25"]


def test_on_play_stopped_resets_controllers_and_shows_tempo(monkeypatch):
    monkeypatch.setattr(main_window.wx, "CallAfter", lambda fn, *a: fn(*a))
    pl = _player(bpm=100)
    calls = []
    win = SimpleNamespace(_router=SimpleNamespace(on_play_stop=lambda: calls.append("stop")),
                          _player=pl, _bpm_ctrl=_Ctrl())
    win._update_bpm_display = lambda: main_window.MainWindow._update_bpm_display(win)
    main_window.MainWindow._on_play_stopped(win)
    assert calls == ["stop"] and win._bpm_ctrl.value == 100


# ---------------------------------------------------------------------------
# Lecture réelle, chronométrée
# ---------------------------------------------------------------------------

def test_real_playback_follows_map():
    """120 BPM, 60 BPM dès le pas 4 : notes aux pas 0, 4, 6 attendues à 0,
    0,5 et 1,0 s ; tempos franchis signalés."""
    pl = _player(bpm=120, changes=[(4, 60)], bars=1)
    pl._pattern._looping = False
    for t in (0, 4, 6):
        pl._pattern._tape[0].append(TapeEvent(ETYPE_PATCH, dur=50,
                                              payload={"note": 60, "vel": 90}, time=t))
    hits, tempos = [], []
    pl._on_patch_tape_cb = lambda *a: hits.append(time.perf_counter())
    pl._on_tempo_cb = tempos.append
    t0 = time.perf_counter()
    pl.play_pattern()
    while len(hits) < 3 and time.perf_counter() - t0 < 3:
        time.sleep(0.01)
    pl.stop_all()
    assert [h - t0 for h in hits] == pytest.approx([0.0, 0.5, 1.0], abs=0.05)
    assert tempos[:2] == [120, 60]
