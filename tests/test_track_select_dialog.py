#python3
"""
    File: tests/test_track_select_dialog.py
    Tests unitaires — TrackSelectDialog : valeurs initiales, checkboxes,
    get_sel_tracks(), get_start_step(), get_end_step(), _fmt_bbt(), _parse_bbt().
    Date: Mon, 16/06/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wx
from ui.dialogs import TrackSelectDialog


# ---------------------------------------------------------------------------
# Paramètres par défaut
# ---------------------------------------------------------------------------

NUM_TRACKS  = 8
NUM_BARS    = 4
NUM_BEATS   = 4
NUM_STEPS   = 16          # steps_per_beat = 4, total_steps = 64
CUR_STEP    = 8           # → "1:3:1"
TOTAL_STEPS = NUM_BARS * NUM_STEPS   # 64
LAST_STEP   = TOTAL_STEPS - 1        # 63 → "4:4:4"

LABELS = [f"Track {i + 1:02d} — Slot_{i + 1:02d}" for i in range(NUM_TRACKS)]


def make_dlg(sel_tracks=None, cur_step=CUR_STEP):
    if sel_tracks is None:
        sel_tracks = {0, 2, 5}
    app   = wx.App(False)
    frame = wx.Frame(None)
    dlg   = TrackSelectDialog(
        frame,
        num_tracks   = NUM_TRACKS,
        sel_tracks   = sel_tracks,
        track_labels = LABELS,
        num_bars     = NUM_BARS,
        num_beats    = NUM_BEATS,
        num_steps    = NUM_STEPS,
        cur_step     = cur_step,
    )
    return app, frame, dlg


def teardown(app, frame, dlg):
    dlg.Destroy()
    frame.Destroy()
    app.Destroy()


# ---------------------------------------------------------------------------
# Valeurs initiales — checkboxes
# ---------------------------------------------------------------------------

def test_precheck_selected_tracks():
    app, frame, dlg = make_dlg(sel_tracks={0, 2, 5})
    assert dlg._checks[0].GetValue() is True
    assert dlg._checks[1].GetValue() is False
    assert dlg._checks[2].GetValue() is True
    assert dlg._checks[3].GetValue() is False
    assert dlg._checks[5].GetValue() is True
    assert dlg._checks[7].GetValue() is False
    teardown(app, frame, dlg)
    print("  checkboxes pré-cochées depuis sel_tracks : OK")


def test_precheck_empty_selection():
    app, frame, dlg = make_dlg(sel_tracks=set())
    assert all(not cb.GetValue() for cb in dlg._checks)
    teardown(app, frame, dlg)
    print("  sel_tracks vide → aucune checkbox cochée : OK")


def test_precheck_all_selected():
    app, frame, dlg = make_dlg(sel_tracks=set(range(NUM_TRACKS)))
    assert all(cb.GetValue() for cb in dlg._checks)
    teardown(app, frame, dlg)
    print("  toutes les pistes sélectionnées → toutes cochées : OK")


def test_num_checkboxes():
    app, frame, dlg = make_dlg()
    assert len(dlg._checks) == NUM_TRACKS
    teardown(app, frame, dlg)
    print(f"  {NUM_TRACKS} checkboxes créées : OK")


# ---------------------------------------------------------------------------
# Valeurs initiales — champs BBT
# ---------------------------------------------------------------------------

def test_start_field_prefilled_with_cur_step():
    app, frame, dlg = make_dlg(cur_step=8)
    assert dlg._start.GetValue() == "1:3:1"
    teardown(app, frame, dlg)
    print("  Début sélection pré-rempli avec position courante (1:3:1) : OK")


def test_end_field_prefilled_with_last_step():
    app, frame, dlg = make_dlg()
    assert dlg._end.GetValue() == "4:4:4"
    teardown(app, frame, dlg)
    print("  Fin sélection pré-remplie avec fin du pattern (4:4:4) : OK")


def test_start_at_origin():
    app, frame, dlg = make_dlg(cur_step=0)
    assert dlg._start.GetValue() == "1:1:1"
    teardown(app, frame, dlg)
    print("  step 0 → '1:1:1' : OK")


# ---------------------------------------------------------------------------
# get_sel_tracks()
# ---------------------------------------------------------------------------

def test_get_sel_tracks_initial():
    app, frame, dlg = make_dlg(sel_tracks={1, 4, 6})
    assert dlg.get_sel_tracks() == {1, 4, 6}
    teardown(app, frame, dlg)
    print("  get_sel_tracks() retourne les pistes initiales : OK")


def test_get_sel_tracks_after_check():
    app, frame, dlg = make_dlg(sel_tracks=set())
    dlg._checks[3].SetValue(True)
    dlg._checks[7].SetValue(True)
    assert dlg.get_sel_tracks() == {3, 7}
    teardown(app, frame, dlg)
    print("  get_sel_tracks() reflète les coches modifiées : OK")


def test_get_sel_tracks_after_uncheck():
    app, frame, dlg = make_dlg(sel_tracks={0, 1, 2})
    dlg._checks[1].SetValue(False)
    assert dlg.get_sel_tracks() == {0, 2}
    teardown(app, frame, dlg)
    print("  get_sel_tracks() reflète une décoché : OK")


def test_get_sel_tracks_empty():
    app, frame, dlg = make_dlg(sel_tracks=set())
    assert dlg.get_sel_tracks() == set()
    teardown(app, frame, dlg)
    print("  get_sel_tracks() retourne set() si rien de coché : OK")


def test_get_sel_tracks_all():
    app, frame, dlg = make_dlg(sel_tracks=set(range(NUM_TRACKS)))
    assert dlg.get_sel_tracks() == set(range(NUM_TRACKS))
    teardown(app, frame, dlg)
    print("  get_sel_tracks() retourne toutes les pistes : OK")


# ---------------------------------------------------------------------------
# _fmt_bbt()
# ---------------------------------------------------------------------------

def test_fmt_bbt_origin():
    app, frame, dlg = make_dlg()
    assert dlg._fmt_bbt(0) == "1:1:1"
    teardown(app, frame, dlg)
    print("  _fmt_bbt(0) == '1:1:1' : OK")


def test_fmt_bbt_last():
    app, frame, dlg = make_dlg()
    assert dlg._fmt_bbt(LAST_STEP) == "4:4:4"
    teardown(app, frame, dlg)
    print("  _fmt_bbt(63) == '4:4:4' : OK")


def test_fmt_bbt_step8():
    app, frame, dlg = make_dlg()
    assert dlg._fmt_bbt(8) == "1:3:1"
    teardown(app, frame, dlg)
    print("  _fmt_bbt(8) == '1:3:1' : OK")


def test_fmt_bbt_first_step_bar2():
    app, frame, dlg = make_dlg()
    assert dlg._fmt_bbt(NUM_STEPS) == "2:1:1"
    teardown(app, frame, dlg)
    print("  _fmt_bbt(16) == '2:1:1' : OK")


def test_fmt_bbt_clamps_below_zero():
    app, frame, dlg = make_dlg()
    assert dlg._fmt_bbt(-5) == "1:1:1"
    teardown(app, frame, dlg)
    print("  _fmt_bbt(-5) clampé à '1:1:1' : OK")


def test_fmt_bbt_clamps_above_total():
    app, frame, dlg = make_dlg()
    assert dlg._fmt_bbt(TOTAL_STEPS + 10) == "4:4:4"
    teardown(app, frame, dlg)
    print("  _fmt_bbt(> total) clampé à '4:4:4' : OK")


# ---------------------------------------------------------------------------
# _parse_bbt()
# ---------------------------------------------------------------------------

def test_parse_bbt_origin():
    app, frame, dlg = make_dlg()
    assert dlg._parse_bbt("1:1:1") == 0
    teardown(app, frame, dlg)
    print("  _parse_bbt('1:1:1') == 0 : OK")


def test_parse_bbt_last():
    app, frame, dlg = make_dlg()
    assert dlg._parse_bbt("4:4:4") == LAST_STEP
    teardown(app, frame, dlg)
    print("  _parse_bbt('4:4:4') == 63 : OK")


def test_parse_bbt_step8():
    app, frame, dlg = make_dlg()
    assert dlg._parse_bbt("1:3:1") == 8
    teardown(app, frame, dlg)
    print("  _parse_bbt('1:3:1') == 8 : OK")


def test_parse_bbt_bar_beat_only():
    app, frame, dlg = make_dlg()
    assert dlg._parse_bbt("2:1") == NUM_STEPS   # début de la mesure 2
    teardown(app, frame, dlg)
    print("  _parse_bbt('2:1') == 16 (bar:beat) : OK")


def test_parse_bbt_bar_only():
    app, frame, dlg = make_dlg()
    assert dlg._parse_bbt("3") == 2 * NUM_STEPS  # début mesure 3
    teardown(app, frame, dlg)
    print("  _parse_bbt('3') == 32 (bar seul) : OK")


def test_parse_bbt_invalid_returns_none():
    app, frame, dlg = make_dlg()
    assert dlg._parse_bbt("abc") is None
    assert dlg._parse_bbt("") is None
    assert dlg._parse_bbt("x:y:z") is None
    teardown(app, frame, dlg)
    print("  _parse_bbt(invalide) == None : OK")


def test_parse_bbt_clamps_high():
    app, frame, dlg = make_dlg()
    result = dlg._parse_bbt("999:999:999")
    assert result == LAST_STEP
    teardown(app, frame, dlg)
    print("  _parse_bbt hors plage → clampé à LAST_STEP : OK")


def test_parse_bbt_clamps_low():
    app, frame, dlg = make_dlg()
    result = dlg._parse_bbt("0:0:0")
    assert result == 0
    teardown(app, frame, dlg)
    print("  _parse_bbt('0:0:0') clampé à 0 : OK")


def test_fmt_parse_roundtrip():
    app, frame, dlg = make_dlg()
    for step in (0, 1, 8, 15, 16, 32, 63):
        assert dlg._parse_bbt(dlg._fmt_bbt(step)) == step
    teardown(app, frame, dlg)
    print("  aller-retour _fmt_bbt → _parse_bbt : OK")


# ---------------------------------------------------------------------------
# get_start_step() / get_end_step()
# ---------------------------------------------------------------------------

def test_get_start_step_initial():
    app, frame, dlg = make_dlg(cur_step=8)
    assert dlg.get_start_step() == 8
    teardown(app, frame, dlg)
    print("  get_start_step() initial == cur_step : OK")


def test_get_end_step_initial():
    app, frame, dlg = make_dlg()
    assert dlg.get_end_step() == LAST_STEP
    teardown(app, frame, dlg)
    print("  get_end_step() initial == LAST_STEP : OK")


def test_get_start_step_after_edit():
    app, frame, dlg = make_dlg()
    dlg._start.SetValue("2:1:1")
    assert dlg.get_start_step() == NUM_STEPS
    teardown(app, frame, dlg)
    print("  get_start_step() après édition '2:1:1' == 16 : OK")


def test_get_end_step_after_edit():
    app, frame, dlg = make_dlg()
    dlg._end.SetValue("3:1:1")
    assert dlg.get_end_step() == 2 * NUM_STEPS
    teardown(app, frame, dlg)
    print("  get_end_step() après édition '3:1:1' == 32 : OK")


def test_get_start_step_fallback_on_invalid():
    app, frame, dlg = make_dlg()
    dlg._start.SetValue("???")
    assert dlg.get_start_step() == 0
    teardown(app, frame, dlg)
    print("  get_start_step() invalide → repli sur 0 : OK")


def test_get_end_step_fallback_on_invalid():
    app, frame, dlg = make_dlg()
    dlg._end.SetValue("???")
    assert dlg.get_end_step() == LAST_STEP
    teardown(app, frame, dlg)
    print("  get_end_step() invalide → repli sur LAST_STEP : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_track_select_dialog ===")
    # Checkboxes initiales
    test_precheck_selected_tracks()
    test_precheck_empty_selection()
    test_precheck_all_selected()
    test_num_checkboxes()
    # Champs BBT initiaux
    test_start_field_prefilled_with_cur_step()
    test_end_field_prefilled_with_last_step()
    test_start_at_origin()
    # get_sel_tracks()
    test_get_sel_tracks_initial()
    test_get_sel_tracks_after_check()
    test_get_sel_tracks_after_uncheck()
    test_get_sel_tracks_empty()
    test_get_sel_tracks_all()
    # _fmt_bbt()
    test_fmt_bbt_origin()
    test_fmt_bbt_last()
    test_fmt_bbt_step8()
    test_fmt_bbt_first_step_bar2()
    test_fmt_bbt_clamps_below_zero()
    test_fmt_bbt_clamps_above_total()
    # _parse_bbt()
    test_parse_bbt_origin()
    test_parse_bbt_last()
    test_parse_bbt_step8()
    test_parse_bbt_bar_beat_only()
    test_parse_bbt_bar_only()
    test_parse_bbt_invalid_returns_none()
    test_parse_bbt_clamps_high()
    test_parse_bbt_clamps_low()
    test_fmt_parse_roundtrip()
    # get_start_step() / get_end_step()
    test_get_start_step_initial()
    test_get_end_step_initial()
    test_get_start_step_after_edit()
    test_get_end_step_after_edit()
    test_get_start_step_fallback_on_invalid()
    test_get_end_step_fallback_on_invalid()
    print("Tous les tests : OK")
