#python3
"""
    File: tests/test_undo_clean_point.py
    « Point propre » de l'Undo (Phase 7 étape 16e1, docs/DESIGN.md § 16a1
    D1-D3) : revenir par Ctrl+Z à l'état sauvegardé efface le marquage
    modifié et l'astérisque du titre, avant et après une sauvegarde,
    réglages regroupés compris ; une annulation (F2, dialogue du pad,
    prise live sans effet) rétablit l'état « modifié » d'avant ; Ctrl+O et
    Ctrl+N vident l'historique.
    Fenêtre factice de test_master_mix.py (vrai ProjectMixin, vrai
    DrumPlayer).
    Date: Mon, 26/10/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import wx

import ui.mw_tracks as mw_tracks
import ui.mw_pads as mw_pads
from pattern import TapeEvent, ETYPE_KIT
from ui.mw_tracks import TrackMixin
from ui.mw_pads import PadMixin
from test_master_mix import _Win, _write_project
from test_mix_undo import _FakePadDialog


class _CleanWin(_Win):
    _rename_track         = TrackMixin._rename_track
    _pad_properties_dialog = PadMixin._pad_properties_dialog

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.window_titles = []
        self._cur_row = 0

    def SetTitle(self, title):            self.window_titles.append(title)
    def _refresh_voice_display(self, i):  pass
    def _play(self, idx):                 pass
    def _play_toggle(self):               pass

    # --- raccourcis de test
    def star(self):
        """Astérisque du dernier titre de fenêtre, cohérent avec le marquage."""
        star = "*" in self.window_titles[-1]
        assert star is self._project_modified
        return star


@pytest.fixture
def win(tmp_path):
    w = _CleanWin(tmp_path)
    w._update_title()
    return w


def _volume(win, vol, t=None):
    if t is not None:
        win.now = t
    win._set_master_volume_undo(vol)


# ---------------------------------------------------------------------------
# Ctrl+Z jusqu'à l'état sauvegardé (D1)
# ---------------------------------------------------------------------------

def test_fresh_project_is_clean(win):
    assert win.star() is False


def test_undo_back_to_saved_state_clears_star(win):
    _volume(win, 90)
    assert win.star() is True
    win._undo_action()
    assert win.star() is False


def test_undo_twice_needed_after_two_changes(win):
    _volume(win, 90)
    win.now = 5.0
    win._set_master_pan_undo(10)
    win._undo_action()
    assert win.star() is True
    win._undo_action()
    assert win.star() is False


def test_redo_after_undo_to_saved_state_marks_again(win):
    _volume(win, 90)
    win._undo_action()
    win._redo_action()
    assert win.star() is True
    assert win._player.volume == 90


def test_undo_past_a_save_marks_modified(win):
    _volume(win, 90)
    win._save_project()
    assert win.star() is False
    win._undo_action()
    assert win.star() is True                   # le fichier a 90, l'appli 100
    win._redo_action()
    assert win.star() is False


def test_grouped_changes_undone_to_saved_state_are_clean(win):
    _volume(win, 95, t=0.0)
    _volume(win, 90, t=0.5)                      # rejoint l'entrée précédente
    assert len(win.titles()) == 1
    win._undo_action()
    assert win.star() is False


def test_grouped_change_after_a_save_marks_and_undo_stays_modified(win):
    _volume(win, 95, t=0.0)
    win._save_project()                          # fichier à 95
    _volume(win, 90, t=0.5)                      # regroupé, mais nouvel état
    assert win.star() is True
    win._undo_action()                           # retour à 100, pas à 95
    assert win._player.volume == 100
    assert win.star() is True


def test_new_branch_after_undo_then_undo_is_clean(win):
    _volume(win, 90)
    win._undo_action()
    _volume(win, 80, t=5.0)
    assert win.star() is True
    win._undo_action()
    assert win.star() is False


# ---------------------------------------------------------------------------
# Annulations (D2)
# ---------------------------------------------------------------------------

class _FakeTextDialog:
    result = wx.ID_CANCEL
    def __init__(self, parent, message, caption, value):
        self._value = value
    def ShowModal(self):  return self.result
    def GetValue(self):   return self._value
    def Destroy(self):    pass


@pytest.mark.parametrize("result", [wx.ID_CANCEL, wx.ID_OK])   # Ok sans changement
@pytest.mark.parametrize("modified", [False, True])
def test_f2_cancelled_restores_modified_state(win, monkeypatch, result, modified):
    if modified:
        _volume(win, 90)
    monkeypatch.setattr(mw_tracks.wx, "TextEntryDialog",
                        type("_Dlg", (_FakeTextDialog,), {"result": result}))
    win._rename_track()
    assert win.star() is modified
    assert len(win.titles()) == (1 if modified else 0)


@pytest.mark.parametrize("modified", [False, True])
def test_pad_dialog_cancelled_restores_modified_state(win, monkeypatch, modified):
    if modified:
        _volume(win, 90)
    dlg = type("_Dlg", (_FakePadDialog,), dict(result=wx.ID_CANCEL, live=None, final=None))
    monkeypatch.setattr(mw_pads, "PadPropertiesDialog", dlg)
    win._pad_properties_dialog()
    assert win.star() is modified


def test_pop_last_undo_updates_title(win):
    win._add_undo("Essai")
    assert win.star() is True
    win._pop_last_undo()
    assert win.star() is False


def _take(win, events=(), save_during=False):
    win._take_begin("Enregistrement piste 1")
    p = win._player
    p.recording = True
    p._pattern._tape[0].extend(events)
    if save_during:
        win._save_project()
    p.recording = False
    win._take_end_if_idle()


def test_empty_take_leaves_project_clean(win):
    _take(win)
    assert win.titles() == []
    assert win.star() is False


def test_empty_take_with_save_during_stays_clean(win):
    _take(win, save_during=True)
    assert win.star() is False


def test_empty_take_on_modified_project_stays_modified(win):
    _volume(win, 90)
    _take(win)
    assert win.star() is True


def test_take_with_notes_is_kept_and_undo_cleans(win):
    _take(win, events=[TapeEvent(ETYPE_KIT, payload={"note": 36, "vel": 100}, time=0.0)])
    assert win.titles() == ["Enregistrement piste 1"]
    assert win.star() is True
    win._undo_action()
    assert win.star() is False


# ---------------------------------------------------------------------------
# L'historique appartient au projet (D3)
# ---------------------------------------------------------------------------

def test_open_project_clears_history_and_future(win):
    _volume(win, 90)
    _volume(win, 80, t=5.0)
    win._undo_action()                           # un Redo en attente
    _write_project(win._project_path)
    win._load_project()
    assert win._undo.history_list() == [] and win._undo.future_list() == []
    assert win.star() is False
    win._undo_action()
    assert win.status[-1] == "Undo: rien à annuler"


def test_new_project_clears_history_without_entry(win):
    _volume(win, 90)
    win._save_project()                          # pas de dialogue de sauvegarde
    win._new_project()
    assert win._undo.history_list() == [] and win._undo.future_list() == []
    assert win.star() is False


def test_change_after_open_then_undo_is_clean(win):
    _write_project(win._project_path, master={"volume": 70, "pan": 0})
    win._load_project()
    _volume(win, 60)
    win._undo_action()
    assert win._player.volume == 70
    assert win.star() is False
