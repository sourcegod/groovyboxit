#python3
"""
    File: tests/test_pad_properties_dialog.py
    Tests unitaires de PadPropertiesDialog : valeurs initiales, callbacks
    on_change / on_play / on_play_toggle, pas de 100 ms sur la durée.
    Date: Thu, 21/05/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wx
from ui.dialogs import PadPropertiesDialog


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class FakeEvent:
    def __init__(self, key=0, ctrl=False):
        self._key    = key
        self._ctrl   = ctrl
        self.skipped = False

    def GetKeyCode(self):  return self._key
    def ControlDown(self): return self._ctrl
    def Skip(self):        self.skipped = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT = dict(volume=75, pan=-20, mute=True, solo=False, duration_ms=500)


def make_dlg(on_change=None, on_play=None, on_play_toggle=None, **kwargs):
    params = {**DEFAULT, **kwargs}
    app    = wx.App(False)
    frame  = wx.Frame(None)
    dlg    = PadPropertiesDialog(
        frame, 3,
        params['volume'],
        params['pan'],
        params['mute'],
        params['solo'],
        params['duration_ms'],
        on_change=on_change,
        on_play=on_play,
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

def test_initial_duration_ms():
    app, frame, dlg = make_dlg()
    assert dlg.get_duration_ms() == 500
    teardown(app, frame, dlg)
    print("  get_duration_ms() == 500 (initial) : OK")

def test_initial_dur_prev():
    app, frame, dlg = make_dlg()
    assert dlg._dur_prev == 500
    teardown(app, frame, dlg)
    print("  _dur_prev == 500 (initial) : OK")


# ---------------------------------------------------------------------------
# Callback on_change
# ---------------------------------------------------------------------------

def test_on_change_receives_initial_values():
    received = []
    app, frame, dlg = make_dlg(on_change=lambda *a: received.append(a))
    dlg._on_check_change(FakeEvent())
    assert received == [(75, -20, True, False, 500)]
    teardown(app, frame, dlg)
    print("  on_change reçoit les valeurs initiales : OK")

def test_on_change_reflects_new_volume():
    received = []
    app, frame, dlg = make_dlg(on_change=lambda *a: received.append(a))
    dlg._vol.SetValue(50)
    dlg._on_spin_change(FakeEvent())
    assert received[-1][0] == 50   # volume
    teardown(app, frame, dlg)
    print("  on_change reflète le nouveau volume : OK")

def test_on_change_reflects_new_pan():
    received = []
    app, frame, dlg = make_dlg(on_change=lambda *a: received.append(a))
    dlg._pan.SetValue(30)
    dlg._on_spin_change(FakeEvent())
    assert received[-1][1] == 30   # pan
    teardown(app, frame, dlg)
    print("  on_change reflète le nouveau pan : OK")

def test_on_change_reflects_mute_unchecked():
    received = []
    app, frame, dlg = make_dlg(on_change=lambda *a: received.append(a))
    dlg._mute.SetValue(False)
    dlg._on_check_change(FakeEvent())
    assert received[-1][2] is False   # mute
    teardown(app, frame, dlg)
    print("  on_change reflète mute=False : OK")

def test_on_change_reflects_solo_checked():
    received = []
    app, frame, dlg = make_dlg(on_change=lambda *a: received.append(a))
    dlg._solo.SetValue(True)
    dlg._on_check_change(FakeEvent())
    assert received[-1][3] is True    # solo
    teardown(app, frame, dlg)
    print("  on_change reflète solo=True : OK")

def test_on_change_reflects_duration_after_dur_spin():
    received = []
    app, frame, dlg = make_dlg(on_change=lambda *a: received.append(a))
    dlg._dur.SetValue(501)           # simule flèche haut depuis 500
    dlg._on_dur_spin(FakeEvent())
    assert received[-1][4] == 600    # durée snappée
    teardown(app, frame, dlg)
    print("  on_change reflète la durée snappée : OK")

def test_on_check_change_skips_event():
    app, frame, dlg = make_dlg()
    ev = FakeEvent()
    dlg._on_check_change(ev)
    assert ev.skipped
    teardown(app, frame, dlg)
    print("  _on_check_change appelle event.Skip() : OK")

def test_on_spin_change_skips_event():
    app, frame, dlg = make_dlg()
    ev = FakeEvent()
    dlg._on_spin_change(ev)
    assert ev.skipped
    teardown(app, frame, dlg)
    print("  _on_spin_change appelle event.Skip() : OK")

def test_no_crash_without_on_change():
    app, frame, dlg = make_dlg(on_change=None)
    dlg._on_check_change(FakeEvent())
    dlg._on_spin_change(FakeEvent())
    dlg._dur.SetValue(501)
    dlg._on_dur_spin(FakeEvent())
    teardown(app, frame, dlg)
    print("  pas de crash si on_change=None : OK")


# ---------------------------------------------------------------------------
# Callback on_play
# ---------------------------------------------------------------------------

def test_on_spin_change_calls_on_play():
    played = []
    app, frame, dlg = make_dlg(on_play=lambda: played.append(1))
    dlg._on_spin_change(FakeEvent())
    assert played == [1]
    teardown(app, frame, dlg)
    print("  _on_spin_change appelle on_play : OK")

def test_on_dur_spin_calls_on_play():
    played = []
    app, frame, dlg = make_dlg(on_play=lambda: played.append(1))
    dlg._dur.SetValue(501)
    dlg._on_dur_spin(FakeEvent())
    assert played == [1]
    teardown(app, frame, dlg)
    print("  _on_dur_spin appelle on_play : OK")

def test_on_check_change_does_not_call_on_play():
    played = []
    app, frame, dlg = make_dlg(on_play=lambda: played.append(1))
    dlg._on_check_change(FakeEvent())
    assert played == []
    teardown(app, frame, dlg)
    print("  _on_check_change n'appelle pas on_play : OK")

def test_no_crash_without_on_play():
    app, frame, dlg = make_dlg(on_play=None)
    dlg._on_spin_change(FakeEvent())
    dlg._dur.SetValue(501)
    dlg._on_dur_spin(FakeEvent())
    teardown(app, frame, dlg)
    print("  pas de crash si on_play=None : OK")


# ---------------------------------------------------------------------------
# Pas de 100 ms (_on_dur_spin)
# ---------------------------------------------------------------------------

def test_dur_spin_up_snaps_to_next_100():
    app, frame, dlg = make_dlg(duration_ms=500)
    dlg._dur.SetValue(501)          # flèche haut depuis 500
    dlg._on_dur_spin(FakeEvent())
    assert dlg._dur.GetValue() == 600
    teardown(app, frame, dlg)
    print("  spin haut: 501 → snap 600 : OK")

def test_dur_spin_down_snaps_to_prev_100():
    app, frame, dlg = make_dlg(duration_ms=500)
    dlg._dur.SetValue(499)          # flèche bas depuis 500
    dlg._on_dur_spin(FakeEvent())
    assert dlg._dur.GetValue() == 400
    teardown(app, frame, dlg)
    print("  spin bas: 499 → snap 400 : OK")

def test_dur_spin_up_from_exact_multiple():
    app, frame, dlg = make_dlg(duration_ms=300)
    dlg._dur.SetValue(301)
    dlg._on_dur_spin(FakeEvent())
    assert dlg._dur.GetValue() == 400
    teardown(app, frame, dlg)
    print("  spin haut depuis multiple exact: 301 → 400 : OK")

def test_dur_spin_down_from_exact_multiple():
    app, frame, dlg = make_dlg(duration_ms=300)
    dlg._dur.SetValue(299)
    dlg._on_dur_spin(FakeEvent())
    assert dlg._dur.GetValue() == 200
    teardown(app, frame, dlg)
    print("  spin bas depuis multiple exact: 299 → 200 : OK")

def test_dur_spin_down_clamps_to_zero():
    app, frame, dlg = make_dlg(duration_ms=100)
    dlg._dur.SetValue(99)
    dlg._on_dur_spin(FakeEvent())
    assert dlg._dur.GetValue() == 0
    teardown(app, frame, dlg)
    print("  spin bas: 99 → clamp 0 : OK")

def test_dur_spin_up_clamps_to_max():
    app, frame, dlg = make_dlg(duration_ms=9900)
    dlg._dur.SetValue(9901)
    dlg._on_dur_spin(FakeEvent())
    assert dlg._dur.GetValue() == 9900
    teardown(app, frame, dlg)
    print("  spin haut: 9901 → clamp 9900 : OK")

def test_dur_spin_no_change_when_equal():
    app, frame, dlg = make_dlg(duration_ms=500)
    dlg._dur.SetValue(500)          # aucune variation
    dlg._on_dur_spin(FakeEvent())
    assert dlg._dur.GetValue() == 500
    teardown(app, frame, dlg)
    print("  spin sans variation: 500 → 500 : OK")

def test_dur_prev_updated_after_snap():
    app, frame, dlg = make_dlg(duration_ms=500)
    dlg._dur.SetValue(501)
    dlg._on_dur_spin(FakeEvent())
    assert dlg._dur_prev == 600
    teardown(app, frame, dlg)
    print("  _dur_prev mis à jour après snap : OK")

def test_dur_spin_sequence_up_twice():
    app, frame, dlg = make_dlg(duration_ms=500)
    dlg._dur.SetValue(501)
    dlg._on_dur_spin(FakeEvent())   # → 600
    dlg._dur.SetValue(601)
    dlg._on_dur_spin(FakeEvent())   # → 700
    assert dlg._dur.GetValue() == 700
    teardown(app, frame, dlg)
    print("  deux spins haut consécutifs: 500 → 600 → 700 : OK")

def test_dur_spin_sequence_down_twice():
    app, frame, dlg = make_dlg(duration_ms=700)
    dlg._dur.SetValue(699)
    dlg._on_dur_spin(FakeEvent())   # → 600
    dlg._dur.SetValue(599)
    dlg._on_dur_spin(FakeEvent())   # → 500
    assert dlg._dur.GetValue() == 500
    teardown(app, frame, dlg)
    print("  deux spins bas consécutifs: 700 → 600 → 500 : OK")

def test_dur_spin_zero_duration_allowed():
    app, frame, dlg = make_dlg(duration_ms=100)
    dlg._dur.SetValue(99)
    dlg._on_dur_spin(FakeEvent())
    assert dlg._dur.GetValue() == 0
    assert dlg.get_duration_ms() == 0
    teardown(app, frame, dlg)
    print("  durée 0 (fin du WAV) autorisée : OK")


# ---------------------------------------------------------------------------
# Callback on_play_toggle (Ctrl+P)
# ---------------------------------------------------------------------------

def test_ctrl_p_calls_play_toggle():
    toggled = []
    app, frame, dlg = make_dlg(on_play_toggle=lambda: toggled.append(1))
    dlg._on_key(FakeEvent(key=ord('P'), ctrl=True))
    assert toggled == [1]
    teardown(app, frame, dlg)
    print("  Ctrl+P appelle on_play_toggle : OK")

def test_p_without_ctrl_does_not_call_toggle():
    toggled = []
    app, frame, dlg = make_dlg(on_play_toggle=lambda: toggled.append(1))
    dlg._on_key(FakeEvent(key=ord('P'), ctrl=False))
    assert toggled == []
    teardown(app, frame, dlg)
    print("  P sans Ctrl n'appelle pas on_play_toggle : OK")

def test_ctrl_other_key_does_not_call_toggle():
    toggled = []
    app, frame, dlg = make_dlg(on_play_toggle=lambda: toggled.append(1))
    dlg._on_key(FakeEvent(key=ord('A'), ctrl=True))
    assert toggled == []
    teardown(app, frame, dlg)
    print("  Ctrl+A n'appelle pas on_play_toggle : OK")

def test_non_p_key_is_skipped():
    app, frame, dlg = make_dlg()
    ev = FakeEvent(key=ord('A'), ctrl=False)
    dlg._on_key(ev)
    assert ev.skipped
    teardown(app, frame, dlg)
    print("  autre touche passe à Skip() : OK")

def test_ctrl_p_not_skipped():
    app, frame, dlg = make_dlg()
    ev = FakeEvent(key=ord('P'), ctrl=True)
    dlg._on_key(ev)
    assert not ev.skipped
    teardown(app, frame, dlg)
    print("  Ctrl+P n'est pas passé à Skip() : OK")

def test_p_without_ctrl_is_skipped():
    app, frame, dlg = make_dlg()
    ev = FakeEvent(key=ord('P'), ctrl=False)
    dlg._on_key(ev)
    assert ev.skipped
    teardown(app, frame, dlg)
    print("  P sans Ctrl passe à Skip() : OK")

def test_no_crash_without_play_toggle():
    app, frame, dlg = make_dlg(on_play_toggle=None)
    dlg._on_key(FakeEvent(key=ord('P'), ctrl=True))
    teardown(app, frame, dlg)
    print("  pas de crash si on_play_toggle=None : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_pad_properties_dialog ===")
    # Valeurs initiales
    test_initial_volume()
    test_initial_pan()
    test_initial_mute_true()
    test_initial_solo_false()
    test_initial_duration_ms()
    test_initial_dur_prev()
    # Callback on_change
    test_on_change_receives_initial_values()
    test_on_change_reflects_new_volume()
    test_on_change_reflects_new_pan()
    test_on_change_reflects_mute_unchecked()
    test_on_change_reflects_solo_checked()
    test_on_change_reflects_duration_after_dur_spin()
    test_on_check_change_skips_event()
    test_on_spin_change_skips_event()
    test_no_crash_without_on_change()
    # Callback on_play
    test_on_spin_change_calls_on_play()
    test_on_dur_spin_calls_on_play()
    test_on_check_change_does_not_call_on_play()
    test_no_crash_without_on_play()
    # Pas de 100 ms
    test_dur_spin_up_snaps_to_next_100()
    test_dur_spin_down_snaps_to_prev_100()
    test_dur_spin_up_from_exact_multiple()
    test_dur_spin_down_from_exact_multiple()
    test_dur_spin_down_clamps_to_zero()
    test_dur_spin_up_clamps_to_max()
    test_dur_spin_no_change_when_equal()
    test_dur_prev_updated_after_snap()
    test_dur_spin_sequence_up_twice()
    test_dur_spin_sequence_down_twice()
    test_dur_spin_zero_duration_allowed()
    # Callback on_play_toggle
    test_ctrl_p_calls_play_toggle()
    test_p_without_ctrl_does_not_call_toggle()
    test_ctrl_other_key_does_not_call_toggle()
    test_non_p_key_is_skipped()
    test_ctrl_p_not_skipped()
    test_p_without_ctrl_is_skipped()
    test_no_crash_without_play_toggle()
    print("Tous les tests : OK")
