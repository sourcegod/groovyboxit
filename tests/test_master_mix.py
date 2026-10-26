#python3
"""
    File: tests/test_master_mix.py
    Volume et pan globaux (Phase 7 étape 15e1, docs/DESIGN.md § 15a1 D2-D4,
    avenant 15a2) : défauts lus dans data/config.json (AppConfig), clé
    "master" du .gvp à la sauvegarde et à l'ouverture (ancien projet sans
    la clé, valeurs invalides), Nouveau projet, Undo regroupé et rétabli
    par Ctrl+Z, et chaque raccourci ou champ qui les règle.
    Les vraies méthodes de ProjectMixin, KeyManager et MainWindow tournent
    sur une fenêtre factice avec un vrai DrumPlayer ; son SoundManager est
    simulé, pour vérifier ce qui atteint le pilote audio.
    Date: Mon, 26/10/2026
    Author: Coolbrother
"""
import sys
import os
import json
import types
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import wx

from app_config import AppConfig
from pattern import Pattern
from song import Song
from rack import Rack
from undo_manager import UndoManager
from player.drum_player import DrumPlayer
from ui.mw_project import ProjectMixin
from ui.main_window import MainWindow
from ui.key_manager import KeyManager


# ---------------------------------------------------------------------------
# Fenêtre factice
# ---------------------------------------------------------------------------

class _Spin:
    def __init__(self, value=0):
        self.value = value
    def GetValue(self):    return self.value
    def SetValue(self, v): self.value = v


class _Win(ProjectMixin):
    def __init__(self, tmp_path, defaults=(100, 0)):
        self._project_path    = str(tmp_path / "projet.gvp")
        self._projects_dir    = str(tmp_path)
        self._rack            = Rack()
        self._pattern_list    = [Pattern() for _ in range(2)]
        self._song_list       = [Song(i) for i in range(2)]
        self._cur_pattern_idx = 0
        self._cur_song_idx    = 0
        self._song_window     = None
        self._player          = DrumPlayer(sound_manager=MagicMock())
        self._router          = MagicMock()
        self._slot_choice     = MagicMock()
        self._pattern_listbox = MagicMock()
        self._volume_ctrl     = _Spin(self._player.volume)
        self._pan_ctrl        = _Spin(self._player.pan)
        self._master_defaults = defaults
        self._project_modified = False
        self._take            = None
        self._note_repeat     = False          # lu par _handle_chars avant +/-
        self._undo            = UndoManager()
        self._pattern_cache       = [None] * len(self._pattern_list)
        self._pattern_cache_dirty = set(range(len(self._pattern_list)))
        self.status = []
        self.now    = 0.0
        self._mix_clock = lambda: self.now

    def _flush_pattern_to_store(self, pat):     pass
    def _apply_pattern_from_store(self, new):   pass
    def _clipboard_to_dict(self):               return None
    def _clipboard_from_dict(self, d):          pass
    def _update_slot_list(self):                pass
    def _load_kit_slot(self, idx):              pass
    def _refresh_pattern_listbox(self):         pass
    def _refresh_grid(self):                    pass
    def _refresh_all_voice_display(self):       pass
    def _refresh_track_list(self):              pass
    def _refresh_pad_list(self):                pass
    def _update_bpm_display(self):              pass
    def SetTitle(self, title):                  pass
    def _show_status(self, msg):                self.status.append(msg)

    # --- raccourcis de test
    def titles(self):
        return [e.title for e in self._undo.history_list()]

    def master(self):
        """(volume, pan) du player, et vérifie que les SpinCtrl suivent."""
        p = self._player
        assert (self._volume_ctrl.value, self._pan_ctrl.value) == (p.volume, p.pan)
        return p.volume, p.pan

    def pilot_volume(self):
        """Dernier volume transmis au pilote audio (SoundManager.set_volume)."""
        return self._player.sound_man.set_volume.call_args.args[0]


@pytest.fixture
def win(tmp_path):
    return _Win(tmp_path)


def _write_config(tmp_path, data):
    os.makedirs(tmp_path / "data", exist_ok=True)
    (tmp_path / "data" / "config.json").write_text(json.dumps(data), encoding="utf-8")
    return AppConfig(str(tmp_path))


def _write_project(path, master=None):
    data = {"version": 1, "rack": Rack().to_dict(),
            "patterns": [Pattern().to_dict()], "songs": [], "cur_song": 0}
    if master is not None:
        data["master"] = master
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


# ---------------------------------------------------------------------------
# AppConfig : défauts de data/config.json (D3, avenant 15a2)
# ---------------------------------------------------------------------------

def test_config_without_file_gives_100_and_0(tmp_path):
    cfg = AppConfig(str(tmp_path))
    assert (cfg.master_volume, cfg.master_pan) == (100, 0)


def test_config_without_keys_gives_100_and_0(tmp_path):
    cfg = _write_config(tmp_path, {"media_dir": "media"})
    assert (cfg.master_volume, cfg.master_pan) == (100, 0)


def test_config_reads_values(tmp_path):
    cfg = _write_config(tmp_path, {"master_volume": 80, "master_pan": -10})
    assert (cfg.master_volume, cfg.master_pan) == (80, -10)


def test_config_clamps_values(tmp_path):
    cfg = _write_config(tmp_path, {"master_volume": 150, "master_pan": -300})
    assert (cfg.master_volume, cfg.master_pan) == (100, -100)
    cfg = _write_config(tmp_path, {"master_volume": -5, "master_pan": 300})
    assert (cfg.master_volume, cfg.master_pan) == (0, 100)


@pytest.mark.parametrize("bad", ["80", None, True, [80], {"v": 80}])
def test_config_invalid_value_gives_default(tmp_path, bad):
    cfg = _write_config(tmp_path, {"master_volume": bad, "master_pan": bad})
    assert (cfg.master_volume, cfg.master_pan) == (100, 0)


def test_config_float_is_truncated(tmp_path):
    cfg = _write_config(tmp_path, {"master_volume": 72.9, "master_pan": -3.5})
    assert (cfg.master_volume, cfg.master_pan) == (72, -3)


def test_repo_config_has_documented_defaults():
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, "data", "config.json"), encoding="utf-8") as f:
        data = json.load(f)
    assert (data["master_volume"], data["master_pan"]) == (100, 0)


def test_player_starts_at_100():
    assert DrumPlayer(sound_manager=MagicMock()).volume == 100


# ---------------------------------------------------------------------------
# Clé "master" du .gvp (D2, D3)
# ---------------------------------------------------------------------------

def test_master_from_dict_missing_or_not_dict_gives_defaults(tmp_path):
    w = _Win(tmp_path, defaults=(80, -10))
    for d in (None, [], "x", 3):
        assert w._master_from_dict(d) == (80, -10)


def test_master_from_dict_partial_and_invalid_fields(tmp_path):
    w = _Win(tmp_path, defaults=(80, -10))
    assert w._master_from_dict({"volume": 60}) == (60, -10)
    assert w._master_from_dict({"pan": 25}) == (80, 25)
    assert w._master_from_dict({"volume": "60", "pan": True}) == (80, -10)
    assert w._master_from_dict({"volume": 500, "pan": -500}) == (100, -100)


def test_save_writes_master_key(win):
    win._set_master_volume_undo(70)
    win._set_master_pan_undo(-20)
    win._save_project()
    with open(win._project_path, encoding="utf-8") as f:
        assert json.load(f)["master"] == {"volume": 70, "pan": -20}


def test_load_project_with_master_applies_it(win):
    _write_project(win._project_path, master={"volume": 65, "pan": 15})
    win._load_project()
    assert win.master() == (65, 15)
    assert win.pilot_volume() == 65


def test_load_old_project_without_master_takes_config_defaults(tmp_path):
    w = _Win(tmp_path, defaults=(80, -10))
    w._apply_master(50, 40)                      # valeurs du projet précédent
    _write_project(w._project_path)
    w._load_project()
    assert w.master() == (80, -10)               # rien ne passe d'un projet au suivant
    assert w.pilot_volume() == 80


def test_load_project_with_invalid_master_takes_defaults_per_field(tmp_path):
    w = _Win(tmp_path, defaults=(80, -10))
    _write_project(w._project_path, master={"volume": "fort", "pan": 30})
    w._load_project()
    assert w.master() == (80, 30)


def test_save_then_load_round_trip(tmp_path):
    w = _Win(tmp_path)
    w._apply_master(42, -7)
    w._save_project()
    w2 = _Win(tmp_path)
    w2._load_project()
    assert w2.master() == (42, -7)


def test_load_does_not_leave_project_modified(win):
    _write_project(win._project_path, master={"volume": 65, "pan": 15})
    win._load_project()
    assert win._project_modified is False
    assert win.titles() == []


def test_new_project_resets_to_config_defaults(tmp_path):
    w = _Win(tmp_path, defaults=(80, -10))
    w._apply_master(50, 40)
    w._new_project()
    assert w.master() == (80, -10)
    assert w.pilot_volume() == 80
    assert w._project_modified is False


# ---------------------------------------------------------------------------
# Undo (D4)
# ---------------------------------------------------------------------------

def test_volume_change_adds_entry_marks_modified_and_reaches_pilot(win):
    assert win._set_master_volume_undo(75) == 75
    assert win.master() == (75, 0)
    assert win.pilot_volume() == 75
    assert win.titles() == ["Volume global: 75"]
    assert win._project_modified is True


def test_volume_burst_is_one_entry_undone_at_once(win):
    for t, v in ((0.0, 99), (0.3, 98), (0.6, 97)):
        win.now = t
        win._set_master_volume_undo(v)
    assert win.titles() == ["Volume global: 97"]
    win._undo_action()
    assert win.master() == (100, 0)
    assert win.pilot_volume() == 100


def test_pan_change_entry_and_undo(win):
    win._set_master_pan_undo(-3)
    assert win.master() == (100, -3)
    assert win.titles() == ["Pan global: -3"]
    win._undo_action()
    assert win.master() == (100, 0)


def test_volume_and_pan_are_separate_entries(win):
    win._set_master_volume_undo(90)
    win.now = 0.2
    win._set_master_pan_undo(5)
    assert win.titles() == ["Pan global: 5", "Volume global: 90"]


def test_unchanged_value_adds_nothing(win):
    win._set_master_volume_undo(100)
    win._set_master_volume_undo(140)              # borné à 100 : inchangé
    win._set_master_pan_undo(0)
    assert win.titles() == []
    assert win._project_modified is False


def test_snapshot_holds_master_and_redo_reapplies(win):
    win._set_master_volume_undo(60)
    assert win._undo.history_list()[0].state["master"] == {"volume": 100, "pan": 0}
    win._undo_action()
    assert win.master() == (100, 0)
    win._redo_action()
    assert win.master() == (60, 0)
    assert win.pilot_volume() == 60


def test_restore_of_snapshot_without_master_keeps_current_values(win):
    win._apply_master(55, 12)
    state = win._capture_state()
    del state["master"]                           # instantané d'avant 15d1
    win._restore_state(state)
    assert win.master() == (55, 12)


# ---------------------------------------------------------------------------
# Raccourcis et champs
# ---------------------------------------------------------------------------

class _Event:
    def __init__(self, key, ukey=0):
        self._key, self._ukey = key, ukey
    def GetKeyCode(self):    return self._key
    def GetUnicodeKey(self): return self._ukey
    def Skip(self):          pass


def _ctx(key, ukey=0, ctrl=False, on_pan=False):
    return types.SimpleNamespace(
        key=key, ukey=ukey, ctrl=ctrl, shift=False, alt=False,
        on_quant_list=False, on_pattern_list=False, on_bpm=False,
        on_volume=False, on_pan=on_pan, on_voice_spin=False,
        on_mode_choice=False, on_scale_choice=False, on_slot_choice=False,
        on_track_list=False, on_pad_list=False, on_vel_list=False,
        on_midi_port_list=False, on_status_ctrl=False,
    )


@pytest.mark.parametrize("key, start, expected, title", [
    (wx.WXK_UP,    (90, 0), (91, 0),  "Volume global: 91"),
    (wx.WXK_DOWN,  (90, 0), (89, 0),  "Volume global: 89"),
    (wx.WXK_RIGHT, (90, 0), (90, 1),  "Pan global: 1"),
    (wx.WXK_LEFT,  (90, 0), (90, -1), "Pan global: -1"),
    (ord('0'),     (90, 7), (90, 0),  "Pan global: 0"),
])
def test_ctrl_shortcuts(win, key, start, expected, title):
    win._apply_master(*start)
    assert KeyManager(win)._handle_ctrl(_Event(key), _ctx(key, ctrl=True))
    assert win.master() == expected
    assert win.titles() == [title]


@pytest.mark.parametrize("key, ukey, expected", [
    (ord('+'), ord('+'), 91),
    (ord('-'), ord('-'), 89),
    (ord('6'), 0,        89),
])
def test_plus_minus_six(win, key, ukey, expected):
    win._apply_master(90, 0)
    assert KeyManager(win)._handle_chars(_Event(key, ukey), _ctx(key, ukey))
    assert win.master() == (expected, 0)
    assert win.titles() == [f"Volume global: {expected}"]
    assert win.status[-1] == f"Volume: {expected}"


def test_plus_at_100_adds_nothing(win):
    KeyManager(win)._handle_chars(_Event(ord('+'), ord('+')), _ctx(ord('+'), ord('+')))
    assert win.master() == (100, 0)
    assert win.titles() == []


@pytest.mark.parametrize("key, expected", [
    (wx.WXK_UP, 1), (wx.WXK_RIGHT, 1), (wx.WXK_DOWN, -1), (wx.WXK_LEFT, -1),
])
def test_arrows_in_pan_field(win, key, expected):
    assert KeyManager(win)._handle_navigation(_Event(key), _ctx(key, on_pan=True))
    assert win.master() == (100, expected)
    assert win.titles() == [f"Pan global: {expected}"]


def test_volume_spin(win):
    win._volume_ctrl.value = 64
    MainWindow._on_volume_spin(win, None)
    assert win.master() == (64, 0)
    assert win.pilot_volume() == 64
    assert win.titles() == ["Volume global: 64"]


def test_pan_spin(win):
    win._pan_ctrl.value = -40
    MainWindow._on_pan_spin(win, None)
    assert win.master() == (100, -40)
    assert win.titles() == ["Pan global: -40"]
