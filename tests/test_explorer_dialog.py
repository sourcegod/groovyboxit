#python3
"""
    File: tests/test_explorer_dialog.py
    Tests unitaires de ExplorerDialog : contenu de la liste, sélection initiale,
    get_selection() par item, double-clic → EndModal(ID_OK).
    Date: Thu, 28/05/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wx
from ui.dialogs import ExplorerDialog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_dlg():
    frame = wx.Frame(None)
    dlg   = ExplorerDialog(frame)
    return frame, dlg


def teardown(frame, dlg):
    dlg.Destroy()
    frame.Destroy()


# ---------------------------------------------------------------------------
# Constante ITEMS
# ---------------------------------------------------------------------------

def test_items_constant():
    assert ExplorerDialog.ITEMS == ["Projects", "Preset", "Kit", "Patch", "Sound"]
    print("  ITEMS == ['Projects', 'Preset', 'Kit', 'Patch', 'Sound'] : OK")


def test_items_count():
    assert len(ExplorerDialog.ITEMS) == 5
    print("  len(ITEMS) == 5 : OK")


# ---------------------------------------------------------------------------
# Titre et contenu du widget
# ---------------------------------------------------------------------------

def test_title():
    frame, dlg = make_dlg()
    assert dlg.GetTitle() == "Explorateur"
    teardown(frame, dlg)
    print("  GetTitle() == 'Explorateur' : OK")


def test_listbox_count():
    frame, dlg = make_dlg()
    assert dlg._listbox.GetCount() == 5
    teardown(frame, dlg)
    print("  listbox.GetCount() == 5 : OK")


def test_listbox_items_match_constant():
    frame, dlg = make_dlg()
    items = [dlg._listbox.GetString(i) for i in range(dlg._listbox.GetCount())]
    assert items == ExplorerDialog.ITEMS
    teardown(frame, dlg)
    print("  items dans la listbox == ITEMS : OK")


# ---------------------------------------------------------------------------
# Sélection initiale
# ---------------------------------------------------------------------------

def test_initial_selection_index():
    frame, dlg = make_dlg()
    assert dlg._listbox.GetSelection() == 0
    teardown(frame, dlg)
    print("  sélection initiale index == 0 : OK")


def test_initial_get_selection_returns_preset():
    frame, dlg = make_dlg()
    assert dlg.get_selection() == "Projects"
    teardown(frame, dlg)
    print("  get_selection() == 'Projects' (initial) : OK")


# ---------------------------------------------------------------------------
# get_selection() pour chaque item
# ---------------------------------------------------------------------------

def test_get_selection_projects():
    frame, dlg = make_dlg()
    dlg._listbox.SetSelection(0)
    assert dlg.get_selection() == "Projects"
    teardown(frame, dlg)
    print("  get_selection() == 'Projects' après SetSelection(0) : OK")


def test_get_selection_preset():
    frame, dlg = make_dlg()
    dlg._listbox.SetSelection(1)
    assert dlg.get_selection() == "Preset"
    teardown(frame, dlg)
    print("  get_selection() == 'Preset' après SetSelection(1) : OK")


def test_get_selection_kit():
    frame, dlg = make_dlg()
    dlg._listbox.SetSelection(2)
    assert dlg.get_selection() == "Kit"
    teardown(frame, dlg)
    print("  get_selection() == 'Kit' après SetSelection(2) : OK")


def test_get_selection_patch():
    frame, dlg = make_dlg()
    dlg._listbox.SetSelection(3)
    assert dlg.get_selection() == "Patch"
    teardown(frame, dlg)
    print("  get_selection() == 'Patch' après SetSelection(3) : OK")


def test_get_selection_sound():
    frame, dlg = make_dlg()
    dlg._listbox.SetSelection(4)
    assert dlg.get_selection() == "Sound"
    teardown(frame, dlg)
    print("  get_selection() == 'Sound' après SetSelection(4) : OK")


# ---------------------------------------------------------------------------
# Double-clic → EndModal(wx.ID_OK)
# ---------------------------------------------------------------------------

def test_dclick_calls_end_modal_ok():
    frame, dlg = make_dlg()
    called = []
    dlg.EndModal = lambda rc: called.append(rc)
    evt = wx.CommandEvent(wx.wxEVT_COMMAND_LISTBOX_DOUBLECLICKED,
                          dlg._listbox.GetId())
    dlg._listbox.GetEventHandler().ProcessEvent(evt)
    assert called == [wx.ID_OK]
    teardown(frame, dlg)
    print("  double-clic appelle EndModal(wx.ID_OK) : OK")


def test_dclick_on_kit_calls_end_modal():
    frame, dlg = make_dlg()
    dlg._listbox.SetSelection(2)
    called = []
    dlg.EndModal = lambda rc: called.append(rc)
    evt = wx.CommandEvent(wx.wxEVT_COMMAND_LISTBOX_DOUBLECLICKED,
                          dlg._listbox.GetId())
    dlg._listbox.GetEventHandler().ProcessEvent(evt)
    assert called == [wx.ID_OK]
    teardown(frame, dlg)
    print("  double-clic sur 'Kit' appelle EndModal(wx.ID_OK) : OK")


def test_dclick_preserves_selection():
    frame, dlg = make_dlg()
    dlg._listbox.SetSelection(3)
    dlg.EndModal = lambda rc: None
    evt = wx.CommandEvent(wx.wxEVT_COMMAND_LISTBOX_DOUBLECLICKED,
                          dlg._listbox.GetId())
    dlg._listbox.GetEventHandler().ProcessEvent(evt)
    assert dlg.get_selection() == "Patch"
    teardown(frame, dlg)
    print("  get_selection() reste 'Patch' après double-clic : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_explorer_dialog ===")
    # Constante
    test_items_constant()
    test_items_count()
    # Titre et contenu
    test_title()
    test_listbox_count()
    test_listbox_items_match_constant()
    # Sélection initiale
    test_initial_selection_index()
    test_initial_get_selection_returns_preset()
    # get_selection() par item
    test_get_selection_projects()
    test_get_selection_preset()
    test_get_selection_kit()
    test_get_selection_patch()
    test_get_selection_sound()
    # Double-clic
    test_dclick_calls_end_modal_ok()
    test_dclick_on_kit_calls_end_modal()
    test_dclick_preserves_selection()
    print("Tous les tests : OK")
