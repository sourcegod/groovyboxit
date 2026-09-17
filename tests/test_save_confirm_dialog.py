#python3
"""
    File: tests/test_save_confirm_dialog.py
    Tests — SaveConfirmDialog (Phase 6 étape 11, correctif régression) :
    Entrée valide le bouton focus, raccourcis O/Y/N/A/C, garde-fou anti
    double EndModal. Bug d'origine (introduit étape 7l, jamais couvert par
    des tests) : Entrée ne validait aucun bouton, raccourcis o/a/c absents,
    Y/N fonctionnaient mais un second EndModal pouvait écraser le résultat.
    Date: Thu, 17/09/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wx
from ui.dialogs import SaveConfirmDialog


class FakeKeyEvent:
    def __init__(self, key):
        self._key    = key
        self.skipped = False

    def GetKeyCode(self):  return self._key
    def Skip(self):        self.skipped = True


def make_dlg():
    app   = wx.App(False)
    frame = wx.Frame(None)
    dlg   = SaveConfirmDialog(frame, "Message", "Titre")
    results = []
    dlg.EndModal = lambda rc: results.append(rc)
    return app, frame, dlg, results


def teardown(app, frame, dlg):
    dlg.Destroy()
    frame.Destroy()
    app.Destroy()


# ---------------------------------------------------------------------------
# Entrée : valide le bouton qui a le focus
# ---------------------------------------------------------------------------

def test_enter_validates_focused_yes_button():
    app, frame, dlg, results = make_dlg()
    dlg._yes_btn.SetFocus()
    dlg._on_key(FakeKeyEvent(wx.WXK_RETURN))
    assert results == [wx.ID_YES]
    teardown(app, frame, dlg)


def test_enter_validates_focused_no_button():
    app, frame, dlg, results = make_dlg()
    dlg._no_btn.SetFocus()
    dlg._on_key(FakeKeyEvent(wx.WXK_RETURN))
    assert results == [wx.ID_NO]
    teardown(app, frame, dlg)


def test_enter_validates_focused_cancel_button():
    app, frame, dlg, results = make_dlg()
    dlg._cancel_btn.SetFocus()
    dlg._on_key(FakeKeyEvent(wx.WXK_RETURN))
    assert results == [wx.ID_CANCEL]
    teardown(app, frame, dlg)


def test_numpad_enter_also_validates_focused_button():
    app, frame, dlg, results = make_dlg()
    dlg._no_btn.SetFocus()
    dlg._on_key(FakeKeyEvent(wx.WXK_NUMPAD_ENTER))
    assert results == [wx.ID_NO]
    teardown(app, frame, dlg)


def test_enter_defaults_to_yes_when_no_button_focused():
    app, frame, dlg, results = make_dlg()
    frame.SetFocus()   # focus hors des 3 boutons du dialog
    dlg._on_key(FakeKeyEvent(wx.WXK_RETURN))
    assert results == [wx.ID_YES]
    teardown(app, frame, dlg)


# ---------------------------------------------------------------------------
# Raccourcis lettres : O/Y = Oui, N = Non, A/C = Annuler, Échap = Annuler
# ---------------------------------------------------------------------------

def test_shortcut_o_selects_yes():
    app, frame, dlg, results = make_dlg()
    dlg._on_key(FakeKeyEvent(ord('O')))
    assert results == [wx.ID_YES]
    teardown(app, frame, dlg)


def test_shortcut_y_selects_yes():
    app, frame, dlg, results = make_dlg()
    dlg._on_key(FakeKeyEvent(ord('Y')))
    assert results == [wx.ID_YES]
    teardown(app, frame, dlg)


def test_shortcut_n_selects_no():
    app, frame, dlg, results = make_dlg()
    dlg._on_key(FakeKeyEvent(ord('N')))
    assert results == [wx.ID_NO]
    teardown(app, frame, dlg)


def test_shortcut_a_selects_cancel():
    app, frame, dlg, results = make_dlg()
    dlg._on_key(FakeKeyEvent(ord('A')))
    assert results == [wx.ID_CANCEL]
    teardown(app, frame, dlg)


def test_shortcut_c_selects_cancel():
    app, frame, dlg, results = make_dlg()
    dlg._on_key(FakeKeyEvent(ord('C')))
    assert results == [wx.ID_CANCEL]
    teardown(app, frame, dlg)


def test_escape_selects_cancel():
    app, frame, dlg, results = make_dlg()
    dlg._on_key(FakeKeyEvent(wx.WXK_ESCAPE))
    assert results == [wx.ID_CANCEL]
    teardown(app, frame, dlg)


def test_unhandled_key_skips():
    app, frame, dlg, results = make_dlg()
    evt = FakeKeyEvent(ord('Z'))
    dlg._on_key(evt)
    assert results == []
    assert evt.skipped is True
    teardown(app, frame, dlg)


# ---------------------------------------------------------------------------
# Garde-fou anti double EndModal (bug signalé : N sauvegardait quand même,
# cohérent avec un second EndModal écrasant le résultat déjà renvoyé)
# ---------------------------------------------------------------------------

def test_second_key_after_answer_is_ignored():
    app, frame, dlg, results = make_dlg()
    dlg._on_key(FakeKeyEvent(ord('N')))
    dlg._on_key(FakeKeyEvent(ord('O')))   # ne doit pas écraser le résultat
    assert results == [wx.ID_NO]
    teardown(app, frame, dlg)


def test_button_click_after_key_answer_is_ignored():
    app, frame, dlg, results = make_dlg()
    dlg._on_key(FakeKeyEvent(ord('N')))
    dlg._end(wx.ID_YES)   # simule un clic quasi simultané sur Oui
    assert results == [wx.ID_NO]
    teardown(app, frame, dlg)


def test_button_click_calls_end():
    app, frame, dlg, results = make_dlg()
    dlg._end(wx.ID_NO)
    assert results == [wx.ID_NO]
    teardown(app, frame, dlg)
