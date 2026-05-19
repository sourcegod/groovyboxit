#python3
"""
    File: tests/test_track_properties_dialog.py
    Tests unitaires de TrackPropertiesDialog : valeurs initiales, callbacks
    on_change / on_play_toggle, gestion des touches.
    Date: Tue, 19/05/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wx
from ui.dialogs import TrackPropertiesDialog


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class FakeRack:
    def labels(self):
        return [f"Slot_{i + 1:02d}" for i in range(16)]


class FakeEvent:
    def __init__(self, key=0):
        self._key    = key
        self.skipped = False

    def GetKeyCode(self): return self._key
    def Skip(self):       self.skipped = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT = dict(cur_slot_idx=2, volume=75, pan=-20, mute=True, solo=False)


def make_dlg(on_change=None, on_play_toggle=None, **kwargs):
    """Crée un wx.App + frame parent + TrackPropertiesDialog."""
    params = {**DEFAULT, **kwargs}
    app   = wx.App(False)
    frame = wx.Frame(None)
    dlg   = TrackPropertiesDialog(
        frame, 0, FakeRack(),
        params['cur_slot_idx'],
        params['volume'],
        params['pan'],
        params['mute'],
        params['solo'],
        on_change=on_change,
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

def test_initial_slot_idx():
    app, frame, dlg = make_dlg()
    assert dlg.get_slot_idx() == 2
    teardown(app, frame, dlg)
    print("  get_slot_idx() == 2 (initial) : OK")

def test_initial_volume():
    app, frame, dlg = make_dlg()
    assert dlg.get_volume() == 75
    teardown(app, frame, dlg)
    print("  get_volume() == 75 (initial) : OK")

def test_initial_pan():
    app, frame, dlg = make_dlg()
    assert dlg.get_pan() == -20
    teardown(app, frame, dlg)
    print("  get_pan() == -20 (initial) : OK")

def test_initial_mute_true():
    app, frame, dlg = make_dlg()
    assert dlg.get_mute() is True
    teardown(app, frame, dlg)
    print("  get_mute() == True (initial) : OK")

def test_initial_solo_false():
    app, frame, dlg = make_dlg()
    assert dlg.get_solo() is False
    teardown(app, frame, dlg)
    print("  get_solo() == False (initial) : OK")


# ---------------------------------------------------------------------------
# Callback on_change
# ---------------------------------------------------------------------------

def test_on_change_receives_initial_values_on_first_call():
    received = []
    app, frame, dlg = make_dlg(on_change=lambda *a: received.append(a))
    dlg._on_widget_change(FakeEvent())
    assert received == [(2, 75, -20, True, False)]
    teardown(app, frame, dlg)
    print("  on_change reçoit les valeurs initiales : OK")

def test_on_change_reflects_new_volume():
    received = []
    app, frame, dlg = make_dlg(on_change=lambda *a: received.append(a))
    dlg._vol.SetValue(50)
    dlg._on_widget_change(FakeEvent())
    assert received[-1][1] == 50   # volume
    teardown(app, frame, dlg)
    print("  on_change reflète le nouveau volume : OK")

def test_on_change_reflects_new_pan():
    received = []
    app, frame, dlg = make_dlg(on_change=lambda *a: received.append(a))
    dlg._pan.SetValue(30)
    dlg._on_widget_change(FakeEvent())
    assert received[-1][2] == 30   # pan
    teardown(app, frame, dlg)
    print("  on_change reflète le nouveau pan : OK")

def test_on_change_reflects_mute_unchecked():
    received = []
    app, frame, dlg = make_dlg(on_change=lambda *a: received.append(a))
    dlg._mute.SetValue(False)
    dlg._on_widget_change(FakeEvent())
    assert received[-1][3] is False   # mute
    teardown(app, frame, dlg)
    print("  on_change reflète mute=False : OK")

def test_on_change_reflects_solo_checked():
    received = []
    app, frame, dlg = make_dlg(on_change=lambda *a: received.append(a))
    dlg._solo.SetValue(True)
    dlg._on_widget_change(FakeEvent())
    assert received[-1][4] is True   # solo
    teardown(app, frame, dlg)
    print("  on_change reflète solo=True : OK")

def test_on_change_reflects_new_slot():
    received = []
    app, frame, dlg = make_dlg(on_change=lambda *a: received.append(a))
    dlg._slots.SetSelection(5)
    dlg._on_widget_change(FakeEvent())
    assert received[-1][0] == 5   # slot
    teardown(app, frame, dlg)
    print("  on_change reflète le nouveau slot : OK")

def test_on_change_skips_event():
    app, frame, dlg = make_dlg()
    ev = FakeEvent()
    dlg._on_widget_change(ev)
    assert ev.skipped
    teardown(app, frame, dlg)
    print("  _on_widget_change appelle event.Skip() : OK")

def test_no_crash_without_on_change_callback():
    app, frame, dlg = make_dlg(on_change=None)
    dlg._on_widget_change(FakeEvent())   # ne doit pas lever d'exception
    teardown(app, frame, dlg)
    print("  pas de crash si on_change=None : OK")


# ---------------------------------------------------------------------------
# Callback on_play_toggle (touche P)
# ---------------------------------------------------------------------------

def test_p_key_calls_play_toggle():
    toggled = []
    app, frame, dlg = make_dlg(on_play_toggle=lambda: toggled.append(1))
    dlg._on_key(FakeEvent(key=ord('P')))
    assert toggled == [1]
    teardown(app, frame, dlg)
    print("  touche P appelle on_play_toggle : OK")

def test_non_p_key_does_not_call_play_toggle():
    toggled = []
    app, frame, dlg = make_dlg(on_play_toggle=lambda: toggled.append(1))
    dlg._on_key(FakeEvent(key=ord('A')))
    assert toggled == []
    teardown(app, frame, dlg)
    print("  autre touche n'appelle pas on_play_toggle : OK")

def test_non_p_key_is_skipped():
    app, frame, dlg = make_dlg()
    ev = FakeEvent(key=ord('A'))
    dlg._on_key(ev)
    assert ev.skipped
    teardown(app, frame, dlg)
    print("  autre touche passe à Skip() : OK")

def test_p_key_not_skipped():
    app, frame, dlg = make_dlg()
    ev = FakeEvent(key=ord('P'))
    dlg._on_key(ev)
    assert not ev.skipped
    teardown(app, frame, dlg)
    print("  touche P n'est pas passée à Skip() : OK")

def test_no_crash_without_play_toggle_callback():
    app, frame, dlg = make_dlg(on_play_toggle=None)
    dlg._on_key(FakeEvent(key=ord('P')))   # ne doit pas lever d'exception
    teardown(app, frame, dlg)
    print("  pas de crash si on_play_toggle=None : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_track_properties_dialog ===")
    # Valeurs initiales
    test_initial_slot_idx()
    test_initial_volume()
    test_initial_pan()
    test_initial_mute_true()
    test_initial_solo_false()
    # Callback on_change
    test_on_change_receives_initial_values_on_first_call()
    test_on_change_reflects_new_volume()
    test_on_change_reflects_new_pan()
    test_on_change_reflects_mute_unchecked()
    test_on_change_reflects_solo_checked()
    test_on_change_reflects_new_slot()
    test_on_change_skips_event()
    test_no_crash_without_on_change_callback()
    # Callback on_play_toggle
    test_p_key_calls_play_toggle()
    test_non_p_key_does_not_call_play_toggle()
    test_non_p_key_is_skipped()
    test_p_key_not_skipped()
    test_no_crash_without_play_toggle_callback()
    print("Tous les tests : OK")
