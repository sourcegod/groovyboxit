#python3
"""
    File: tests/test_midi_handler.py
    Tests — statut MIDI live de l'éditeur MIDI (Phase 6 étape 10g).
    format_midi_status (pur) + MidiHandler._notify_editor_midi (glue vers
    MidiEditorWindow._set_midi_status quand la fenêtre est ouverte).
    Date: Wed, 16/09/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import ui.midi_handler as mh
from synth_engine import midi_to_note_name


# ---------------------------------------------------------------------------
# format_midi_status — fonction pure
# ---------------------------------------------------------------------------

def test_format_note_on():
    msg = mh.format_midi_status("note_on", 9, note=48, velocity=100)
    assert msg == f"Note: On, Chan: 10, Pitch: 48 ({midi_to_note_name(48)}), Vel: 100"


def test_format_note_off():
    msg = mh.format_midi_status("note_off", 0, note=60)
    assert msg == f"Note: Off, Chan: 1, Pitch: 60 ({midi_to_note_name(60)})"


def test_format_cc_known_number_shows_name():
    msg = mh.format_midi_status("cc", 0, cc_num=64, value=126)
    assert msg == "CC, Chan: 1, Num: 64 (Sustain Pedal), Val: 126"


def test_format_cc_unknown_number_has_no_name():
    msg = mh.format_midi_status("cc", 0, cc_num=3, value=10)
    assert msg == "CC, Chan: 1, Num: 3, Val: 10"


def test_format_pitch_bend_positive():
    msg = mh.format_midi_status("pitch_bend", 0, bend=500)
    assert msg == "Pitch Bend, Chan: 1, Val: +500"


def test_format_pitch_bend_negative():
    msg = mh.format_midi_status("pitch_bend", 0, bend=-200)
    assert msg == "Pitch Bend, Chan: 1, Val: -200"


def test_format_channel_is_1based():
    assert "Chan: 16" in mh.format_midi_status("cc", 15, cc_num=1, value=0)


def test_format_unknown_kind_returns_empty():
    assert mh.format_midi_status("unknown", 0) == ""


def test_cc_names_cover_app_handled_controllers():
    for cc_num, expected in (
        (1, "Modulation Wheel"), (7, "Channel Volume"), (10, "Pan"),
        (64, "Sustain Pedal"), (120, "All Sound Off"),
        (121, "Reset All Controllers"), (123, "All Notes Off"),
    ):
        assert mh.CC_NAMES[cc_num] == expected


# ---------------------------------------------------------------------------
# MidiHandler._notify_editor_midi — glue vers MidiEditorWindow._set_midi_status
# ---------------------------------------------------------------------------

class _FakeMidiStatusCtrl:
    def __init__(self):
        self.last = None

    def _set_midi_status(self, msg):
        self.last = msg


class _FakeWinNoEditor:
    _midi_editor_window = None


class _FakeWinWithEditor:
    def __init__(self):
        self._midi_editor_window = _FakeMidiStatusCtrl()


def test_notify_editor_midi_noop_when_editor_closed():
    handler = mh.MidiHandler(_FakeWinNoEditor())
    handler._notify_editor_midi("note_on", 0, note=60, velocity=100)   # ne doit pas lever


def test_notify_editor_midi_updates_open_editor():
    win     = _FakeWinWithEditor()
    handler = mh.MidiHandler(win)
    handler._notify_editor_midi("cc", 0, cc_num=1, value=64)
    assert win._midi_editor_window.last == "CC, Chan: 1, Num: 1 (Modulation Wheel), Val: 64"
