#python3
"""
    File: tests/test_playback_rewind.py
    Lecture remise au début (Phase 8 étape 7e2, docs/DESIGN.md avancement
    7d2, remarque de l'essai de 7d1) : après Ctrl+N, Ctrl+O, l'ouverture ou
    la fermeture de la fenêtre Song, la lecture du pattern ou du song repart
    du début, même après une pause (position gardée dans _resume_offset) ;
    la lecture en cours est arrêtée et le mode Song quitté au changement de
    projet. _rewind_playback sur un lecteur factice, puis une vraie fenêtre
    principale (sans FluidSynth ni sfizz).
    Date: Wed, 04/11/2026
    Author: Coolbrother
"""
import sys
import os
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import wx

from ui.mw_project import ProjectMixin
from ui.main_window import MainWindow


# ---------------------------------------------------------------------------
# _rewind_playback sur un lecteur factice
# ---------------------------------------------------------------------------

class _FakePlayer:
    def __init__(self):
        self.calls = []
        self._song_mode, self._song_looping = True, True
        self._song_sequence, self._song_pos = [3, 4, 5], 2

    def stop_all(self):
        self.calls.append("stop_all")

    def goto_start(self):
        self.calls.append("goto_start")


def test_rewind_stops_quits_song_mode_and_goes_to_start():
    calls = []
    win = types.SimpleNamespace(
        _player=_FakePlayer(),
        _router=types.SimpleNamespace(stop_all_synth_voices=lambda: calls.append("voices")))
    ProjectMixin._rewind_playback(win)
    p = win._player
    assert p.calls == ["stop_all", "goto_start"]
    assert calls == ["voices"]
    assert (p._song_mode, p._song_looping, p._song_sequence, p._song_pos) == (False, False, [], 0)


# ---------------------------------------------------------------------------
# Vraie fenêtre principale
# ---------------------------------------------------------------------------

# Des fichiers passés avant celui-ci (test_key_manager, test_midi_export_ui)
# détruisent la wx.App de session : la recréer au besoin, gardée dans le
# module (sans référence, elle serait libérée aussitôt).
_APP = None


@pytest.fixture(scope="module")
def win():
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)
    w = MainWindow(no_fluidsynth=True, no_sfizz=True)
    w._router.wait_loaded()
    yield w
    if w._song_window:
        w._song_window.Destroy()
        w._song_window = None
    w._audio_driver.close()
    w.Destroy()


def _pause_at(win, offset=20.0, song=False):
    """Lecteur arrêté en pause au pas offset (comme pause_pattern), en mode
    Song si song."""
    p = win._player
    p.stop_all()
    p._resume_offset = offset
    if song:
        p._song_mode, p._song_looping = True, True
        p._song_sequence, p._song_pos = [0, 1, 2], 2
    assert p._current_offset() == offset


def _at_start(win):
    p = win._player
    return p._current_offset() == 0.0 and p._resume_offset is None and p._song_pos == 0


def test_pause_position_is_kept_without_rewind(win):
    # Le défaut corrigé : sans remise au début, la pause survit
    _pause_at(win, 12.0)
    win._refresh_grid()
    assert win._player._current_offset() == 12.0


def test_new_project_rewinds(win):
    _pause_at(win, song=True)
    win._project_modified = False             # pas de question d'enregistrement
    win._new_project()
    p = win._player
    assert _at_start(win)
    assert not p._song_mode and p._song_sequence == []


def test_open_project_rewinds_and_quits_song_mode(win, tmp_path):
    win._project_path = str(tmp_path / "essai.gvp")
    win._save_project()
    assert os.path.isfile(win._project_path)
    _pause_at(win, 33.0, song=True)
    win._load_project()                       # le chargement de Ctrl+O
    p = win._player
    assert _at_start(win)
    assert not p._song_mode and not p._song_looping and p._song_sequence == []


def test_open_project_stops_playback(win, tmp_path):
    win._project_path = str(tmp_path / "essai2.gvp")
    win._save_project()
    p = win._player
    p.stop_all()
    p.playing = True                          # lecture en cours (sans fil de lecture)
    p._resume_offset = 8.0
    win._load_project()
    assert not p.playing and _at_start(win)


def test_open_song_window_rewinds(win):
    _pause_at(win, 25.0)
    win._player._song_pos = 2
    win._open_song_window()
    try:
        assert win._song_window is not None
        assert _at_start(win)
    finally:
        win._song_window.Close()
    assert win._song_window is None


def test_reopening_shown_song_window_keeps_position(win):
    # Fenêtre déjà ouverte : seulement montrée, la position ne change pas
    win._open_song_window()
    try:
        win._player._resume_offset = 9.0
        win._open_song_window()
        assert win._player._current_offset() == 9.0
    finally:
        win._song_window.Close()


def test_close_song_window_rewinds(win):
    win._open_song_window()
    _pause_at(win, 14.0, song=True)
    win._song_window.Close()
    p = win._player
    assert win._song_window is None
    assert _at_start(win) and not p._song_mode and p._song_sequence == []
