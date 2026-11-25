#python3
"""
    File: tests/test_loop_end_excluded.py
    Fin de boucle exclue, comme dans Sonar (Phase 9 étape 4c1, tests de 4b1 ;
    docs/DESIGN.md § Phase 9 étape 4a) :
    - LoopManager : quatre mesures = 64 pas exactement (le délai au retour de
      boucle venait d'un pas en trop), fin du pattern, bornes ;
    - migration des projets version 1 (fin + 1) ; version 2 écrite ;
    - dialogue des Points de boucle : fin exclue, « Fin du pattern » = mesure
      suivante, refus si la fin n'est pas après le début ;
    - vraie fenêtre principale : Shift+L (refus d'une boucle vide, bip
      d'alerte), le même Shift+L pour l'éditeur et Songs, Shift+Fin,
      limiteurs ↔ boucle.
    Date: Wed, 25/11/2026
    Author: Coolbrother
"""
import json
from types import SimpleNamespace

import pytest
import wx

from loop_manager import LoopManager
from project_manager import ProjectManager
from ui import menu_bar


def _pat(num_bars=8, num_steps=16, start=None, end=None, looping=True):
    return SimpleNamespace(_num_bars=num_bars, _num_steps=num_steps, _loop_start=start,
                           _loop_end=end, _looping=looping)


# ----------------------------------------------------------------------
# Lecteur : fenêtre de boucle
# ----------------------------------------------------------------------

def test_four_bars_play_exactly_64_steps():
    """Essai de 3b5 : boucle de 1:1:1 à 5:1:1 (fin 64) — 64 pas, pas 65."""
    w = LoopManager().compute_window(_pat(end=64))
    assert (w.lp_start, w.lp_end, w.total_steps, w.loop_bars) == (0, 63, 64, 4)


def test_window_from_bar_2_to_bar_4():
    w = LoopManager().compute_window(_pat(start=16, end=48))
    assert (w.lp_start, w.lp_end, w.total_steps) == (16, 47, 32)


def test_no_end_is_the_end_of_the_pattern():
    w = LoopManager().compute_window(_pat(start=16, end=None))
    assert (w.lp_end, w.total_steps) == (127, 112)


def test_end_beyond_the_pattern_is_clamped():
    w = LoopManager().compute_window(_pat(end=500))
    assert (w.lp_end, w.total_steps) == (127, 128)


# ----------------------------------------------------------------------
# Projets
# ----------------------------------------------------------------------

def test_version_1_project_gets_end_plus_one():
    data = {"version": 1, "patterns": [{"loop_end": 63}, {"loop_end": None}, {}]}
    out = ProjectManager.migrate(data)
    assert [p.get("loop_end") for p in out["patterns"]] == [64, None, None]
    assert out["version"] == 2


def test_project_without_version_is_version_1():
    out = ProjectManager.migrate({"patterns": [{"loop_end": 15}]})
    assert out["patterns"][0]["loop_end"] == 16


def test_version_2_project_is_left_alone():
    data = {"version": 2, "patterns": [{"loop_end": 64}]}
    assert ProjectManager.migrate(data)["patterns"][0]["loop_end"] == 64
    assert ProjectManager.migrate([1, 2]) == [1, 2]                 # pas un projet


def test_load_migrates_and_version_is_2(tmp_path):
    path = tmp_path / "old.gvp"
    path.write_text(json.dumps({"version": 1, "patterns": [{"loop_end": 31}]}),
                    encoding="utf-8")
    assert ProjectManager.load(str(path))["patterns"][0]["loop_end"] == 32
    assert ProjectManager.VERSION == 2


# ----------------------------------------------------------------------
# Dialogue des Points de boucle
# ----------------------------------------------------------------------

@pytest.fixture
def parent():
    frame = wx.Frame(None)
    yield frame
    frame.Destroy()


def _loop_dlg(parent, start=None, end=None, lim_left=None, lim_right=None):
    from ui.dialogs_temporal import LoopSelectDialog
    # 8 mesures de 16 pas, 4 temps
    return LoopSelectDialog(parent, 8, 4, 16, 4, start, end, 0, looping=True,
                            lim_left=lim_left, lim_right=lim_right)


@pytest.mark.gui
def test_dialog_end_of_pattern_is_the_next_bar(parent):
    dlg = _loop_dlg(parent)
    try:
        assert dlg._end_ctrl.GetValue() == "9:1:1"
        assert dlg.get_loop_end() is None and dlg.get_end_step() == 128
        dlg._end_ctrl.SetValue("5:1:1")
        assert dlg.get_loop_end() == 64
        dlg._end_ctrl.SetValue("12:1:1")                          # borné à 9:1:1
        assert dlg.get_end_step() == 128
        dlg._start_list.SetSelection(2)                           # début : fin du pattern
        dlg._on_start_source(None)
        assert dlg._start_ctrl.GetValue() == "8:4:4"              # le dernier pas
    finally:
        dlg.Destroy()


@pytest.mark.gui
def test_dialog_opens_on_the_excluded_end(parent):
    dlg = _loop_dlg(parent, start=16, end=48, lim_left=16, lim_right=47)
    try:
        assert dlg._end_ctrl.GetValue() == "4:1:1"
        assert dlg._end_list.GetSelection() == 4                  # limiteur droit + 1
        assert dlg._fmt_end(128) == "9:1:1"
    finally:
        dlg.Destroy()


@pytest.mark.gui
def test_dialog_refuses_an_empty_loop(parent, monkeypatch):
    import ui.ui_beep as ui_beep
    beeps, boxes, ended = [], [], []
    monkeypatch.setattr(ui_beep, "alert", lambda w=None: beeps.append(w))
    monkeypatch.setattr(wx, "MessageBox", lambda msg, *a, **k: boxes.append(msg))
    dlg = _loop_dlg(parent)
    try:
        monkeypatch.setattr(dlg, "EndModal", ended.append)
        dlg._start_ctrl.SetValue("3:1:1")
        dlg._end_ctrl.SetValue("3:1:1")                           # vide
        dlg._on_ok(None)
        assert ended == [] and beeps == [dlg]
        assert boxes == ["La fin de boucle doit être après son début."]
        dlg._end_ctrl.SetValue("3:1:2")                           # un pas
        dlg._on_ok(None)
        assert ended == [wx.ID_OK]
    finally:
        dlg.Destroy()


@pytest.mark.gui
def test_limiter_dialog_end_of_loop_is_its_last_step(parent):
    from ui.dialogs_temporal import LimiterSelectDialog
    dlg = LimiterSelectDialog(parent, 8, 4, 16, 4, None, None, 16, 48)
    try:
        dlg._end_list.SetSelection(4)                             # Fin de boucle
        dlg._on_end_source(None)
        assert dlg.get_end_step() == 47                           # limiteur inclus (4d1 : exclu)
    finally:
        dlg.Destroy()


# ----------------------------------------------------------------------
# Vraie fenêtre principale
# ----------------------------------------------------------------------

@pytest.fixture(scope="module")
def main_win():
    from ui.main_window import MainWindow
    win = MainWindow()
    yield win
    win._router.wait_loaded()
    win._close_midi_devices()
    win._audio_driver.close()
    win.Destroy()


@pytest.fixture
def win(main_win, monkeypatch):
    import ui.ui_beep as ui_beep
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: None))
    w = main_win
    pat = w._player._pattern
    pat._loop_start = pat._loop_end = None
    w._pattern_list[w._cur_pattern_idx]._loop_start = None
    w._pattern_list[w._cur_pattern_idx]._loop_end = None
    w._track_editor.reset_lims()
    w._undo.clear()
    status, beeps = [], []
    monkeypatch.setattr(w, "_show_status", status.append)
    monkeypatch.setattr(ui_beep, "alert", lambda win=None: beeps.append(win))
    w.status, w.beeps = status, beeps
    yield w
    w._player._go_to_offset(0.0)


def _key(w, accel):
    w.status.clear()
    w._key_manager.handle(menu_bar.key_event(accel))
    return w.status[-1] if w.status else None


def _ns(w):
    return w._player._pattern._num_steps


@pytest.mark.gui
def test_shift_l_sets_the_excluded_end(win):
    win._player._go_to_offset(2.0 * _ns(win))                     # 3:1:1
    assert _key(win, "Shift+L").startswith("Boucle fin: 3:1:1")
    pat = win._player._pattern
    assert pat._loop_end == 2 * _ns(win)
    assert win._pattern_list[win._cur_pattern_idx]._loop_end == pat._loop_end
    w = LoopManager().compute_window(pat)
    assert w.total_steps == 2 * _ns(win)                          # deux mesures, sans délai


@pytest.mark.gui
def test_shift_l_refuses_an_empty_loop(win):
    win._player._go_to_offset(0.0)
    assert _key(win, "Shift+L").startswith("Fin de boucle refusée")
    assert win.beeps == [win] and win._player._pattern._loop_end is None
    pat = win._player._pattern
    pat._loop_start = 2 * _ns(win)
    win._player._go_to_offset(2.0 * _ns(win))                     # au début de boucle
    assert _key(win, "Shift+L").startswith("Fin de boucle refusée")
    assert pat._loop_end is None and len(win.beeps) == 2
    assert [e.title for e in win._undo.history_list()] == []


@pytest.mark.gui
def test_shift_l_of_the_editor_and_songs_is_the_same(win):
    win._player._go_to_offset(2.0 * _ns(win))
    win._key_manager.handle_transport(menu_bar.key_event("Shift+L"))
    assert win._player._pattern._loop_end == 2 * _ns(win)
    win._player._go_to_offset(0.0)
    win._key_manager.handle_transport(menu_bar.key_event("Shift+L"))
    assert win.beeps == [win]


@pytest.mark.gui
def test_shift_end_goes_to_the_excluded_end(win):
    pat = win._player._pattern
    pat._loop_end = 4 * _ns(win)
    assert _key(win, "Shift+Fin").startswith("Fin boucle: 5:1:1")
    pat._loop_end = None                                          # fin du pattern
    total = pat._num_bars * _ns(win)
    assert _key(win, "Shift+Fin").startswith(
        f"Fin boucle: {win._lim_bbt(total - 1)}")


@pytest.mark.gui
def test_limiters_to_loop_and_back_with_the_excluded_end(win):
    te, pat = win._track_editor, win._player._pattern
    total = pat._num_bars * _ns(win)
    te.set_lim_left(_ns(win))
    te.set_lim_right(3 * _ns(win) - 1)                            # dernier pas de la mesure 3
    assert _key(win, "Alt+Fin") == "Boucle : 2:1:1 à 4:1:1"
    assert pat._loop_end == 3 * _ns(win)
    te.reset_lims()
    _key(win, "Alt+Début")
    assert (te._lim_left, te._lim_right) == (_ns(win), 3 * _ns(win) - 1)
    te.set_lim_left(0)
    te.set_lim_right(total - 1)                                    # tout le pattern
    _key(win, "Alt+Fin")
    assert (pat._loop_start, pat._loop_end) == (None, None)


@pytest.mark.gui
def test_saved_project_is_version_2(win, tmp_path, monkeypatch):
    path = str(tmp_path / "v2.gvp")
    monkeypatch.setattr(win, "_remember_project", lambda: None)
    win._project_path = path
    pat = win._player._pattern
    pat._loop_end = 3 * _ns(win)
    win._pattern_list[win._cur_pattern_idx]._loop_end = pat._loop_end    # comme Shift+L
    win._save_project()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["version"] == 2
    assert data["patterns"][win._cur_pattern_idx]["loop_end"] == 3 * _ns(win)
    assert ProjectManager.load(path)["patterns"][win._cur_pattern_idx]["loop_end"] == \
        3 * _ns(win)                                               # relu tel quel (v2)
    pat._loop_end = None
    win._pattern_list[win._cur_pattern_idx]._loop_end = None
