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


# ---------------------------------------------------------------------------
# Grille courante (étape 7d) — _grid_idx vit sur le player, pas sur Pattern
# (régression : une version précédente lisait/écrivait _parent._player._pattern._grid_idx)
# ---------------------------------------------------------------------------

class _FakeGridPattern:
    def __init__(self, num_steps=16, num_beats=4, bpm=100):
        self._num_steps = num_steps
        self._num_beats = num_beats
        self._bpm       = bpm


class _FakeGridPlayer:
    def __init__(self, grid_idx):
        self._pattern  = _FakeGridPattern()
        self._grid_idx = grid_idx


class _FakeGridParent:
    def __init__(self, grid_idx):
        self._player     = _FakeGridPlayer(grid_idx)
        self.undo_titles = []

    def _add_undo(self, title):
        self.undo_titles.append(title)

    def _pop_last_undo(self):
        self.undo_titles.pop()


class _FakeGridWindow:
    """Objet minimal exposant les méthodes de grille de MidiEditorWindow."""
    _set_status       = mew.MidiEditorWindow._set_status
    _add_undo         = mew.MidiEditorWindow._add_undo
    _grid_value_steps = mew.MidiEditorWindow._grid_value_steps
    _grid_value_ms    = mew.MidiEditorWindow._grid_value_ms
    _show_grid_value  = mew.MidiEditorWindow._show_grid_value
    _change_grid_idx  = mew.MidiEditorWindow._change_grid_idx
    _SNAP_NOTE_NAMES  = mew.MidiEditorWindow._SNAP_NOTE_NAMES

    def __init__(self, grid_idx):
        self._parent      = _FakeGridParent(grid_idx)
        self._status_ctrl = _FakeStatusCtrl()


def test_grid_value_steps_reads_player_grid_idx_not_pattern():
    from pattern import Pattern
    win = _FakeGridWindow(grid_idx=10)   # "1/16"
    assert win._grid_value_steps() == Pattern.grid_step_size(10, 16)


def test_show_grid_value_reports_current_grid_and_note_name():
    win = _FakeGridWindow(grid_idx=10)   # "1/16" → snap 16 → Double croche
    win._show_grid_value()
    assert win._status_ctrl.last == "Grille: 1/16, Double croche"


def test_change_grid_idx_updates_player_not_pattern():
    win = _FakeGridWindow(grid_idx=10)
    win._change_grid_idx(1)
    assert win._parent._player._grid_idx == 11
    assert not hasattr(win._parent._player._pattern, "_grid_idx")
    assert win._parent.undo_titles == ["Grille : 1/16 → 1/24"]


def test_change_grid_idx_clamped_at_upper_bound():
    from pattern import Pattern
    win = _FakeGridWindow(grid_idx=len(Pattern.GRID_RESOLUTIONS) - 1)
    win._change_grid_idx(1)
    assert win._status_ctrl.last == "Grille: déjà à la borne"
    assert win._parent.undo_titles == []


def test_change_grid_idx_clamped_at_lower_bound():
    win = _FakeGridWindow(grid_idx=0)
    win._change_grid_idx(-1)
    assert win._status_ctrl.last == "Grille: déjà à la borne"
    assert win._parent.undo_titles == []
