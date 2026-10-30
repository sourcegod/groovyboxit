#python3
"""
    File: tests/test_signature.py
    Tests des signatures rythmiques (Phase 7 étape 20c1, docs/DESIGN.md
    § 20a1 S1-S9, avancement 20b1) : unités du pattern (temps du
    dénominateur, noire du tempo, résolution), pas par mesure, changement
    de signature qui garde les notes en place, sauvegarde et copie, valeurs
    de note (grille, quantisation, enregistrement, Note Repeat), minutage
    du player, métronome, position affichée, décompte, import et export
    (3/4, 6/8, 5/4, 7/8, 2/2), aller-retour.
    Date: Fri, 30/10/2026
    Author: Coolbrother
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mido
import pytest

from pattern import Pattern, TapeEvent, ETYPE_PATCH
from metronome import Metronome
from player.drum_player import DrumPlayer
from midi.midi_import import build_pattern_from_midi
from midi.midi_export import build_pattern_midi


def _pat(num=4, den=4, bars=4, res=16):
    """Pattern de `bars` mesures dans la signature num/den (set_signature
    garde la longueur : le nombre de mesures est fixé après)."""
    p = Pattern()
    p._num_steps = Pattern.steps_for(res, 4, 4)
    assert p.set_signature(num, den)
    p._num_bars = bars
    return p


def _note(p, t, note=60, dur=100):
    p._tape[0].append(TapeEvent(ETYPE_PATCH, dur=dur, payload={"note": note, "vel": 90}, time=t))


class _Silent:
    def stop_all(self):           pass
    def play_sound(self, *a):     pass
    def play_note(self, *a):      pass
    def play_metronome(self, *a): pass


def _player(p, bpm=120):
    pl = DrumPlayer(_Silent())
    pl._pattern.copy_from(p)
    pl.set_bpm(bpm)
    return pl


# ---------------------------------------------------------------------------
# Unités du pattern
# ---------------------------------------------------------------------------

def test_default_is_4_4():
    p = Pattern()
    assert (p._num_beats, p._denumerator, p._num_steps) == (4, 4, 16)
    assert (p.steps_per_beat(), p.steps_per_quarter(), p.resolution(), p.quarters_per_bar()) \
        == (4, 4, 16, 4)


@pytest.mark.parametrize("res, num, den, steps", [
    (16, 4, 4, 16), (16, 3, 4, 12), (16, 6, 8, 12), (16, 5, 4, 20), (16, 7, 8, 14),
    (16, 2, 2, 16), (16, 3, 16, 3), (32, 3, 4, 24), (128, 7, 8, 112), (16, 1, 32, None),
])
def test_steps_for(res, num, den, steps):
    assert Pattern.steps_for(res, num, den) == steps


@pytest.mark.parametrize("num, den, steps, spb, qpb", [
    (3, 4, 12, 4, 3), (6, 8, 12, 2, 3), (5, 4, 20, 4, 5), (7, 8, 14, 2, 3.5), (2, 2, 16, 8, 4),
])
def test_units_by_signature(num, den, steps, spb, qpb):
    p = _pat(num, den)
    assert p._num_steps == steps
    assert p.steps_per_beat() == spb                 # temps = dénominateur (S4)
    assert p.quarters_per_bar() == qpb
    assert p.steps_per_quarter() == 4                # tempo en noires (S5)
    assert p.resolution() == 16


def test_note_steps_are_note_values():
    p = _pat(3, 4)
    assert (p.note_steps(16), p.note_steps(8), p.note_steps(4), p.note_steps(1)) == (1, 2, 4, 16)
    p = _pat(6, 8, res=32)
    assert p._num_steps == 24 and p.note_steps(16) == 2


# ---------------------------------------------------------------------------
# Changer la signature : les notes gardent leur place (S3)
# ---------------------------------------------------------------------------

def test_set_signature_keeps_positions_and_times():
    p = _pat()                                       # 4/4, 4 mesures
    for t in (0, 4, 16, 20, 36):
        _note(p, t)
    p.set_tempo_changes([(32, 60)])
    p._loop_start, p._loop_end = 8, 40
    secs = [p.tempo_map().secs(e.time) for e in p._tape[0]]
    assert p.set_signature(6, 8)
    assert [e.time for e in p._tape[0]] == [0, 4, 16, 20, 36]
    assert [p.tempo_map().secs(e.time) for e in p._tape[0]] == secs
    assert p._tempo_changes == [(32, 60)] and (p._loop_start, p._loop_end) == (8, 40)
    assert (p._num_steps, p._num_bars) == (12, 6)    # 64 pas → 6 mesures de 12


def test_set_signature_rounds_bars_up():
    p = _pat(bars=3)                                 # 48 pas
    p.set_signature(5, 4)                            # 20 pas par mesure → 2,4 mesures
    assert p._num_bars == 3


def test_set_signature_round_trip():
    p = _pat(bars=3)
    p.set_signature(3, 4)
    p.set_signature(4, 4)
    assert (p._num_steps, p._num_bars) == (16, 3)


@pytest.mark.parametrize("num, den", [(4, 3), (4, 32), (0, 4), (17, 4)])
def test_set_signature_refused(num, den):
    p = _pat()
    assert not p.set_signature(num, den)
    assert (p._num_beats, p._denumerator, p._num_steps) == (4, 4, 16)


# ---------------------------------------------------------------------------
# Sauvegarde et copie (S8)
# ---------------------------------------------------------------------------

def test_to_dict_from_dict():
    p = _pat(7, 8)
    d = p.to_dict()
    assert (d["num_beats"], d["denominator"], d["num_steps"]) == (7, 8, 14)
    q = Pattern()
    q.from_dict(d)
    assert (q._num_beats, q._denumerator, q._num_steps) == (7, 8, 14)


def test_from_dict_without_signature_is_4_4():
    d = Pattern().to_dict()
    del d["num_beats"], d["denominator"]
    q = _pat(3, 4)                                   # Ctrl+O recharge dans un Pattern existant
    q.from_dict(d)
    assert (q._num_beats, q._denumerator) == (4, 4)


def test_copy_from_copies_signature():
    q = Pattern()
    q.copy_from(_pat(6, 8))
    assert (q._num_beats, q._denumerator, q._num_steps) == (6, 8, 12)


# ---------------------------------------------------------------------------
# Valeurs de note (S6)
# ---------------------------------------------------------------------------

def test_grid_step_size_note_values():
    p = _pat(3, 4)
    idx = {label: i for i, (label, _k, _v) in enumerate(Pattern.GRID_RESOLUTIONS)}
    size = lambda label: Pattern.grid_step_size(idx[label], p._num_steps, p.resolution())
    assert (size("1/16"), size("1/8"), size("1/4")) == (1, 2, 4)
    assert size("1 mes.") == 12 and size("2 mes.") == 24
    assert Pattern.grid_step_size(idx["1/16"], 16) == 1            # sans résolution : 4/4


def test_note_repeat_interval_is_note_value():
    pl = _player(_pat(3, 4, bars=1))
    pl._note_repeat_active = True
    pl._nr_quant_idx = Pattern.QUANT_LIST.index("1/16")
    nr = [e for e in pl._build_measure_events(0, 11, 12, 1, 0.0) if e[1] == DrumPlayer.NR_EVENT]
    assert len(nr) == 12                                            # 12 doubles croches


def test_record_quantize_is_note_value():
    pl = _player(_pat(3, 4, bars=2))
    pl.playing = True
    pl._cur_lp_start, pl._cur_loop_steps = 0, 0
    pl.quant_idx = Pattern.QUANT_LIST.index("1/8")
    pl._measure_start = time.perf_counter() - 3.3 * pl.step_duration
    off, bar, step = pl._compute_record_offset()
    assert (off, bar, step) == (4, 0, 4)                            # 3,3 → croche la plus proche


def test_quant_row_in_3_4():
    pl = _player(_pat(3, 4, bars=1))
    pl.apply_quant_row(Pattern.QUANT_LIST.index("1/4"), 0)
    assert pl._pattern.grid_row(0, 0, 0) == [100, 0, 0, 0, 100, 0, 0, 0, 100, 0, 0, 0]


def test_quantize_grid_continuous_across_bars():
    """Blanche en 3/4 (8 pas) : la grille ne recommence pas à chaque mesure."""
    pl = _player(_pat(3, 4, bars=2))
    _note(pl._pattern, 13)
    pl.apply_quant_to_pattern(Pattern.QUANT_LIST.index("1/2"))
    assert [e.time for e in pl._pattern._tape[0]] == [16]


def test_quantize_unchanged_in_4_4():
    pl = _player(_pat(4, 4, bars=2))
    _note(pl._pattern, 13)
    pl.apply_quant_to_pattern(Pattern.QUANT_LIST.index("1/4"))
    assert [e.time for e in pl._pattern._tape[0]] == [12]


# ---------------------------------------------------------------------------
# Player : minutage, métronome, position, décompte
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("num, den, bar_secs", [(4, 4, 2.0), (3, 4, 1.5), (6, 8, 1.5),
                                               (7, 8, 1.75), (5, 4, 2.5), (2, 2, 2.0)])
def test_bar_duration_at_120_bpm(num, den, bar_secs):
    pl = _player(_pat(num, den))
    assert pl.step_duration == pytest.approx(0.125)                 # 4 pas par noire
    assert pl.tempo_map().secs(pl._pattern._num_steps) == pytest.approx(bar_secs)


@pytest.mark.parametrize("num, den, clicks", [(3, 4, [0, 0.5, 1.0]),
                                             (6, 8, [0, 0.25, 0.5, 0.75, 1.0, 1.25]),
                                             (7, 8, [0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5])])
def test_metronome_one_click_per_beat(num, den, clicks):
    p = _pat(num, den, bars=1)
    m = Metronome()
    m.active = True
    ev = m.build_events(1, p._num_steps, p._num_beats, lambda s: s * 0.125, 0.0)
    assert [e[0] for e in ev] == pytest.approx(clicks)
    assert [e[2] for e in ev] == list(range(num))                   # accent : temps 0


def test_position_str_in_6_8():
    pl = _player(_pat(6, 8, bars=2))
    pl._resume_offset = 6.0                                         # 4e croche
    assert pl.position_str() == "1:4:1 / 2:6:2"


def test_count_in_bar_in_6_8():
    pl = _player(_pat(6, 8))
    pl._count_in = 1
    pl._count_in_resume_offset = 0.0
    assert pl._measure_clock(0)(pl._pattern._num_steps) == pytest.approx(1.5)


def test_song_advance_takes_next_signature():
    pl = _player(_pat(4, 4))
    nxt = _pat(3, 4)
    pl._pattern_list_ref = [Pattern(), nxt]
    pl._song_sequence, pl._song_pos, pl._song_mode = [0, 1], 0, True
    pl._pattern._looping = False
    pl.playing = True
    pl._wakeup.clear()
    secs = 16 * pl.step_duration
    pl._on_measure_end(time.perf_counter() - 2 * secs, secs, 0)
    assert (pl._pattern._num_beats, pl._pattern._num_steps) == (3, 12)


# ---------------------------------------------------------------------------
# Import et export (S9)
# ---------------------------------------------------------------------------

def _mid(num, den, notes, ppq=480, end=None, extra_sigs=()):
    mid = mido.MidiFile(type=1, ticks_per_beat=ppq)
    cond = mido.MidiTrack([mido.MetaMessage("time_signature", numerator=num, denominator=den)])
    now = 0
    for at, n, d in extra_sigs:
        cond.append(mido.MetaMessage("time_signature", numerator=n, denominator=d, time=at - now))
        now = at
    mid.tracks.append(cond)
    track, now, evs = mido.MidiTrack(), 0, []
    for start, stop in notes:
        evs += [(start, mido.Message("note_on", note=60, velocity=90)),
                (stop, mido.Message("note_off", note=60))]
    for at, msg in sorted(evs, key=lambda e: e[0]):
        track.append(msg.copy(time=at - now))
        now = at
    if end:
        track.append(mido.MetaMessage("end_of_track", time=end - now))
    mid.tracks.append(track)
    return mid


def test_import_6_8_positions():
    # croche = 240 ticks ; notes sur les croches 1, 4, puis mesure 2
    pat, rep = build_pattern_from_midi(_mid(6, 8, [(0, 100), (720, 800), (1440, 1500)]))
    assert (pat._num_beats, pat._denumerator, pat._num_steps) == (6, 8, 12)
    assert rep.resolution == 16 and rep.time_signature == (6, 8)
    assert [e.time for e in pat._tape[0] if e.etype == ETYPE_PATCH] == [0, 6, 12]


def test_import_7_8_with_odd_ppq():
    """Ticks par mesure fractionnaires (PPQ 25 : 87,5 ticks par mesure de 7/8)."""
    pat, rep = build_pattern_from_midi(_mid(7, 8, [(0, 10), (25, 30), (175, 180)], ppq=25))
    assert (pat._num_steps, pat._num_bars) == (14, 3)
    times = [e.time for e in pat._tape[0] if e.etype == ETYPE_PATCH]
    assert times == [0, 4, 28] and all(isinstance(t, int) for t in times)


def test_import_unsupported_signature_read_as_4_4():
    pat, rep = build_pattern_from_midi(_mid(5, 32, [(0, 100)]))
    assert (pat._num_beats, pat._denumerator) == (4, 4)
    assert rep.unsupported_signature == (5, 32)
    assert "signature 5/32 non prise en charge, lue en 4/4" in rep.details()


def test_import_signature_changes_counted():
    pat, rep = build_pattern_from_midi(_mid(3, 4, [(0, 100)], end=4 * 1440,
                                            extra_sigs=[(1440, 3, 4), (2880, 4, 4), (4320, 3, 4)]))
    assert (pat._num_beats, pat._denumerator) == (3, 4)
    assert rep.signature_changes == 2                               # 3/4 répété : pas compté
    assert "2 changements de signature ignorés" in rep.details()


def test_import_resolution_follows_notes():
    # doubles croches pointées en 3/4 : 1/16 ne suffit pas, 1/32 oui
    pat, rep = build_pattern_from_midi(_mid(3, 4, [(0, 10), (60, 70)]))
    assert rep.resolution == 32 and pat._num_steps == 24


def _export(p):
    n = Pattern.DEFAULT_NUM_TRACKS
    return build_pattern_midi(p, name="P", bpm=120, track_channels=list(range(16)),
                              track_is_synth=[True] * n, track_names=[""] * n,
                              kit_pad_notes=[36] * 16, synth_grid_notes=[60] * 16,
                              voice_durations=[500] * 16)


def test_export_time_signature_and_ticks():
    p = _pat(6, 8, bars=2)
    _note(p, 6)
    mid = _export(p)
    sig = [m for m in mid.tracks[0] if m.type == "time_signature"][0]
    assert (sig.numerator, sig.denominator) == (6, 8)
    now, on = 0, None
    for m in mid.tracks[1]:
        now += m.time
        if m.type == "note_on":
            on = now
    assert on == 720                                                # 4e croche
    assert sum(m.time for m in mid.tracks[0]) == 2 * 1440            # fin : 2 mesures de 6/8


@pytest.mark.parametrize("num, den", [(3, 4), (6, 8), (7, 8), (5, 4), (2, 2)])
def test_round_trip(num, den):
    p = _pat(num, den, bars=3)
    for t in (0, 3, p._num_steps + 1, 2 * p._num_steps):
        _note(p, t)
    q, _ = build_pattern_from_midi(_export(p))
    assert (q._num_beats, q._denumerator, q._num_steps, q._num_bars) == \
        (num, den, p._num_steps, 3)
    assert [e.time for e in q._tape[0] if e.etype == ETYPE_PATCH] == \
        [e.time for e in p._tape[0]]
