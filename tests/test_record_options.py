#python3
"""
    File: tests/test_record_options.py
    Options de l'enregistrement (Phase 8 étape 16b1, docs/DESIGN.md § Phase 8
    étape 16a, O1-O11, et essais de 16b1) : table des modes (record_modes) et
    lecture des options ; dialogue Ctrl+Shift+R ; RecordOptionsMixin (Undo,
    annonces, options appliquées au lecteur) ; touches (R, Shift+R, Ctrl+R,
    Ctrl+Shift+R dans les trois fenêtres, Espace et Ctrl+Espace avec le
    décompte de lecture) ; lecteur (clic pendant la lecture, décomptes de
    lecture et d'enregistrement, fin du décompte) ; vraie fenêtre principale
    (projet : sauvegarde, relecture, ancien projet, Ctrl+N, Undo / Redo).
    Date: Tue, 17/11/2026
    Author: Coolbrother
"""
import sys
import os
import json
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import wx

import record_modes as rm
from player.drum_player import DrumPlayer
from ui.dialogs import RecordOptionsDialog
from ui.mw_record_options import RecordOptionsMixin
import ui.mw_record_options as mro
import ui.midi_editor_window as mew
from ui.song_window import SongWindow
from ui.key_manager import KeyManager
from test_key_manager import FakeWindow, FakeEvent


# ---------------------------------------------------------------------------
# Table des modes et options
# ---------------------------------------------------------------------------

def test_modes_table():
    assert [m.id for m in rm.MODES] == ["overdub", "replace", "mpc"]
    assert [m.label for m in rm.MODES] == ["Overdub", "Remplacer",
                                           "Remplacer puis Overdub (MPC)"]
    assert [(m.replace, m.then_overdub) for m in rm.MODES] == \
        [(False, False), (True, False), (True, True)]
    assert [m.short for m in rm.MODES] == ["Rec", "Replace Rec", "Rec (MPC)"]


@pytest.mark.parametrize("mode_id, expected", [
    ("overdub", "overdub"), ("replace", "replace"), ("mpc", "mpc"),
    ("punch", "overdub"), (None, "overdub"), (3, "overdub")])     # inconnu → Overdub
def test_mode_of(mode_id, expected):
    assert rm.mode_of(mode_id).id == expected
    assert rm.MODES[rm.mode_index(mode_id)].id == expected


def test_defaults_are_the_old_behaviour():
    assert rm.DEFAULTS == {"mode": "overdub", "click_play": False, "count_in_play": 0,
                           "click_record": True, "count_in": 1,
                           "monitor": False}            # monitoring décoché (20d1, M1b)
    assert rm.COUNT_IN_CHOICES == (0, 1, 2, 4, 8)


@pytest.mark.parametrize("data", [None, [], "x", {}])
def test_normalize_without_options(data):
    assert rm.normalize(data) == rm.DEFAULTS


def test_normalize_keeps_valid_fields():
    opts = {"mode": "mpc", "click_play": True, "count_in_play": 4, "click_record": False,
            "count_in": 8, "monitor": True}
    assert rm.normalize(opts) == opts


@pytest.mark.parametrize("bad, key", [
    ({"mode": "inconnu"}, "mode"), ({"click_play": 1}, "click_play"),
    ({"click_record": "oui"}, "click_record"), ({"count_in": 3}, "count_in"),
    ({"count_in": True}, "count_in"), ({"count_in_play": -1}, "count_in_play"),
    ({"count_in_play": 2.0}, "count_in_play"), ({"monitor": 1}, "monitor"),
    ({"monitor": "oui"}, "monitor")])
def test_normalize_invalid_field_gets_its_default(bad, key):
    assert rm.normalize(bad)[key] == rm.DEFAULTS[key]


def test_normalize_returns_a_new_dict():
    out = rm.normalize(None)
    out["mode"] = "mpc"
    assert rm.DEFAULTS["mode"] == "overdub"


@pytest.mark.parametrize("n, label", [(0, "aucun"), (1, "1 mesure"), (4, "4 mesures")])
def test_count_label(n, label):
    assert rm.count_label(n) == label


def test_describe():
    assert rm.describe(rm.DEFAULTS) == ("Mode : Overdub ; clic : enregistrement ; décompte "
                                        "de lecture : aucun ; décompte d'enregistrement : "
                                        "1 mesure")
    assert rm.describe({"mode": "mpc", "click_play": True, "click_record": False,
                        "count_in": 0, "count_in_play": 2}) == \
        ("Mode : Remplacer puis Overdub (MPC) ; clic : lecture ; décompte de lecture : "
         "2 mesures ; décompte d'enregistrement : aucun")
    assert "clic : aucun" in rm.describe({"click_record": False})
    # monitoring (20d1) : nommé seulement s'il est coché
    assert rm.describe({"monitor": True}).endswith(" ; monitoring de l'entrée")
    assert "monitoring" not in rm.describe({"monitor": False})


# ---------------------------------------------------------------------------
# Dialogue
# ---------------------------------------------------------------------------

def test_dialog_fields_in_order_with_focus_on_the_mode():
    dlg = RecordOptionsDialog(None, rm.DEFAULTS)
    try:
        assert dlg.GetTitle() == "Options de l'enregistrement"
        fields = [c for c in dlg.GetChildren() if not isinstance(c, (wx.StaticText, wx.Button))]
        assert fields == [dlg._mode_lb, dlg._click_play, dlg._count_play_lb,
                          dlg._click_record, dlg._count_lb, dlg._monitor]
        assert wx.Window.FindFocus() in (dlg._mode_lb, None)
        assert dlg._mode_lb.GetStrings() == ["Mode : Overdub", "Mode : Remplacer",
                                             "Mode : Remplacer puis Overdub (MPC)"]
        assert dlg._click_play.GetLabel() == "Clic pendant la lecture"
        assert dlg._click_record.GetLabel() == "Clic pendant l'enregistrement"
        assert dlg._count_play_lb.GetStrings()[:2] == [
            "Décompte pendant la lecture : aucun", "Décompte pendant la lecture : 1 mesure"]
        assert dlg._count_lb.GetStrings()[-1] == "Décompte pendant l'enregistrement : 8 mesures"
        assert dlg._monitor.GetLabel() == "Monitoring de l'entrée (F8)"     # 20d1
        assert not dlg._monitor.GetValue()
    finally:
        dlg.Destroy()


def test_dialog_shows_and_returns_the_options():
    opts = {"mode": "mpc", "click_play": True, "count_in_play": 2, "click_record": False,
            "count_in": 4, "monitor": True}
    dlg = RecordOptionsDialog(None, opts)
    try:
        assert dlg.get_options() == opts
        dlg._mode_lb.SetSelection(1)
        dlg._count_lb.SetSelection(0)
        dlg._click_play.SetValue(False)
        dlg._monitor.SetValue(False)
        assert dlg.get_options() == dict(opts, mode="replace", count_in=0, click_play=False,
                                         monitor=False)
    finally:
        dlg.Destroy()


def test_dialog_invalid_options_shown_as_defaults():
    dlg = RecordOptionsDialog(None, {"mode": "?", "count_in": 7})
    try:
        assert dlg.get_options() == rm.DEFAULTS
    finally:
        dlg.Destroy()


@pytest.mark.parametrize("name", ["_mode_lb", "_count_play_lb", "_count_lb"])
def test_dialog_enter_on_a_list_validates(name):
    dlg = RecordOptionsDialog(None, rm.DEFAULTS)
    ended = []
    dlg.EndModal = ended.append
    try:
        lb = getattr(dlg, name)
        lb.ProcessEvent(wx.CommandEvent(wx.EVT_LISTBOX_DCLICK.typeId, lb.GetId()))
        assert ended == [wx.ID_OK]
    finally:
        dlg.Destroy()


# ---------------------------------------------------------------------------
# RecordOptionsMixin
# ---------------------------------------------------------------------------

class _S:
    def __getattr__(self, name):
        return lambda *a, **k: None


def _player():
    p = DrumPlayer(_S())
    p.start_thread = p.stop_thread = lambda: None
    return p


class OptWin(RecordOptionsMixin):
    def __init__(self):
        self._player = _player()
        self.statuses, self.undos, self.titles = [], [], 0
        self._record_options = dict(rm.DEFAULTS)

    def _show_status(self, msg): self.statuses.append(msg)
    def _add_undo(self, title):  self.undos.append(title)
    def _update_title(self):     self.titles += 1


class _FakeOptDlg:
    result, options, opened = wx.ID_OK, None, []

    def __init__(self, parent, options):
        _FakeOptDlg.opened.append((parent, dict(options)))
    def ShowModal(self):   return _FakeOptDlg.result
    def get_options(self): return dict(_FakeOptDlg.options)
    def Destroy(self):     pass


@pytest.fixture
def fake_dialog(monkeypatch):
    _FakeOptDlg.result, _FakeOptDlg.opened = wx.ID_OK, []
    monkeypatch.setattr(mro, "RecordOptionsDialog", _FakeOptDlg)
    return _FakeOptDlg


def test_apply_record_options_sets_the_player():
    win = OptWin()
    win._apply_record_options({"mode": "replace", "click_play": True, "count_in_play": 2,
                               "click_record": False, "count_in": 4})
    p = win._player
    assert (p.count_in_bars, p.click_in_recording, p.click_in_playback,
            p.count_in_play_bars) == (4, False, True, 2)
    assert win._record_mode().id == "replace"
    win._apply_record_options(None)                      # défauts
    assert (p.count_in_bars, p.click_in_recording, p.click_in_playback,
            p.count_in_play_bars) == (1, True, False, 0)


def test_open_options_changed_adds_undo_and_announces(fake_dialog):
    win = OptWin()
    fake_dialog.options = dict(rm.DEFAULTS, mode="mpc", count_in=2)
    said, parent = [], object()
    assert win._open_record_options(parent=parent, status=said.append) is True
    assert fake_dialog.opened == [(parent, rm.DEFAULTS)]
    assert win.undos == ["Options de l'enregistrement"]
    assert win._record_options["mode"] == "mpc" and win._player.count_in_bars == 2
    assert said == ["Options de l'enregistrement — " + rm.describe(win._record_options)]
    assert win.titles == 1 and win.statuses == []


def test_open_options_unchanged_or_cancelled(fake_dialog):
    win = OptWin()
    fake_dialog.options = dict(rm.DEFAULTS)
    assert win._open_record_options() is False
    assert win.statuses == ["Options de l'enregistrement inchangées"] and win.undos == []
    fake_dialog.result = wx.ID_CANCEL
    fake_dialog.options = dict(rm.DEFAULTS, mode="replace")
    assert win._open_record_options() is False
    assert win.statuses[-1] == "Options de l'enregistrement : annulé"
    assert win._record_options["mode"] == "overdub" and win.undos == []


def test_open_options_normalizes_the_dialog_values(fake_dialog):
    win = OptWin()
    fake_dialog.options = {"mode": "mpc", "count_in": 99}
    win._open_record_options()
    assert win._record_options == dict(rm.DEFAULTS, mode="mpc")


# ---------------------------------------------------------------------------
# Touches
# ---------------------------------------------------------------------------

def _km(mode="overdub", **player):
    win = FakeWindow()                   # wx.App de la session (conftest)
    win.record_mode_id = mode
    for k, v in player.items():
        setattr(win._player, k, v)
    return win, KeyManager(win)


@pytest.mark.parametrize("mode, call, title, short", [
    ("overdub", "record_pattern", "Enregistrement piste 1", "Rec"),
    ("replace", "start_replace_recording", "Remplacement piste 1", "Replace Rec"),
    ("mpc", "start_replace_recording", "Remplacement piste 1", "Rec (MPC)")])
def test_r_follows_the_mode(mode, call, title, short):
    win, km = _km(mode)
    km.handle(FakeEvent(key=ord('R')))
    assert call in win._player.calls
    assert ('_take_begin', title, False) in win.calls
    status = [c[1] for c in win.calls if isinstance(c, tuple) and c[0] == '_show_status']
    assert status[-1].startswith(f"{short}: Piste 1")


@pytest.mark.parametrize("mode, replace", [("overdub", False), ("replace", True),
                                           ("mpc", True)])
def test_r_on_an_audio_track_prepares_the_take_in_the_mode(mode, replace):
    win, km = _km(mode)
    win.audio_track = True
    km.handle(FakeEvent(key=ord('R')))
    assert win.audio_replace is replace


@pytest.mark.parametrize("mode, replace", [("overdub", False), ("replace", True),
                                           ("mpc", True)])
def test_ctrl_r_follows_the_mode(mode, replace):
    win, km = _km(mode)
    km.handle(FakeEvent(key=ord('R'), ctrl=True))
    assert 'record_pattern_with_count_in' in win._player.calls
    assert win._player.count_in_replace is replace


def test_shift_r_stays_replace_whatever_the_mode():
    win, km = _km("overdub")
    km.handle(FakeEvent(key=ord('R'), shift=True))
    assert 'start_replace_recording' in win._player.calls


def test_ctrl_shift_r_opens_the_options_main_window():
    win, km = _km()
    km.handle(FakeEvent(key=ord('R'), ctrl=True, shift=True))
    assert '_open_record_options' in win.calls
    assert 'record_pattern_with_count_in' not in win._player.calls


class _Key:
    def __init__(self, key, ctrl=False, shift=False, alt=False):
        self._k, self._c, self._s, self._a = key, ctrl, shift, alt
        self.skipped = False
    def GetKeyCode(self):    return self._k
    def GetUnicodeKey(self): return self._k
    def ControlDown(self):   return self._c
    def ShiftDown(self):     return self._s
    def AltDown(self):       return self._a
    def Skip(self):          self.skipped = True


def test_ctrl_shift_r_opens_the_options_midi_editor():
    calls = []
    parent = SimpleNamespace(
        _open_record_options=lambda parent=None, status=None: calls.append((parent, status)),
        _key_manager=SimpleNamespace(handle_transport=lambda evt: False))
    ed = SimpleNamespace(_parent=parent, _set_status=lambda m: None)
    mew.MidiEditorWindow._on_key(ed, _Key(ord('R'), ctrl=True, shift=True))
    assert calls == [(ed, ed._set_status)]


def test_ctrl_shift_r_opens_the_options_song_window():
    calls = []
    parent = SimpleNamespace(
        _open_record_options=lambda parent=None, status=None: calls.append((parent, status)),
        _key_manager=SimpleNamespace(handle_transport=lambda evt: False))
    stub = SimpleNamespace(_parent=parent, _cur_song_idx=0, _set_status=lambda m: None)
    SongWindow._on_key(stub, FakeEvent(key=ord('R'), ctrl=True, shift=True))
    assert calls == [(stub, stub._set_status)]


def _with_play_count_in(win, bars):
    win._player.count_in_play_bars = bars
    win._player.play_with_count_in = lambda: win._player.calls.append('play_with_count_in')


def test_space_with_a_play_count_in():
    win, km = _km()
    _with_play_count_in(win, 2)
    km.handle(FakeEvent(key=wx.WXK_SPACE))
    assert win._player.calls == ['play_with_count_in']
    assert ('_show_status', "Décompte : 2 mesures...") in win.calls


def test_space_without_play_count_in_plays():
    win, km = _km()
    _with_play_count_in(win, 0)
    km.handle(FakeEvent(key=wx.WXK_SPACE))
    assert win._player.calls == ['play_pattern']


def test_space_during_a_play_count_in_cancels_it():
    win, km = _km(_count_in=1, _count_in_record=False)
    km.handle(FakeEvent(key=wx.WXK_SPACE))
    assert win._player.calls == ['stop_all']
    assert ('_show_status', "Décompte annulé") in win.calls


def test_ctrl_space_with_a_play_count_in():
    win, km = _km()
    _with_play_count_in(win, 1)
    win._player.goto_start = lambda: win._player.calls.append('goto_start')
    km.handle(FakeEvent(key=wx.WXK_SPACE, ctrl=True))
    assert win._player.calls == ['goto_start', 'play_with_count_in']
    assert ('_show_status', "Décompte : 1 mesure...") in win.calls


# ---------------------------------------------------------------------------
# Lecteur : clics et décomptes
# ---------------------------------------------------------------------------

def test_click_in_playback_started_by_play_stopped_by_pause():
    p = _player()
    p.click_in_playback = True
    p.play_pattern()
    assert p.clicking and p._click_by_play
    p.pause_pattern()
    assert not p.clicking and not p._click_by_play


def test_click_in_playback_off_play_has_no_click():
    p = _player()
    p.play_pattern()
    assert not p.clicking


def test_manual_click_not_stopped_by_pause():
    p = _player()
    p.click_in_playback = True
    p.clicking = True                                  # C avant Play
    p.play_pattern()
    p.pause_pattern()
    assert p.clicking


@pytest.mark.parametrize("stop", ["stop_pattern", "stop_all", "stop_click"])
def test_stops_forget_the_play_click(stop):
    p = _player()
    p.click_in_playback = True
    p.play_pattern()
    getattr(p, stop)()
    assert not p._click_by_play and not p.clicking


def test_record_stop_during_playback_keeps_the_play_click():
    p = _player()
    p.click_in_playback = True
    p.record_pattern()                    # le clic d'enregistrement démarre (Rec depuis l'arrêt)
    assert p.clicking and p.playing
    p.stop_record()
    assert p.clicking and p._click_by_play          # la lecture continue avec son clic
    p.pause_pattern()
    assert not p.clicking


def test_record_stop_without_play_click_stops_the_record_click():
    p = _player()
    p.record_pattern()
    p.stop_record()
    assert not p.clicking


def test_click_in_recording_off_rec_has_no_click():
    p = _player()
    p.click_in_recording = False
    p.record_pattern()
    assert not p.clicking


@pytest.mark.parametrize("replace", [False, True])
def test_count_in_record_keeps_the_mode(replace):
    p = _player()
    p.record_pattern_with_count_in(2, replace=replace)
    assert p._count_in == 2 and p._count_in_record is True
    assert p.replace_recording is replace and not p.recording


@pytest.mark.parametrize("replace, flag", [(False, False), (True, True)])
def test_count_in_record_without_bars_starts_at_once(replace, flag):
    p = _player()
    p.record_pattern_with_count_in(0, replace=replace)
    assert p.recording and p.replace_recording is flag and p._count_in == 0


def test_play_with_count_in_starts_the_count_in():
    p = _player()
    chased = []
    p._chase = lambda pos: chased.append(pos)
    p.count_in_play_bars = 2
    p.play_with_count_in()
    assert p._count_in == 2 and p._count_in_record is False
    assert not p.playing and not p.recording and p.clicking
    assert chased == [0.0]


@pytest.mark.parametrize("bars, playing", [(0, False), (2, True)])
def test_play_with_count_in_plays_at_once(bars, playing):
    p = _player()
    p.count_in_play_bars = bars
    p.playing = playing
    played = []
    p.play_pattern = lambda: played.append(1)
    p.play_with_count_in()
    assert played == [1] and p._count_in == 0


def _end_count_in(p):
    """Fin du dernier temps du décompte (fenêtre déjà passée : pas d'attente)."""
    secs = p._pattern._num_steps * p.step_duration
    p._on_count_in_done_cb = None
    p._on_measure_end(time.perf_counter() - secs - 0.01, secs, 0)


def test_end_of_play_count_in_plays_without_recording():
    p = _player()
    p.count_in_play_bars = 1
    p.play_with_count_in()
    _end_count_in(p)
    assert p.playing and not p.recording and p._count_in == 0


def test_end_of_record_count_in_records():
    p = _player()
    p.record_pattern_with_count_in(1, replace=True)
    _end_count_in(p)
    assert p.playing and p.recording and p.replace_recording


@pytest.mark.parametrize("record, click_record, click_play, before, clicking", [
    (True, True, False, False, True),      # clic pendant l'enregistrement
    (True, False, False, False, False),    # décoché : le clic du décompte s'arrête
    (True, False, False, True, True),      # tournait déjà avant
    (True, False, True, False, True),      # la lecture le demande
    (False, True, False, False, False),    # décompte de lecture, sans clic de lecture
    (False, False, True, False, True),     # clic pendant la lecture
    (False, False, False, True, True),     # tournait déjà avant
])
def test_count_in_click_done(record, click_record, click_play, before, clicking):
    p = _player()
    p.clicking = True
    p._count_in_record = record
    p.click_in_recording = click_record
    p.click_in_playback = click_play
    p._metro._before_rec = before
    p._count_in_clicked_before = before
    p._count_in_click_done()
    assert p.clicking is clicking


# ---------------------------------------------------------------------------
# Vraie fenêtre principale : projet, Undo
# ---------------------------------------------------------------------------

_APP = None


@pytest.mark.gui
def test_real_main_window_project_options(isolated_preferences, monkeypatch, tmp_path):
    """Une seule vraie MainWindow (clients ALSA)."""
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)
    from ui.main_window import MainWindow
    monkeypatch.setattr(mro, "RecordOptionsDialog", _FakeOptDlg)
    _FakeOptDlg.result = wx.ID_OK
    win = None
    try:
        win = MainWindow(no_fluidsynth=True, no_sfizz=True)
        win._router.wait_loaded()
        p = win._player
        assert win._record_options == rm.DEFAULTS
        new = {"mode": "replace", "click_play": True, "count_in_play": 2,
               "click_record": False, "count_in": 4, "monitor": False}
        _FakeOptDlg.options = new
        assert win._open_record_options()
        assert (p.count_in_bars, p.click_in_recording, p.click_in_playback,
                p.count_in_play_bars) == (4, False, True, 2)
        assert win._project_modified

        # Undo / Redo
        win._undo_action()
        assert win._record_options == rm.DEFAULTS and p.count_in_bars == 1
        win._redo_action()
        assert win._record_options == new and p.count_in_bars == 4

        # sauvegarde et relecture
        win._project_path = str(tmp_path / "P.gvp")
        win._save_project()
        assert json.load(open(win._project_path))["record_options"] == new
        win._apply_record_options(None)
        win._load_project()
        assert win._record_options == new and p.click_in_playback is True

        # ancien projet sans la clé
        d = json.load(open(win._project_path))
        del d["record_options"]
        json.dump(d, open(str(tmp_path / "old.gvp"), "w"))
        win._project_path = str(tmp_path / "old.gvp")
        win._load_project()
        assert win._record_options == rm.DEFAULTS and p.count_in_bars == 1

        # Ctrl+N : défauts
        win._apply_record_options(new)
        win._project_modified = False
        win._new_project()
        assert win._record_options == rm.DEFAULTS and p.click_in_playback is False
    finally:
        if win is not None:
            win._player.stop_all()
            win._router.wait_loaded()
            win._close_midi_devices()
            win._audio_driver.close()
            win.Destroy()
