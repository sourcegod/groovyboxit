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

DEFAULT = dict(cur_slot_idx=2, volume=75, pan=-20, mute=True, solo=False, channel=3)


def make_dlg(on_change=None, on_play_toggle=None, channel_after_slot=None,
             slot_program=None, **kwargs):
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
        channel=params['channel'],
        channel_after_slot=channel_after_slot,
        slot_program=slot_program,
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
    # canal en 6e (10f1), programme en 7e (10h3) : None sans slot_program
    assert received == [(2, 75, -20, True, False, 3, None)]
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

def test_non_p_key_does_not_call_play_toggle():
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

def test_no_crash_without_play_toggle_callback():
    app, frame, dlg = make_dlg(on_play_toggle=None)
    dlg._on_key(FakeEvent(key=ord('P'), ctrl=True))   # ne doit pas lever d'exception
    teardown(app, frame, dlg)
    print("  pas de crash si on_play_toggle=None : OK")


# ---------------------------------------------------------------------------
# Canal MIDI (Phase 7 étape 10f1)
# ---------------------------------------------------------------------------

def _fake_kit_rule(slot_idx, channel):
    """Règle simulée : slot 0 = kit → canal 10 ; autre slot sur 10 → canal 4."""
    if slot_idx == 0:
        return 9
    return 3 if channel == 9 else channel

def test_initial_channel():
    app, frame, dlg = make_dlg()
    assert dlg.get_channel() == 3
    assert dlg._channels.GetCount() == 16
    assert dlg._channels.GetString(0) == "Canal 1"
    assert dlg._channels.GetString(15) == "Canal 16"
    teardown(app, frame, dlg)
    print("  liste Canal : 16 entrées, canal initial sélectionné : OK")

def test_channel_list_follows_slots_in_tab_order():
    app, frame, dlg = make_dlg()
    order = [w for w in dlg.GetChildren() if w.AcceptsFocus()]
    order = list(dlg.GetChildren())   # ordre de création = ordre Tab
    assert order.index(dlg._channels) > order.index(dlg._slots)
    assert order.index(dlg._programs) > order.index(dlg._channels)
    assert order.index(dlg._vol) > order.index(dlg._programs)
    focusable = [w for w in order if w.AcceptsFocus()]
    assert focusable.index(dlg._channels) == focusable.index(dlg._slots) + 1
    teardown(app, frame, dlg)
    print("  ordre Tab : Slots → Canal → Programme → Volume : OK")

def test_on_change_reflects_new_channel():
    received = []
    app, frame, dlg = make_dlg(on_change=lambda *a: received.append(a))
    dlg._channels.SetSelection(11)
    dlg._on_widget_change(FakeEvent())
    assert received[-1][5] == 11
    assert dlg.get_channel() == 11
    teardown(app, frame, dlg)
    print("  on_change reflète le canal choisi : OK")

def test_slot_change_to_kit_applies_channel_rule():
    received = []
    app, frame, dlg = make_dlg(on_change=lambda *a: received.append(a),
                               channel_after_slot=_fake_kit_rule)
    dlg._slots.SetSelection(0)
    ev = FakeEvent()
    dlg._on_slot_change(ev)
    assert dlg.get_channel() == 9
    assert received[-1][0] == 0 and received[-1][5] == 9
    assert ev.skipped
    teardown(app, frame, dlg)
    print("  slot kit → canal 10 dans la liste, aperçu transmis : OK")

def test_slot_change_back_from_kit_restores_channel():
    app, frame, dlg = make_dlg(channel_after_slot=_fake_kit_rule, channel=9)
    dlg._slots.SetSelection(5)
    dlg._on_slot_change(FakeEvent())
    assert dlg.get_channel() == 3
    teardown(app, frame, dlg)
    print("  slot synthé depuis le canal 10 → canal par défaut : OK")

def test_slot_change_without_rule_keeps_channel():
    app, frame, dlg = make_dlg()
    dlg._slots.SetSelection(0)
    dlg._on_slot_change(FakeEvent())
    assert dlg.get_channel() == 3
    teardown(app, frame, dlg)
    print("  sans règle : canal inchangé au changement de slot : OK")

def test_channel_change_does_not_call_rule():
    calls = []
    app, frame, dlg = make_dlg(channel_after_slot=lambda s, c: calls.append((s, c)) or c)
    dlg._channels.SetSelection(7)
    dlg._on_widget_change(FakeEvent())
    assert calls == [] and dlg.get_channel() == 7
    teardown(app, frame, dlg)
    print("  choix manuel du canal : règle non appliquée : OK")


# ---------------------------------------------------------------------------
# Programme GM du slot (Phase 7 étape 10h3)
# ---------------------------------------------------------------------------

def _fake_slot_program(slot_idx):
    """Slot 0 = kit (TR-808 Kit, 25), slot 2 = synthé (Drawbar Organ, 16),
    slot 5 = synthé sans programme valide, autres = vides."""
    return {0: ("kit", 25), 2: ("synth", 16), 5: ("synth", None)}.get(slot_idx, (None, None))

def test_programs_list_for_synth_slot():
    app, frame, dlg = make_dlg(slot_program=_fake_slot_program)   # slot initial 2
    assert dlg._programs.GetCount() == 128
    assert dlg._programs.GetString(0) == "1 - Acoustic Grand Piano"
    assert dlg._programs.GetString(127) == "128 - Gunshot"
    assert dlg._programs.IsEnabled()
    assert dlg.get_program() == 16
    assert dlg._programs.GetStringSelection() == "17 - Drawbar Organ"
    teardown(app, frame, dlg)
    print("  slot synthé : 128 instruments GM, programme du slot sélectionné : OK")

def test_programs_list_for_kit_slot():
    app, frame, dlg = make_dlg(slot_program=_fake_slot_program, cur_slot_idx=0)
    assert dlg._programs.GetCount() == 9
    assert dlg._programs.GetString(0) == "1 - Standard Kit"
    assert dlg._programs.GetString(8) == "57 - SFX Kit"
    assert dlg.get_program() == 25
    assert dlg._programs.GetStringSelection() == "26 - TR-808 Kit"
    teardown(app, frame, dlg)
    print("  slot kit : 9 kits GM2, kit du slot sélectionné : OK")

def test_programs_list_disabled_for_empty_slot():
    app, frame, dlg = make_dlg(slot_program=_fake_slot_program, cur_slot_idx=7)
    assert dlg._programs.GetCount() == 0
    assert not dlg._programs.IsEnabled()
    assert dlg.get_program() is None
    teardown(app, frame, dlg)
    print("  slot vide : liste vide et désactivée, programme None : OK")

def test_programs_list_disabled_without_callback():
    app, frame, dlg = make_dlg()
    assert not dlg._programs.IsEnabled() and dlg.get_program() is None
    teardown(app, frame, dlg)
    print("  sans slot_program : liste désactivée : OK")

def test_program_without_valid_value_has_no_selection():
    app, frame, dlg = make_dlg(slot_program=_fake_slot_program, cur_slot_idx=5)
    assert dlg._programs.GetCount() == 128
    assert dlg.get_program() is None
    teardown(app, frame, dlg)
    print("  programme inconnu : liste remplie, aucune sélection : OK")

def test_program_list_follows_channel_in_tab_order():
    app, frame, dlg = make_dlg(slot_program=_fake_slot_program)
    focusable = [w for w in dlg.GetChildren() if w.AcceptsFocus()]
    assert focusable.index(dlg._programs) == focusable.index(dlg._channels) + 1
    assert focusable.index(dlg._vol) == focusable.index(dlg._programs) + 1
    teardown(app, frame, dlg)
    print("  ordre Tab avec programme actif : Canal → Programme → Volume : OK")

def test_slot_change_reloads_programs_synth_to_kit_and_back():
    received = []
    app, frame, dlg = make_dlg(on_change=lambda *a: received.append(a),
                               slot_program=_fake_slot_program)
    dlg._slots.SetSelection(0)
    dlg._on_slot_change(FakeEvent())
    assert dlg._programs.GetCount() == 9 and dlg.get_program() == 25
    assert received[-1][6] == 25
    dlg._slots.SetSelection(7)
    dlg._on_slot_change(FakeEvent())
    assert not dlg._programs.IsEnabled() and received[-1][6] is None
    dlg._slots.SetSelection(2)
    dlg._on_slot_change(FakeEvent())
    assert dlg._programs.GetCount() == 128 and dlg._programs.IsEnabled()
    assert dlg.get_program() == 16
    teardown(app, frame, dlg)
    print("  changement de slot : liste rechargée (synthé ↔ kit ↔ vide) : OK")

def test_on_change_reflects_chosen_program():
    received = []
    app, frame, dlg = make_dlg(on_change=lambda *a: received.append(a),
                               slot_program=_fake_slot_program, cur_slot_idx=0)
    dlg._programs.SetSelection(3)          # 4e kit : Electronic Kit, programme 24
    dlg._on_widget_change(FakeEvent())
    assert received[-1][6] == 24 and dlg.get_program() == 24
    teardown(app, frame, dlg)
    print("  on_change reçoit le programme choisi (index → numéro de kit) : OK")


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
    # Callback on_play_toggle (Ctrl+P)
    test_ctrl_p_calls_play_toggle()
    test_p_without_ctrl_does_not_call_toggle()
    test_non_p_key_does_not_call_play_toggle()
    test_non_p_key_is_skipped()
    test_ctrl_p_not_skipped()
    test_p_without_ctrl_is_skipped()
    test_no_crash_without_play_toggle_callback()
    # Canal MIDI
    test_initial_channel()
    test_channel_list_follows_slots_in_tab_order()
    test_on_change_reflects_new_channel()
    test_slot_change_to_kit_applies_channel_rule()
    test_slot_change_back_from_kit_restores_channel()
    test_slot_change_without_rule_keeps_channel()
    test_channel_change_does_not_call_rule()
    # Programme GM du slot
    test_programs_list_for_synth_slot()
    test_programs_list_for_kit_slot()
    test_programs_list_disabled_for_empty_slot()
    test_programs_list_disabled_without_callback()
    test_program_without_valid_value_has_no_selection()
    test_program_list_follows_channel_in_tab_order()
    test_slot_change_reloads_programs_synth_to_kit_and_back()
    test_on_change_reflects_chosen_program()
    print("Tous les tests : OK")
