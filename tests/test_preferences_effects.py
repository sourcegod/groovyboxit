#python3
"""
    File: tests/test_preferences_effects.py
    Effets des Préférences (Phase 8 étapes 10f1, 10f2, docs/DESIGN.md
    § 10a P2, P5, P8 ; § 10f2) : projet ouvert au démarrage
    (_resolve_project_path), dernier projet retenu (_remember_project, par
    Ctrl+O, l'Explorateur, Ctrl+S), dossier de départ de l'Explorateur
    (_explorer_dir), effet immédiat ou au prochain lancement
    (_apply_preferences_now, _refresh_dirs_from_cfg), gain de FluidSynth en
    cours de route (FluidSynthEngine.set_gain), bouton « Valeurs par
    défaut » (restore_defaults, AppConfig.defaults_only) ; vraie fenêtre
    principale : démarrage « Nouveau projet », Autoplay lu, limiteur coupé
    tout de suite.
    Date: Wed, 11/11/2026
    Author: Coolbrother
"""
import sys
import os
import json
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import wx

from app_config import AppConfig
from project_manager import ProjectManager
from ui.mw_project import ProjectMixin
from ui.mw_pads import PadMixin
from ui.dialogs_preferences import PreferencesDialog
from audio.engines.fluidsynth_engine import FluidSynthEngine, fluidsynth_available


def _cfg(tmp_path, prefs=None, defaults=None):
    base = tmp_path / "app"
    os.makedirs(base / "data", exist_ok=True)
    if defaults is not None:
        (base / "data" / "config.json").write_text(json.dumps(defaults), encoding="utf-8")
    path = tmp_path / "cfg" / "preferences.json"
    if prefs is not None:
        os.makedirs(path.parent, exist_ok=True)
        path.write_text(json.dumps(prefs), encoding="utf-8")
    return AppConfig(str(base), prefs_path=str(path))


def _prefs(cfg):
    try:
        with open(cfg.prefs_path, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    return str(path)


# ---------------------------------------------------------------------------
# Démarrage : _resolve_project_path (P5)
# ---------------------------------------------------------------------------

def _start_win(tmp_path, cfg):
    projects = str(tmp_path / "PROJECTS")
    win = SimpleNamespace(_cfg=cfg, _projects_dir=projects, _presets_dir=str(tmp_path / "PRESETS"))
    win._find_free_project_path = lambda: ProjectMixin._find_free_project_path(win)
    return win


def test_startup_new_gives_a_free_name(tmp_path):
    win = _start_win(tmp_path, _cfg(tmp_path, {"startup": "new"}))
    _touch(tmp_path / "PROJECTS" / "project_01.gvp")
    _touch(tmp_path / "PROJECTS" / "noname_001.gvp")
    path = ProjectMixin._resolve_project_path(win)
    assert path == str(tmp_path / "PROJECTS" / "noname_002.gvp")
    assert not os.path.exists(path)          # rien à charger : patterns neufs


def test_startup_last_opens_last_project(tmp_path):
    last = _touch(tmp_path / "ailleurs" / "mon.gvp")
    _touch(tmp_path / "PROJECTS" / "project_01.gvp")
    win = _start_win(tmp_path, _cfg(tmp_path, {"last_project": last}))
    assert ProjectMixin._resolve_project_path(win) == last


def test_startup_last_missing_falls_back_to_project_01(tmp_path):
    win = _start_win(tmp_path, _cfg(tmp_path, {"last_project": "/nulle/part.gvp"}))
    assert ProjectMixin._resolve_project_path(win) == \
        str(tmp_path / "PROJECTS" / ProjectManager.DEFAULT_NAME)


def test_startup_last_on_a_folder_falls_back(tmp_path):
    os.makedirs(tmp_path / "dossier.gvp")
    win = _start_win(tmp_path, _cfg(tmp_path, {"last_project": str(tmp_path / "dossier.gvp")}))
    assert ProjectMixin._resolve_project_path(win).endswith(ProjectManager.DEFAULT_NAME)


def test_startup_without_preference_unchanged(tmp_path):
    legacy = _touch(tmp_path / "PRESETS" / "preset_01.json")
    win = _start_win(tmp_path, _cfg(tmp_path))
    assert ProjectMixin._resolve_project_path(win) == legacy


def test_startup_without_config(tmp_path):
    win = _start_win(tmp_path, None)
    assert ProjectMixin._resolve_project_path(win).endswith(ProjectManager.DEFAULT_NAME)


# ---------------------------------------------------------------------------
# Dernier projet : _remember_project (P5)
# ---------------------------------------------------------------------------

def test_remember_writes_absolute_path(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _touch(tmp_path / "w" / "p.gvp")
    monkeypatch.chdir(tmp_path / "w")
    ProjectMixin._remember_project(SimpleNamespace(_cfg=cfg, _project_path="p.gvp"))
    assert _prefs(cfg) == {"last_project": str(tmp_path / "w" / "p.gvp")}
    assert cfg.last_project == str(tmp_path / "w" / "p.gvp")


def test_remember_skips_missing_file(tmp_path):
    cfg = _cfg(tmp_path)
    ProjectMixin._remember_project(SimpleNamespace(_cfg=cfg, _project_path=str(tmp_path / "x.gvp")))
    assert not os.path.exists(cfg.prefs_path)


def test_remember_skips_unchanged(tmp_path, monkeypatch):
    path = _touch(tmp_path / "p.gvp")
    cfg = _cfg(tmp_path, {"last_project": path})
    monkeypatch.setattr(cfg, "save_preferences", lambda v: pytest.fail("écrit pour rien"))
    ProjectMixin._remember_project(SimpleNamespace(_cfg=cfg, _project_path=path))


def test_remember_ignores_write_error(tmp_path, monkeypatch):
    path = _touch(tmp_path / "p.gvp")
    cfg = _cfg(tmp_path)

    def boom(values):
        raise OSError("lecture seule")
    monkeypatch.setattr(cfg, "save_preferences", boom)
    ProjectMixin._remember_project(SimpleNamespace(_cfg=cfg, _project_path=path))


def test_remember_without_config_or_path():
    ProjectMixin._remember_project(SimpleNamespace(_project_path="/x.gvp"))
    ProjectMixin._remember_project(SimpleNamespace(_cfg=None, _project_path=""))


class _FileDialog:
    def __init__(self, path):
        self._path = path
    def __call__(self, *args, **kwargs):
        return self
    def ShowModal(self):
        return wx.ID_OK
    def GetPath(self):
        return self._path
    def Destroy(self):
        pass


def _opener(tmp_path):
    calls = []
    win = SimpleNamespace(_project_modified=False, _projects_dir=str(tmp_path / "PROJECTS"),
                          _cfg=None, statuses=[])
    win._take_end_if_idle = lambda: None
    win._load_project = lambda: calls.append("load")
    win._remember_project = lambda: calls.append("remember")
    win._project_loaded_msg = lambda: "chargé"
    win._show_status = win.statuses.append
    return win, calls


def test_ctrl_o_remembers_after_loading(tmp_path):
    path = _touch(tmp_path / "PROJECTS" / "a.gvp")
    win, calls = _opener(tmp_path)
    with patch("ui.mw_project.wx.FileDialog", _FileDialog(path)):
        ProjectMixin._open_project(win)
    assert win._project_path == path and calls == ["load", "remember"]


def test_explorer_projects_remembers_after_loading(tmp_path):
    path = _touch(tmp_path / "PROJECTS" / "b.gvp")
    win, calls = _opener(tmp_path)
    win._explorer_dir = lambda user_dir, app_sub="": user_dir
    with patch("ui.mw_pads.wx.FileDialog", _FileDialog(path)):
        PadMixin._explorer_projects(win)
    assert win._project_path == path and calls == ["load", "remember"]


def test_save_remembers_the_project(tmp_path):
    calls = []
    pat = SimpleNamespace(_voices=None, to_dict=lambda: {})
    win = SimpleNamespace(
        _project_path=str(tmp_path / "s.gvp"), _cur_pattern_idx=0, _pattern_list=[pat],
        _player=SimpleNamespace(voice_manager=SimpleNamespace(to_list=lambda: [])),
        _rack=SimpleNamespace(to_dict=lambda: {}), _song_list=[], _cur_song_idx=0,
        _project_modified=True, statuses=[])
    win._flush_pattern_to_store = lambda p: None
    win._master_dict = lambda: {}
    win._update_title = lambda: None
    win._show_status = win.statuses.append
    win._remember_project = lambda: calls.append(os.path.isfile(win._project_path))
    ProjectMixin._save_project(win)
    assert calls == [True]                   # après l'écriture du fichier


def test_failed_save_does_not_remember(tmp_path):
    calls = []
    win = SimpleNamespace(_project_path=str(tmp_path / "x.gvp"), _cur_pattern_idx=0,
                          _pattern_list=[], statuses=[])
    win._show_status = win.statuses.append
    win._remember_project = lambda: calls.append(1)
    ProjectMixin._save_project(win)          # _pattern_list vide : erreur annoncée
    assert calls == [] and win.statuses[0].startswith("ERREUR sauvegarde")


# ---------------------------------------------------------------------------
# Explorateur : _explorer_dir (P8)
# ---------------------------------------------------------------------------

def test_explorer_user_dir_first(tmp_path):
    user = tmp_path / "KITS"
    os.makedirs(user)
    os.makedirs(tmp_path / "app" / "banks" / "KITS")
    win = SimpleNamespace(_cfg=_cfg(tmp_path))
    assert PadMixin._explorer_dir(win, str(user), "KITS") == str(user)


def test_explorer_app_banks_when_user_dir_missing(tmp_path):
    os.makedirs(tmp_path / "app" / "banks" / "sf2")
    win = SimpleNamespace(_cfg=_cfg(tmp_path))
    assert PadMixin._explorer_dir(win, str(tmp_path / "absent"), "sf2") == \
        str(tmp_path / "app" / "banks" / "sf2")


def test_explorer_app_projects_when_user_projects_missing(tmp_path):
    os.makedirs(tmp_path / "app" / "projects")
    win = SimpleNamespace(_cfg=_cfg(tmp_path))
    assert PadMixin._explorer_dir(win, str(tmp_path / "absent")) == \
        str(tmp_path / "app" / "projects")


def test_explorer_home_when_nothing_exists(tmp_path):
    win = SimpleNamespace(_cfg=_cfg(tmp_path))
    assert PadMixin._explorer_dir(win, str(tmp_path / "absent"), "KITS") == \
        os.path.expanduser("~")


def test_explorer_without_config(tmp_path):
    assert PadMixin._explorer_dir(SimpleNamespace(), str(tmp_path)) == str(tmp_path)
    assert PadMixin._explorer_dir(SimpleNamespace(), "") == os.path.expanduser("~")


# ---------------------------------------------------------------------------
# Effet immédiat : _apply_preferences_now (P2)
# ---------------------------------------------------------------------------

class _Engine:
    def __init__(self):
        self.gains = []
        self.gain = 1.5
    def set_gain(self, g):
        self.gains.append(g)


class _Driver:
    def __init__(self):
        self.limiter_calls = []
    def set_limiter(self, on):
        self.limiter_calls.append(on)


def _live_win(cfg):
    win = SimpleNamespace(_cfg=cfg, _autoplay=True, _audio_driver=_Driver(),
                          _bank_engine=_Engine(), _sfz_engine=_Engine(),
                          _router=SimpleNamespace(sfz_dir="ancien"),
                          _master_defaults=(100, 0),
                          PREFS_DIR_KEYS=ProjectMixin.PREFS_DIR_KEYS,
                          PREFS_AT_RESTART=ProjectMixin.PREFS_AT_RESTART,
                          PREFS_AUDIO_OUT_KEYS=ProjectMixin.PREFS_AUDIO_OUT_KEYS,
                          PREFS_MIDI_KEYS=ProjectMixin.PREFS_MIDI_KEYS)
    win._refresh_dirs_from_cfg = lambda: ProjectMixin._refresh_dirs_from_cfg(win)
    return win


def _apply(win, changes):
    win._cfg.save_preferences(changes)
    return ProjectMixin._apply_preferences_now(win, changes)


def test_autoplay_now(tmp_path):
    win = _live_win(_cfg(tmp_path))
    assert _apply(win, {"autoplay": False}) == []
    assert win._autoplay is False


def test_limiter_now(tmp_path):
    win = _live_win(_cfg(tmp_path))
    _apply(win, {"live_limiter": False})
    _apply(win, {"live_limiter": True})
    assert win._audio_driver.limiter_calls == [False, True]


def test_gains_now(tmp_path):
    win = _live_win(_cfg(tmp_path))
    _apply(win, {"fluidsynth_gain": 3.6, "sfizz_gain": 2.0})
    assert win._bank_engine.gains == [3.6]
    assert win._sfz_engine.gain == 2.0


def test_gains_without_engines(tmp_path):
    win = _live_win(_cfg(tmp_path))
    win._bank_engine = win._sfz_engine = None
    assert _apply(win, {"fluidsynth_gain": 3.6, "sfizz_gain": 2.0}) == []


def test_untouched_settings_not_reapplied(tmp_path):
    win = _live_win(_cfg(tmp_path))
    _apply(win, {"autoplay": False})
    assert win._bank_engine.gains == [] and win._audio_driver.limiter_calls == []
    assert win._router.sfz_dir == "ancien"


def test_master_defaults_now(tmp_path):
    win = _live_win(_cfg(tmp_path))
    _apply(win, {"master_volume": 150, "master_pan": -20})
    assert win._master_defaults == (150, -20)


def test_dirs_now(tmp_path):
    win = _live_win(_cfg(tmp_path))
    user = tmp_path / "u"
    os.makedirs(user / "banks" / "sfz")
    _apply(win, {"user_banks_dir": str(user), "projects_dir": str(user / "PROJECTS")})
    assert win._kits_dir == str(user / "KITS")
    assert win._patches_dir == str(user / "PATCHS")
    assert win._samples_dir == str(user / "SAMPLES")
    assert win._projects_dir == str(user / "PROJECTS")
    assert win._exports_dir == str(user / "EXPORTS")
    assert win._sfz_dir == str(user / "banks" / "sfz")
    assert win._router.sfz_dir == win._sfz_dir


@pytest.mark.parametrize("key, label", [("fluidsynth", "moteur FluidSynth"),
                                        ("sfizz", "moteur sfizz"),
                                        ("midi_bank_select", "sélection de banque")])
def test_settings_at_next_launch(tmp_path, key, label):
    win = _live_win(_cfg(tmp_path))
    value = "mma" if key == "midi_bank_select" else False
    assert _apply(win, {key: value}) == [label]


def test_apply_preferences_announces_next_launch(tmp_path):
    win = _live_win(_cfg(tmp_path))
    win._apply_preferences_now = lambda changes: ProjectMixin._apply_preferences_now(win, changes)
    said = []
    ProjectMixin._apply_preferences(win, {"fluidsynth": False, "sfizz": False, "autoplay": False},
                                    said.append)
    assert said == ["Préférences enregistrées (3 réglages) ; au prochain lancement : "
                    "moteur FluidSynth, moteur sfizz"]


def test_apply_preferences_failure_applies_nothing(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("x")
    cfg = AppConfig(str(tmp_path), prefs_path=str(blocker / "p.json"))
    win = _live_win(cfg)
    win._apply_preferences_now = lambda changes: pytest.fail("appliqué malgré l'erreur")
    said = []
    assert ProjectMixin._apply_preferences(win, {"autoplay": False}, said.append) is False
    assert win._autoplay is True and said[0].startswith("ERREUR")


# ---------------------------------------------------------------------------
# FluidSynthEngine.set_gain (vraie bibliothèque)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not fluidsynth_available(), reason="libfluidsynth absente")
def test_fluidsynth_set_gain():
    eng = FluidSynthEngine(gain=0.4)
    try:
        assert eng.gain == 0.4
        eng.set_gain(3.6)
        assert eng.gain == 3.6
        eng.set_gain(50)
        assert eng.gain == 10.0
        eng.set_gain(-1)
        assert eng.gain == 0.0
    finally:
        eng.close()


# ---------------------------------------------------------------------------
# Valeurs par défaut (10f2)
# ---------------------------------------------------------------------------

def test_defaults_only_ignores_preferences(tmp_path):
    cfg = _cfg(tmp_path, {"fluidsynth_gain": 3.6}, {"fluidsynth_gain": 0.5})
    assert cfg.fluidsynth_gain == 3.6
    d = cfg.defaults_only()
    assert d.fluidsynth_gain == 0.5 and d.preferences() == {}
    assert d.prefs_path == os.devnull


@pytest.fixture
def dialog(tmp_path):
    made = []

    def build(prefs, defaults=None):
        cfg = _cfg(tmp_path, prefs, defaults)
        applied = []
        dlg = PreferencesDialog(None, cfg, on_apply=applied.append)
        made.append(dlg)
        return dlg, applied
    yield build
    for dlg in made:
        dlg.Destroy()


def test_default_buttons_on_settable_tabs(dialog):
    dlg, _ = dialog({})
    for tab in ("Général", "Audio", "Midi", "Projet"):
        last = list(dlg._pages[tab].GetChildren())[-1]
        assert isinstance(last, wx.Button) and last.GetLabel() == "Valeurs par défaut"
    for tab in ("Matériel", "Raccourcis", "Divers"):
        assert not any(isinstance(c, wx.Button) for c in dlg._pages[tab].GetChildren())


def test_restore_defaults_only_this_tab(dialog):
    dlg, _ = dialog({"fluidsynth_gain": 3.6, "master_volume": 150, "autoplay": False,
                     "midi_bank_select": "mma"})
    dlg.restore_defaults("Audio")
    assert dlg.changes() == {"fluidsynth_gain": 0.4, "master_volume": 100}
    assert dlg._autoplay.GetValue() is False              # onglet Général gardé
    assert dlg._bank_select.GetStringSelection().startswith("MMA")


def test_restore_defaults_applies_nothing_by_itself(dialog):
    dlg, applied = dialog({"autoplay": False})
    dlg.restore_defaults("Général")
    assert applied == []


def test_restored_value_removes_the_key(dialog):
    dlg, applied = dialog({"fluidsynth_gain": 3.6, "autoplay": False})
    dlg.restore_defaults("Audio")
    dlg._apply()
    assert applied == [{"fluidsynth_gain": None}]


def test_value_equal_to_default_is_sent_as_none(dialog):
    dlg, applied = dialog({"master_volume": 150})
    dlg._master_volume.SetValue(100)
    dlg._apply()
    assert applied == [{"master_volume": None}]


def test_defaults_follow_config_json(dialog):
    dlg, _ = dialog({"sfizz_gain": 3.0}, defaults={"sfizz_gain": 1.2})
    dlg.restore_defaults("Audio")
    assert dlg._sfizz_gain.GetValue() == 12


def test_restore_project_paths(dialog, tmp_path):
    dlg, applied = dialog({"projects_dir": "/u/P", "app_banks_dir": "/opt/b"},
                          defaults={"projects_dir": "/gb/PROJECTS"})
    dlg.restore_defaults("Projet")
    assert dlg._paths["projects_dir"].GetValue() == "/gb/PROJECTS"
    assert dlg._paths["app_banks_dir"].GetValue() == str(tmp_path / "app" / "banks")
    # banques de l'utilisateur : défaut = parent du dossier des projets par défaut
    assert dlg._paths["user_banks_dir"].GetValue() == "/gb"
    dlg._apply()
    assert applied == [{"projects_dir": None, "app_banks_dir": None, "user_banks_dir": None}]


def test_restore_general_and_midi(dialog):
    dlg, _ = dialog({"startup": "new", "explorer_autoplay": False, "midi_bank_select": "mma"})
    dlg.restore_defaults("Général")
    dlg.restore_defaults("Midi")
    assert dlg._startup.GetSelection() == 0
    assert dlg._explorer_autoplay.GetValue() is True
    assert dlg._bank_select.GetSelection() == 0


def test_default_button_click(dialog):
    dlg, _ = dialog({"master_pan": 40})
    btn = dlg._default_btns["Audio"]
    evt = wx.CommandEvent(wx.wxEVT_BUTTON, btn.GetId())
    evt.SetEventObject(btn)
    btn.GetEventHandler().ProcessEvent(evt)
    assert dlg._master_pan.GetValue() == 0


# ---------------------------------------------------------------------------
# Vraie fenêtre principale : démarrage, Autoplay, limiteur
# ---------------------------------------------------------------------------

def test_real_main_window_startup_new_and_live_settings(isolated_preferences, monkeypatch):
    """Une seule vraie MainWindow (clients ALSA, cf. test_auto_input_mode)."""
    from ui.main_window import MainWindow
    path = str(isolated_preferences)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"startup": "new", "autoplay": False}, f)
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    win = None
    try:
        win = MainWindow(no_fluidsynth=True, no_sfizz=True)
        assert os.path.basename(win._project_path).startswith("noname_")
        assert not os.path.exists(win._project_path)
        assert win._autoplay is False
        assert win._audio_driver.limiter is not None
        win._apply_preferences({"live_limiter": False, "autoplay": True})
        assert win._audio_driver.limiter is None and win._autoplay is True
        assert win._status_ctrl.GetString(0).startswith("Préférences enregistrées (2 réglages)")
    finally:
        if win is not None:
            win._router.wait_loaded()     # fils de chargement finis avant Destroy
            win._midi.close()
            win._audio_driver.close()
            win.Destroy()
        os.remove(path)
