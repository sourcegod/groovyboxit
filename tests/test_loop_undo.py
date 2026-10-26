#python3
"""
    File: tests/test_loop_undo.py
    Undo et projet modifié pour les points de boucle du pattern et la case
    « Boucler » du song (Phase 7 étape 15g1, docs/DESIGN.md § 15a1 D5) :
    Ctrl+L, Shift+L, Alt+L, dialogue Ctrl+Shift+L (Ok changé, Ok inchangé,
    Annuler), case de la fenêtre Songs ; valeur inchangée sans entrée ;
    Ctrl+Z rétablit les points, le compteur de répétitions, la boucle du
    song en lecture, et réveille le thread de lecture.
    Fenêtre factice de test_master_mix.py (vrai ProjectMixin, vrai
    DrumPlayer).
    Date: Mon, 26/10/2026
    Author: Coolbrother
"""
import sys
import os
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import wx

import ui.mw_patterns as mw_patterns
from track_editor import TrackEditor
from ui.mw_patterns import PatternMixin
from ui.song_window import SongWindow
from ui.key_manager import KeyManager
from test_master_mix import _Win, _Event, _ctx


class _LoopWin(_Win):
    _loop_select_dialog = PatternMixin._loop_select_dialog

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self._track_editor = TrackEditor()
        self._player._pattern._num_bars = 4          # 64 pas

    def _apply_pattern_from_store(self, new):
        self._player._pattern._looping = new._looping
    def _play_toggle(self):
        pass

    # --- raccourcis de test
    def loop(self):
        pat = self._player._pattern
        saved = self._pattern_list[self._cur_pattern_idx]
        live = (pat._loop_start, pat._loop_end, pat._loop_count, pat._looping)
        assert (saved._loop_start, saved._loop_end) == live[:2]   # store synchronisé
        return live

    def go(self, step):
        self._player._go_to_offset(float(step))


@pytest.fixture
def win(tmp_path):
    return _LoopWin(tmp_path)


def _ctrl_l(win):
    k = ord('L')
    assert KeyManager(win)._handle_ctrl(_Event(k), _ctx(k, ctrl=True))


def _shift_l(win):
    k = ord('L')
    ctx = _ctx(k)
    ctx.shift = True
    assert KeyManager(win)._handle_chars(_Event(k), ctx)


def _alt_l(win):
    k = ord('L')
    ctx = _ctx(k)
    ctx.alt = True
    assert KeyManager(win)._handle_alt(_Event(k), ctx)


# ---------------------------------------------------------------------------
# Ctrl+L, Shift+L, Alt+L
# ---------------------------------------------------------------------------

def test_ctrl_l_sets_start_with_entry_and_undo(win):
    win.go(20)
    _ctrl_l(win)
    assert win.loop()[0] == 20
    assert win.titles() == ["Début de boucle: 2:2:1"]
    assert win._project_modified is True
    win._undo_action()
    assert win.loop()[0] is None


def test_ctrl_l_at_same_place_adds_nothing(win):
    _ctrl_l(win)                                     # pas 0 → None, déjà None
    assert win.titles() == []
    win.go(8)
    _ctrl_l(win)
    _ctrl_l(win)
    assert len(win.titles()) == 1


def test_shift_l_sets_end_with_entry_and_undo(win):
    win.go(40)
    _shift_l(win)
    assert win.loop()[1] == 40
    assert win.titles() == ["Fin de boucle: 3:3:1"]
    assert win._project_modified is True
    win._undo_action()
    assert win.loop()[1] is None


def test_shift_l_on_last_step_without_end_adds_nothing(win):
    win.go(63)                                       # dernier pas → None, déjà None
    _shift_l(win)
    assert win.titles() == []
    assert win._project_modified is False


def test_start_then_end_undone_one_by_one(win):
    win.go(8)
    _ctrl_l(win)
    win.go(40)
    _shift_l(win)
    win._undo_action()
    assert win.loop()[:2] == (8, None)
    win._undo_action()
    assert win.loop()[:2] == (None, None)


def test_alt_l_resets_with_entry_and_undo_restores_both(win):
    win.go(8)
    _ctrl_l(win)
    win.go(40)
    _shift_l(win)
    _alt_l(win)
    assert win.loop()[:2] == (None, None)
    assert win.titles()[0] == "Réinitialiser la boucle"
    win._undo_action()
    assert win.loop()[:2] == (8, 40)


def test_alt_l_without_points_adds_nothing(win):
    _alt_l(win)
    assert win.titles() == []
    assert win._project_modified is False


# ---------------------------------------------------------------------------
# Dialogue Ctrl+Shift+L
# ---------------------------------------------------------------------------

class _FakeLoopDialog:
    result = wx.ID_OK
    values = None                                   # (start, end, count, looping)

    def __init__(self, parent, **kw):
        self._vals = self.values or (kw["loop_start"], kw["loop_end"],
                                     kw["loop_count"], kw["looping"])
    def ShowModal(self):         return self.result
    def get_loop_start(self):    return self._vals[0]
    def get_loop_end(self):      return self._vals[1]
    def get_loop_count(self):    return self._vals[2]
    def get_looping(self):       return self._vals[3]
    def _fmt_bbt(self, step):    return str(step)
    def Destroy(self):           pass


def _dialog(monkeypatch, win, result=wx.ID_OK, values=None):
    dlg = type("_Dlg", (_FakeLoopDialog,), dict(result=result, values=values))
    monkeypatch.setattr(mw_patterns, "LoopSelectDialog", dlg)
    win._loop_select_dialog()


def test_dialog_ok_changed_adds_entry_and_undo_restores_all(win, monkeypatch):
    before = win.loop()
    _dialog(monkeypatch, win, values=(4, 48, 3, True))
    assert win.loop() == (4, 48, 3, True)
    assert win._player._loop_remaining == 3
    assert win.titles() == ["Boucle du pattern"]
    assert win._project_modified is True
    win._undo_action()
    assert win.loop() == before
    assert win._player._loop_remaining == before[2]


def test_dialog_ok_unchanged_adds_nothing(win, monkeypatch):
    _dialog(monkeypatch, win)
    assert win.titles() == []
    assert win._project_modified is False


def test_dialog_cancel_adds_nothing_and_changes_nothing(win, monkeypatch):
    before = win.loop()
    _dialog(monkeypatch, win, result=wx.ID_CANCEL, values=(4, 48, 3, True))
    assert win.loop() == before
    assert win.titles() == []


# ---------------------------------------------------------------------------
# Case « Boucler » de la fenêtre Songs
# ---------------------------------------------------------------------------

class _Check:
    def __init__(self, value=False): self.value = value
    def GetValue(self):    return self.value
    def SetValue(self, v): self.value = v


class _SongWin:
    """Fenêtre Songs factice : la vraie _on_loop_toggle, et set_cur_song
    qui remet la case à jour comme la vraie."""
    _on_loop_toggle = SongWindow._on_loop_toggle

    def __init__(self, parent, idx):
        self._parent      = parent
        self._cur_song_idx = idx
        self._chk_loop    = _Check()
    def set_cur_song(self, idx):
        self._cur_song_idx = idx
        self._chk_loop.SetValue(self._parent._song_list[idx]._looping)


def test_song_loop_checkbox_entry_and_undo(win):
    win._cur_song_idx = 1
    sw = win._song_window = _SongWin(win, 1)
    sw._chk_loop.value = True
    sw._on_loop_toggle(None)
    assert win._song_list[1]._looping is True
    assert win.titles() == ["Song 02: boucle On"]
    assert win._project_modified is True
    win._undo_action()
    assert win._song_list[1]._looping is False
    assert sw._chk_loop.value is False


def test_song_loop_unchanged_adds_nothing(win):
    sw = _SongWin(win, 0)
    sw._on_loop_toggle(None)                        # case déjà décochée
    assert win.titles() == []


def test_undo_syncs_song_looping_while_song_plays(win):
    p = win._player
    p._song_mode = True
    sw = win._song_window = _SongWin(win, 0)
    sw._chk_loop.value = True
    sw._on_loop_toggle(None)
    assert p._song_looping is True
    win._undo_action()
    assert p._song_looping is False


def test_undo_outside_song_mode_leaves_song_looping(win):
    p = win._player
    p._song_looping = True
    sw = win._song_window = _SongWin(win, 0)
    sw._chk_loop.value = True
    sw._on_loop_toggle(None)
    p._song_looping = True
    win._undo_action()
    assert p._song_looping is True


# ---------------------------------------------------------------------------
# Réveil du thread de lecture
# ---------------------------------------------------------------------------

def test_undo_wakes_playing_thread(win):
    win.go(8)
    _ctrl_l(win)
    p = win._player
    p._wakeup.clear()
    p.playing = True
    try:
        win._undo_action()
    finally:
        p.playing = False
    assert p._wakeup.is_set()


def test_undo_when_stopped_does_not_wake(win):
    win.go(8)
    _ctrl_l(win)
    win._player._wakeup.clear()
    win._undo_action()
    assert not win._player._wakeup.is_set()
