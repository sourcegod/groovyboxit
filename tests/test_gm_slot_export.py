#python3
"""
    File: tests/test_gm_slot_export.py
    Tests de la Phase 7 étape 12g1 (docs/DESIGN.md § 12a2 D4, D5) :
    transposition et gain GM d'un slot (InstrumentSlot.gm_transpose /
    gm_gain_db et leurs setters, config remplacée, sérialisation du Rack),
    et leur effet à l'export (notes PATCH et GRID d'un synthé transposées,
    CC7 atténués par apply_gain_db).
    Date: Sat, 24/10/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from pattern import (Pattern, TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH,
                     ETYPE_CC)
from rack import Rack, InstrumentSlot, InstrumentType
from midi.midi_export import build_pattern_midi, apply_gain_db, volume_to_cc7

SYNTH_NOTES = [60 + i for i in range(16)]


def _slot(kind, config=None):
    s = InstrumentSlot(2)
    s.type, s.name, s.config = kind, "Slot", dict(config or {})
    return s


# ---------------------------------------------------------------------------
# InstrumentSlot.gm_transpose / set_gm_transpose
# ---------------------------------------------------------------------------

def test_transpose_default_zero():
    assert _slot(InstrumentType.SYNTH).gm_transpose() == 0
    print("  gm_transpose : 0 par défaut : OK")


def test_transpose_read_from_config():
    assert _slot(InstrumentType.SYNTH, {"gm_transpose": 12}).gm_transpose() == 12
    assert _slot(InstrumentType.SYNTH, {"gm_transpose": -7}).gm_transpose() == -7
    print("  gm_transpose : lu dans config : OK")


@pytest.mark.parametrize("value, expected", [(30, 24), (-99, -24), (24, 24), (-24, -24)])
def test_transpose_config_clamped(value, expected):
    assert _slot(InstrumentType.SYNTH, {"gm_transpose": value}).gm_transpose() == expected


@pytest.mark.parametrize("bad", ["12", 12.0, True, None, [12]])
def test_transpose_non_int_config_is_zero(bad):
    assert _slot(InstrumentType.SYNTH, {"gm_transpose": bad}).gm_transpose() == 0


@pytest.mark.parametrize("kind", [InstrumentType.KIT, InstrumentType.LOOP, None])
def test_transpose_only_for_synth(kind):
    assert _slot(kind, {"gm_transpose": 12}).gm_transpose() == 0


def test_set_transpose_clamps_and_replaces_config():
    s = _slot(InstrumentType.SYNTH, {"patch": "o.json", "gm_program": 16})
    before = s.config
    s.set_gm_transpose(12)
    assert s.config == {"patch": "o.json", "gm_program": 16, "gm_transpose": 12}
    assert s.config is not before and "gm_transpose" not in before
    s.set_gm_transpose(40)
    assert s.gm_transpose() == 24
    s.set_gm_transpose(-40)
    assert s.gm_transpose() == -24
    print("  set_gm_transpose : borné, config remplacée (instantanés d'Undo intacts) : OK")


# ---------------------------------------------------------------------------
# InstrumentSlot.gm_gain_db / set_gm_gain_db
# ---------------------------------------------------------------------------

def test_gain_default_zero():
    assert _slot(InstrumentType.SYNTH).gm_gain_db() == 0
    print("  gm_gain_db : 0 par défaut : OK")


@pytest.mark.parametrize("kind", [InstrumentType.SYNTH, InstrumentType.KIT, InstrumentType.AUDIO])
def test_gain_for_any_non_empty_slot(kind):
    assert _slot(kind, {"gm_gain_db": -14}).gm_gain_db() == -14


def test_gain_zero_for_empty_slot():
    assert _slot(None, {"gm_gain_db": -14}).gm_gain_db() == 0
    print("  gm_gain_db : 0 pour un slot vide : OK")


@pytest.mark.parametrize("value, expected", [(5, 0), (-50, -40), (0, 0), (-40, -40)])
def test_gain_config_clamped(value, expected):
    assert _slot(InstrumentType.SYNTH, {"gm_gain_db": value}).gm_gain_db() == expected


@pytest.mark.parametrize("bad", ["-6", -6.5, False, None])
def test_gain_non_int_config_is_zero(bad):
    assert _slot(InstrumentType.SYNTH, {"gm_gain_db": bad}).gm_gain_db() == 0


def test_set_gain_clamps_and_replaces_config():
    s = _slot(InstrumentType.KIT, {"kit": "k.json"})
    before = s.config
    s.set_gm_gain_db(-11)
    assert s.config == {"kit": "k.json", "gm_gain_db": -11} and s.config is not before
    s.set_gm_gain_db(6)
    assert s.gm_gain_db() == 0
    s.set_gm_gain_db(-100)
    assert s.gm_gain_db() == -40
    print("  set_gm_gain_db : borné, config remplacée : OK")


def test_settings_survive_rack_serialization():
    rack = Rack()
    rack.set_slot(3, InstrumentType.SYNTH, "DrawbarOrgan", {"patch": "o.json"})
    rack.get_slot(3).set_gm_transpose(12)
    rack.get_slot(3).set_gm_gain_db(-14)
    copy = Rack()
    copy.from_dict(rack.to_dict())
    assert (copy.get_slot(3).gm_transpose(), copy.get_slot(3).gm_gain_db()) == (12, -14)
    print("  transposition et gain : conservés par to_dict / from_dict du Rack : OK")


# ---------------------------------------------------------------------------
# apply_gain_db
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cc7, db, expected", [
    (127, 0, 127), (127, -14, 57), (100, -14, 45), (127, -40, 13),
    (127, -6, 90), (0, -14, 0), (64, -20, 20),
])
def test_apply_gain_db(cc7, db, expected):
    assert apply_gain_db(cc7, db) == expected


def test_apply_gain_db_is_db_on_a_gm_player():
    # Lecteur GM : 40·log10(CC7/127) dB → l'atténuation vaut db, à l'arrondi près
    import math
    for db in (-3, -6, -11, -14, -20):
        cc = apply_gain_db(127, db)
        assert 40 * math.log10(cc / 127) == pytest.approx(db, abs=0.3), db
    print("  apply_gain_db : -N dB dans un lecteur GM (courbe 40·log10) : OK")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _pattern():
    p = Pattern()
    p.new_pattern(1, 16)
    return p


def _add(p, track, etype, time_val, payload, dur=0):
    p._tape[track].append(TapeEvent(etype, dur=dur, payload=payload, time=time_val))


def _build(p, *, is_synth=None, transposes=None, gains=None, volumes=None):
    n = p._num_tracks
    return build_pattern_midi(
        p, name="P", bpm=120, track_channels=[Pattern.default_channel(t) for t in range(n)],
        track_is_synth=is_synth if is_synth is not None else [True] * n,
        track_names=[""] * n, kit_pad_notes=list(range(36, 52)),
        synth_grid_notes=SYNTH_NOTES, voice_durations=[500] * 16,
        track_volumes=volumes, track_transposes=transposes, track_gain_db=gains)


def _per_track(value, track=0, n=16):
    out = [0] * n
    out[track] = value
    return out


def _notes(track):
    return [m.note for m in track if m.type == "note_on"]


def _cc7(track):
    return [m.value for m in track if m.type == "control_change" and m.control == 7]


def test_patch_and_synth_grid_transposed():
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 67, "vel": 90}, dur=100)
    _add(p, 0, ETYPE_GRID, 4.0, {"pad": 2, "vel": 100})
    mid = _build(p, transposes=_per_track(12))
    assert _notes(mid.tracks[1]) == [79, SYNTH_NOTES[2] + 12]
    print("  synthé : PATCH et GRID transposés : OK")


def test_negative_transpose():
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 60, "vel": 90}, dur=100)
    assert _notes(_build(p, transposes=_per_track(-24)).tracks[1]) == [36]
    print("  transposition négative : OK")


def test_kit_track_grid_and_kit_events_not_transposed():
    p = _pattern()
    _add(p, 0, ETYPE_GRID, 0.0, {"pad": 2, "vel": 100})
    _add(p, 0, ETYPE_KIT, 4.0, {"note": 49, "vel": 100})
    _add(p, 1, ETYPE_KIT, 0.0, {"note": 38, "vel": 100})        # KIT sur piste synthé
    is_synth = [False, True] + [True] * 14
    mid = _build(p, is_synth=is_synth, transposes=[12] * 16)
    assert _notes(mid.tracks[1]) == [38, 49]
    assert _notes(mid.tracks[2]) == [38]
    print("  piste kit et notes KIT : jamais transposées : OK")


def test_transpose_clamped_to_midi_range():
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 120, "vel": 90}, dur=100)
    _add(p, 1, ETYPE_PATCH, 0.0, {"note": 5, "vel": 90}, dur=100)
    mid = _build(p, transposes=[24, -24] + [0] * 14)
    assert _notes(mid.tracks[1]) == [127] and _notes(mid.tracks[2]) == [0]
    print("  transposition : note bornée à 0..127 : OK")


def test_transpose_is_per_track():
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 60, "vel": 90}, dur=100)
    _add(p, 1, ETYPE_PATCH, 0.0, {"note": 60, "vel": 90}, dur=100)
    mid = _build(p, transposes=_per_track(12, track=1))
    assert _notes(mid.tracks[1]) == [60] and _notes(mid.tracks[2]) == [72]
    print("  transposition : propre à chaque piste : OK")


def test_gain_on_tick_0_volume():
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 60, "vel": 90}, dur=100)
    mid = _build(p, volumes=[100] * 16, gains=_per_track(-14))
    assert _cc7(mid.tracks[1]) == [57]
    mid = _build(p, volumes=[45] * 16, gains=_per_track(-14))
    assert _cc7(mid.tracks[1]) == [apply_gain_db(volume_to_cc7(45), -14)]
    print("  gain : CC7 du tick 0 atténué : OK")


def test_gain_on_captured_cc7_only():
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 60, "vel": 90}, dur=100)
    _add(p, 0, ETYPE_CC, 4.0, {"cc_num": 7, "value": 100})
    _add(p, 0, ETYPE_CC, 5.0, {"cc_num": 1, "value": 100})
    _add(p, 0, ETYPE_CC, 6.0, {"cc_num": 10, "value": 100})
    mid = _build(p, gains=_per_track(-14))
    ccs = [(m.control, m.value) for m in mid.tracks[1] if m.type == "control_change"]
    assert ccs == [(91, 0), (93, 0), (7, 45), (1, 100), (10, 100)]
    print("  gain : CC7 capturé atténué, autres CC intacts : OK")


def test_gain_zero_or_none_leaves_cc7():
    p = _pattern()
    _add(p, 0, ETYPE_CC, 4.0, {"cc_num": 7, "value": 100})
    assert _cc7(_build(p, volumes=[100] * 16, gains=None).tracks[1]) == [127, 100]
    assert _cc7(_build(p, volumes=[100] * 16, gains=[0] * 16).tracks[1]) == [127, 100]
    print("  gain None ou 0 : CC7 inchangés : OK")


def test_none_transposes_leaves_notes():
    p = _pattern()
    _add(p, 0, ETYPE_PATCH, 0.0, {"note": 60, "vel": 90}, dur=100)
    assert _notes(_build(p, transposes=None).tracks[1]) == [60]
    print("  track_transposes=None : notes inchangées : OK")
