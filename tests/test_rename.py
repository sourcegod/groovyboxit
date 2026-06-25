#python3
"""
    File: test_rename.py
    Tests du renommage par F2 : piste, pattern, song.
    Date: Thu, 25/06/2026
    Author: Coolbrother
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wx
from unittest.mock import patch, MagicMock

from pattern import Pattern
from song import Song
from ui.mw_tracks   import TrackMixin
from ui.mw_patterns import PatternMixin
from ui.song_window import SongWindow


# ──────────────────────────────────────────────────────────────────────────────
# Helpers communs
# ──────────────────────────────────────────────────────────────────────────────

def _fake_dialog(return_code, value=""):
    """Crée une classe factice pour wx.TextEntryDialog."""
    class FakeDlg:
        def __init__(self, *a, **kw): pass
        def ShowModal(self):   return return_code
        def GetValue(self):    return value
        def Destroy(self):     pass
    return FakeDlg


# ──────────────────────────────────────────────────────────────────────────────
# Fake objets pour TrackMixin._rename_track
# ──────────────────────────────────────────────────────────────────────────────

class FakeVoiceManager:
    def __init__(self):
        self._names = [""] * 8
    def get_name(self, idx): return self._names[idx]
    def set_name(self, idx, name): self._names[idx] = name


class FakePlayer:
    def __init__(self):
        self._cur_track  = 0
        self.voice_manager = FakeVoiceManager()


class FakeTrackWindow(TrackMixin):
    """Fenêtre minimale pour tester TrackMixin._rename_track."""
    def __init__(self):
        self._player          = FakePlayer()
        self._cur_pattern_idx = 0
        self._pattern_list    = [Pattern() for _ in range(4)]
        self.calls            = []

    def _add_undo(self, title):       self.calls.append(('_add_undo', title))
    def _pop_last_undo(self):         self.calls.append('_pop_last_undo')
    def _refresh_track_list(self):    self.calls.append('_refresh_track_list')
    def _show_status(self, msg):      self.calls.append(('_show_status', msg))


# ──────────────────────────────────────────────────────────────────────────────
# Tests — _rename_track
# ──────────────────────────────────────────────────────────────────────────────

def test_rename_track_ok():
    win = FakeTrackWindow()
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_OK, "Melody")):
        win._rename_track()
    assert win._player.voice_manager.get_name(0) == "Melody"
    assert win._pattern_list[0]._voices[0]["name"] == "Melody"
    assert any(t[0] == '_add_undo' for t in win.calls if isinstance(t, tuple))
    assert '_pop_last_undo' not in win.calls
    assert '_refresh_track_list' in win.calls


def test_rename_track_cancel_no_change():
    win = FakeTrackWindow()
    win._player.voice_manager.set_name(0, "Keep")
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_CANCEL, "IgnoredName")):
        win._rename_track()
    assert win._player.voice_manager.get_name(0) == "Keep"
    assert any(t[0] == '_add_undo' for t in win.calls if isinstance(t, tuple))
    assert '_pop_last_undo' in win.calls


def test_rename_track_same_name_pops_undo():
    win = FakeTrackWindow()
    win._player.voice_manager.set_name(0, "Same")
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_OK, "Same")):
        win._rename_track()
    assert win._player.voice_manager.get_name(0) == "Same"
    assert any(t[0] == '_add_undo' for t in win.calls if isinstance(t, tuple))
    assert '_pop_last_undo' in win.calls


def test_rename_track_empty_name():
    win = FakeTrackWindow()
    win._player.voice_manager.set_name(0, "OldName")
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_OK, "")):
        win._rename_track()
    assert win._player.voice_manager.get_name(0) == ""
    assert '_pop_last_undo' not in win.calls


def test_rename_track_undo_title():
    win = FakeTrackWindow()
    win._player._cur_track = 2
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_OK, "Bass")):
        win._rename_track()
    undo_calls = [t for t in win.calls if isinstance(t, tuple) and t[0] == '_add_undo']
    assert len(undo_calls) == 1
    assert "3" in undo_calls[0][1]


def test_rename_track_status_message():
    win = FakeTrackWindow()
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_OK, "Lead")):
        win._rename_track()
    status = [t[1] for t in win.calls if isinstance(t, tuple) and t[0] == '_show_status']
    assert any("Lead" in s for s in status)


# ──────────────────────────────────────────────────────────────────────────────
# Fake objets pour PatternMixin._rename_pattern
# ──────────────────────────────────────────────────────────────────────────────

class FakePatternListBox:
    def GetSelection(self): return 0
    def Set(self, items):   pass
    def SetSelection(self, i): pass


class FakePatternWindow(PatternMixin):
    """Fenêtre minimale pour tester PatternMixin._rename_pattern."""
    def __init__(self):
        self._cur_pattern_idx = 0
        self._pattern_list    = [Pattern() for _ in range(4)]
        self._player          = MagicMock()
        self._player._pattern = self._pattern_list[0]
        self._pattern_listbox = FakePatternListBox()
        self.calls            = []

    def _add_undo(self, title):          self.calls.append(('_add_undo', title))
    def _pop_last_undo(self):            self.calls.append('_pop_last_undo')
    def _refresh_pattern_listbox(self):  self.calls.append('_refresh_pattern_listbox')
    def _show_status(self, msg):         self.calls.append(('_show_status', msg))


# ──────────────────────────────────────────────────────────────────────────────
# Tests — _rename_pattern
# ──────────────────────────────────────────────────────────────────────────────

def test_rename_pattern_ok():
    win = FakePatternWindow()
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_OK, "Groove A")):
        win._rename_pattern()
    assert win._pattern_list[0]._name == "Groove A"
    assert win._player._pattern._name == "Groove A"
    assert any(t[0] == '_add_undo' for t in win.calls if isinstance(t, tuple))
    assert '_pop_last_undo' not in win.calls
    assert '_refresh_pattern_listbox' in win.calls


def test_rename_pattern_cancel_no_change():
    win = FakePatternWindow()
    win._pattern_list[0]._name = "Keep"
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_CANCEL, "Ignored")):
        win._rename_pattern()
    assert win._pattern_list[0]._name == "Keep"
    assert any(t[0] == '_add_undo' for t in win.calls if isinstance(t, tuple))
    assert '_pop_last_undo' in win.calls


def test_rename_pattern_same_name_pops_undo():
    win = FakePatternWindow()
    win._pattern_list[0]._name = "Same"
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_OK, "Same")):
        win._rename_pattern()
    assert any(t[0] == '_add_undo' for t in win.calls if isinstance(t, tuple))
    assert '_pop_last_undo' in win.calls


def test_rename_pattern_undo_title():
    win = FakePatternWindow()
    win._cur_pattern_idx = 3
    win._player._pattern = win._pattern_list[3]
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_OK, "Break")):
        win._rename_pattern()
    undo_calls = [t for t in win.calls if isinstance(t, tuple) and t[0] == '_add_undo']
    assert "04" in undo_calls[0][1]


def test_rename_pattern_status_message():
    win = FakePatternWindow()
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_OK, "Intro")):
        win._rename_pattern()
    status = [t[1] for t in win.calls if isinstance(t, tuple) and t[0] == '_show_status']
    assert any("Intro" in s for s in status)


def test_rename_pattern_persisted_in_pattern_label():
    win = FakePatternWindow()
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_OK, "MyPat")):
        win._rename_pattern()
    label = win._pattern_label(0)
    assert "MyPat" in label


# ──────────────────────────────────────────────────────────────────────────────
# Tests — _rename_song (SongWindow)
# ──────────────────────────────────────────────────────────────────────────────

class FakeParent:
    """Parent minimal de SongWindow pour _rename_song."""
    def __init__(self):
        self._song_list = [Song(i) for i in range(Song.MAX_SONGS)]
        self.calls      = []

    def _add_undo(self, title):  self.calls.append(('_add_undo', title))
    def _pop_last_undo(self):    self.calls.append('_pop_last_undo')


class FakeSongWindow:
    """SongWindow minimal — ne crée pas de vrai wx.Frame."""
    def __init__(self):
        self._parent       = FakeParent()
        self._cur_song_idx = 0
        self.calls         = []

    def _refresh_song_lb(self):          self.calls.append('_refresh_song_lb')
    def _set_status(self, msg):          self.calls.append(('_set_status', msg))

    _rename_song = SongWindow._rename_song


def test_rename_song_ok():
    sw = FakeSongWindow()
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_OK, "My Song")):
        sw._rename_song()
    assert sw._parent._song_list[0]._name == "My Song"
    assert any(t[0] == '_add_undo' for t in sw._parent.calls if isinstance(t, tuple))
    assert '_pop_last_undo' not in sw._parent.calls
    assert '_refresh_song_lb' in sw.calls


def test_rename_song_cancel_no_change():
    sw = FakeSongWindow()
    sw._parent._song_list[0]._name = "Keep"
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_CANCEL, "Ignored")):
        sw._rename_song()
    assert sw._parent._song_list[0]._name == "Keep"
    assert any(t[0] == '_add_undo' for t in sw._parent.calls if isinstance(t, tuple))
    assert '_pop_last_undo' in sw._parent.calls


def test_rename_song_same_name_pops_undo():
    sw = FakeSongWindow()
    sw._parent._song_list[0]._name = "Same"
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_OK, "Same")):
        sw._rename_song()
    assert any(t[0] == '_add_undo' for t in sw._parent.calls if isinstance(t, tuple))
    assert '_pop_last_undo' in sw._parent.calls


def test_rename_song_undo_title():
    sw = FakeSongWindow()
    sw._cur_song_idx = 2
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_OK, "Rock")):
        sw._rename_song()
    undo = [t for t in sw._parent.calls if isinstance(t, tuple) and t[0] == '_add_undo']
    assert "03" in undo[0][1]


def test_rename_song_status_message():
    sw = FakeSongWindow()
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_OK, "Jazz")):
        sw._rename_song()
    status = [t[1] for t in sw.calls if isinstance(t, tuple) and t[0] == '_set_status']
    assert any("Jazz" in s for s in status)


def test_rename_song_empty_name():
    sw = FakeSongWindow()
    sw._parent._song_list[0]._name = "Old"
    with patch("wx.TextEntryDialog", _fake_dialog(wx.ID_OK, "")):
        sw._rename_song()
    assert sw._parent._song_list[0]._name == ""
    assert '_pop_last_undo' not in sw._parent.calls
