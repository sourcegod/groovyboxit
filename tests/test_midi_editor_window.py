#python3
"""
    File: tests/test_midi_editor_window.py
    Tests unitaires — MidiEditorWindow._toggle_track_solo/_toggle_track_mute
    (Phase 6 étape 7c). Utilise un objet factice (duck-typing) au lieu d'un
    vrai wx.Frame : ces méthodes sont de la pure orchestration (get_effective_tracks
    + TrackRouter.toggle_* + refresh + status), sans logique wx propre à tester.
    Date: Fri, 17/07/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import ui.midi_editor_window as mew
from track_editor import TrackEditor


class _FakeStatusCtrl:
    def __init__(self):
        self.last = None

    def SetString(self, idx, msg):
        self.last = msg


class _FakeRouter:
    def __init__(self, num_tracks=8):
        self._mutes = [False] * num_tracks
        self._solos = [False] * num_tracks

    def toggle_track_mute(self, track_idx):
        self._mutes[track_idx] = not self._mutes[track_idx]
        return self._mutes[track_idx]

    def toggle_track_solo(self, track_idx):
        self._solos[track_idx] = not self._solos[track_idx]
        return self._solos[track_idx]


class _FakePlayer:
    def __init__(self, cur_track=0):
        self._cur_track = cur_track


class _FakeParent:
    def __init__(self):
        self._track_editor = TrackEditor()
        self._player       = _FakePlayer()
        self._router       = _FakeRouter()
        self.refresh_calls = 0

    def _refresh_track_list(self):
        self.refresh_calls += 1


class _FakeMidiEditorWindow:
    """Objet minimal exposant les vraies méthodes de MidiEditorWindow."""
    _set_status          = mew.MidiEditorWindow._set_status
    _toggle_track_solo   = mew.MidiEditorWindow._toggle_track_solo
    _toggle_track_mute   = mew.MidiEditorWindow._toggle_track_mute

    def __init__(self):
        self._parent      = _FakeParent()
        self._status_ctrl = _FakeStatusCtrl()


# ---------------------------------------------------------------------------
# Solo — piste courante (pas de multi-sélection)
# ---------------------------------------------------------------------------

def test_toggle_solo_current_track_on():
    win = _FakeMidiEditorWindow()
    win._parent._player._cur_track = 2
    win._toggle_track_solo()
    assert win._parent._router._solos == [False, False, True, False, False, False, False, False]
    assert win._status_ctrl.last == "Piste 3: Solo On"
    assert win._parent.refresh_calls == 1


def test_toggle_solo_current_track_off_on_second_call():
    win = _FakeMidiEditorWindow()
    win._toggle_track_solo()
    win._toggle_track_solo()
    assert win._parent._router._solos[0] is False
    assert win._status_ctrl.last == "Piste 1: Solo Off"


# ---------------------------------------------------------------------------
# Solo — pistes sélectionnées (multi-sélection active)
# ---------------------------------------------------------------------------

def test_toggle_solo_multi_selection():
    win = _FakeMidiEditorWindow()
    te = win._parent._track_editor
    te.select_one(0)
    te.toggle_track(2)   # sélection = {0, 2}
    win._toggle_track_solo()
    assert win._parent._router._solos[0] is True
    assert win._parent._router._solos[2] is True
    assert win._parent._router._solos[1] is False
    assert win._status_ctrl.last == "Pistes 1, 3: Solo basculé"


# ---------------------------------------------------------------------------
# Mute — piste courante et multi-sélection
# ---------------------------------------------------------------------------

def test_toggle_mute_current_track_on():
    win = _FakeMidiEditorWindow()
    win._parent._player._cur_track = 1
    win._toggle_track_mute()
    assert win._parent._router._mutes[1] is True
    assert win._status_ctrl.last == "Piste 2: Mute On"
    assert win._parent.refresh_calls == 1


def test_toggle_mute_multi_selection():
    win = _FakeMidiEditorWindow()
    te = win._parent._track_editor
    te.select_one(1)
    te.toggle_track(3)   # sélection = {1, 3}
    win._toggle_track_mute()
    assert win._parent._router._mutes[1] is True
    assert win._parent._router._mutes[3] is True
    assert win._status_ctrl.last == "Pistes 2, 4: Mute basculé"


def test_toggle_mute_and_solo_are_independent():
    win = _FakeMidiEditorWindow()
    win._toggle_track_mute()
    win._toggle_track_solo()
    assert win._parent._router._mutes[0] is True
    assert win._parent._router._solos[0] is True
