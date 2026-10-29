#python3
"""
    File: tests/test_tempo_map.py
    Tests de la carte de tempo (Phase 7 étape 19c1, docs/DESIGN.md § 19a1
    T2-T6) : clamp_bpm, normalize_changes, TempoMap (pas ↔ secondes par
    morceaux, tempo en vigueur, tempo unique = ancien calcul linéaire) ;
    Pattern._tempo_changes (.gvp, copy_from, resize, doubler, diviser,
    nouveau pattern, réinitialisation) ; import (changements gardés, tempo
    de départ, durées au tempo local) et export (un set_tempo par
    changement, fins de notes au tempo local, aller-retour exact).
    Date: Thu, 29/10/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mido
import pytest

from pattern import Pattern, TapeEvent, ETYPE_PATCH, ETYPE_CC
from tempo_map import TempoMap, normalize_changes, clamp_bpm, format_bpm
from midi.midi_import import build_pattern_from_midi
from midi.midi_export import build_pattern_midi, PPQ

BAR = PPQ * 4


# ---------------------------------------------------------------------------
# clamp_bpm, normalize_changes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bpm, expected", [(92, 92), (93.6, 93.6), (93.756, 93.76),
                                           (0, 1), (-5, 1), (601, 600), (1200.4, 600)])
def test_clamp_bpm(bpm, expected):
    # À 0,01 près (Phase 7 étape 19d3, § 19d2 R1)
    assert clamp_bpm(bpm) == expected


def test_clamp_bpm_integral_value_is_int():
    assert isinstance(clamp_bpm(92.0), int) and isinstance(clamp_bpm(92.004), int)
    assert isinstance(clamp_bpm(92.5), float)


@pytest.mark.parametrize("bpm, text", [(92, "92"), (92.0, "92"), (46.5, "46,5"),
                                       (93.75, "93,75"), (93.756, "93,76"), (0.2, "1")])
def test_format_bpm(bpm, text):
    assert format_bpm(bpm) == text


def test_normalize_sorts_and_drops_non_positive_positions():
    assert normalize_changes(100, [(32, 80), (0, 70), (-4, 60), (16, 90)]) == [(16, 90), (32, 80)]


def test_normalize_last_wins_at_same_position():
    assert normalize_changes(100, [(16, 80), (16, 90)]) == [(16, 90)]


def test_normalize_drops_redundant_tempo():
    """Un changement égal au tempo qui le précède est retiré (Sonar, T2)."""
    assert normalize_changes(100, [(16, 100), (32, 80), (48, 80), (64, 100)]) == \
        [(32, 80), (64, 100)]


def test_normalize_rounds_and_clamps():
    assert normalize_changes(100, [(16, 93.604), (32, 900)]) == [(16, 93.6), (32, 600)]


# ---------------------------------------------------------------------------
# TempoMap
# ---------------------------------------------------------------------------

def test_constant_map_matches_linear_step_duration():
    """À tempo unique, l'ancien calcul pas × step_duration (T4)."""
    for bpm in (60, 100, 137):
        for spb in (4, 8, 32):
            m = TempoMap(bpm, (), spb)
            step_duration = 60.0 / (bpm * spb)
            assert m.is_constant
            for steps in (0, 1, 7.5, 128, 3000):
                assert m.secs(steps) == pytest.approx(steps * step_duration)
                assert m.steps(steps * step_duration) == pytest.approx(steps)


def test_piecewise_secs():
    # 120 BPM, 4 pas par noire : 0,125 s par pas ; 60 BPM dès le pas 16 : 0,25 s
    m = TempoMap(120, [(16, 60)], 4)
    assert m.secs(16) == pytest.approx(2.0)
    assert m.secs(20) == pytest.approx(3.0)
    assert m.secs_between(12, 20) == pytest.approx(0.5 + 1.0)


def test_steps_is_inverse_of_secs():
    m = TempoMap(92, [(10, 94), (15.5, 60), (300, 40)], 4)
    for steps in (0, 3, 10, 12.25, 15.5, 100, 299.9, 300, 512):
        assert m.steps(m.secs(steps)) == pytest.approx(steps)


def test_bpm_at_applies_from_change_position():
    m = TempoMap(100, [(16, 80), (32, 120)], 4)
    assert [m.bpm_at(p) for p in (0, 15.9, 16, 31, 32, 99)] == [100, 100, 80, 80, 120, 120]


def test_map_normalizes_its_input():
    m = TempoMap(100.004, [(32, 80), (16, 100), (0, 50)], 4)
    assert m.start_bpm == 100
    assert m.changes == [(32, 80)]
    assert not m.is_constant


def test_bach_like_ritardando_lengthens():
    slow = TempoMap(92, [(512, 60), (520, 40)], 4)
    flat = TempoMap(92, (), 4)
    assert slow.secs(528) > flat.secs(528)
    assert slow.secs(512) == pytest.approx(flat.secs(512))


# ---------------------------------------------------------------------------
# Pattern._tempo_changes
# ---------------------------------------------------------------------------

def _pat(bpm=100, changes=(), bars=4, steps=16):
    p = Pattern()
    p._bpm, p._num_bars, p._num_steps = bpm, bars, steps
    p.set_tempo_changes(changes)
    return p


def test_new_pattern_has_single_tempo():
    p = Pattern()
    assert p._tempo_changes == []
    assert p.tempo_map().is_constant


def test_set_tempo_changes_normalizes():
    p = _pat(changes=[(32, 80), (16, 100)])
    assert p._tempo_changes == [(32, 80)]


def test_tempo_map_of_pattern():
    p = _pat(bpm=120, changes=[(16, 60)], steps=32)
    m = p.tempo_map()
    assert m.steps_per_beat == 8
    assert m.start_bpm == 120 and m.changes == [(16, 60)]
    assert p.tempo_map(start_bpm=90).start_bpm == 90       # tempo du player


def test_to_dict_from_dict_round_trip():
    p = _pat(changes=[(16, 80), (40.5, 120)])
    q = Pattern()
    q.from_dict(p.to_dict())
    assert q._tempo_changes == [(16, 80), (40.5, 120)]
    assert p.to_dict()["tempo_changes"] == [[16, 80], [40.5, 120]]


def test_from_dict_without_key_single_tempo():
    p = _pat(changes=[(16, 80)])
    d = p.to_dict()
    del d["tempo_changes"]
    q = _pat(changes=[(8, 70)])            # Ctrl+O recharge dans un Pattern existant
    q.from_dict(d)
    assert q._tempo_changes == []


def test_from_dict_normalizes():
    d = _pat().to_dict()
    d["tempo_changes"] = [[32, 100], [16, 80]]
    q = Pattern()
    q.from_dict(d)
    assert q._tempo_changes == [(16, 80), (32, 100)]


def test_copy_from_copies_changes():
    p = _pat(changes=[(16, 80)])
    q = Pattern()
    q.copy_from(p)
    assert q._tempo_changes == [(16, 80)]
    p._tempo_changes.append((32, 90))
    assert q._tempo_changes == [(16, 80)]                   # copie


def test_resize_moves_changes_like_events():
    p = _pat(changes=[(16, 80), (20.5, 90), (60, 70)], bars=4, steps=16)
    p.resize(2, 32)                        # mesure 1 pas 0 → 32 ; mesure 1 pas 4,5 → 36,5
    assert p._tempo_changes == [(32, 80), (36.5, 90)]       # mesure 3 : hors pattern


def test_resize_drops_redundant_after_cut():
    p = _pat(bpm=100, changes=[(16, 80), (40, 100)], bars=4)
    p.resize(4, 8)                         # pas 8..15 de chaque mesure perdus
    assert p._tempo_changes == [(8, 80)]


def test_double_bars_second_half_restarts_from_start_tempo():
    p = _pat(bpm=100, changes=[(16, 80)], bars=2)
    assert p.double_bars()
    assert p._tempo_changes == [(16, 80), (32, 100), (48, 80)]


def test_double_bars_without_changes_stays_single():
    p = _pat(bars=2)
    p.double_bars()
    assert p._tempo_changes == []


def test_halve_bars_keeps_first_half():
    p = _pat(changes=[(16, 80), (32, 90), (48, 70)], bars=4)
    assert p.halve_bars()
    assert p._tempo_changes == [(16, 80)]


def test_new_pattern_action_clears_changes():
    p = _pat(changes=[(16, 80)])
    p.new_pattern(2, 16)
    assert p._tempo_changes == []


def test_reset_pattern_keeps_changes():
    """Shift+Suppr n'efface que les notes (19b1)."""
    p = _pat(changes=[(16, 80)])
    p.reset_pattern()
    assert p._tempo_changes == [(16, 80)]


# ---------------------------------------------------------------------------
# Import (T5, T6)
# ---------------------------------------------------------------------------

def _tempo_track(*tempos):
    """Piste conductor : [(tick, bpm)]."""
    track, now = mido.MidiTrack(), 0
    for at, bpm in tempos:
        track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=at - now))
        now = at
    return track


def _note_track(notes, end=4 * BAR):
    track, now, events = mido.MidiTrack(), 0, []
    for start, stop, note in notes:
        events += [(start, mido.Message("note_on", note=note, velocity=90)),
                   (stop, mido.Message("note_off", note=note))]
    for at, msg in sorted(events, key=lambda e: e[0]):
        track.append(msg.copy(time=at - now))
        now = at
    track.append(mido.MetaMessage("end_of_track", time=end - now))
    return track


def _import(conductor, notes, end=4 * BAR):
    mid = mido.MidiFile(type=1, ticks_per_beat=PPQ)
    mid.tracks.extend([conductor, _note_track(notes, end)])
    return build_pattern_from_midi(mid)


def test_import_changes_positions_and_bpm():
    pat, rep = _import(_tempo_track((0, 100), (BAR, 80), (BAR + PPQ // 2, 60)), [(0, 10, 60)])
    assert pat._bpm == 100
    assert pat._tempo_changes == [(16, 80), (18, 60)]
    assert rep.tempo_changes == 2
    assert "2 changements de tempo" in rep.details()


def test_import_off_grid_tempo_keeps_exact_position():
    pat, _ = _import(_tempo_track((0, 100), (BAR + 7, 80)), [(0, 10, 60)])
    assert pat._tempo_changes == [((BAR + 7) * 16 / BAR, 80)]


def test_import_first_tempo_after_start_begins_at_120():
    pat, _ = _import(_tempo_track((BAR, 90)), [(0, 10, 60)])
    assert pat._bpm == 120
    assert pat._tempo_changes == [(16, 90)]


def test_import_last_tempo_at_tick_0_wins():
    pat, _ = _import(_tempo_track((0, 100), (0, 72)), [(0, 10, 60)])
    assert pat._bpm == 72 and pat._tempo_changes == []


def test_import_drops_tempo_at_or_after_pattern_end():
    # La piste conductor finit au dernier tempo (mesure 6) : 5 mesures ;
    # le tempo placé pile à la fin du pattern ne sert à rien
    pat, _ = _import(_tempo_track((0, 100), (BAR, 80), (4 * BAR, 60), (5 * BAR, 50)),
                     [(0, 10, 60)], end=4 * BAR)
    assert pat._num_bars == 5
    assert pat._tempo_changes == [(16, 80), (64, 60)]


def test_import_durations_at_local_tempo():
    # Noire à 120 BPM = 500 ms ; à 60 BPM = 1000 ms ; une note à cheval :
    # demi-noire à 120 puis demi-noire à 60 = 250 + 500 ms
    pat, _ = _import(_tempo_track((0, 120), (BAR, 60)),
                     [(0, PPQ, 60), (BAR, BAR + PPQ, 62), (BAR - PPQ // 2, BAR + PPQ // 2, 64)])
    durs = {ev.payload["note"]: ev.dur for ev in pat._tape[0] if ev.etype == ETYPE_PATCH}
    assert durs == {60: 500, 62: 1000, 64: 750}


# ---------------------------------------------------------------------------
# Export (T5, T6)
# ---------------------------------------------------------------------------

def _export(p, bpm=None):
    n = Pattern.DEFAULT_NUM_TRACKS
    return build_pattern_midi(
        p, name="P", bpm=p._bpm if bpm is None else bpm, track_channels=list(range(16)),
        track_is_synth=[True] * n, track_names=[""] * n, kit_pad_notes=[36] * 16,
        synth_grid_notes=[60] * 16, voice_durations=[500] * 16)


def _abs(track):
    now, out = 0, []
    for msg in track:
        now += msg.time
        out.append((now, msg))
    return out


def test_export_writes_one_set_tempo_per_change():
    p = _pat(bpm=100, changes=[(16, 80), (40, 120)])
    tempos = [(at, round(mido.tempo2bpm(m.tempo))) for at, m in _abs(_export(p).tracks[0])
              if m.type == "set_tempo"]
    assert tempos == [(0, 100), (BAR, 80), (BAR * 40 // 16, 120)]


def test_export_start_tempo_is_player_bpm():
    p = _pat(bpm=100, changes=[(16, 80)])
    tempos = [round(mido.tempo2bpm(m.tempo)) for m in _export(p, bpm=90).tracks[0]
              if m.type == "set_tempo"]
    assert tempos == [90, 80]


def test_export_conductor_ends_at_pattern_end():
    p = _pat(changes=[(16, 80)], bars=4)
    assert _abs(_export(p).tracks[0])[-1][0] == 4 * BAR


def test_export_single_tempo_unchanged():
    p = _pat(bpm=100)
    p._tape[0].append(TapeEvent(ETYPE_PATCH, dur=600, payload={"note": 60, "vel": 90}, time=0))
    track = _export(p).tracks[1]
    off = [at for at, m in _abs(track) if m.type == "note_off"]
    assert off == [round(0.6 * 100 / 60 * PPQ)]


def test_export_note_end_at_local_tempo():
    # 120 BPM puis 60 BPM au pas 16 ; note de 750 ms partant d'une demi-noire
    # avant : 250 ms à 120 (une demi-noire) + 500 ms à 60 (une demi-noire)
    p = _pat(bpm=120, changes=[(16, 60)])
    p._tape[0].append(TapeEvent(ETYPE_PATCH, dur=750, payload={"note": 60, "vel": 90}, time=14))
    p._tape[0].append(TapeEvent(ETYPE_PATCH, dur=1000, payload={"note": 62, "vel": 90}, time=16))
    notes = {}
    for at, m in _abs(_export(p).tracks[1]):
        if m.type in ("note_on", "note_off"):
            notes.setdefault(m.note, []).append(at)
    assert notes[60] == [BAR - PPQ // 2, BAR + PPQ // 2]
    assert notes[62] == [BAR, BAR + PPQ]


def test_round_trip_export_import_keeps_map_and_durations():
    p = _pat(bpm=100, changes=[(16, 80), (24.5, 60), (40, 120)], bars=4)
    p._tape[0] = [TapeEvent(ETYPE_PATCH, dur=d, payload={"note": 60 + i, "vel": 90}, time=t)
                  for i, (t, d) in enumerate([(0, 400), (15, 900), (24, 333), (44, 250)])]
    q, rep = build_pattern_from_midi(_export(p))
    assert q._bpm == 100
    assert q._tempo_changes == p._tempo_changes
    assert rep.tempo_changes == 3
    assert [(e.time, e.dur) for e in q._tape[0] if e.etype == ETYPE_PATCH] == \
        [(0, 400), (15, 900), (24, 333), (44, 250)]
