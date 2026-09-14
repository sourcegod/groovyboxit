#python3
"""
    File: tests/test_event_filter_dialog.py
    Tests unitaires — EventFilterDialog (Phase 6 étape 8a-11) : valeurs par
    défaut, get_criteria(), activation/désactivation des groupes, types
    "à venir"/indisponibles en MODE_NOTES, Effacer le filtre, boutons
    on_action (Ok/Appliquer/Ajouter/Supprimer/Réinitialiser), Tab order,
    Escape.
    Date: Mon, 14/09/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wx
from ui.dialogs import EventFilterDialog


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class FakeKeyEvent:
    def __init__(self, key=0, ctrl=False, shift=False, alt=False, unicode_key=None):
        self._key    = key
        self._ctrl   = ctrl
        self._shift  = shift
        self._alt    = alt
        self._ukey   = unicode_key if unicode_key is not None else key
        self.skipped = False

    def GetKeyCode(self):    return self._key
    def GetUnicodeKey(self): return self._ukey
    def ControlDown(self):   return self._ctrl
    def ShiftDown(self):     return self._shift
    def AltDown(self):       return self._alt
    def Skip(self):          self.skipped = True


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

# num_bars=2, num_steps=16 → total=32 steps ; steps_per_beat = 16//4 = 4
NUM_BARS  = 2
NUM_BEATS = 4
NUM_STEPS = 16
TOTAL     = NUM_BARS * NUM_STEPS   # 32

MODE_NOTES = 0
MODE_ALL   = 1


def _events():
    return [
        {"type": "note", "offset": 0, "pad": 60, "vel": 100, "bar": 0, "step": 0, "track": 0},
        {"type": "bend", "offset": 2, "value": -200, "bar": 0, "step": 2, "track": 0},
    ]


def make_dlg(events=None, lim_left=None, lim_right=None, view_mode=MODE_ALL,
             state=None, on_action=None):
    # Une seule wx.App pour toute la session (conftest.py, fixture autouse) :
    # ne pas en créer/détruire une par test ici (cf. test_explorer_dialog.py),
    # sous peine d'invalider le pointeur "app courante" pour les fichiers de
    # tests suivants dans la même session pytest.
    app   = wx.GetApp()
    frame = wx.Frame(None)
    dlg   = EventFilterDialog(
        frame,
        events    = events if events is not None else _events(),
        num_bars  = NUM_BARS,
        num_beats = NUM_BEATS,
        num_steps = NUM_STEPS,
        lim_left  = lim_left,
        lim_right = lim_right,
        view_mode = view_mode,
        state     = state,
        on_action = on_action,
    )
    return app, frame, dlg


def teardown(app, frame, dlg):
    dlg.Destroy()
    frame.Destroy()


# ---------------------------------------------------------------------------
# Valeurs par défaut
# ---------------------------------------------------------------------------

def test_default_type_is_all():
    app, frame, dlg = make_dlg()
    assert dlg._type_lb.GetSelection() == 0
    teardown(app, frame, dlg)


def test_default_active_checked():
    app, frame, dlg = make_dlg()
    assert dlg._active_cb.GetValue() is True
    teardown(app, frame, dlg)


def test_default_invert_unchecked():
    app, frame, dlg = make_dlg()
    assert dlg._invert_cb.GetValue() is False
    teardown(app, frame, dlg)


def test_default_note_bounds_full_range():
    app, frame, dlg = make_dlg()
    assert dlg._note_lo_lb.GetSelection() == 0
    assert dlg._note_hi_lb.GetSelection() == 127
    teardown(app, frame, dlg)


def test_default_velocity_bounds_full_range():
    app, frame, dlg = make_dlg()
    assert dlg._vel_lo_spin.GetValue() == 0
    assert dlg._vel_hi_spin.GetValue() == 127
    teardown(app, frame, dlg)


def test_default_pitch_bounds_full_range():
    app, frame, dlg = make_dlg()
    assert dlg._pitch_lo_spin.GetValue() == -8192
    assert dlg._pitch_hi_spin.GetValue() == 8191
    teardown(app, frame, dlg)


def test_default_position_full_range_without_limiters():
    app, frame, dlg = make_dlg(lim_left=None, lim_right=None)
    assert dlg._pos_from_ctrl.GetValue() == dlg._bbt.fmt(0)
    assert dlg._pos_to_ctrl.GetValue()   == dlg._bbt.fmt(TOTAL - 1)
    teardown(app, frame, dlg)


def test_default_position_prefilled_with_limiters():
    app, frame, dlg = make_dlg(lim_left=4, lim_right=20)
    assert dlg._pos_from_ctrl.GetValue() == dlg._bbt.fmt(4)
    assert dlg._pos_to_ctrl.GetValue()   == dlg._bbt.fmt(20)
    teardown(app, frame, dlg)


# ---------------------------------------------------------------------------
# get_criteria()
# ---------------------------------------------------------------------------

def test_get_criteria_default():
    app, frame, dlg = make_dlg()
    c = dlg.get_criteria()
    assert c["active"] is True
    assert c["invert"] is False
    assert c["etype_filter"] == "all"
    assert c["note_lo"] == 0 and c["note_hi"] == 127
    assert c["vel_lo"]  == 0 and c["vel_hi"]  == 127
    assert c["bend_lo"] == -8192 and c["bend_hi"] == 8191
    assert c["pos_from"] == 0 and c["pos_to"] == TOTAL - 1
    teardown(app, frame, dlg)


def test_get_criteria_reflects_widget_changes():
    app, frame, dlg = make_dlg()
    dlg._type_lb.SetSelection(1)   # Notes
    dlg._note_lo_lb.SetSelection(60)
    dlg._note_hi_lb.SetSelection(72)
    dlg._vel_lo_spin.SetValue(10)
    dlg._vel_hi_spin.SetValue(100)
    dlg._active_cb.SetValue(False)
    dlg._invert_cb.SetValue(True)
    c = dlg.get_criteria()
    assert c["etype_filter"] == "note"
    assert c["note_lo"] == 60 and c["note_hi"] == 72
    assert c["vel_lo"]  == 10 and c["vel_hi"]  == 100
    assert c["active"] is False
    assert c["invert"] is True
    teardown(app, frame, dlg)


def test_get_criteria_pitch_bend_type():
    app, frame, dlg = make_dlg()
    dlg._type_lb.SetSelection(2)   # Pitch Bend
    dlg._pitch_lo_spin.SetValue(-100)
    dlg._pitch_hi_spin.SetValue(100)
    c = dlg.get_criteria()
    assert c["etype_filter"] == "bend"
    assert c["bend_lo"] == -100 and c["bend_hi"] == 100
    teardown(app, frame, dlg)


def test_get_criteria_mod_type():
    app, frame, dlg = make_dlg()
    dlg._type_lb.SetSelection(3)   # Mod Wheel
    c = dlg.get_criteria()
    assert c["etype_filter"] == "mod"
    teardown(app, frame, dlg)


# ---------------------------------------------------------------------------
# État initial depuis `state` (persistance)
# ---------------------------------------------------------------------------

def test_state_prefills_widgets():
    state = {
        "active": False, "invert": True, "etype_filter": "note",
        "note_lo": 40, "note_hi": 80, "vel_lo": 20, "vel_hi": 110,
        "bend_lo": -500, "bend_hi": 500, "pos_from": 2, "pos_to": 10,
    }
    app, frame, dlg = make_dlg(state=state)
    assert dlg._active_cb.GetValue() is False
    assert dlg._invert_cb.GetValue() is True
    assert dlg._type_lb.GetSelection() == 1   # note
    assert dlg._note_lo_lb.GetSelection() == 40
    assert dlg._note_hi_lb.GetSelection() == 80
    assert dlg._vel_lo_spin.GetValue() == 20
    assert dlg._vel_hi_spin.GetValue() == 110
    assert dlg._pos_from_ctrl.GetValue() == dlg._bbt.fmt(2)
    assert dlg._pos_to_ctrl.GetValue()   == dlg._bbt.fmt(10)
    teardown(app, frame, dlg)


# ---------------------------------------------------------------------------
# Type "à venir" (désactivé) — revert + statut
# ---------------------------------------------------------------------------

def test_selecting_to_come_type_reverts_to_last_valid():
    app, frame, dlg = make_dlg()
    dlg._type_lb.SetSelection(1)   # Notes (valide)
    dlg._on_type_change(None)
    dlg._type_lb.SetSelection(4)   # "(à venir) CC générique"
    dlg._on_type_change(None)
    assert dlg._type_lb.GetSelection() == 1
    assert "indisponible" in dlg._status_ctrl.GetString(0).lower()
    teardown(app, frame, dlg)


def test_selecting_to_come_type_does_not_crash():
    app, frame, dlg = make_dlg()
    for idx in range(4, 9):
        dlg._type_lb.SetSelection(idx)
        dlg._on_type_change(None)
    teardown(app, frame, dlg)


# ---------------------------------------------------------------------------
# MODE_NOTES désactive Bend/Mod en plus des "à venir"
# ---------------------------------------------------------------------------

def test_mode_notes_disables_bend_and_mod():
    app, frame, dlg = make_dlg(view_mode=MODE_NOTES)
    assert dlg._type_unavailable(2) is True    # bend
    assert dlg._type_unavailable(3) is True    # mod
    assert dlg._type_unavailable(1) is False   # notes reste dispo
    teardown(app, frame, dlg)


def test_mode_all_keeps_bend_and_mod_available():
    app, frame, dlg = make_dlg(view_mode=MODE_ALL)
    assert dlg._type_unavailable(2) is False
    assert dlg._type_unavailable(3) is False
    teardown(app, frame, dlg)


def test_selecting_bend_in_mode_notes_reverts_with_specific_message():
    app, frame, dlg = make_dlg(view_mode=MODE_NOTES)
    dlg._type_lb.SetSelection(2)   # Pitch Bend
    dlg._on_type_change(None)
    assert dlg._type_lb.GetSelection() == 0   # revert au dernier valide (Tous)
    assert "mode notes" in dlg._status_ctrl.GetString(0).lower()
    teardown(app, frame, dlg)


# ---------------------------------------------------------------------------
# Activation/désactivation des groupes de widgets selon le type
# ---------------------------------------------------------------------------

def test_notes_group_enabled_when_type_notes():
    app, frame, dlg = make_dlg()
    dlg._type_lb.SetSelection(1)
    dlg._update_group_enabled()
    assert dlg._note_lo_lb.IsEnabled() is True
    assert dlg._vel_lo_spin.IsEnabled() is True
    assert dlg._pitch_lo_spin.IsEnabled() is False
    teardown(app, frame, dlg)


def test_pitch_group_enabled_when_type_bend():
    app, frame, dlg = make_dlg()
    dlg._type_lb.SetSelection(2)
    dlg._update_group_enabled()
    assert dlg._pitch_lo_spin.IsEnabled() is True
    assert dlg._note_lo_lb.IsEnabled() is False
    teardown(app, frame, dlg)


def test_both_groups_disabled_when_type_all():
    app, frame, dlg = make_dlg()
    dlg._type_lb.SetSelection(0)
    dlg._update_group_enabled()
    assert dlg._note_lo_lb.IsEnabled() is False
    assert dlg._pitch_lo_spin.IsEnabled() is False
    teardown(app, frame, dlg)


def test_both_groups_disabled_when_type_mod():
    app, frame, dlg = make_dlg()
    dlg._type_lb.SetSelection(3)
    dlg._update_group_enabled()
    assert dlg._note_lo_lb.IsEnabled() is False
    assert dlg._pitch_lo_spin.IsEnabled() is False
    teardown(app, frame, dlg)


# ---------------------------------------------------------------------------
# _fmt_bbt / _parse_bbt (délégation BBTHelper)
# ---------------------------------------------------------------------------

def test_fmt_bbt_delegates_to_bbt_helper():
    app, frame, dlg = make_dlg()
    assert dlg._fmt_bbt(0) == "1:1:1"
    teardown(app, frame, dlg)


def test_parse_bbt_delegates_to_bbt_helper():
    app, frame, dlg = make_dlg()
    assert dlg._parse_bbt("1:1:1") == 0
    teardown(app, frame, dlg)


# ---------------------------------------------------------------------------
# Effacer le filtre
# ---------------------------------------------------------------------------

def test_clear_filter_resets_to_permissive_state():
    state = {
        "active": False, "invert": True, "etype_filter": "note",
        "note_lo": 40, "note_hi": 80, "vel_lo": 20, "vel_hi": 110,
        "bend_lo": -500, "bend_hi": 500, "pos_from": 2, "pos_to": 10,
    }
    app, frame, dlg = make_dlg(state=state)
    dlg._on_clear_filter(None)
    c = dlg.get_criteria()
    assert c == {
        "active": True, "invert": False, "etype_filter": "all",
        "note_lo": 0, "note_hi": 127, "vel_lo": 0, "vel_hi": 127,
        "bend_lo": -8192, "bend_hi": 8191, "pos_from": 0, "pos_to": TOTAL - 1,
    }
    teardown(app, frame, dlg)


def test_clear_filter_does_not_touch_selection_callback():
    calls = []
    app, frame, dlg = make_dlg(on_action=lambda *a: calls.append(a))
    dlg._on_clear_filter(None)
    assert calls == []
    teardown(app, frame, dlg)


# ---------------------------------------------------------------------------
# Boutons non-fermants — on_action(action, matched, criteria)
# ---------------------------------------------------------------------------

def test_apply_button_invokes_on_action_with_matched_and_criteria():
    calls = []
    app, frame, dlg = make_dlg(on_action=lambda *a: calls.append(a))
    dlg._on_apply(None)
    assert len(calls) == 1
    action, matched, criteria = calls[0]
    assert action == "apply"
    assert matched == {0, 1}   # type "all" par défaut : tout passe
    assert criteria["etype_filter"] == "all"
    teardown(app, frame, dlg)


def test_apply_keeps_dialog_open():
    app, frame, dlg = make_dlg()
    dlg._on_apply(None)
    assert dlg.IsBeingDeleted() is False
    teardown(app, frame, dlg)


def test_add_button_invokes_on_action_add():
    calls = []
    app, frame, dlg = make_dlg(on_action=lambda *a: calls.append(a))
    dlg._type_lb.SetSelection(2)   # bend seulement
    dlg._on_add(None)
    action, matched, criteria = calls[0]
    assert action == "add"
    assert matched == {1}
    teardown(app, frame, dlg)


def test_remove_button_invokes_on_action_remove():
    calls = []
    app, frame, dlg = make_dlg(on_action=lambda *a: calls.append(a))
    dlg._type_lb.SetSelection(1)   # note seulement
    dlg._on_remove(None)
    action, matched, criteria = calls[0]
    assert action == "remove"
    assert matched == {0}
    teardown(app, frame, dlg)


def test_reset_sel_button_invokes_on_action_with_empty_set_no_criteria():
    calls = []
    app, frame, dlg = make_dlg(on_action=lambda *a: calls.append(a))
    dlg._on_reset_sel(None)
    assert len(calls) == 1
    assert calls[0][0] == "reset_sel"
    assert calls[0][1] == set()
    teardown(app, frame, dlg)


def test_status_updated_after_apply():
    app, frame, dlg = make_dlg()
    dlg._on_apply(None)
    assert "Filtre appliqué" in dlg._status_ctrl.GetString(0)
    teardown(app, frame, dlg)


# ---------------------------------------------------------------------------
# Ok / Annuler — EndModal + on_action
# ---------------------------------------------------------------------------

def test_ok_calls_on_action_apply_then_end_modal_ok():
    calls  = []
    ended  = []
    app, frame, dlg = make_dlg(on_action=lambda *a: calls.append(a))
    dlg.EndModal = lambda code: ended.append(code)
    dlg._on_ok(None)
    assert len(calls) == 1 and calls[0][0] == "apply"
    assert ended == [wx.ID_OK]
    teardown(app, frame, dlg)


def test_cancel_via_escape_never_calls_on_action():
    calls = []
    ended = []
    app, frame, dlg = make_dlg(on_action=lambda *a: calls.append(a))
    dlg.EndModal = lambda code: ended.append(code)
    dlg._on_key(FakeKeyEvent(key=wx.WXK_ESCAPE))
    assert calls == []
    assert ended == [wx.ID_CANCEL]
    teardown(app, frame, dlg)


# ---------------------------------------------------------------------------
# Tab order — saute les contrôles désactivés
# ---------------------------------------------------------------------------

def test_tab_order_skips_disabled_controls():
    app, frame, dlg = make_dlg()
    dlg._type_lb.SetSelection(0)   # "Tous" → Notes et Pitch Bend désactivés
    dlg._update_group_enabled()
    order = [w for w in dlg._tab_order_full if w.IsEnabled()]
    assert dlg._note_lo_lb not in order
    assert dlg._pitch_lo_spin not in order
    assert dlg._type_lb in order
    assert dlg._active_cb in order
    teardown(app, frame, dlg)


def test_tab_order_includes_notes_group_when_type_notes():
    app, frame, dlg = make_dlg()
    dlg._type_lb.SetSelection(1)
    dlg._update_group_enabled()
    order = [w for w in dlg._tab_order_full if w.IsEnabled()]
    assert dlg._note_lo_lb in order
    assert dlg._vel_lo_spin in order
    assert dlg._pitch_lo_spin not in order
    teardown(app, frame, dlg)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
