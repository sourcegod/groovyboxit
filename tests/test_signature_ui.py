#python3
"""
    File: tests/test_signature_ui.py
    Tests de l'interface des signatures rythmiques (Phase 7 étape 20e1,
    docs/DESIGN.md § 20a1 S7, S10, avancement 20d1) : dialogue des
    propriétés du pattern (signature, résolution, longueur recalculée en
    direct sur une durée exacte), application au pattern (signature d'abord,
    notes en place ; Nouveau ; Doubler sans toucher la signature ; statut,
    Undo), grille de la fenêtre principale (colonnes de la mesure, cases hors
    mesure refusées, curseur borné).
    Date: Fri, 30/10/2026
    Author: Coolbrother
"""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import wx

import ui.main_window as main_window
from pattern import Pattern, TapeEvent, ETYPE_PATCH
from metronome import Metronome
from player.drum_player import DrumPlayer
from ui.dialogs import PatternPropertiesDialog
from ui.mw_patterns import PatternMixin

RES = Pattern.VALID_RESOLUTIONS


@pytest.fixture
def frame():
    """wx.App propre au test (comme les autres tests de dialogues)."""
    app = wx.App(False)
    f = wx.Frame(None)
    yield f
    for w in wx.GetTopLevelWindows():
        w.Destroy()
    app.Destroy()


def _dlg(frame, num_bars=4, num_steps=16, num_beats=4, denominator=4, max_bars=999):
    return PatternPropertiesDialog(frame, 0, "P", 0, num_bars, num_steps, True, max_bars,
                                   RES, num_beats=num_beats, denominator=denominator)


def _sig(dlg, num, den):
    """Change la signature comme l'utilisateur : temps, puis valeur."""
    dlg._beats.SetValue(num)
    dlg._on_signature_change(wx.CommandEvent())
    dlg._den.SetSelection(PatternPropertiesDialog.DENOMINATORS.index(den))
    dlg._on_signature_change(wx.CommandEvent())


# ---------------------------------------------------------------------------
# Dialogue des propriétés du pattern
# ---------------------------------------------------------------------------

def test_dialog_initial_signature_and_resolution(frame):
    dlg = _dlg(frame, num_steps=12, num_beats=3, denominator=4)
    assert (dlg.get_num_beats(), dlg.get_denominator(), dlg.get_resolution()) == (3, 4, 16)
    assert dlg.get_num_steps() == 12
    dlg = _dlg(frame, num_steps=24, num_beats=6, denominator=8)
    assert (dlg.get_num_beats(), dlg.get_denominator(), dlg.get_resolution()) == (6, 8, 32)


def test_dialog_labels(frame):
    dlg = _dlg(frame)
    assert [dlg._den.GetString(i) for i in range(4)] == \
        ["2 (blanche)", "4 (noire)", "8 (croche)", "16 (double croche)"]
    assert dlg._steps.GetString(0) == "1/16 (double croche)"
    assert dlg._steps.GetString(1) == "1/32 (triple croche)"
    assert (dlg._beats.GetMin(), dlg._beats.GetMax()) == (1, 16)
    assert dlg._beats.GetName() == "Signature, temps par mesure"


def test_dialog_num_steps_follow_signature_and_resolution(frame):
    dlg = _dlg(frame)
    _sig(dlg, 6, 8)
    assert dlg.get_num_steps() == 12
    dlg._steps.SetSelection(1)                       # 1/32
    assert dlg.get_num_steps() == 24
    _sig(dlg, 7, 8)
    assert dlg.get_num_steps() == 28


def test_dialog_length_recomputed_on_signature_change(frame):
    dlg = _dlg(frame, num_bars=4)                    # 64 pas
    _sig(dlg, 3, 4)
    assert dlg.get_num_bars() == 6                   # 64 / 12 → 6
    assert dlg._start.GetCount() == 6


def test_dialog_length_exact_through_intermediate_signature(frame):
    """20d1 : 3/4 → 6/8 en passant par 6/4 ajoutait une mesure."""
    dlg = _dlg(frame, num_bars=49, num_steps=12, num_beats=3)
    _sig(dlg, 6, 8)
    assert dlg.get_num_bars() == 49


def test_dialog_manual_length_then_signature(frame):
    dlg = _dlg(frame, num_bars=4)
    dlg._length.SetSelection(7)                      # 8 mesures de 4/4 = 128 pas
    dlg._on_length_change(_Sel(7))
    _sig(dlg, 2, 4)
    assert dlg.get_num_bars() == 16


class _Sel:
    def __init__(self, sel): self._sel = sel
    def GetSelection(self):  return self._sel


def test_dialog_same_signature_keeps_length(frame):
    dlg = _dlg(frame, num_bars=5)
    _sig(dlg, 4, 4)
    assert dlg.get_num_bars() == 5


# ---------------------------------------------------------------------------
# Application au pattern (_pattern_properties_dialog)
# ---------------------------------------------------------------------------

class _Silent:
    def stop_all(self):           pass
    def play_sound(self, *a):     pass
    def play_note(self, *a):      pass
    def play_metronome(self, *a): pass


class _Win(PatternMixin):
    def __init__(self, num_bars=4):
        self._cur_pattern_idx = 0
        self._pattern_list    = [Pattern() for _ in range(2)]
        self._player          = DrumPlayer(_Silent())
        self._player._pattern._num_bars = num_bars
        self._player.set_bpm(120)
        for t in (0, 4, 16, 36):
            self._player._pattern._tape[0].append(
                TapeEvent(ETYPE_PATCH, dur=100, payload={"note": 60, "vel": 90}, time=t))
        self._pattern_list[0].copy_from(self._player._pattern)
        self.calls = []
    def _add_undo(self, title):          self.calls.append(("undo", title))
    def _refresh_grid(self):             self.calls.append("grille")
    def _refresh_pattern_listbox(self):  pass
    def _show_status(self, msg):         self.calls.append(("statut", msg))
    def _play_toggle(self):              pass


def _fake_dialog(action, num_beats, den, res=16, num_bars=None):
    class FakeDlg:
        def __init__(self, *a, **kw):  FakeDlg.kwargs = kw
        def ShowModal(self):           return wx.ID_OK
        def get_name(self):            return ""
        def get_start_bar(self):       return 0
        def get_num_bars(self):        return num_bars
        def get_num_steps(self):       return Pattern.steps_for(res, num_beats, den)
        def get_num_beats(self):       return num_beats
        def get_denominator(self):     return den
        def get_resolution(self):      return res
        def get_looping(self):         return True
        def get_action(self):          return action
        def Destroy(self):             pass
    return FakeDlg


def _apply(win, fake):
    with patch("ui.mw_patterns.PatternPropertiesDialog", fake):
        win._pattern_properties_dialog()


def test_dialog_receives_current_signature():
    win = _Win()
    win._player._pattern.set_signature(6, 8)
    fake = _fake_dialog("Courant", 6, 8, num_bars=6)
    _apply(win, fake)
    assert (fake.kwargs["num_beats"], fake.kwargs["denominator"]) == (6, 8)


def test_apply_courant_signature_keeps_notes_in_place():
    win = _Win(num_bars=4)
    live = win._player._pattern
    secs = [win._player.tempo_map().secs(e.time) for e in live._tape[0]]
    _apply(win, _fake_dialog("Courant", 3, 4, num_bars=6))
    assert (live._num_beats, live._denumerator, live._num_steps, live._num_bars) == (3, 4, 12, 6)
    assert [e.time for e in live._tape[0]] == [0, 4, 16, 36]
    assert [win._player.tempo_map().secs(e.time) for e in live._tape[0]] == secs
    store = win._pattern_list[0]
    assert (store._num_beats, store._num_steps) == (3, 12)
    assert ("statut", "Pattern 01: mis à jour — 3/4, résolution 1/16") in win.calls
    assert ("undo", "Redimensionner pattern 01") in win.calls


def test_apply_courant_updates_step_duration_and_metronome():
    win = _Win()
    _apply(win, _fake_dialog("Courant", 6, 8, num_bars=6))
    assert win._player.step_duration == pytest.approx(0.125)
    win._player.clicking = True
    clicks = [e[2] for e in win._player._build_measure_events(0, 11, 12, 1, 0.0)
              if e[1] == Metronome.METRO_EVENT]
    assert clicks == [0, 1, 2, 3, 4, 5]


def test_apply_courant_resolution_after_signature():
    win = _Win()
    _apply(win, _fake_dialog("Courant", 3, 4, res=32, num_bars=6))
    live = win._player._pattern
    assert (live._num_steps, live.resolution()) == (24, 32)


def test_apply_nouveau_in_chosen_signature():
    win = _Win()
    _apply(win, _fake_dialog("Nouveau", 7, 8, num_bars=2))
    live, store = win._player._pattern, win._pattern_list[0]
    for p in (live, store):
        assert (p._num_beats, p._denumerator, p._num_steps, p._num_bars) == (7, 8, 14, 2)
    assert live.is_empty()
    assert ("statut", "Pattern 01: nouveau — 7/8, résolution 1/16") in win.calls


def test_apply_doubler_keeps_signature():
    win = _Win(num_bars=2)
    win._player._pattern.set_signature(3, 4)
    win._player._pattern._num_bars = 2
    _apply(win, _fake_dialog("Doubler", 6, 8, num_bars=2))
    live = win._player._pattern
    assert (live._num_beats, live._denumerator, live._num_bars) == (3, 4, 4)


# ---------------------------------------------------------------------------
# Grille de la fenêtre principale (S10)
# ---------------------------------------------------------------------------

class _Cell:
    def __init__(self):
        self.value, self.enabled, self.focused = False, True, False
    def SetValue(self, v):  self.value = bool(v)
    def GetValue(self):     return self.value
    def Enable(self, on=True): self.enabled = on
    def IsEnabled(self):    return self.enabled
    def SetFocus(self):     self.focused = True


class _GridWin(PatternMixin):
    ROWS, COLS = 16, 16
    _active_cols  = main_window.MainWindow._active_cols
    _set_cell     = main_window.MainWindow._set_cell
    _on_checkbox  = main_window.MainWindow._on_checkbox
    _move         = main_window.MainWindow._move

    def __init__(self, num=3, den=4):
        self._player = DrumPlayer(_Silent())
        self._player._pattern.set_signature(num, den)
        self._cells  = [[_Cell() for _ in range(self.COLS)] for _ in range(self.ROWS)]
        self._cur_row, self._cur_col, self._autoplay = 0, 0, False
        self.undos = []
    def _add_undo(self, title): self.undos.append(title)
    def _play(self, r):         pass


def test_active_cols():
    assert _GridWin(3, 4)._active_cols() == 12
    assert _GridWin(6, 8)._active_cols() == 12
    assert _GridWin(4, 4)._active_cols() == 16
    win = _GridWin(4, 4)
    win._player._pattern._num_steps = 32
    assert win._active_cols() == 16


def test_refresh_grid_disables_columns_beyond_bar():
    win = _GridWin(3, 4)
    win._player._pattern.set_cell(0, 2, 0, 5, 100)
    win._refresh_grid()
    assert [c.enabled for c in win._cells[0]] == [True] * 12 + [False] * 4
    assert win._cells[2][5].value and not any(c.value for c in win._cells[2][12:])


def test_refresh_grid_clamps_cursor():
    win = _GridWin(3, 4)
    win._cur_col = 15
    win._refresh_grid()
    assert win._cur_col == 11


def test_refresh_grid_4_4_unchanged():
    win = _GridWin(4, 4)
    win._refresh_grid()
    assert all(c.enabled for c in win._cells[0])


def test_set_cell_beyond_bar_refused(monkeypatch):
    bells = []
    monkeypatch.setattr(main_window.wx, "Bell", lambda: bells.append(True))
    win = _GridWin(3, 4)
    win._set_cell(0, 13, True)
    assert bells == [True] and win._player._pattern.is_empty()
    win._set_cell(0, 11, True)
    assert win._player._pattern.get_cell(0, 0, 0, 11) == 100


def test_checkbox_beyond_bar_reset():
    win = _GridWin(3, 4)
    win._cells[1][14].value = True
    win._on_checkbox(1, 14)
    assert not win._cells[1][14].value
    assert win.undos == [] and win._player._pattern.is_empty()


def test_move_stops_at_last_column_of_bar(monkeypatch):
    bells = []
    monkeypatch.setattr(main_window.wx, "Bell", lambda: bells.append(True))
    win = _GridWin(3, 4)
    win._cur_col = 11
    win._move(0, 1)
    assert bells == [True] and win._cells[0][11].focused
