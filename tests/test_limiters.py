#python3
"""
    File: tests/test_limiters.py
    Limiteurs dans le projet et l'Undo, dialogue Sélection des limiteurs,
    bips de l'historique (Phase 9 étape 3g5, tests de 3g4 ; docs/DESIGN.md
    § Phase 9 étapes 3g2 et 3g3) :
    - LimiterSelectDialog : Points de boucle généralisés (panneaux, sources,
      sans options de boucle, refus si gauche > droite avec le bip d'alerte) ;
    - vraie fenêtre principale (une pour le module) : une entrée d'Undo par
      commande, rien si rien ne change, Ctrl+Z / Shift+Z ; .gvp (écrit, relu,
      ancien projet, Ctrl+N) ; Ctrl+Shift+I dans les deux fenêtres ;
      Ctrl+Shift+N dans l'éditeur MIDI ; bips de Ctrl+Z, Shift+Z,
      Ctrl+Shift+Z ;
    - LimitersMixin seul : clé "limiters" invalide.
    Date: Tue, 24/11/2026
    Author: Coolbrother
"""
import json
import os

import pytest
import wx

from ui import menu_bar
from ui.dialogs_temporal import LimiterSelectDialog, LoopSelectDialog, _SRC_CUSTOM


# ----------------------------------------------------------------------
# Dialogue
# ----------------------------------------------------------------------

@pytest.fixture
def parent():
    frame = wx.Frame(None)
    yield frame
    frame.Destroy()


def _dlg(parent, lim_left=16, lim_right=47, loop_start=8, loop_end=64, cur=4):
    # loop_end exclu (Phase 9 étape 4b1) : la source « Fin de boucle » vaut 63
    # 8 mesures de 16 pas, 4 temps
    return LimiterSelectDialog(parent, 8, 4, 16, cur, lim_left, lim_right,
                               loop_start, loop_end)


@pytest.mark.gui
def test_dialog_panels_sources_and_no_loop_options(parent):
    dlg = _dlg(parent)
    try:
        assert dlg.GetTitle() == "Sélection des limiteurs"
        boxes = [c.GetLabel() for c in dlg.GetChildren() if isinstance(c, wx.StaticBox)]
        assert boxes == ["Limiteur gauche", "Limiteur droit"]
        assert [dlg._start_list.GetString(i) for i in range(6)] == [
            "Position courante", "Début du pattern", "Fin du pattern", "Début de boucle",
            "Fin de boucle", "Personnalisé"]
        assert not dlg._looping_cb.IsShown() and not dlg._rep_spin.IsShown()
        assert (dlg.get_start_step(), dlg.get_end_step()) == (16, 47)   # limiteurs posés
        assert dlg._start_list.GetSelection() == _SRC_CUSTOM
    finally:
        dlg.Destroy()


@pytest.mark.gui
def test_dialog_sources_give_their_step(parent):
    dlg = _dlg(parent)
    try:
        for src, step in ((0, 4), (1, 0), (2, 127), (3, 8), (4, 63)):
            dlg._start_list.SetSelection(src)
            dlg._on_start_source(None)
            assert dlg.get_start_step() == step, src
        dlg._end_list.SetSelection(3)                           # Début de boucle
        dlg._on_end_source(None)
        assert dlg.get_end_step() == 8
    finally:
        dlg.Destroy()


@pytest.mark.gui
def test_dialog_opens_on_the_whole_pattern_without_limiters(parent):
    dlg = _dlg(parent, None, None, None, None, cur=30)
    try:
        assert (dlg.get_start_step(), dlg.get_end_step()) == (0, 127)
        assert dlg._start_list.GetSelection() == 1 and dlg._end_list.GetSelection() == 2
        dlg._start_list.SetSelection(3)                         # sans boucle : début
        dlg._on_start_source(None)
        assert dlg.get_start_step() == 0
    finally:
        dlg.Destroy()


@pytest.mark.gui
def test_dialog_refuses_crossed_limiters_with_the_alert_beep(parent, monkeypatch):
    import ui.ui_beep as ui_beep
    beeps, boxes, ended = [], [], []
    monkeypatch.setattr(ui_beep, "alert", lambda w=None: beeps.append(w))
    monkeypatch.setattr(wx, "MessageBox", lambda msg, *a, **k: boxes.append(msg))
    dlg = _dlg(parent)
    try:
        monkeypatch.setattr(dlg, "EndModal", ended.append)
        dlg._start_ctrl.SetValue("5:1:1")
        dlg._end_ctrl.SetValue("2:1:1")
        dlg._on_ok(None)
        assert ended == [] and beeps == [dlg]
        assert boxes == ["Le limiteur gauche est après le limiteur droit."]
        dlg._end_ctrl.SetValue("5:1:1")                         # égaux : permis
        dlg._on_ok(None)
        assert ended == [wx.ID_OK] and len(beeps) == 1
    finally:
        dlg.Destroy()


@pytest.mark.gui
def test_loop_dialog_keeps_its_sources_and_options(parent, monkeypatch):
    """Généralisé, le dialogue des Points de boucle garde ses sources et ses
    options ; depuis 4b1 (fin exclue), il refuse une fin qui n'est pas après
    le début."""
    import ui.ui_beep as ui_beep
    beeps = []
    monkeypatch.setattr(ui_beep, "alert", lambda w=None: beeps.append(w))
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: None)
    dlg = LoopSelectDialog(parent, 8, 4, 16, 4, 16, 48, 2, looping=True,
                           lim_left=8, lim_right=63)
    try:
        assert dlg.GetTitle() == "Points de boucle"
        assert dlg._start_list.GetString(3) == "Limiteur gauche"
        assert dlg._looping_cb.IsShown() and dlg._rep_spin.IsShown()
        dlg._start_ctrl.SetValue("5:1:1")
        dlg._end_ctrl.SetValue("2:1:1")
        assert not dlg._validate() and beeps == [dlg]
        dlg._start_list.SetSelection(3)
        dlg._on_start_source(None)
        assert dlg.get_loop_start() == 8
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
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: None))
    w = main_win
    w._track_editor.reset_lims()
    w._undo.clear()
    status = []
    monkeypatch.setattr(w, "_show_status", status.append)
    w.status = status
    return w


def _lims(w):
    return (w._track_editor._lim_left, w._track_editor._lim_right)


def _titles(w):
    return [e.title for e in w._undo.history_list()]


def _key(w, accel):
    w._key_manager.handle(menu_bar.key_event(accel))


def _last(w):
    pat = w._player._pattern
    return pat._num_bars * pat._num_steps - 1


@pytest.mark.gui
def test_each_limiter_key_is_one_undo_entry(win):
    _key(win, "Shift+I")
    _key(win, "Shift+O")
    assert _lims(win) == (0, _last(win))
    assert _titles(win)[:2] == [f"Limiteur droit : {win._lim_bbt(_last(win))}",
                                "Limiteur gauche : 1:1:1"]
    _key(win, "Shift+O")                                        # inchangé : rien
    assert len(_titles(win)) == 2
    win._undo_action()
    assert _lims(win) == (0, None)
    win._undo_action()
    assert _lims(win) == (None, None)
    win._redo_action()
    win._redo_action()
    assert _lims(win) == (0, _last(win))


@pytest.mark.gui
def test_i_and_o_at_the_position(win):
    win._player._go_to_offset(16.0)
    _key(win, "I")
    win._player._go_to_offset(31.0)
    _key(win, "O")
    assert _lims(win) == (16, 31)
    assert _titles(win)[:2] == ["Limiteur droit : 2:4:4", "Limiteur gauche : 2:1:1"]
    win._player._go_to_offset(0.0)


@pytest.mark.gui
def test_select_all_and_deselect_all(win):
    _key(win, "Ctrl+A")
    assert _lims(win) == (0, _last(win)) and _titles(win) == ["Limiteurs : plage complète"]
    _key(win, "Ctrl+A")                                         # déjà : rien
    assert len(_titles(win)) == 1
    _key(win, "Ctrl+Shift+A")
    assert _lims(win) == (None, None) and _titles(win)[0] == "Limiteurs effacés"
    _key(win, "Ctrl+Shift+A")
    assert len(_titles(win)) == 2
    win._undo_action()
    assert _lims(win) == (0, _last(win))


@pytest.mark.gui
def test_loop_to_limiters_has_its_entry(win):
    pat = win._player._pattern
    pat._loop_start, pat._loop_end = 16, 48          # fin exclue (Phase 9 étape 4b1)
    _key(win, "Alt+Début")
    assert _lims(win) == (16, 47)
    assert _titles(win) == ["Limiteurs : 2:1:1 à 3:4:4"]
    win._undo_action()
    assert _lims(win) == (None, None)
    pat = win._player._pattern
    pat._loop_start = pat._loop_end = None


@pytest.mark.gui
def test_any_undo_entry_brings_back_the_limiters_of_its_moment(win):
    win._set_limiters_undo(4, 20)
    win._add_undo("Autre action")                              # limiteurs (4, 20) capturés
    win._track_editor.reset_lims()                             # (sans entrée)
    win._undo_action()
    assert _lims(win) == (4, 20)


@pytest.mark.gui
def test_track_select_dialog_limiters_undo(win, monkeypatch):
    from ui.dialogs_temporal import TrackSelectDialog

    def show(dlg):
        dlg._sel = getattr(dlg, "_sel", None)
        return wx.ID_OK
    monkeypatch.setattr(TrackSelectDialog, "ShowModal", show)
    monkeypatch.setattr(TrackSelectDialog, "get_start_step", lambda dlg: 40)
    monkeypatch.setattr(TrackSelectDialog, "get_end_step", lambda dlg: 8)
    win._track_select_dialog()
    assert _lims(win) == (8, 40)                               # échangés, comme avant
    assert _titles(win) == [f"Limiteurs : {win._lim_bbt(8)} à {win._lim_bbt(40)}"]


@pytest.mark.gui
def test_limiter_dialog_from_the_main_window(win, monkeypatch):
    seen = []

    def show(dlg):
        seen.append((dlg.get_start_step(), dlg.get_end_step(), dlg._sources[3][1]))
        dlg._start_ctrl.SetValue("2:1:1")
        dlg._end_ctrl.SetValue("3:4:4")
        return wx.ID_OK
    monkeypatch.setattr(LimiterSelectDialog, "ShowModal", show)
    pat = win._player._pattern
    pat._loop_start = 8
    _key(win, "Ctrl+Shift+I")
    assert seen == [(0, _last(win), 8)]                         # boucle pour repère
    assert _lims(win) == (16, 47)
    assert win.status[-1] == "Limiteurs : 2:1:1 à 3:4:4"
    assert _titles(win) == ["Limiteurs : 2:1:1 à 3:4:4"]
    monkeypatch.setattr(LimiterSelectDialog, "ShowModal", lambda dlg: wx.ID_CANCEL)
    _key(win, "Ctrl+Shift+I")
    assert _lims(win) == (16, 47) and len(_titles(win)) == 1     # Annuler : rien
    pat._loop_start = None


@pytest.mark.gui
def test_limiter_dialog_item_in_the_menu(win, monkeypatch):
    called = []
    monkeypatch.setattr(win, "_limiter_select_dialog", lambda *a, **k: called.append(1))
    it = [i for i in win._menu_items.values() if i.text() == "Sélection des limiteurs…"][0]
    assert it.accel == "Ctrl+Shift+I"
    menu_bar.run(win, it)
    assert called == [1]


@pytest.fixture
def editor(main_win):
    main_win._open_midi_editor_window()
    ed = main_win._midi_editor_window
    yield ed
    ed.Destroy()
    main_win._midi_editor_window = None    # sinon la fixture suivante reprend un éditeur détruit


@pytest.mark.gui
def test_editor_ctrl_shift_n_inserts_and_ctrl_shift_i_sets_limiters(win, editor, monkeypatch):
    calls = []
    monkeypatch.setattr(editor, "_insert_dialog", lambda: calls.append("insert"))
    status = []
    monkeypatch.setattr(editor, "_set_status", status.append)

    def show(dlg):
        dlg._start_ctrl.SetValue("1:1:1")
        dlg._end_ctrl.SetValue("1:4:4")
        return wx.ID_OK
    monkeypatch.setattr(LimiterSelectDialog, "ShowModal", show)
    editor._on_key(menu_bar.key_event("Ctrl+Shift+N"))
    assert calls == ["insert"] and _lims(win) == (None, None)
    editor._on_key(menu_bar.key_event("Ctrl+Shift+I"))
    assert calls == ["insert"] and _lims(win) == (0, 15)
    assert status == ["Limiteurs : 1:1:1 à 1:4:4"]


@pytest.mark.gui
def test_editor_limiter_keys_are_undoable(win, editor):
    editor._on_key(menu_bar.key_event("Shift+I"))
    editor._on_key(menu_bar.key_event("Shift+O"))
    assert _lims(win) == (0, _last(win))
    assert len(_titles(win)) == 2
    editor._on_key(menu_bar.key_event("Ctrl+Début"))           # limiteurs réinitialisés
    assert _lims(win) == (None, None) and _titles(win)[0] == "Limiteurs effacés"
    editor._undo_action()
    assert _lims(win) == (0, _last(win))


@pytest.mark.gui
def test_editor_selection_does_not_add_entries(win, editor):
    """Les limiteurs suivis par la sélection de l'éditeur n'ont pas
    d'entrée propre (U3)."""
    editor._selected_indices = set()
    editor._sync_lims_from_selection()
    assert _titles(win) == []


# --- Projet -----------------------------------------------------------

@pytest.mark.gui
def test_limiters_saved_and_read_back(win, tmp_path, monkeypatch):
    path = str(tmp_path / "lims.gvp")
    monkeypatch.setattr(win, "_remember_project", lambda: None)
    win._project_path = path
    win._set_limiters_undo(16, 47)
    win._save_project()
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["limiters"] == {"left": 16, "right": 47}
    win._track_editor.reset_lims()
    win._load_project()                                         # le vrai chemin (Ctrl+O)
    assert _lims(win) == (16, 47)


def test_limiters_from_dict_ignores_bad_values():
    from track_editor import TrackEditor
    from ui.mw_limiters import LimitersMixin

    class _W(LimitersMixin):
        _track_editor = TrackEditor()
    w = _W()
    for d, expected in ((None, (None, None)), ({}, (None, None)),
                        ({"left": 3, "right": 9}, (3, 9)),
                        ({"left": -1, "right": "x"}, (None, None)),
                        ({"left": True, "right": 2.5}, (None, None)),
                        ({"left": None, "right": 7}, (None, 7))):
        w._track_editor._lim_left = w._track_editor._lim_right = 99
        w._limiters_from_dict(d)
        assert (w._track_editor._lim_left, w._track_editor._lim_right) == expected, d
    w._track_editor._lim_left, w._track_editor._lim_right = 3, None
    assert w._limiters_dict() == {"left": 3, "right": None}


@pytest.mark.gui
def test_old_project_and_new_project_have_no_limiters(win):
    win._set_limiters_undo(4, 8)
    win._limiters_from_dict(None)                              # ancien .gvp sans la clé
    assert _lims(win) == (None, None)
    win._set_limiters_undo(4, 8)
    win._project_modified = False
    win._new_project()
    assert _lims(win) == (None, None)


@pytest.mark.gui
def test_limiters_in_the_undo_state(win):
    win._set_limiters_undo(2, 5)
    assert win._capture_state()["limiters"] == {"left": 2, "right": 5}


# --- Bips de l'historique ---------------------------------------------

@pytest.fixture
def bells(monkeypatch):
    rang = []
    monkeypatch.setattr(wx, "Bell", lambda: rang.append(1))
    return rang


@pytest.mark.gui
def test_history_beeps_only_when_nothing_can_be_done(win, bells, monkeypatch):
    """Essai de 4c8 : bip seulement quand la commande ne peut rien faire —
    jamais en atteignant la première ou la dernière entrée (3g4, retiré)."""
    from ui import dialogs
    monkeypatch.setattr(dialogs, "UndoHistoryDialog",
                        type("_D", (), {"__init__": lambda s, *a: None,
                                        "ShowModal": lambda s: wx.ID_CANCEL,
                                        "Destroy": lambda s: None}))

    def beeps(fn):
        n = len(bells)
        fn()
        return len(bells) > n
    # niveau 0 (lancement) : les trois
    assert beeps(win._undo_action) and beeps(win._redo_action)
    assert beeps(win._undo_history_dialog)
    assert win.status[-1] == "Historique Undo: vide"
    win._add_undo("A")                                          # niveau 1
    assert beeps(win._redo_action)                              # rien à refaire
    assert not beeps(win._undo_history_dialog)
    win._add_undo("B")                                          # niveau 2
    assert beeps(win._redo_action)
    assert not beeps(win._undo_action)                          # → 1, sans bip
    assert not beeps(win._redo_action)                          # → 2, la dernière : sans bip
    assert not beeps(win._undo_action)                          # → 1
    assert not beeps(win._undo_action)                          # → 0, la première : sans bip
    assert beeps(win._undo_action)                              # plus rien


@pytest.mark.gui
def test_editor_history_dialog_beeps_when_empty(win, editor, bells, monkeypatch):
    status = []
    monkeypatch.setattr(editor, "_set_status", status.append)
    editor._undo_history_dialog()
    assert bells == [1] and status == ["Historique Undo: vide"]
