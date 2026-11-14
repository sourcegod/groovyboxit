#python3
"""
    File: tests/test_quantize_notes.py
    Quantisation de toutes les notes (Phase 8 étape 13d1, docs/DESIGN.md
    § 13a V6-V9) et quantisation à l'enregistrement (Phase 8 étape 13d2,
    Alt+Shift+Q) : grille, kit et synthé quantisés de la même façon à partir
    de leurs événements (vélocité, canal, durée gardés), « Enlever les
    doublons » (la dernière note jouée reste), « Quantiser la vélocité »,
    réglages retenus (quant_kwargs, dialogue, Ctrl+Q, Shift+Q, état de
    l'Undo) ; QuantizeDialog (cases, liste, mode enregistrement) ;
    snap_position ; frappes enregistrées (position, vélocité, doublons) ;
    _record_quantize_dialog (réglages, annonces, Undo) ; Alt+Shift+Q dans la
    fenêtre principale et l'éditeur MIDI ; arrondi au pas hors de la
    fenêtre (13d3).
    Date: Sat, 14/11/2026
    Author: Coolbrother
"""
import sys
import os
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import wx

from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH, ETYPE_CC
from player.drum_player import DrumPlayer
from ui.dialogs_simple import QuantizeDialog
from ui.mw_patterns import PatternMixin
import ui.midi_editor_window as mew
from ui.key_manager import KeyManager
from test_key_manager import FakeWindow, FakeEvent

Q4  = Pattern.QUANT_STEPS.index(4)            # grille de 4 pas (noires en 4/4, 16 pas)
Q16 = Pattern.QUANT_STEPS.index(16)

_APP = None


@pytest.fixture(autouse=True)
def wx_app_alive():
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)
    yield


class _Snd:
    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def player():
    p = DrumPlayer(_Snd())
    p._measure_start = None
    p.start_thread = p.stop_thread = lambda: None
    return p


def _G(pad, vel, time, channel=0, dur=0):
    return TapeEvent(ETYPE_GRID, payload={"pad": pad, "vel": vel}, time=time, channel=channel,
                     dur=dur)


def _K(note, vel, time, channel=0):
    return TapeEvent(ETYPE_KIT, payload={"note": note, "vel": vel}, time=time, channel=channel)


def _P(note, vel, time, channel=0, dur=300):
    return TapeEvent(ETYPE_PATCH, payload={"note": note, "vel": vel}, time=time,
                     channel=channel, dur=dur)


def _put(player, *events):
    player._pattern._tape[0].extend(events)


def _notes(player):
    return [(e.etype, e.payload.get("pad", e.payload.get("note", e.payload.get("cc_num"))),
             e.payload.get("vel"), e.time) for e in player._pattern._tape[0]]


# ---------------------------------------------------------------------------
# Toutes les notes, de la même façon (V6)
# ---------------------------------------------------------------------------

def test_every_kind_of_note_snapped_with_its_velocity(player):
    _put(player, _G(1, 40, 3), _K(38, 70, 5), _P(60, 55, 9))
    player.apply_quant_to_pattern(Q4)
    assert _notes(player) == [("GRID", 1, 40, 4), ("KIT", 38, 70, 4), ("PATCH", 60, 55, 8)]


def test_grid_velocity_no_longer_reset_to_100(player):
    _put(player, _G(2, 33, 5))
    player.apply_quant_to_pattern(Q4)
    assert player._pattern.get_cell(0, 2, 0, 4) == 33


def test_channel_and_duration_kept(player):
    _put(player, _G(2, 33, 5, channel=9, dur=120), _P(60, 50, 7, channel=3, dur=400))
    player.apply_quant_to_pattern(Q4)
    g, p = player._pattern._tape[0]
    assert (g.channel, g.dur) == (9, 120) and (p.channel, p.dur) == (3, 400)


def test_grid_duration_quantised_like_the_others(player):
    _put(player, _G(2, 33, 4, dur=130))           # 130 ms au tempo par défaut
    player.apply_quant_to_pattern(Q16, quant_starts=False, quant_durations=True)
    assert player._pattern._tape[0][0].dur != 130


def test_controllers_untouched(player):
    cc = TapeEvent(ETYPE_CC, payload={"cc_num": 1, "value": 5}, time=5.3)
    _put(player, cc, _G(1, 40, 3))
    player.apply_quant_to_pattern(Q4)
    assert player._pattern._tape[0][0] is cc


def test_float_offsets_rebuilt_from_the_notes(player):
    _put(player, _G(2, 33, 5), _G(2, 33, 11))
    player.apply_quant_to_pattern(Q4)
    assert player.float_offsets[2] == [4.0, 12.0]


def test_out_of_window_rounded_to_the_step(player):       # 13d3
    _put(player, _G(0, 80, 1.5))
    player.apply_quant_to_pattern(Q4, window_idx=2)
    assert player._pattern.get_cell(0, 0, 0, 2) == 80


def test_nothing_to_do_changes_nothing(player):
    _put(player, _G(1, 40, 3))
    before = list(player._pattern._tape[0])
    player.apply_quant_to_pattern(Q4, quant_starts=False, quant_durations=False,
                                  remove_duplicates=False, velocity=None)
    assert player._pattern._tape[0] == before
    player.apply_quant_to_pattern(-1)
    assert player._pattern._tape[0] == before


# ---------------------------------------------------------------------------
# Enlever les doublons (V7)
# ---------------------------------------------------------------------------

def test_duplicates_keep_the_last_played(player):
    _put(player, _G(2, 40, 3), _G(2, 90, 5), _K(38, 70, 4), _K(38, 125, 4),
         _P(60, 20, 8), _P(60, 99, 9))
    player.apply_quant_to_pattern(Q4, remove_duplicates=True)
    assert _notes(player) == [("GRID", 2, 90, 4), ("KIT", 38, 125, 4), ("PATCH", 60, 99, 8)]


def test_not_duplicates_when_anything_differs(player):
    _put(player, _G(2, 40, 4), _G(3, 50, 4),                 # autre pad
         _K(38, 70, 4), _K(38, 80, 4, channel=9),            # autre canal
         _K(36, 70, 4), _P(36, 70, 4))                       # autre type
    player.apply_quant_to_pattern(Q4, remove_duplicates=True)
    assert len(player._pattern._tape[0]) == 6


def test_duplicates_kept_when_unchecked(player):
    _put(player, _K(38, 70, 4), _K(38, 125, 4))
    player.apply_quant_to_pattern(Q4, remove_duplicates=False)
    assert len(player._pattern._tape[0]) == 2


def test_duplicates_removed_without_moving_the_notes(player):
    _put(player, _K(38, 70, 4.3), _K(38, 125, 4.3))
    player.apply_quant_to_pattern(Q4, quant_starts=False, remove_duplicates=True)
    assert _notes(player) == [("KIT", 38, 125, 4.3)]


def test_controllers_never_deduplicated(player):
    cc = lambda v: TapeEvent(ETYPE_CC, payload={"cc_num": 1, "value": v}, time=4)
    _put(player, cc(5), cc(5))
    player.apply_quant_to_pattern(Q4, remove_duplicates=True)
    assert len(player._pattern._tape[0]) == 2


# ---------------------------------------------------------------------------
# Quantiser la vélocité (V8)
# ---------------------------------------------------------------------------

def test_velocity_given_to_every_note(player):
    _put(player, _G(1, 40, 3), _K(38, 70, 5), _P(60, 55, 9))
    player.apply_quant_to_pattern(Q4, velocity=64)
    assert [v for _, _, v, _ in _notes(player)] == [64, 64, 64]


def test_velocity_bounded(player):
    _put(player, _K(38, 70, 4))
    player.apply_quant_to_pattern(Q4, velocity=300)
    assert player._pattern._tape[0][0].payload["vel"] == 127


def test_velocity_alone_keeps_positions(player):
    _put(player, _K(38, 70, 5))
    player.apply_quant_to_pattern(Q4, quant_starts=False, velocity=90)
    assert _notes(player) == [("KIT", 38, 90, 5)]


# ---------------------------------------------------------------------------
# Réglages retenus (V9)
# ---------------------------------------------------------------------------

def test_defaults_and_quant_kwargs(player):
    assert (player._quant_dedupe, player._quant_velocity, player._quant_velocity_value) == \
        (True, False, 100)
    kw = player.quant_kwargs()
    assert kw["remove_duplicates"] is True and kw["velocity"] is None
    player._quant_velocity, player._quant_velocity_value = True, 70
    assert player.quant_kwargs()["velocity"] == 70


class _QuantWin:
    """Fenêtre minimale pour les quantisations de la fenêtre principale."""
    def __init__(self, player):
        self._player = player
        self.statuses, self.undos, self.calls = [], [], []
        player.apply_quant_to_pattern = lambda res=None, **kw: self.calls.append((res, kw))
        player._grid_idx = Pattern.GRID_RESOLUTIONS.index(
            next(g for g in Pattern.GRID_RESOLUTIONS if g[1] == "snaps"))
    def _add_undo(self, t):      self.undos.append(t)
    def _pop_last_undo(self):    self.undos.append("pop")
    def _refresh_grid(self):     pass
    def _show_status(self, m):   self.statuses.append(m)


@pytest.mark.parametrize("action", ["_quantize_from_grid", "_quantize_with_last_params"])
def test_shortcuts_pass_the_new_settings(player, action):
    player._quant_res_idx = Q4
    player._quant_dedupe, player._quant_velocity, player._quant_velocity_value = False, True, 50
    win = _QuantWin(player)
    getattr(PatternMixin, action)(win)
    (res, kw), = win.calls
    assert kw["remove_duplicates"] is False and kw["velocity"] == 50


def test_quantize_dialog_reads_and_stores_the_settings(player):
    player._quant_res_idx = Q4
    win = _QuantWin(player)
    seen = {}

    class Dlg:
        def __init__(self, parent, **kw):
            seen.update(kw)
        def ShowModal(self):                 return wx.ID_OK
        def Destroy(self):                   pass
        def get_resolution(self):            return Q4
        def get_force_idx(self):             return 4
        def get_swing_idx(self):             return 0
        def get_window_idx(self):            return 4
        def get_quant_starts(self):          return True
        def get_quant_durations(self):       return False
        def get_direction_idx(self):         return 0
        def get_remove_duplicates(self):     return False
        def get_quant_velocity(self):        return True
        def get_velocity_value(self):        return 64
    with patch("ui.mw_patterns.QuantizeDialog", Dlg):
        PatternMixin._quantize_pattern_dialog(win)
    assert (seen["remove_duplicates"], seen["quant_velocity"], seen["velocity_value"]) == \
        (True, False, 100)
    assert (player._quant_dedupe, player._quant_velocity, player._quant_velocity_value) == \
        (False, True, 64)
    (res, kw), = win.calls
    assert kw["velocity"] == 64 and kw["remove_duplicates"] is False


# ---------------------------------------------------------------------------
# Dialogue
# ---------------------------------------------------------------------------

@pytest.fixture
def dialog():
    made = []

    def build(**kw):
        dlg = QuantizeDialog(None, **kw)
        made.append(dlg)
        return dlg
    yield build
    for dlg in made:
        dlg.Destroy()


def _labels(dlg):
    return [c.GetLabel() for c in dlg.GetChildren() if isinstance(c, (wx.CheckBox, wx.Button))]


def test_dialog_new_controls_and_defaults(dialog):
    dlg = dialog()
    assert "Enlever les doublons" in _labels(dlg) and "Quantiser la vélocité" in _labels(dlg)
    assert dlg.get_remove_duplicates() is True and dlg.get_quant_velocity() is False
    assert dlg.get_velocity_value() == 100
    assert not dlg._velocity_lb.IsEnabled()
    assert dlg._velocity_lb.GetString(0) == "Vélocité: 127"


def test_dialog_velocity_list_follows_its_checkbox(dialog):
    dlg = dialog()
    dlg._velocity_cb.SetValue(True)
    dlg._velocity_cb.GetEventHandler().ProcessEvent(
        wx.CommandEvent(wx.wxEVT_CHECKBOX, dlg._velocity_cb.GetId()))
    assert dlg._velocity_lb.IsEnabled()
    dlg._velocity_lb.SetSelection(QuantizeDialog.VELOCITIES.index(64))
    assert dlg.get_velocity_value() == 64


def test_dialog_given_values(dialog):
    dlg = dialog(remove_duplicates=False, quant_velocity=True, velocity_value=50)
    assert (dlg.get_remove_duplicates(), dlg.get_quant_velocity(), dlg.get_velocity_value()) == \
        (False, True, 50)
    assert dialog(velocity_value=77).get_velocity_value() == 100     # hors liste → 100


def test_dialog_resolution_values_unchanged(dialog):
    assert dialog(res_idx=-2).get_resolution() == -2
    assert dialog(res_idx=-1).get_resolution() == -1
    assert dialog(res_idx=Q4).get_resolution() == Q4
    assert "Appliquer" in _labels(dialog())


def test_record_dialog(dialog):
    dlg = dialog(record=True, res_idx=-3, enabled=False)
    assert dlg.GetTitle() == "Quantisation à l'enregistrement"
    kids = [c for c in dlg.GetChildren()]
    assert isinstance(kids[0], wx.CheckBox) and kids[0].GetLabel() == "Quantiser à l'enregistrement"
    assert dlg.get_enabled() is False
    assert dlg._res_lb.GetString(0) == "Résolution: Quant courante"
    assert dlg._res_lb.GetString(1) == "Résolution: Grille courante"
    assert dlg.get_resolution() == -3
    labels = _labels(dlg)
    assert "Appliquer" not in labels
    assert "Quantiser les débuts" not in labels and "Quantiser les durées" not in labels
    assert dlg.get_quant_starts() is True and dlg.get_quant_durations() is False
    assert dlg.get_remove_duplicates() is True


def test_record_dialog_resolutions(dialog):
    assert dialog(record=True, res_idx=-2).get_resolution() == -2
    assert dialog(record=True, res_idx=Q16).get_resolution() == Q16
    assert dialog(record=True, res_idx=-1).get_resolution() == -3        # pas d'« Aucune »
    assert dialog().get_enabled() is True


# ---------------------------------------------------------------------------
# Quantisation à l'enregistrement (13d2)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pos, kw, expected", [
    (2.6, {}, 4.0),
    (2.6, {"force_idx": 2}, 3.3),
    (1.5, {"window_idx": 2}, 1.5),                 # hors de la fenêtre : inchangée
    (2.6, {"direction_idx": 1}, 0.0),
    (1.2, {"direction_idx": 2}, 4.0),
    (15.6, {}, 16.0),                              # fin de boucle : 16 (→ 0 modulo)
])
def test_snap_position(player, pos, kw, expected):
    assert player._qm.snap_position(pos, Q4, **kw) == pytest.approx(expected)


def test_snap_position_swing(player):
    assert player._qm.snap_position(4.4, Q4, swing_idx=4) == pytest.approx(6.0)


def test_record_resolution(player):
    player.quant_idx = Q16
    assert player._record_quant_res() == Q16                  # Quant courante
    player._rq_res_idx = Q4
    assert player._record_quant_res() == Q4
    player._rq_res_idx = -2
    kind, val = Pattern.GRID_RESOLUTIONS[player._grid_idx][1:]
    expected = Pattern.QUANT_STEPS.index(val) if kind == "snaps" and val in Pattern.QUANT_STEPS else -1
    assert player._record_quant_res() == expected
    player._quant_in_recording = False
    assert player._record_quant_res() == -1


def _at(player, monkeypatch, pos):
    monkeypatch.setattr(player, "_position_at", lambda now: pos)
    player._measure_start = 0.0


def test_hit_snapped_by_the_record_settings(player, monkeypatch):
    _at(player, monkeypatch, 2.6)
    player._rq_res_idx = Q4
    assert player.record_hit(0, 90) == (0, 4)
    player._rq_force_idx = 0
    assert player.record_hit(1, 90) == (0, 3)                 # force 0 : pas le plus proche


def test_hit_not_snapped_when_disabled(player, monkeypatch):
    _at(player, monkeypatch, 2.6)
    player._rq_res_idx = Q4
    player._quant_in_recording = False
    assert player.record_hit(0, 90) == (0, 3)


def test_record_velocity(player):
    assert player._rec_velocity(200) == 127
    player._rq_velocity, player._rq_velocity_value = True, 64
    assert player._rec_velocity(10) == 64
    player._quant_in_recording = False
    assert player._rec_velocity(10) == 10


def test_record_duplicates_replaced_by_the_last(player):
    player.record_hit(4, 60)
    player.record_hit(4, 110)
    player.record_kit_note(38, 70)
    player.record_kit_note(38, 125)
    player.record_patch_note(60, 50, 100)
    player.record_patch_note(60, 99, 200)
    t = player._pattern._tape[0]
    assert [e.payload["vel"] for e in t if e.etype == ETYPE_GRID] == [110]
    assert [e.payload["vel"] for e in t if e.etype == ETYPE_KIT] == [125]
    assert [(e.payload["vel"], e.dur) for e in t if e.etype == ETYPE_PATCH] == [(99, 200)]


def test_record_duplicates_other_channel_kept(player):
    player.record_kit_note(38, 70, channel=0)
    player.record_kit_note(38, 125, channel=9)
    assert len([e for e in player._pattern._tape[0] if e.etype == ETYPE_KIT]) == 2


def test_record_duplicates_kept_when_unchecked(player):
    player._rq_dedupe = False
    player.record_kit_note(38, 70)
    player.record_kit_note(38, 125)
    assert len(player._pattern._tape[0]) == 2


def test_note_repeat_hit_follows_the_settings(player):
    player._rq_velocity, player._rq_velocity_value = True, 40
    player._record_nr_hit(2, 4.0)
    player._record_nr_hit(2, 4.0)
    grid = [e for e in player._pattern._tape[0] if e.etype == ETYPE_GRID]
    assert [e.payload["vel"] for e in grid] == [40]


# ---------------------------------------------------------------------------
# _record_quantize_dialog : réglages, annonces, Undo
# ---------------------------------------------------------------------------

def _rq_dialog(result, **values):
    v = dict(enabled=True, res=-3, force=4, swing=0, window=4, direction=0, dedupe=True,
             velocity=False, value=100)
    v.update(values)

    class Dlg:
        seen = {}
        def __init__(self, parent, **kw):
            Dlg.seen = dict(kw, parent=parent)
        def ShowModal(self):              return result
        def Destroy(self):                pass
        def get_enabled(self):            return v["enabled"]
        def get_resolution(self):         return v["res"]
        def get_force_idx(self):          return v["force"]
        def get_swing_idx(self):          return v["swing"]
        def get_window_idx(self):         return v["window"]
        def get_direction_idx(self):      return v["direction"]
        def get_remove_duplicates(self):  return v["dedupe"]
        def get_quant_velocity(self):     return v["velocity"]
        def get_velocity_value(self):     return v["value"]
    return Dlg


def _run_rq(player, dlg, **kw):
    win = _QuantWin(player)
    with patch("ui.mw_patterns.QuantizeDialog", dlg):
        PatternMixin._record_quantize_dialog(win, **kw)
    return win


def test_rq_dialog_opened_with_the_settings(player):
    player._rq_dedupe = False
    dlg = _rq_dialog(wx.ID_CANCEL)
    win = _run_rq(player, dlg)
    assert dlg.seen["record"] is True and dlg.seen["enabled"] is True
    assert dlg.seen["remove_duplicates"] is False and dlg.seen["parent"] is win


def test_rq_dialog_stores_and_announces(player):
    player.quant_idx = Q16
    win = _run_rq(player, _rq_dialog(wx.ID_OK, velocity=True, value=64, force=2))
    assert (player._rq_velocity, player._rq_velocity_value, player._rq_force_idx) == (True, 64, 2)
    assert win.undos == ["Quantisation à l'enregistrement"]
    assert win.statuses == [f"Quantisation à l'enregistrement : {Pattern.QUANT_LIST[Q16]}, "
                            "doublons enlevés, vélocité 64"]


def test_rq_dialog_disabled(player):
    win = _run_rq(player, _rq_dialog(wx.ID_OK, enabled=False))
    assert player._quant_in_recording is False
    assert win.statuses == ["Quantisation à l'enregistrement : désactivée"]


def test_rq_dialog_unchanged_or_cancelled_pops_the_undo(player):
    win = _run_rq(player, _rq_dialog(wx.ID_OK))
    assert win.undos == ["Quantisation à l'enregistrement", "pop"]
    assert win.statuses == ["Quantisation à l'enregistrement : inchangée"]
    win = _run_rq(player, _rq_dialog(wx.ID_CANCEL, dedupe=False))
    assert win.undos == ["Quantisation à l'enregistrement", "pop"]
    assert player._rq_dedupe is True                          # Annuler : rien de changé


def test_rq_dialog_from_another_window(player):
    said = []
    editor = object()
    dlg = _rq_dialog(wx.ID_OK, dedupe=False)
    _run_rq(player, dlg, parent=editor, status=said.append)
    assert dlg.seen["parent"] is editor and said[0].startswith("Quantisation à l'enregistrement")


def _undo_host(player):
    from ui.mw_project import ProjectMixin
    win = SimpleNamespace(_player=player, RECORD_QUANT_KEYS=ProjectMixin.RECORD_QUANT_KEYS)
    return win, ProjectMixin


def test_quant_params_round_trip_through_the_undo_state(player):
    win, PM = _undo_host(player)
    player._quant_dedupe, player._quant_velocity, player._quant_velocity_value = False, True, 70
    player._quant_in_recording, player._rq_dedupe, player._rq_velocity_value = False, False, 40
    qp = PM._quant_params(win)
    assert qp["record"]["_rq_velocity_value"] == 40 and qp["velocity_value"] == 70
    other = DrumPlayer(_Snd())
    host, _ = _undo_host(other)
    PM._restore_quant_params(host, qp)
    assert (other._quant_dedupe, other._quant_velocity, other._quant_velocity_value) == \
        (False, True, 70)
    assert (other._quant_in_recording, other._rq_dedupe, other._rq_velocity_value) == \
        (False, False, 40)


def test_restore_quant_params_defaults_and_unknown_keys(player):
    win, PM = _undo_host(player)
    player._quant_dedupe = False
    PM._restore_quant_params(win, {"res_idx": Q4, "record": {"_inconnu": 1}})
    assert player._quant_dedupe is True and player._quant_res_idx == Q4
    assert not hasattr(player, "_inconnu")


# ---------------------------------------------------------------------------
# Alt+Shift+Q (fenêtre principale, éditeur MIDI)
# ---------------------------------------------------------------------------

def test_alt_shift_q_main_window():
    win = FakeWindow()
    km = KeyManager(win)
    calls = []
    win._record_quantize_dialog = lambda: calls.append("rq")
    win._quantize_with_last_params = lambda: calls.append("shift+q")
    km.handle(FakeEvent(key=ord('Q'), alt=True, shift=True))
    assert calls == ["rq"]


def test_alt_shift_q_midi_editor():
    calls = []
    parent = SimpleNamespace(
        _record_quantize_dialog=lambda parent=None, status=None: calls.append((parent, status)))
    ed = SimpleNamespace(_parent=parent, _set_status=lambda m: None,
                         _quantize_with_last_params=lambda: calls.append("shift+q"))
    mew.MidiEditorWindow._on_key(ed, FakeEvent(key=ord('Q'), ukey=ord('Q'), alt=True, shift=True))
    assert calls == [(ed, ed._set_status)]
