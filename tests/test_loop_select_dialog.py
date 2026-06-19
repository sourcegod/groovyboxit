#python3
"""
    File: tests/test_loop_select_dialog.py
    Tests unitaires de LoopSelectDialog : valeurs initiales, sources ListBox,
    BBT format/parse, get_loop_start/end, looping, Ctrl+P.
    Date: Fri, 20/06/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wx
from ui.dialogs import (
    LoopSelectDialog,
    _SRC_CUR, _SRC_START, _SRC_END, _SRC_LIM_L, _SRC_LIM_R, _SRC_CUSTOM,
)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class FakeKeyEvent:
    def __init__(self, key=0, ctrl=False):
        self._key    = key
        self._ctrl   = ctrl
        self.skipped = False

    def GetKeyCode(self):  return self._key
    def ControlDown(self): return self._ctrl
    def Skip(self):        self.skipped = True


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

# num_bars=4, num_steps=16 → total=64 steps
# steps_per_beat = 16//4 = 4
# step 0  → "1:1:1"   step 4  → "1:2:1"   step 16 → "2:1:1"   step 63 → "4:4:4"
DEFAULT = dict(
    num_bars   = 4,
    num_beats  = 4,
    num_steps  = 16,
    cur_step   = 8,      # "1:3:1"
    loop_start = None,
    loop_end   = None,
    loop_count = 0,
    looping    = True,
    lim_left   = 4,      # "1:2:1"
    lim_right  = 28,     # "2:4:1"
)
TOTAL = 64   # 4 * 16


def make_dlg(on_play_toggle=None, **kwargs):
    p   = {**DEFAULT, **kwargs}
    app   = wx.App(False)
    frame = wx.Frame(None)
    dlg   = LoopSelectDialog(
        frame,
        num_bars       = p['num_bars'],
        num_beats      = p['num_beats'],
        num_steps      = p['num_steps'],
        cur_step       = p['cur_step'],
        loop_start     = p['loop_start'],
        loop_end       = p['loop_end'],
        loop_count     = p['loop_count'],
        looping        = p['looping'],
        lim_left       = p['lim_left'],
        lim_right      = p['lim_right'],
        on_play_toggle = on_play_toggle,
    )
    return app, frame, dlg


def teardown(app, frame, dlg):
    dlg.Destroy()
    frame.Destroy()
    app.Destroy()


# ---------------------------------------------------------------------------
# Valeurs initiales — get_loop_start / get_loop_end
# ---------------------------------------------------------------------------

def test_initial_loop_start_none():
    app, frame, dlg = make_dlg(loop_start=None)
    assert dlg.get_loop_start() is None
    teardown(app, frame, dlg)
    print("  get_loop_start() == None si loop_start=None (début pattern) : OK")

def test_initial_loop_end_none():
    app, frame, dlg = make_dlg(loop_end=None)
    assert dlg.get_loop_end() is None
    teardown(app, frame, dlg)
    print("  get_loop_end() == None si loop_end=None (fin pattern) : OK")

def test_initial_loop_start_nonzero():
    app, frame, dlg = make_dlg(loop_start=16)
    assert dlg.get_loop_start() == 16
    teardown(app, frame, dlg)
    print("  get_loop_start() == 16 si loop_start=16 : OK")

def test_initial_loop_end_nonfinal():
    app, frame, dlg = make_dlg(loop_end=32)
    assert dlg.get_loop_end() == 32
    teardown(app, frame, dlg)
    print("  get_loop_end() == 32 si loop_end=32 : OK")

def test_loop_start_zero_returns_none():
    # step=0 correspond au début du pattern → get_loop_start() retourne None
    app, frame, dlg = make_dlg(loop_start=None)
    dlg._start_ctrl.SetValue("1:1:1")
    assert dlg.get_loop_start() is None
    teardown(app, frame, dlg)
    print("  get_loop_start() == None quand TextCtrl = '1:1:1' (step 0) : OK")

def test_loop_end_last_returns_none():
    # step=63 correspond à la fin → get_loop_end() retourne None
    app, frame, dlg = make_dlg(loop_end=None)
    dlg._end_ctrl.SetValue("4:4:4")
    assert dlg.get_loop_end() is None
    teardown(app, frame, dlg)
    print("  get_loop_end() == None quand TextCtrl = '4:4:4' (step 63) : OK")

def test_initial_loop_count():
    app, frame, dlg = make_dlg(loop_count=3)
    assert dlg.get_loop_count() == 3
    teardown(app, frame, dlg)
    print("  get_loop_count() == 3 (initial) : OK")

def test_initial_loop_count_zero():
    app, frame, dlg = make_dlg(loop_count=0)
    assert dlg.get_loop_count() == 0
    teardown(app, frame, dlg)
    print("  get_loop_count() == 0 (infini, initial) : OK")

def test_initial_looping_true():
    app, frame, dlg = make_dlg(looping=True)
    assert dlg.get_looping() is True
    teardown(app, frame, dlg)
    print("  get_looping() == True (initial) : OK")

def test_initial_looping_false():
    app, frame, dlg = make_dlg(looping=False)
    assert dlg.get_looping() is False
    teardown(app, frame, dlg)
    print("  get_looping() == False (initial) : OK")


# ---------------------------------------------------------------------------
# _step_to_source — pré-sélection de la ListBox
# ---------------------------------------------------------------------------

def test_source_cur_step():
    app, frame, dlg = make_dlg(loop_start=8)   # cur_step=8
    assert dlg._start_list.GetSelection() == _SRC_CUR
    teardown(app, frame, dlg)
    print("  loop_start == cur_step → source = Position courante : OK")

def test_source_start_of_pattern():
    app, frame, dlg = make_dlg(loop_start=None)   # → step 0
    assert dlg._start_list.GetSelection() == _SRC_START
    teardown(app, frame, dlg)
    print("  loop_start=None (step 0) → source = Début du pattern : OK")

def test_source_end_of_pattern():
    app, frame, dlg = make_dlg(loop_end=None)     # → step 63
    assert dlg._end_list.GetSelection() == _SRC_END
    teardown(app, frame, dlg)
    print("  loop_end=None (step 63) → source = Fin du pattern : OK")

def test_source_lim_left():
    app, frame, dlg = make_dlg(loop_start=4)   # lim_left=4
    assert dlg._start_list.GetSelection() == _SRC_LIM_L
    teardown(app, frame, dlg)
    print("  loop_start == lim_left → source = Limiteur gauche : OK")

def test_source_lim_right():
    app, frame, dlg = make_dlg(loop_end=28)    # lim_right=28
    assert dlg._end_list.GetSelection() == _SRC_LIM_R
    teardown(app, frame, dlg)
    print("  loop_end == lim_right → source = Limiteur droit : OK")

def test_source_custom():
    app, frame, dlg = make_dlg(loop_start=20)   # pas de correspondance
    assert dlg._start_list.GetSelection() == _SRC_CUSTOM
    teardown(app, frame, dlg)
    print("  loop_start sans correspondance → source = Personnalisé : OK")


# ---------------------------------------------------------------------------
# _source_to_step — changement de source met à jour la TextCtrl
# ---------------------------------------------------------------------------

def test_select_start_updates_ctrl():
    app, frame, dlg = make_dlg(loop_start=20)
    dlg._start_list.SetSelection(_SRC_START)
    dlg._on_start_source(None)
    assert dlg._start_ctrl.GetValue() == "1:1:1"
    teardown(app, frame, dlg)
    print("  source Début → TextCtrl = '1:1:1' : OK")

def test_select_end_updates_ctrl():
    app, frame, dlg = make_dlg(loop_end=20)
    dlg._end_list.SetSelection(_SRC_END)
    dlg._on_end_source(None)
    assert dlg._end_ctrl.GetValue() == "4:4:4"
    teardown(app, frame, dlg)
    print("  source Fin → TextCtrl = '4:4:4' : OK")

def test_select_cur_step_updates_ctrl():
    app, frame, dlg = make_dlg(loop_start=20)   # cur_step=8
    dlg._start_list.SetSelection(_SRC_CUR)
    dlg._on_start_source(None)
    assert dlg._start_ctrl.GetValue() == "1:3:1"   # step 8
    teardown(app, frame, dlg)
    print("  source Position courante → TextCtrl = '1:3:1' (step 8) : OK")

def test_select_lim_left_updates_ctrl():
    app, frame, dlg = make_dlg(loop_start=20)   # lim_left=4
    dlg._start_list.SetSelection(_SRC_LIM_L)
    dlg._on_start_source(None)
    assert dlg._start_ctrl.GetValue() == "1:2:1"   # step 4
    teardown(app, frame, dlg)
    print("  source Limiteur gauche → TextCtrl = '1:2:1' (step 4) : OK")

def test_select_lim_right_updates_ctrl():
    app, frame, dlg = make_dlg(loop_end=20)    # lim_right=28
    dlg._end_list.SetSelection(_SRC_LIM_R)
    dlg._on_end_source(None)
    assert dlg._end_ctrl.GetValue() == "2:4:1"   # step 28
    teardown(app, frame, dlg)
    print("  source Limiteur droit → TextCtrl = '2:4:1' (step 28) : OK")

def test_select_custom_does_not_update_ctrl():
    app, frame, dlg = make_dlg(loop_start=20)
    dlg._start_ctrl.SetValue("3:2:1")
    dlg._start_list.SetSelection(_SRC_CUSTOM)
    dlg._on_start_source(None)
    assert dlg._start_ctrl.GetValue() == "3:2:1"   # inchangé
    teardown(app, frame, dlg)
    print("  source Personnalisé → TextCtrl inchangée : OK")


# ---------------------------------------------------------------------------
# Saisie manuelle → ListBox passe sur Personnalisé
# ---------------------------------------------------------------------------

def test_manual_text_sets_custom_source():
    app, frame, dlg = make_dlg(loop_start=None)   # source = _SRC_START
    dlg._on_start_text(None)
    assert dlg._start_list.GetSelection() == _SRC_CUSTOM
    teardown(app, frame, dlg)
    print("  saisie manuelle → source passe à Personnalisé : OK")

def test_manual_text_end_sets_custom_source():
    app, frame, dlg = make_dlg(loop_end=None)
    dlg._on_end_text(None)
    assert dlg._end_list.GetSelection() == _SRC_CUSTOM
    teardown(app, frame, dlg)
    print("  saisie manuelle fin → source passe à Personnalisé : OK")


# ---------------------------------------------------------------------------
# _fmt_bbt / _parse_bbt
# ---------------------------------------------------------------------------

def test_fmt_bbt_step0():
    app, frame, dlg = make_dlg()
    assert dlg._fmt_bbt(0) == "1:1:1"
    teardown(app, frame, dlg)
    print("  _fmt_bbt(0) == '1:1:1' : OK")

def test_fmt_bbt_last_step():
    app, frame, dlg = make_dlg()
    assert dlg._fmt_bbt(63) == "4:4:4"
    teardown(app, frame, dlg)
    print("  _fmt_bbt(63) == '4:4:4' : OK")

def test_fmt_bbt_mid_step():
    app, frame, dlg = make_dlg()
    assert dlg._fmt_bbt(16) == "2:1:1"
    teardown(app, frame, dlg)
    print("  _fmt_bbt(16) == '2:1:1' : OK")

def test_parse_bbt_full():
    app, frame, dlg = make_dlg()
    assert dlg._parse_bbt("2:1:1") == 16
    teardown(app, frame, dlg)
    print("  _parse_bbt('2:1:1') == 16 : OK")

def test_parse_bbt_bar_only():
    app, frame, dlg = make_dlg()
    assert dlg._parse_bbt("3") == 32   # mesure 3 → step 32
    teardown(app, frame, dlg)
    print("  _parse_bbt('3') == 32 (barre seule) : OK")

def test_parse_bbt_bar_beat():
    app, frame, dlg = make_dlg()
    assert dlg._parse_bbt("2:3") == 24   # step 16 + 2*4 = 24
    teardown(app, frame, dlg)
    print("  _parse_bbt('2:3') == 24 (barre:temps) : OK")

def test_parse_bbt_invalid():
    app, frame, dlg = make_dlg()
    assert dlg._parse_bbt("abc") is None
    teardown(app, frame, dlg)
    print("  _parse_bbt('abc') == None : OK")

def test_fmt_parse_roundtrip():
    app, frame, dlg = make_dlg()
    for step in (0, 1, 15, 16, 32, 63):
        assert dlg._parse_bbt(dlg._fmt_bbt(step)) == step
    teardown(app, frame, dlg)
    print("  _parse_bbt(_fmt_bbt(step)) == step pour steps variés : OK")


# ---------------------------------------------------------------------------
# Ctrl+P → on_play_toggle
# ---------------------------------------------------------------------------

def test_ctrl_p_calls_play_toggle():
    toggled = []
    app, frame, dlg = make_dlg(on_play_toggle=lambda: toggled.append(1))
    dlg._on_key(FakeKeyEvent(key=ord('P'), ctrl=True))
    assert toggled == [1]
    teardown(app, frame, dlg)
    print("  Ctrl+P appelle on_play_toggle : OK")

def test_p_without_ctrl_does_not_toggle():
    toggled = []
    app, frame, dlg = make_dlg(on_play_toggle=lambda: toggled.append(1))
    dlg._on_key(FakeKeyEvent(key=ord('P'), ctrl=False))
    assert toggled == []
    teardown(app, frame, dlg)
    print("  P sans Ctrl n'appelle pas on_play_toggle : OK")

def test_ctrl_p_no_crash_without_callback():
    app, frame, dlg = make_dlg(on_play_toggle=None)
    dlg._on_key(FakeKeyEvent(key=ord('P'), ctrl=True))   # ne doit pas lever
    teardown(app, frame, dlg)
    print("  Ctrl+P sans callback ne lève pas d'exception : OK")

def test_other_key_skipped():
    app, frame, dlg = make_dlg()
    ev = FakeKeyEvent(key=ord('A'), ctrl=False)
    dlg._on_key(ev)
    assert ev.skipped
    teardown(app, frame, dlg)
    print("  touche inconnue → Skip() appelé : OK")


# ---------------------------------------------------------------------------
# Modification des widgets
# ---------------------------------------------------------------------------

def test_set_looping_false():
    app, frame, dlg = make_dlg(looping=True)
    dlg._looping_cb.SetValue(False)
    assert dlg.get_looping() is False
    teardown(app, frame, dlg)
    print("  get_looping() reflète False après décoché : OK")

def test_set_loop_count_via_spin():
    app, frame, dlg = make_dlg(loop_count=0)
    dlg._rep_spin.SetValue(5)
    assert dlg.get_loop_count() == 5
    teardown(app, frame, dlg)
    print("  get_loop_count() == 5 après SetValue(5) : OK")

def test_get_loop_start_from_ctrl():
    app, frame, dlg = make_dlg()
    dlg._start_ctrl.SetValue("2:1:1")   # step 16
    assert dlg.get_loop_start() == 16
    teardown(app, frame, dlg)
    print("  get_loop_start() == 16 après TextCtrl '2:1:1' : OK")

def test_get_loop_end_from_ctrl():
    app, frame, dlg = make_dlg()
    dlg._end_ctrl.SetValue("3:1:1")   # step 32
    assert dlg.get_loop_end() == 32
    teardown(app, frame, dlg)
    print("  get_loop_end() == 32 après TextCtrl '3:1:1' : OK")

def test_get_loop_start_invalid_text_returns_none():
    app, frame, dlg = make_dlg()
    dlg._start_ctrl.SetValue("xyz")   # invalide → step 0 → None
    assert dlg.get_loop_start() is None
    teardown(app, frame, dlg)
    print("  get_loop_start() == None si TextCtrl invalide (→ step 0) : OK")

def test_get_loop_end_invalid_text_returns_none():
    app, frame, dlg = make_dlg()
    dlg._end_ctrl.SetValue("xyz")   # invalide → step 63 → None
    assert dlg.get_loop_end() is None
    teardown(app, frame, dlg)
    print("  get_loop_end() == None si TextCtrl invalide (→ step 63) : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_loop_select_dialog ===")
    # Valeurs initiales
    test_initial_loop_start_none()
    test_initial_loop_end_none()
    test_initial_loop_start_nonzero()
    test_initial_loop_end_nonfinal()
    test_loop_start_zero_returns_none()
    test_loop_end_last_returns_none()
    test_initial_loop_count()
    test_initial_loop_count_zero()
    test_initial_looping_true()
    test_initial_looping_false()
    # _step_to_source
    test_source_cur_step()
    test_source_start_of_pattern()
    test_source_end_of_pattern()
    test_source_lim_left()
    test_source_lim_right()
    test_source_custom()
    # _source_to_step → TextCtrl
    test_select_start_updates_ctrl()
    test_select_end_updates_ctrl()
    test_select_cur_step_updates_ctrl()
    test_select_lim_left_updates_ctrl()
    test_select_lim_right_updates_ctrl()
    test_select_custom_does_not_update_ctrl()
    # Saisie manuelle
    test_manual_text_sets_custom_source()
    test_manual_text_end_sets_custom_source()
    # BBT
    test_fmt_bbt_step0()
    test_fmt_bbt_last_step()
    test_fmt_bbt_mid_step()
    test_parse_bbt_full()
    test_parse_bbt_bar_only()
    test_parse_bbt_bar_beat()
    test_parse_bbt_invalid()
    test_fmt_parse_roundtrip()
    # Ctrl+P
    test_ctrl_p_calls_play_toggle()
    test_p_without_ctrl_does_not_toggle()
    test_ctrl_p_no_crash_without_callback()
    test_other_key_skipped()
    # Widgets
    test_set_looping_false()
    test_set_loop_count_via_spin()
    test_get_loop_start_from_ctrl()
    test_get_loop_end_from_ctrl()
    test_get_loop_start_invalid_text_returns_none()
    test_get_loop_end_invalid_text_returns_none()
    print("Tous les tests : OK")
