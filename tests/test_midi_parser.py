#python3
"""
    File: tests/test_midi_parser.py
    Tests unitaires de midi_parser, en isolation (pas de dépendance
    rtmidi/wx) : decode_message sur des octets construits à la main,
    describe_note/describe_cc/describe_program.
    Date: Mon, 21/09/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import midi_parser as mp
from midi_parser import CVoice, MidiMessage, decode_message


# ---------------------------------------------------------------------------
# decode_message — Note On / Note Off
# ---------------------------------------------------------------------------

def test_decode_note_on():
    msg = decode_message([0x90, 60, 100])
    assert msg == MidiMessage(CVoice.NoteOn, 0, {"note": 60, "vel": 100})


def test_decode_note_on_channel():
    # 0x93 = Note On, canal 3 (0-indexé)
    msg = decode_message([0x93, 64, 90])
    assert msg.mtype   == CVoice.NoteOn
    assert msg.channel == 3
    assert msg.payload == {"note": 64, "vel": 90}


def test_decode_note_on_velocity_zero_not_reinterpreted():
    # Le parser est littéral : Note On vel=0 reste NoteOn, pas NoteOff.
    msg = decode_message([0x90, 60, 0])
    assert msg.mtype == CVoice.NoteOn
    assert msg.payload["vel"] == 0


def test_decode_note_off():
    msg = decode_message([0x80, 60, 64])
    assert msg == MidiMessage(CVoice.NoteOff, 0, {"note": 60, "vel": 64})


def test_decode_note_on_truncated_returns_none():
    assert decode_message([0x90, 60]) is None
    assert decode_message([0x90]) is None


# ---------------------------------------------------------------------------
# decode_message — Control Change
# ---------------------------------------------------------------------------

def test_decode_cc():
    msg = decode_message([0xB2, 1, 127])
    assert msg == MidiMessage(CVoice.ControllerChange, 2, {"cc_num": 1, "value": 127})


def test_decode_cc_truncated_returns_none():
    assert decode_message([0xB0, 1]) is None


# ---------------------------------------------------------------------------
# decode_message — Program Change
# ---------------------------------------------------------------------------

def test_decode_program_change():
    msg = decode_message([0xC9, 41])
    assert msg == MidiMessage(CVoice.ProgramChange, 9, {"program": 41})


def test_decode_program_change_only_two_bytes():
    # Program Change n'a qu'un seul octet de données (pas de 3e octet).
    msg = decode_message([0xC0, 0])
    assert msg == MidiMessage(CVoice.ProgramChange, 0, {"program": 0})


def test_decode_program_change_truncated_returns_none():
    assert decode_message([0xC0]) is None


# ---------------------------------------------------------------------------
# decode_message — Pitch Bend
# ---------------------------------------------------------------------------

def test_decode_pitch_bend_center():
    # LSB=0, MSB=64 -> (64<<7)|0 = 8192, centre -> bend=0
    msg = decode_message([0xE0, 0, 64])
    assert msg == MidiMessage(CVoice.PitchBend, 0, {"bend": 0})


def test_decode_pitch_bend_min_max():
    msg_min = decode_message([0xE0, 0, 0])
    assert msg_min.payload["bend"] == -8192
    msg_max = decode_message([0xE0, 127, 127])
    assert msg_max.payload["bend"] == 8191


def test_decode_pitch_bend_truncated_returns_none():
    assert decode_message([0xE0, 0]) is None


# ---------------------------------------------------------------------------
# decode_message — types non reconnus / entrées invalides
# ---------------------------------------------------------------------------

def test_decode_poly_aftertouch_returns_none():
    # Fondations CVoice posées mais décodage hors périmètre 2a-2i.
    assert decode_message([0xA0, 60, 10]) is None


def test_decode_channel_pressure_returns_none():
    assert decode_message([0xD0, 90]) is None


def test_decode_empty_returns_none():
    assert decode_message([]) is None
    assert decode_message(None) is None


def test_decode_accepts_bytes_object():
    msg = decode_message(bytes([0x90, 60, 100]))
    assert msg == MidiMessage(CVoice.NoteOn, 0, {"note": 60, "vel": 100})


# ---------------------------------------------------------------------------
# MidiMessage — égalité / repr
# ---------------------------------------------------------------------------

def test_midi_message_equality():
    a = MidiMessage(CVoice.NoteOn, 0, {"note": 60, "vel": 100})
    b = MidiMessage(CVoice.NoteOn, 0, {"note": 60, "vel": 100})
    c = MidiMessage(CVoice.NoteOn, 1, {"note": 60, "vel": 100})
    assert a == b
    assert a != c


def test_midi_message_payload_is_copied():
    payload = {"note": 60, "vel": 100}
    msg = MidiMessage(CVoice.NoteOn, 0, payload)
    payload["vel"] = 0
    assert msg.payload["vel"] == 100


def test_midi_message_repr_contains_fields():
    msg = MidiMessage(CVoice.NoteOn, 0, {"note": 60, "vel": 100})
    text = repr(msg)
    assert "0x90" in text
    assert "note" in text


# ---------------------------------------------------------------------------
# describe_note / describe_cc / describe_program
# ---------------------------------------------------------------------------

def test_describe_note():
    assert mp.describe_note(60) == "C4"


def test_describe_cc_known_and_unknown():
    assert mp.describe_cc(1) == "Modulation Wheel"
    assert mp.describe_cc(3) is None


def test_describe_program_melodic():
    assert mp.describe_program(0) == "Acoustic Grand Piano"
    assert mp.describe_program(40) == "Violin"


def test_describe_program_drum_kit():
    assert mp.describe_program(0, is_drum=True) == "Standard Kit"
    assert mp.describe_program(25, is_drum=True) == "TR-808 Kit"


def test_describe_program_drum_unnamed_returns_none():
    # Program number sans kit GM2 standard : pas de nom, pas l'entier brut.
    assert mp.describe_program(1, is_drum=True) is None


def test_describe_program_out_of_range_returns_none():
    assert mp.describe_program(-1) is None
    assert mp.describe_program(128) is None
