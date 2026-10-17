#python3
"""
    File: tests/test_midi_handler_window.py
    Tests — statut MIDI live de l'éditeur MIDI (Phase 6 étape 10g).
    format_midi_status (pur) + MidiHandler._notify_editor_midi (glue vers
    MidiEditorWindow._set_midi_status quand la fenêtre est ouverte).
    Date: Wed, 16/09/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import ui.midi_handler_window as mh
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


def test_format_program_change_melodic():
    msg = mh.format_midi_status("program_change", 0, program=0)
    assert msg == "Program Change, Chan: 1, Program: 0 (Acoustic Grand Piano)"


def test_format_program_change_melodic_channel_not_10():
    # Canal != 10 (0-indexé != 9) : toujours interprété comme patch mélodique GM1.
    msg = mh.format_midi_status("program_change", 8, program=25)
    assert msg == "Program Change, Chan: 9, Program: 25 (Acoustic Guitar (steel))"


def test_format_program_change_drum_kit_named():
    # Canal 10 (0-indexé 9) : traité comme percussion GM, table des kits GM2.
    msg = mh.format_midi_status("program_change", 9, program=25)
    assert msg == "Program Change, Chan: 10, Program: 25 (TR-808 Kit)"


def test_format_program_change_drum_kit_unnamed_shows_number_only():
    msg = mh.format_midi_status("program_change", 9, program=1)
    assert msg == "Program Change, Chan: 10, Program: 1"


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


class _FakePlayer:
    """Pas de record_mod ici volontairement (Phase 7 étape 5h) : si on_cc
    l'appelait encore pour CC#1, ce serait un AttributeError — garde-fou de
    non-régression pour test_on_cc_cc1_does_not_call_record_mod."""
    def __init__(self):
        self.recording  = False
        self._cur_track = 0
        self.recorded_programs = []   # [(program, channel), ...] via record_program_change
        self.recorded_ccs      = []   # [(cc_num, value, channel), ...] via record_cc

    def record_program_change(self, program, channel=0):
        self.recorded_programs.append((program, channel))

    def record_cc(self, cc_num, value, channel=0):
        self.recorded_ccs.append((cc_num, value, channel))


class _FakeRouter:
    def __init__(self):
        self.assigned_slot = None   # (track, slot_idx) du dernier assign_slot()

    def assign_slot(self, track, slot_idx):
        self.assigned_slot = (track, slot_idx)

    def synth_ready(self):
        return False


class _FakeWinNoEditor:
    _midi_editor_window = None

    def __init__(self):
        self._player = _FakePlayer()
        self._router = _FakeRouter()

    def _show_status(self, msg):
        pass


class _FakeWinWithEditor:
    def __init__(self):
        self._midi_editor_window = _FakeMidiStatusCtrl()
        self._player = _FakePlayer()
        self._router = _FakeRouter()

    def _show_status(self, msg):
        pass


def test_notify_editor_midi_noop_when_editor_closed():
    handler = mh.MidiHandler(_FakeWinNoEditor())
    handler._notify_editor_midi("note_on", 0, note=60, velocity=100)   # ne doit pas lever


def test_notify_editor_midi_updates_open_editor():
    win     = _FakeWinWithEditor()
    handler = mh.MidiHandler(win)
    handler._notify_editor_midi("cc", 0, cc_num=1, value=64)
    assert win._midi_editor_window.last == "CC, Chan: 1, Num: 1 (Modulation Wheel), Val: 64"


# ---------------------------------------------------------------------------
# MidiHandler.on_program_change — statut live minimum (Phase 7 étape 2h)
# ---------------------------------------------------------------------------

def test_on_program_change_updates_open_editor():
    win     = _FakeWinWithEditor()
    handler = mh.MidiHandler(win)
    handler.on_program_change(41, 0)
    assert win._midi_editor_window.last == "Program Change, Chan: 1, Program: 41 (Viola)"


def test_on_program_change_noop_when_editor_closed():
    handler = mh.MidiHandler(_FakeWinNoEditor())
    handler.on_program_change(41, 0)   # ne doit pas lever


# ---------------------------------------------------------------------------
# MidiHandler.on_program_change — effet live assign_slot (Phase 7 étape 4h,
# décision révisée sur 2a : voir docs/DESIGN.md § Phase 7 étape 4a)
# ---------------------------------------------------------------------------

def test_on_program_change_assigns_rack_slot_on_current_track():
    win     = _FakeWinNoEditor()
    win._player._cur_track = 2
    handler = mh.MidiHandler(win)
    handler.on_program_change(5, 0)
    assert win._router.assigned_slot == (2, 5)


def test_on_program_change_assigns_slot_modulo_16():
    win     = _FakeWinNoEditor()
    handler = mh.MidiHandler(win)
    handler.on_program_change(127, 0)   # 127 % 16 = 15
    assert win._router.assigned_slot == (0, 15)


def test_on_program_change_captures_when_recording():
    win = _FakeWinNoEditor()
    win._player.recording = True
    handler = mh.MidiHandler(win)
    handler.on_program_change(41, 3)
    assert win._player.recorded_programs == [(41, 3)]


def test_on_program_change_no_capture_when_not_recording():
    win = _FakeWinNoEditor()
    win._player.recording = False
    handler = mh.MidiHandler(win)
    handler.on_program_change(41, 3)
    assert win._player.recorded_programs == []


# ---------------------------------------------------------------------------
# MidiHandler.on_cc — CC#1 n'a plus qu'une seule capture (Phase 7 étape 5h)
# ---------------------------------------------------------------------------

def test_on_cc_cc1_does_not_call_record_mod():
    """record_mod a disparu en 5h — _FakePlayer ne le définit pas exprès :
    si on_cc l'appelait encore, cet appel lèverait AttributeError."""
    win = _FakeWinNoEditor()
    win._player.recording = True
    handler = mh.MidiHandler(win)
    handler.on_cc(1, 90, 0)   # ne doit pas lever


def test_on_cc_cc1_captured_once_via_record_cc():
    win = _FakeWinNoEditor()
    win._player.recording = True
    handler = mh.MidiHandler(win)
    handler.on_cc(1, 90, 0)
    assert win._player.recorded_ccs == [(1, 90, 0)]
