#python3
"""
    File: tests/test_cc_event_edit_dialog.py
    Tests — _CcEventEditDialog (Phase 7 étape 4n) : dialog d'édition d'un
    événement non-note, généralisé en étape 4m aux types "cc" (CC générique
    de _tape) et "pgm" (Program Change) en plus de "bend". Le type "mod" a
    disparu en 5f : CC#1 (Mod Wheel) passe désormais par la branche "cc".
    Couvre aussi le dispatch de MidiEditorWindow._edit_cc_dialog (quelle
    méthode d'édition de MidiEditor est appelée selon le type).
    Date: Wed, 15/10/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wx
from pattern import Pattern, TapeEvent, ETYPE_CC, ETYPE_PGM
from midi.midi_editor import MidiEditor
from ui.midi_editor_dialogs import _CcEventEditDialog
import ui.mew_editing as mew_editing
import ui.midi_editor_window as mew


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pattern():
    p = Pattern()
    p.resize(2, 16)
    return p


def make_dlg(ev):
    # wx.App de session (conftest.py, fixture autouse) : ne pas en créer ici.
    frame = wx.Frame(None)
    dlg   = _CcEventEditDialog(frame, ev, _pattern())
    return frame, dlg


def teardown(frame, dlg):
    dlg.Destroy()
    frame.Destroy()


def _cc_ev(cc_num=74, value=90, bar=0, step=0):
    return {"type": "cc", "track": 0, "bar": bar, "step": step, "offset": step,
            "cc_num": cc_num, "value": value, "channel": 0, "event_idx": 0}


def _pgm_ev(program=41, bar=0, step=0):
    return {"type": "pgm", "track": 0, "bar": bar, "step": step, "offset": step,
            "program": program, "channel": 0, "event_idx": 0}


# ---------------------------------------------------------------------------
# Titre / libellé / bornes par type
# ---------------------------------------------------------------------------

def test_cc_dialog_title_mentions_controller_number():
    frame, dlg = make_dlg(_cc_ev(cc_num=74))
    assert dlg.GetTitle() == "Éditer CC #74"
    teardown(frame, dlg)


def test_cc_dialog_value_bounds_and_initial():
    frame, dlg = make_dlg(_cc_ev(cc_num=74, value=90))
    assert dlg._val_sp.GetMin()   == 0
    assert dlg._val_sp.GetMax()   == 127
    assert dlg._val_sp.GetValue() == 90
    teardown(frame, dlg)


def test_pgm_dialog_title_and_bounds():
    frame, dlg = make_dlg(_pgm_ev(program=41))
    assert dlg.GetTitle() == "Éditer Program Change"
    assert dlg._val_sp.GetMin()   == 0
    assert dlg._val_sp.GetMax()   == 127
    teardown(frame, dlg)


def test_pgm_dialog_initial_value_read_from_program_field():
    """Program Change porte sa valeur dans "program", pas dans "value"."""
    frame, dlg = make_dlg(_pgm_ev(program=41))
    assert dlg._val_sp.GetValue() == 41
    teardown(frame, dlg)


def test_bend_dialog_unchanged():
    ev = {"type": "bend", "track": 0, "bar": 0, "step": 0, "offset": 0, "value": 500}
    frame, dlg = make_dlg(ev)
    assert dlg.GetTitle()       == "Éditer pitch bend"
    assert dlg._val_sp.GetMin() == -8192
    assert dlg._val_sp.GetMax() == 8191
    teardown(frame, dlg)


def test_value_spinctrl_has_accessible_name():
    """Un SpinCtrl seul n'annonce que sa valeur (cf. feedback_accessibility_spinctrl)."""
    frame, dlg = make_dlg(_pgm_ev())
    assert dlg._val_sp.GetName() == "Program (0..127)"
    teardown(frame, dlg)


# ---------------------------------------------------------------------------
# Getters position / valeur
# ---------------------------------------------------------------------------

def test_getters_return_zero_based_position():
    frame, dlg = make_dlg(_cc_ev(bar=1, step=6))
    assert dlg.get_bar()  == 1
    assert dlg.get_step() == 6
    teardown(frame, dlg)


def test_get_value_returns_spin_value():
    frame, dlg = make_dlg(_cc_ev(value=90))
    dlg._val_sp.SetValue(20)
    assert dlg.get_value() == 20
    teardown(frame, dlg)


# ---------------------------------------------------------------------------
# Dispatch de MidiEditorWindow._edit_cc_dialog (étape 4m)
# ---------------------------------------------------------------------------

class _StubDialog:
    """Remplace _CcEventEditDialog : valide immédiatement avec des valeurs fixes."""
    value, bar, step = 55, 0, 3
    created_with     = []

    def __init__(self, parent, ev, pattern):
        _StubDialog.created_with.append(ev)

    def ShowModal(self):  return wx.ID_OK
    def get_value(self):  return self.value
    def get_bar(self):    return self.bar
    def get_step(self):   return self.step
    def Destroy(self):    pass


class _FakeEditPlayer:
    def __init__(self, pattern):
        self._pattern = pattern
        self.playing  = False


class _FakeEditParent:
    def __init__(self, pattern):
        self._player = _FakeEditPlayer(pattern)
        self.popped  = 0

    def _pop_last_undo(self):
        self.popped += 1


class _FakeEditWindow:
    """Objet minimal exposant le vrai _edit_cc_dialog et _bbt_str."""
    _edit_cc_dialog = mew.MidiEditorWindow._edit_cc_dialog
    _bbt_str        = mew.MidiEditorWindow._bbt_str

    def __init__(self, pattern):
        self._parent       = _FakeEditParent(pattern)
        self._midi_editor  = MidiEditor()
        self._events       = []
        self._num_steps    = pattern._num_steps
        self._num_beats    = pattern._num_beats
        self.undos         = []
        self.status        = None
        self.refreshed     = 0
        self.navigated_to  = None

    def _add_undo(self, label):     self.undos.append(label)
    def _refresh(self):             self.refreshed += 1
    def _navigate_to(self, idx):    self.navigated_to = idx
    def _set_status(self, msg):     self.status = msg


def _win_with_cc_pgm(monkeypatch):
    monkeypatch.setattr(mew_editing, "_CcEventEditDialog", _StubDialog)
    _StubDialog.created_with = []
    p = _pattern()
    t = p._bar_step_to_time(0, 4)
    p._tape[0].append(TapeEvent(ETYPE_CC,  channel=1, payload={"cc_num": 74, "value": 90}, time=t))
    p._tape[0].append(TapeEvent(ETYPE_PGM, channel=1, payload={"program": 5},              time=t))
    return _FakeEditWindow(p), p


def test_edit_cc_dialog_edits_cc_value_in_tape(monkeypatch):
    win, p = _win_with_cc_pgm(monkeypatch)
    ev = [e for e in win._midi_editor.get_cc_pgm_events(p, 0) if e["type"] == "cc"][0]
    win._edit_cc_dialog(ev)
    cc = [e for e in p._tape[0] if e.etype == ETYPE_CC][0]
    assert cc.payload == {"cc_num": 74, "value": 55}   # cc_num préservé
    assert cc.time == p._bar_step_to_time(0, 3)        # déplacé au pas 3
    assert "CC #74" in win.undos[0]
    assert "Valeur:55" in win.status


def test_edit_cc_dialog_edits_program_in_tape(monkeypatch):
    win, p = _win_with_cc_pgm(monkeypatch)
    ev = [e for e in win._midi_editor.get_cc_pgm_events(p, 0) if e["type"] == "pgm"][0]
    win._edit_cc_dialog(ev)
    pgm = [e for e in p._tape[0] if e.etype == ETYPE_PGM][0]
    assert pgm.payload == {"program": 55}
    assert "Program Change" in win.undos[0]
    assert "Valeur:55" in win.status


def test_edit_cc_dialog_pops_undo_when_edit_refused(monkeypatch):
    """Position hors pattern → edit_* renvoie None, l'undo posé est retiré."""
    win, p = _win_with_cc_pgm(monkeypatch)
    ev  = [e for e in win._midi_editor.get_cc_pgm_events(p, 0) if e["type"] == "cc"][0]
    bad = dict(ev, event_idx=99)   # index introuvable → édition refusée
    win._edit_cc_dialog(bad)
    assert win._parent.popped == 1
    assert "annulée" in win.status.lower()


def test_edit_cc_dialog_still_handles_bend(monkeypatch):
    """Non-régression : bend passe toujours par edit_bend_event."""
    win, p = _win_with_cc_pgm(monkeypatch)
    p._bend_tape[0] = [(4, 100)]
    ev = {"type": "bend", "track": 0, "bar": 0, "step": 4, "offset": 4, "value": 100}
    win._edit_cc_dialog(ev)
    assert (3, 55) in p._bend_tape[0]
    assert "Bend" in win.undos[0]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
