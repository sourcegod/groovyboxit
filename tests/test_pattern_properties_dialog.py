#python3
"""
    File: tests/test_pattern_properties_dialog.py
    Tests unitaires de PatternPropertiesDialog : valeurs initiales, listbox
    Actions, mise à jour dynamique de Début, touche Ctrl+P.
    Date: Wed, 20/05/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wx
from ui.dialogs import PatternPropertiesDialog


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

VALID_STEPS = (16, 32, 64, 128)

class FakeKeyEvent:
    def __init__(self, key=0, ctrl=False):
        self._key    = key
        self._ctrl   = ctrl
        self.skipped = False

    def GetKeyCode(self):  return self._key
    def ControlDown(self): return self._ctrl
    def Skip(self):        self.skipped = True


class FakeListEvent:
    """Simule un EVT_LISTBOX avec GetSelection()."""
    def __init__(self, selection=0):
        self._sel = selection

    def GetSelection(self): return self._sel


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

DEFAULT = dict(
    name      = "TestPat",
    start_bar = 1,         # "Mesure 2"
    num_bars  = 4,
    num_steps = 32,        # index 1 dans VALID_STEPS
    looping   = True,
    max_bars  = 8,
)


def make_dlg(on_play_toggle=None, **kwargs):
    p = {**DEFAULT, **kwargs}
    app   = wx.App(False)
    frame = wx.Frame(None)
    dlg   = PatternPropertiesDialog(
        frame, 0,
        p['name'], p['start_bar'], p['num_bars'], p['num_steps'],
        p['looping'], p['max_bars'], VALID_STEPS,
        on_play_toggle=on_play_toggle,
    )
    return app, frame, dlg


def teardown(app, frame, dlg):
    dlg.Destroy()
    frame.Destroy()
    app.Destroy()


# ---------------------------------------------------------------------------
# Valeurs initiales
# ---------------------------------------------------------------------------

def test_initial_name():
    app, frame, dlg = make_dlg()
    assert dlg.get_name() == "TestPat"
    teardown(app, frame, dlg)
    print("  get_name() == 'TestPat' (initial) : OK")

def test_initial_start_bar():
    app, frame, dlg = make_dlg()
    assert dlg.get_start_bar() == 1   # 0-indexed
    teardown(app, frame, dlg)
    print("  get_start_bar() == 1 (initial) : OK")

def test_initial_num_bars():
    app, frame, dlg = make_dlg()
    assert dlg.get_num_bars() == 4
    teardown(app, frame, dlg)
    print("  get_num_bars() == 4 (initial) : OK")

def test_initial_num_steps():
    app, frame, dlg = make_dlg()
    assert dlg.get_num_steps() == 32
    teardown(app, frame, dlg)
    print("  get_num_steps() == 32 (initial) : OK")

def test_initial_looping_true():
    app, frame, dlg = make_dlg()
    assert dlg.get_looping() is True
    teardown(app, frame, dlg)
    print("  get_looping() == True (initial) : OK")

def test_initial_looping_false():
    app, frame, dlg = make_dlg(looping=False)
    assert dlg.get_looping() is False
    teardown(app, frame, dlg)
    print("  get_looping() == False (initial) : OK")

def test_initial_action_courant():
    app, frame, dlg = make_dlg()
    assert dlg.get_action() == "Courant"
    teardown(app, frame, dlg)
    print("  get_action() == 'Courant' par défaut : OK")

def test_start_bar_clamped_to_num_bars():
    # start_bar >= num_bars → sélection sur le dernier item
    app, frame, dlg = make_dlg(start_bar=10, num_bars=3)
    assert dlg.get_start_bar() == 2   # min(10, 3-1)
    teardown(app, frame, dlg)
    print("  start_bar hors limites → clampé au dernier item : OK")


# ---------------------------------------------------------------------------
# Listbox Actions
# ---------------------------------------------------------------------------

def test_action_nouveau():
    app, frame, dlg = make_dlg()
    dlg._actions.SetSelection(1)
    assert dlg.get_action() == "Nouveau"
    teardown(app, frame, dlg)
    print("  get_action() == 'Nouveau' (index 1) : OK")

def test_action_doubler():
    app, frame, dlg = make_dlg()
    dlg._actions.SetSelection(2)
    assert dlg.get_action() == "Doubler"
    teardown(app, frame, dlg)
    print("  get_action() == 'Doubler' (index 2) : OK")

def test_action_diviser():
    app, frame, dlg = make_dlg()
    dlg._actions.SetSelection(3)
    assert dlg.get_action() == "Diviser par 2"
    teardown(app, frame, dlg)
    print("  get_action() == 'Diviser par 2' (index 3) : OK")


# ---------------------------------------------------------------------------
# Mise à jour dynamique de Début quand Longueur change
# ---------------------------------------------------------------------------

def test_length_change_updates_start_count():
    app, frame, dlg = make_dlg(num_bars=4)
    # Simuler la sélection de "6" dans la listbox Longueur
    dlg._on_length_change(FakeListEvent(selection=5))   # 5+1 = 6 bars
    assert dlg._start.GetCount() == 6
    teardown(app, frame, dlg)
    print("  _on_length_change(5) → Start a 6 items : OK")

def test_length_change_preserves_start_selection():
    # start_bar=1, on passe à 6 bars → sélection inchangée
    app, frame, dlg = make_dlg(start_bar=1, num_bars=4)
    dlg._on_length_change(FakeListEvent(selection=5))
    assert dlg.get_start_bar() == 1
    teardown(app, frame, dlg)
    print("  Start préserve sa sélection si longueur augmente : OK")

def test_length_change_clamps_start_selection():
    # start_bar=3, on réduit à 2 bars → sélection clampée à 1
    app, frame, dlg = make_dlg(start_bar=3, num_bars=4)
    dlg._on_length_change(FakeListEvent(selection=1))   # 1+1 = 2 bars
    assert dlg.get_start_bar() == 1   # min(3, 2-1)
    teardown(app, frame, dlg)
    print("  Start clampé quand longueur diminue en-dessous : OK")

def test_length_change_updates_get_num_bars():
    app, frame, dlg = make_dlg(num_bars=4)
    dlg._length.SetSelection(6)   # index 6 → 7 bars
    assert dlg.get_num_bars() == 7
    teardown(app, frame, dlg)
    print("  get_num_bars() reflète la nouvelle sélection : OK")


# ---------------------------------------------------------------------------
# Modification des widgets
# ---------------------------------------------------------------------------

def test_set_name_via_ctrl():
    app, frame, dlg = make_dlg()
    dlg._name.SetValue("  Nouveau nom  ")
    assert dlg.get_name() == "Nouveau nom"   # strip()
    teardown(app, frame, dlg)
    print("  get_name() strip les espaces : OK")

def test_set_looping_false():
    app, frame, dlg = make_dlg(looping=True)
    dlg._loop.SetValue(False)
    assert dlg.get_looping() is False
    teardown(app, frame, dlg)
    print("  get_looping() reflète False après décoché : OK")

def test_set_steps_64():
    app, frame, dlg = make_dlg(num_steps=16)
    dlg._steps.SetSelection(2)   # index 2 → 64
    assert dlg.get_num_steps() == 64
    teardown(app, frame, dlg)
    print("  get_num_steps() == 64 après SetSelection(2) : OK")


# ---------------------------------------------------------------------------
# Touche Ctrl+P → on_play_toggle
# ---------------------------------------------------------------------------

def test_ctrl_p_calls_play_toggle():
    toggled = []
    app, frame, dlg = make_dlg(on_play_toggle=lambda: toggled.append(1))
    dlg._on_key(FakeKeyEvent(key=ord('P'), ctrl=True))
    assert toggled == [1]
    teardown(app, frame, dlg)
    print("  Ctrl+P appelle on_play_toggle : OK")

def test_p_without_ctrl_does_not_call_toggle():
    toggled = []
    app, frame, dlg = make_dlg(on_play_toggle=lambda: toggled.append(1))
    dlg._on_key(FakeKeyEvent(key=ord('P'), ctrl=False))
    assert toggled == []
    teardown(app, frame, dlg)
    print("  P sans Ctrl n'appelle pas on_play_toggle : OK")

def test_other_key_does_not_call_toggle():
    toggled = []
    app, frame, dlg = make_dlg(on_play_toggle=lambda: toggled.append(1))
    dlg._on_key(FakeKeyEvent(key=ord('A'), ctrl=True))
    assert toggled == []
    teardown(app, frame, dlg)
    print("  Ctrl+A n'appelle pas on_play_toggle : OK")

def test_ctrl_p_not_skipped():
    app, frame, dlg = make_dlg()
    ev = FakeKeyEvent(key=ord('P'), ctrl=True)
    dlg._on_key(ev)
    assert not ev.skipped
    teardown(app, frame, dlg)
    print("  Ctrl+P n'est pas passé à Skip() : OK")

def test_other_key_is_skipped():
    app, frame, dlg = make_dlg()
    ev = FakeKeyEvent(key=ord('A'), ctrl=False)
    dlg._on_key(ev)
    assert ev.skipped
    teardown(app, frame, dlg)
    print("  autre touche passe à Skip() : OK")

def test_no_crash_without_play_toggle():
    app, frame, dlg = make_dlg(on_play_toggle=None)
    dlg._on_key(FakeKeyEvent(key=ord('P'), ctrl=True))   # ne doit pas lever
    teardown(app, frame, dlg)
    print("  pas de crash si on_play_toggle=None : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_pattern_properties_dialog ===")
    # Valeurs initiales
    test_initial_name()
    test_initial_start_bar()
    test_initial_num_bars()
    test_initial_num_steps()
    test_initial_looping_true()
    test_initial_looping_false()
    test_initial_action_courant()
    test_start_bar_clamped_to_num_bars()
    # Actions
    test_action_nouveau()
    test_action_doubler()
    test_action_diviser()
    # Mise à jour dynamique Début ↔ Longueur
    test_length_change_updates_start_count()
    test_length_change_preserves_start_selection()
    test_length_change_clamps_start_selection()
    test_length_change_updates_get_num_bars()
    # Modification des widgets
    test_set_name_via_ctrl()
    test_set_looping_false()
    test_set_steps_64()
    # Ctrl+P / on_play_toggle
    test_ctrl_p_calls_play_toggle()
    test_p_without_ctrl_does_not_call_toggle()
    test_other_key_does_not_call_toggle()
    test_ctrl_p_not_skipped()
    test_other_key_is_skipped()
    test_no_crash_without_play_toggle()
    print("Tous les tests : OK")
