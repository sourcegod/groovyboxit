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


# ----------------------------------------------------------------------
# Correctif 4c2 : la boucle et les clips audio suivent le changement de
# pattern (tests de 4c4)
# ----------------------------------------------------------------------

def _set_loop(w, idx, start, end, count=0):
    stored = w._pattern_list[idx]
    stored._loop_start, stored._loop_end, stored._loop_count = start, end, count
    if idx == w._cur_pattern_idx:
        live = w._player._pattern
        live._loop_start, live._loop_end, live._loop_count = start, end, count


def _live_loop(w):
    live = w._player._pattern
    return (live._loop_start, live._loop_end, live._loop_count)


@pytest.fixture
def two_patterns(win):
    if win._cur_pattern_idx:
        win._switch_pattern(0)
    _set_loop(win, 0, 16, 32, 2)
    _set_loop(win, 1, None, None, 0)
    yield win
    _set_loop(win, 1, None, None, 0)
    if win._cur_pattern_idx:
        win._switch_pattern(0)
    _set_loop(win, 0, None, None, 0)


@pytest.mark.gui
def test_switching_pattern_loads_its_loop(two_patterns):
    w = two_patterns
    w._switch_pattern(1)
    assert _live_loop(w) == (None, None, 0)                        # pas celle du pattern 1
    _set_loop(w, 1, 0, 8, 0)
    w._switch_pattern(0)
    assert _live_loop(w) == (16, 32, 2)
    assert w._player._loop_remaining == 2                          # compteur rechargé
    w._switch_pattern(1)
    assert _live_loop(w) == (0, 8, 0)


@pytest.mark.gui
def test_reopened_project_has_the_loop_of_its_pattern(two_patterns, tmp_path, monkeypatch):
    w = two_patterns
    monkeypatch.setattr(w, "_remember_project", lambda: None)
    w._project_path = str(tmp_path / "boucle.gvp")
    w._save_project()
    _set_loop(w, 0, None, None, 0)                                 # oubliée en mémoire
    w._load_project()
    assert _live_loop(w) == (16, 32, 2)


@pytest.mark.gui
def test_switching_pattern_cuts_the_audio_clips(two_patterns, monkeypatch):
    w = two_patterns
    cuts = []
    monkeypatch.setattr(w._router, "stop_audio_clips", lambda *a: cuts.append(a))
    w._switch_pattern(1)
    assert cuts == [()]                                            # tous les clips
    w._switch_pattern(1)                                           # le même : rien
    assert cuts == [()]
    w._switch_pattern(0)
    assert len(cuts) == 2


def test_copy_from_still_leaves_the_loop():
    """copy_from sert aussi à la lecture du song et à l'export : il ne recopie
    pas la boucle (4c2 corrige le seul chargement d'un pattern du store)."""
    from pattern import Pattern
    a, b = Pattern(), Pattern()
    a._loop_start, a._loop_end, a._loop_count = 4, 12, 3
    b.copy_from(a)
    assert (b._loop_start, b._loop_end, b._loop_count) == (None, None, 0)


# ----------------------------------------------------------------------
# Correctif 4c3 : Boucle On / Off pendant la lecture
# ----------------------------------------------------------------------

@pytest.mark.gui
def test_toggle_loop_while_playing_keeps_the_position(win, monkeypatch):
    p = win._player
    monkeypatch.setattr(p, "playing", True, raising=False)
    monkeypatch.setattr(p, "_current_offset", lambda: 20.5)
    p._pattern._looping = True
    p._wakeup.clear()
    p._resync_offset = None
    assert _key(win, "L") == "Boucle: Off"
    assert p._pattern._looping is False
    assert p._resync_offset == 20.5 and p._wakeup.is_set()
    assert [e.title for e in win._undo.history_list()] == ["Boucle: Off"]
    p._resync_offset = None
    p._wakeup.clear()


@pytest.mark.gui
def test_toggle_loop_stopped_does_not_wake_the_player(win):
    p = win._player
    p._pattern._looping = False
    p._wakeup.clear()
    p._resync_offset = None
    assert _key(win, "L") == "Boucle: On"
    assert p._resync_offset is None and not p._wakeup.is_set()


@pytest.mark.gui
def test_toggle_loop_of_the_editor_and_songs_is_the_same(win, monkeypatch):
    calls = []
    monkeypatch.setattr(win._key_manager, "toggle_loop", lambda: calls.append(1))
    win._key_manager.handle_transport(menu_bar.key_event("L"))
    assert calls == [1]


@pytest.mark.gui
@pytest.mark.slow
def test_loop_off_while_playing_goes_on_to_the_end_of_the_pattern(win):
    """Essai de 4c2 : Boucle Off en lecture arrêtait le pattern à la fin de
    la boucle ; la lecture doit continuer au-delà."""
    import time
    p = win._player
    pat = p._pattern
    old_bpm = p.bpm
    p.set_bpm(480)
    pat._looping, pat._loop_start, pat._loop_end = True, None, pat._num_steps
    try:
        p.play_pattern()
        time.sleep(0.2)
        assert p._current_offset() < pat._num_steps                 # dans la boucle
        _key(win, "L")                                              # Boucle Off
        t0 = time.time()
        while p._current_offset() <= pat._num_steps + 2 and time.time() - t0 < 3:
            time.sleep(0.02)
        assert p.playing and p._current_offset() > pat._num_steps + 2
        assert p._cur_loop_steps == 0                               # fenêtre : tout le pattern
    finally:
        p.stop_all()
        p.set_bpm(old_bpm)
        pat._looping, pat._loop_end = True, None
