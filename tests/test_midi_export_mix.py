#python3
"""
    File: tests/test_midi_export_mix.py
    Tests de la Phase 7 étape 10h5 : volume et pan de piste exportés (CC#7
    et CC#10 au tick 0 de chaque piste, après le programme, sur le canal de
    la piste ; conversions inverses de TrackRouter.on_cc_tape) et notes
    PATCH omises sur une piste sans slot SYNTH (muettes au rejeu).
    Date: Wed, 21/10/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import Pattern, TapeEvent, ETYPE_PATCH, ETYPE_CC, ETYPE_KIT, ETYPE_GRID
from midi.midi_export import build_pattern_midi, volume_to_cc7, pan_to_cc10


# ---------------------------------------------------------------------------
# Conversions
# ---------------------------------------------------------------------------

def _router_volume(value):   # TrackRouter.on_cc_tape, CC#7
    return round(value * 100 / 127)

def _router_pan(value):      # TrackRouter.on_cc_tape, CC#10
    return round((value - 64) * 100 / 63)

def test_volume_to_cc7_bounds_and_example():
    assert (volume_to_cc7(0), volume_to_cc7(45), volume_to_cc7(100)) == (0, 57, 127)
    assert volume_to_cc7(150) == 127 and volume_to_cc7(-3) == 0
    print("  volume → CC7 : 0, 45 → 57, 100 → 127, borné : OK")

def test_volume_round_trip_is_exact():
    assert all(_router_volume(volume_to_cc7(v)) == v for v in range(101))
    print("  volume : aller-retour export → rejeu exact sur 0..100 : OK")

def test_pan_to_cc10_bounds():
    assert (pan_to_cc10(-100), pan_to_cc10(0), pan_to_cc10(100)) == (1, 64, 127)
    assert pan_to_cc10(-500) == 1 and pan_to_cc10(500) == 127
    print("  pan → CC10 : -100 → 1, 0 → 64, +100 → 127, borné : OK")

def test_pan_round_trip_within_one():
    assert all(abs(_router_pan(pan_to_cc10(p)) - p) <= 1 for p in range(-100, 101))
    assert all(_router_pan(pan_to_cc10(p)) == p for p in (-100, 0, 100))   # 50 → CC 96 → 51
    print("  pan : aller-retour à ±1 près (127 valeurs pour 201 positions) : OK")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _pattern():
    p = Pattern()
    p._tape[0].append(TapeEvent(ETYPE_PATCH, dur=200, payload={"note": 60, "vel": 90}, time=0.0))
    p._tape[9].append(TapeEvent(ETYPE_PATCH, dur=200, payload={"note": 38, "vel": 90}, time=4.0))
    return p

def _export(p, programs=None, volumes=None, pans=None, channels=None):
    n = p._num_tracks
    return build_pattern_midi(
        p, name="P", bpm=120,
        track_channels=channels or [Pattern.default_channel(t) for t in range(n)],
        track_is_synth=[True] * n, track_names=[""] * n, kit_pad_notes=list(range(36, 52)),
        synth_grid_notes=list(range(60, 76)), voice_durations=[500] * 16,
        track_programs=programs, track_volumes=volumes, track_pans=pans)

def _head(smf):
    """Messages au tick 0 avant la première note, sans le track_name."""
    out = []
    for m in smf[1:]:
        if m.time or m.type == "note_on":
            break
        out.append(m)
    return out

def test_volume_and_pan_at_tick_0_after_program():
    volumes, pans = [100] * 16, [0] * 16
    volumes[0], pans[0] = 45, -100
    head = _head(_export(_pattern(), [24] + [None] * 15, volumes, pans).tracks[1])
    assert [(m.type, getattr(m, "control", None)) for m in head] == \
        [("program_change", None), ("control_change", 7), ("control_change", 10)]
    assert (head[1].value, head[2].value) == (57, 1)
    assert all(m.channel == 0 for m in head)
    print("  piste : programme, CC7, CC10 au tick 0, sur son canal : OK")

def test_volume_and_pan_written_even_without_program():
    head = _head(_export(_pattern(), None, [80] * 16, [30] * 16).tracks[2])
    assert [(m.control, m.value, m.channel) for m in head] == [(7, 102, 9), (10, 83, 9)]
    print("  piste sans programme (canal 10) : CC7 et CC10 quand même : OK")

def test_none_writes_no_mix_cc():
    mid = _export(_pattern())
    assert not any(m.type == "control_change" for tr in mid.tracks for m in tr)
    head = _head(_export(_pattern(), volumes=[90] * 16).tracks[1])
    assert [m.control for m in head] == [7]
    print("  track_volumes / track_pans None : rien d'écrit pour eux : OK")

def test_captured_cc7_at_tick_0_comes_after_and_wins():
    p = _pattern()
    p._tape[0].insert(0, TapeEvent(ETYPE_CC, payload={"cc_num": 7, "value": 20}, time=0.0))
    head = _head(_export(p, volumes=[100] * 16, pans=[0] * 16).tracks[1])
    assert [(m.control, m.value) for m in head] == [(7, 127), (10, 64), (7, 20)]
    print("  CC7 capturé au tick 0 : écrit après le volume de piste, l'emporte : OK")

def test_shared_channel_each_track_writes_its_own():
    p = _pattern()
    p._tape[1].append(TapeEvent(ETYPE_PATCH, dur=200, payload={"note": 40, "vel": 90}, time=0.0))
    volumes = [100] * 16
    volumes[0], volumes[1] = 30, 70
    mid = _export(p, volumes=volumes, channels=[0] * 16)
    vals = [[(m.channel, m.value) for m in _head(tr)] for tr in mid.tracks[1:3]]
    assert vals == [[(0, 38)], [(0, 89)]]
    print("  canal partagé : chaque piste écrit son volume (le lecteur garde le dernier) : OK")


# ---------------------------------------------------------------------------
# Notes PATCH sur une piste sans slot SYNTH : omises (muettes au rejeu)
# ---------------------------------------------------------------------------

def _notes(smf):
    return [m.note for m in smf if m.type == "note_on"]

def test_patch_notes_skipped_on_non_synth_track():
    p = Pattern()
    p._tape[1].append(TapeEvent(ETYPE_GRID, payload={"pad": 0, "vel": 100}, time=0.0))
    p._tape[1].append(TapeEvent(ETYPE_KIT, payload={"note": 49, "vel": 100}, time=2.0))
    p._tape[1].append(TapeEvent(ETYPE_PATCH, dur=200, payload={"note": 55, "vel": 90}, time=4.0))
    n = p._num_tracks
    is_synth = [True] * n
    is_synth[1] = False
    mid = build_pattern_midi(
        p, name="P", bpm=120, track_channels=[9] * n, track_is_synth=is_synth,
        track_names=[""] * n, kit_pad_notes=list(range(36, 52)), synth_grid_notes=list(range(60, 76)),
        voice_durations=[500] * 16)
    assert _notes(mid.tracks[1]) == [36, 49]      # GRID du kit et KIT gardés
    print("  piste kit : notes PATCH omises, GRID et KIT gardés : OK")

def test_patch_notes_kept_on_synth_track():
    p = Pattern()
    p._tape[0].append(TapeEvent(ETYPE_PATCH, dur=200, payload={"note": 55, "vel": 90}, time=0.0))
    n = p._num_tracks
    mid = build_pattern_midi(
        p, name="P", bpm=120, track_channels=[0] * n, track_is_synth=[True] * n,
        track_names=[""] * n, kit_pad_notes=list(range(36, 52)), synth_grid_notes=list(range(60, 76)),
        voice_durations=[500] * 16)
    assert _notes(mid.tracks[1]) == [55]
    print("  piste synthé : notes PATCH exportées : OK")

def test_track_with_only_patch_on_kit_still_gets_its_smf_track():
    """La piste reste non vide dans _tape : sa piste SMF existe, sans note."""
    p = Pattern()
    p._tape[3].append(TapeEvent(ETYPE_PATCH, dur=200, payload={"note": 55, "vel": 90}, time=0.0))
    n = p._num_tracks
    mid = build_pattern_midi(
        p, name="P", bpm=120, track_channels=[9] * n, track_is_synth=[False] * n,
        track_names=[""] * n, kit_pad_notes=list(range(36, 52)), synth_grid_notes=list(range(60, 76)),
        voice_durations=[500] * 16)
    assert len(mid.tracks) == 2 and _notes(mid.tracks[1]) == []
    print("  piste avec seulement des PATCH sur un kit : piste SMF sans note : OK")
