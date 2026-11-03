"""
    File: tests/test_exclusive_mute_solo.py
    Mute / Solo exclusifs et F5 (Phase 8 étape 6e1, tests de 6d1 et 6d2 ;
    docs/DESIGN.md § Phase 8 étape 6a, N4-N6, N10-N15, révision 6d2) :
    F3 / F4 activent le mode (Undo, notes coupées), la navigation des pistes
    le suit (Undo groupé), un second F3 / F4 le quitte en rétablissant les
    Mute / Solo d'avant ; X, S, Shift+X, Shift+S le quittent ; F5 remet
    tout à zéro.
    Date: Tue, 03/11/2026
    Author: Coolbrother
"""

import os
import pathlib
import sys
import threading
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import wx

import track_router as tr_mod
from ui.key_manager import KeyManager
from ui.mew_playback import _quit_exclusive_of
from test_bank_slot import FakeTimer
from test_rack_mode_ui import _UndoWin, _Synth
from test_mix_undo import _char


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    if wx.GetApp() is None:
        globals()["_APP"] = wx.App(False)
    FakeTimer.created = []
    monkeypatch.setattr(tr_mod, "threading",
                        types.SimpleNamespace(Timer=FakeTimer, Thread=threading.Thread))
    monkeypatch.setattr(tr_mod, "SynthEngine", _Synth)


class _ExclWin(_UndoWin):
    """Fenêtre factice : vrai Undo, vraie liste des pistes, horloge du
    regroupement des Undo de mixage, coupures notées."""

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.now = 0.0
        self._mix_clock = lambda: self.now
        self._mix_undo_last = None
        self._exclusive = self._exclusive_saved = None
        self._track_list = wx.ListBox(self._frame, choices=[""] * 16)
        self._track_editor = types.SimpleNamespace(is_selected=lambda i: False,
                                                   clear_selection=lambda: None)
        r = self._router
        self.cuts = []
        r.cut_all_notes = lambda: self.cuts.append(self.state())

    def state(self):
        r = self._router
        return ([i + 1 for i, m in enumerate(r._track_mutes) if m],
                [i + 1 for i, s in enumerate(r._track_solos) if s])

    def titles(self):
        return [e.title for e in self._undo.history_list()]


@pytest.fixture
def win(tmp_path):
    w = _ExclWin(tmp_path)
    r = w._router
    r._track_mutes[5] = True                    # piste 6 muette
    r._track_solos[7] = True                    # piste 8 en solo
    yield w
    w.close()


# ---------------------------------------------------------------------------
# Activation (N10-N13)
# ---------------------------------------------------------------------------

def test_f4_solo_exclusive_on_current_track(win):
    win._router._track_mutes[0] = True          # la piste courante était muette
    win._toggle_exclusive("solo")
    assert win._exclusive == "solo"
    assert win.state() == ([6], [1])            # solo de 1 seul, 1 démutée
    assert win.titles() == ["Solo exclusif : piste 1"]
    assert win.statuses[-1] == "Solo exclusif : On — piste 1"
    assert win.cuts == [([1, 6], [8])]          # notes coupées avant (N1)


def test_f3_mute_exclusive_on_current_track(win):
    win._toggle_exclusive("mute")
    assert win._exclusive == "mute"
    assert win.state() == ([1], [])             # mute de 1 seul, aucun solo
    assert win.statuses[-1] == "Mute exclusif : On — piste 1"


def test_f4_then_f3_switches_mode(win):
    win._toggle_exclusive("solo")
    win._toggle_exclusive("mute")
    assert win._exclusive == "mute" and win.state() == ([1], [])


def test_refused_while_recording(win):
    win._player.recording = True
    win._toggle_exclusive("solo")
    assert win._exclusive is None and win.state() == ([6], [8])
    assert win.statuses[-1] == "Solo exclusif : impossible pendant l'enregistrement"
    assert win.titles() == []


# ---------------------------------------------------------------------------
# Navigation (N5, N11, N12)
# ---------------------------------------------------------------------------

def test_navigation_moves_exclusive_solo(win):
    win._toggle_exclusive("solo")
    win._go_to_track(2)
    assert win.state() == ([6], [3])
    assert win.statuses[-1].endswith(" — Solo exclusif")
    assert win.statuses[-1].startswith("Piste 3 — ")


def test_navigation_moves_exclusive_mute(win):
    win._toggle_exclusive("mute")
    win._go_to_track(4)
    assert win.state() == ([5], [])


def test_quick_navigation_is_one_undo_entry(win):
    win._toggle_exclusive("solo")
    win._go_to_track(1)
    win.now = 0.5
    win._go_to_track(2)
    assert win.titles() == ["Solo exclusif : piste 3", "Solo exclusif : piste 1"]
    win.now = 5.0
    win._go_to_track(3)
    assert win.titles()[0] == "Solo exclusif : piste 4" and len(win.titles()) == 3


def test_navigation_cuts_notes_before_change(win):
    win._toggle_exclusive("solo")
    win.cuts.clear()
    win._go_to_track(2)
    assert win.cuts == [([6], [1])]


def test_navigation_without_mode_changes_nothing(win):
    win._go_to_track(2)
    assert win.state() == ([6], [8]) and win.titles() == [] and win.cuts == []


def test_same_track_does_not_reapply(win):
    win._toggle_exclusive("solo")
    win.cuts.clear()
    win._go_to_track(0)
    assert win.cuts == [] and len(win.titles()) == 1


# ---------------------------------------------------------------------------
# Sortie : second F3 / F4 = état d'avant rétabli (6d2, révise N4)
# ---------------------------------------------------------------------------

def test_second_f4_restores_state_before_mode(win):
    win._toggle_exclusive("solo")
    win._go_to_track(2)
    win._toggle_exclusive("solo")
    assert win._exclusive is None and win._exclusive_saved is None
    assert win.state() == ([6], [8])
    assert win.titles()[0] == "Solo exclusif : Off"
    assert win.statuses[-1] == "Solo exclusif : Off — Mute et Solo d'avant rétablis"
    assert win.cuts[-1] == ([6], [3])           # coupé avant le retour


def test_exit_after_switching_modes_restores_first_state(win):
    win._toggle_exclusive("solo")
    win._toggle_exclusive("mute")
    win._toggle_exclusive("mute")
    assert win.state() == ([6], [8])


def test_undo_of_exit_returns_to_exclusive_state(win):
    win._toggle_exclusive("solo")
    win._toggle_exclusive("solo")
    win._undo_action()
    assert win.state() == ([6], [1])


def test_undo_of_activation_returns_to_state_before(win):
    win._toggle_exclusive("mute")
    win._undo_action()
    assert win.state() == ([6], [8])


def test_exclusive_flags_are_real_mute_solo(win):
    """N4 : écrits dans les drapeaux, donc suivis par l'écoute et l'export."""
    win._toggle_exclusive("solo")
    win._go_to_track(3)
    r = win._router
    assert [t for t in range(16) if r._track_is_audible(t)] == [3]


# ---------------------------------------------------------------------------
# X, S, Shift+X, Shift+S pendant un mode (N14, N15)
# ---------------------------------------------------------------------------

def test_x_quits_mode_without_restoring(win):
    win._toggle_exclusive("solo")
    win._go_to_track(2)
    _char(win, "X", on_track_list=True)
    assert win._exclusive is None
    assert win.state() == ([3, 6], [3])         # bascule normale, rien rétabli
    assert win.statuses[-1] == "Piste 3: Mute On — Solo exclusif : Off"


def test_s_quits_mute_mode(win):
    win._toggle_exclusive("mute")
    _char(win, "S", on_track_list=True)
    assert win._exclusive is None
    assert win.statuses[-1] == "Piste 1: Solo On — Mute exclusif : Off"


def test_shift_x_quits_mute_mode_only(win):
    win._toggle_exclusive("mute")
    _char(win, "X", shift=True, on_track_list=True)
    assert win._exclusive is None and win.state() == ([], [])
    assert win.statuses[-1] == "Toutes les Pistes: Démutées — Mute exclusif : Off"
    win._toggle_exclusive("solo")
    _char(win, "X", shift=True, on_track_list=True)
    assert win._exclusive == "solo"             # Shift+X ne quitte pas le Solo exclusif


def test_shift_s_quits_solo_mode(win):
    win._toggle_exclusive("solo")
    _char(win, "S", shift=True, on_track_list=True)
    assert win._exclusive is None and win.state()[1] == []
    assert win.statuses[-1] == "Toutes les Pistes: Désolées — Solo exclusif : Off"


def test_midi_editor_x_quits_main_window_mode(win):
    win._toggle_exclusive("solo")
    assert _quit_exclusive_of(win) == " — Solo exclusif : Off"
    assert win._exclusive is None
    assert _quit_exclusive_of(types.SimpleNamespace()) == ""    # parent sans mode


# ---------------------------------------------------------------------------
# F5 : tout réinitialiser (6d2)
# ---------------------------------------------------------------------------

def test_f5_resets_all_and_quits_mode(win):
    win._toggle_exclusive("solo")
    win._reset_mute_solo()
    assert win.state() == ([], []) and win._exclusive is None
    assert win.titles()[0] == "Réinitialiser Mute / Solo"
    assert win.statuses[-1] == "Toutes les Pistes: Mute et Solo réinitialisés — Solo exclusif : Off"
    assert win.cuts[-1] == ([6], [1])


def test_f5_without_mode(win):
    win._reset_mute_solo()
    assert win.state() == ([], [])
    assert win.statuses[-1] == "Toutes les Pistes: Mute et Solo réinitialisés"
    win._undo_action()
    assert win.state() == ([6], [8])


def test_f5_with_nothing_to_reset_adds_no_undo(win):
    win._router._track_mutes[5] = win._router._track_solos[7] = False
    win._reset_mute_solo()
    assert win.titles() == []


# ---------------------------------------------------------------------------
# Touches F3, F4, F5 par le vrai KeyManager (N5, N10)
# ---------------------------------------------------------------------------

class _KeyEvent:
    def __init__(self, key, shift=False, ctrl=False, alt=False):
        self._key, self._shift, self._ctrl, self._alt = key, shift, ctrl, alt
    def GetKeyCode(self):    return self._key
    def GetUnicodeKey(self): return 0
    def ShiftDown(self):     return self._shift
    def ControlDown(self):   return self._ctrl
    def AltDown(self):       return self._alt
    def Skip(self):          pass


def _press(win, key, **mods):
    for name in ("_quant_list", "_volume_ctrl", "_pan_ctrl", "_mode_choice",
                 "_scale_choice", "_pad_list", "_vel_list", "_midi_port_list",
                 "_status_ctrl"):
        if not hasattr(win, name):
            setattr(win, name, None)
    win._vol_ctrls = getattr(win, "_vol_ctrls", [])
    win._pan_ctrls = getattr(win, "_pan_ctrls", [])
    km = KeyManager(win)
    # les autres gestionnaires (Alt, Ctrl, navigation…) ne sont pas en jeu
    for name in ("_handle_alt", "_handle_ctrl", "_handle_navigation",
                 "_handle_numpad", "_handle_chars"):
        setattr(km, name, lambda event, ctx: True)
    km.handle(_KeyEvent(key, **mods))


def test_keys_f3_f4_f5(win):
    _press(win, wx.WXK_F4)
    assert win._exclusive == "solo"
    _press(win, wx.WXK_F3)
    assert win._exclusive == "mute"
    _press(win, wx.WXK_F3)
    assert win._exclusive is None and win.state() == ([6], [8])
    _press(win, wx.WXK_F5)
    assert win.state() == ([], [])


@pytest.mark.parametrize("mods", [{"shift": True}, {"ctrl": True}, {"alt": True}])
def test_f4_with_modifier_is_not_exclusive(win, mods):
    _press(win, wx.WXK_F4, **mods)
    assert win._exclusive is None
