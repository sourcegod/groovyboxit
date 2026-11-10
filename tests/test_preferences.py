#python3
"""
    File: tests/test_preferences.py
    Préférences de l'utilisateur (Phase 8 étape 10b1, docs/DESIGN.md § 10a
    P1, P5, P8, P9) : preferences.json lu par-dessus data/config.json,
    save_preferences (clés gardées, None = retour au défaut, fichier
    illisible gardé en .bak, écriture par renommage), nouvelles clés du
    dialogue, dossiers par défaut sous user_banks_dir (banks/sf2, banks/sfz,
    anciens dossiers tant qu'ils manquent), AppConfig.relocate et
    ProjectMixin._relocate_rack_files ; isolation des tests (conftest).
    Date: Tue, 10/11/2026
    Author: Coolbrother
"""
import sys
import os
import json
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from app_config import AppConfig
from rack import Rack, InstrumentType


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(data, str):
            f.write(data)
        else:
            json.dump(data, f)


def _cfg(tmp_path, defaults=None, prefs=None):
    """AppConfig de tmp_path/app, préférences dans tmp_path/cfg."""
    base = tmp_path / "app"
    os.makedirs(base, exist_ok=True)
    if defaults is not None:
        _write(str(base / "data" / "config.json"), defaults)
    prefs_path = str(tmp_path / "cfg" / "preferences.json")
    if prefs is not None:
        _write(prefs_path, prefs)
    return AppConfig(str(base), prefs_path=prefs_path)


def _read(cfg):
    with open(cfg.prefs_path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Lecture : preferences.json par-dessus data/config.json (P1)
# ---------------------------------------------------------------------------

def test_preference_overrides_default(tmp_path):
    cfg = _cfg(tmp_path, {"sfizz_gain": 1.5, "fluidsynth_gain": 0.4},
               {"sfizz_gain": 2.0})
    assert cfg.sfizz_gain == 2.0
    assert cfg.fluidsynth_gain == 0.4          # clé non réglée : défaut


def test_missing_preferences_file_gives_defaults(tmp_path):
    cfg = _cfg(tmp_path, {"sfizz_gain": 1.2})
    assert cfg.sfizz_gain == 1.2
    assert cfg.preferences() == {}


@pytest.mark.parametrize("content", ["{pas du json", "[1, 2]", "3", ""])
def test_unreadable_preferences_are_ignored(tmp_path, content):
    cfg = _cfg(tmp_path, {"sfizz_gain": 1.2}, content)
    assert cfg.sfizz_gain == 1.2
    assert cfg.preferences() == {}


def test_default_ignores_preferences(tmp_path):
    cfg = _cfg(tmp_path, {"sfizz_gain": 1.5}, {"sfizz_gain": 3.0})
    assert cfg.default("sfizz_gain") == 1.5
    assert cfg.default("absente", "x") == "x"


def test_prefs_path_from_environment(tmp_path, monkeypatch):
    path = str(tmp_path / "ailleurs" / "p.json")
    monkeypatch.setenv(AppConfig.PREFS_ENV, path)
    assert AppConfig(str(tmp_path)).prefs_path == path


def test_prefs_path_default_in_dot_config(tmp_path, monkeypatch):
    monkeypatch.delenv(AppConfig.PREFS_ENV, raising=False)
    expected = os.path.expanduser("~/.config/groovyboxit/preferences.json")
    assert AppConfig(str(tmp_path)).prefs_path == expected


def test_explicit_prefs_path_wins_over_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(AppConfig.PREFS_ENV, str(tmp_path / "env.json"))
    path = str(tmp_path / "explicite.json")
    assert AppConfig(str(tmp_path), prefs_path=path).prefs_path == path


def test_tests_never_read_real_preferences(isolated_preferences):
    # conftest : GROOVYBOXIT_PREFS pointe un fichier temporaire, hors ~/.config
    cfg = AppConfig(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert cfg.prefs_path == str(isolated_preferences)
    assert not cfg.prefs_path.startswith(os.path.expanduser("~/.config"))


# ---------------------------------------------------------------------------
# Écriture : save_preferences (P1)
# ---------------------------------------------------------------------------

def test_save_creates_folder_and_file(tmp_path):
    cfg = _cfg(tmp_path)
    path = cfg.save_preferences({"autoplay": False})
    assert path == cfg.prefs_path
    assert _read(cfg) == {"autoplay": False}


def test_save_applies_to_the_instance(tmp_path):
    cfg = _cfg(tmp_path, {"sfizz_gain": 1.5})
    cfg.save_preferences({"sfizz_gain": 2.5, "autoplay": False})
    assert cfg.sfizz_gain == 2.5
    assert cfg.autoplay is False
    assert cfg.preferences() == {"sfizz_gain": 2.5, "autoplay": False}


def test_save_keeps_unknown_keys(tmp_path):
    cfg = _cfg(tmp_path, prefs={"inconnue": [1, 2], "autoplay": True})
    cfg.save_preferences({"autoplay": False})
    assert _read(cfg) == {"inconnue": [1, 2], "autoplay": False}


def test_save_rereads_the_file_first(tmp_path):
    # une clé écrite entre-temps (autre instance) n'est pas perdue
    cfg = _cfg(tmp_path)
    other = AppConfig(str(tmp_path / "app"), prefs_path=cfg.prefs_path)
    other.save_preferences({"startup": "new"})
    cfg.save_preferences({"autoplay": False})
    assert _read(cfg) == {"startup": "new", "autoplay": False}


def test_none_removes_the_key_back_to_default(tmp_path):
    cfg = _cfg(tmp_path, {"sfizz_gain": 1.5}, {"sfizz_gain": 3.0, "autoplay": False})
    cfg.save_preferences({"sfizz_gain": None})
    assert _read(cfg) == {"autoplay": False}
    assert cfg.sfizz_gain == 1.5


def test_none_on_absent_key_is_harmless(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.save_preferences({"absente": None})
    assert _read(cfg) == {}


def test_unreadable_file_kept_as_bak(tmp_path):
    cfg = _cfg(tmp_path, prefs="{cassé")
    cfg.save_preferences({"autoplay": False})
    assert _read(cfg) == {"autoplay": False}
    with open(cfg.prefs_path + ".bak", encoding="utf-8") as f:
        assert f.read() == "{cassé"


def test_empty_file_not_kept_as_bak(tmp_path):
    cfg = _cfg(tmp_path, prefs="")
    cfg.save_preferences({"autoplay": False})
    assert not os.path.exists(cfg.prefs_path + ".bak")


def test_save_leaves_no_temporary_file(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.save_preferences({"autoplay": False})
    cfg.save_preferences({"startup": "new"})
    assert os.listdir(os.path.dirname(cfg.prefs_path)) == ["preferences.json"]


def test_failed_write_keeps_old_file(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, prefs={"autoplay": True})

    def boom(*args, **kwargs):
        raise OSError("disque plein")
    monkeypatch.setattr(json, "dump", boom)
    with pytest.raises(OSError):
        cfg.save_preferences({"autoplay": False})
    monkeypatch.undo()
    assert _read(cfg) == {"autoplay": True}
    assert os.listdir(os.path.dirname(cfg.prefs_path)) == ["preferences.json"]
    assert cfg.autoplay is True                # instance inchangée


def test_saved_file_is_readable_utf8(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.save_preferences({"projects_dir": "/home/é/Projets"})
    again = AppConfig(str(tmp_path / "app"), prefs_path=cfg.prefs_path)
    assert again.projects_dir == "/home/é/Projets"


# ---------------------------------------------------------------------------
# Général (P5)
# ---------------------------------------------------------------------------

def test_startup_default_last(tmp_path):
    assert _cfg(tmp_path).startup == AppConfig.STARTUP_LAST == "last"


@pytest.mark.parametrize("value, expected", [
    ("new", "new"), ("NEW", "new"), (" last ", "last"),
    ("autre", "last"), (3, "last"), ("", "last")])
def test_startup_values(tmp_path, value, expected):
    assert _cfg(tmp_path, prefs={"startup": value}).startup == expected


def test_last_project(tmp_path):
    assert _cfg(tmp_path).last_project == ""
    assert _cfg(tmp_path, prefs={"last_project": "/p/a.gvp"}).last_project == "/p/a.gvp"
    assert _cfg(tmp_path, prefs={"last_project": "~/a.gvp"}).last_project == \
        os.path.expanduser("~/a.gvp")
    assert _cfg(tmp_path, prefs={"last_project": 5}).last_project == ""


@pytest.mark.parametrize("key", ["autoplay", "explorer_autoplay"])
def test_autoplay_keys(tmp_path, key):
    assert getattr(_cfg(tmp_path), key) is True
    assert getattr(_cfg(tmp_path, prefs={key: False}), key) is False
    assert getattr(_cfg(tmp_path, prefs={key: "non"}), key) is True    # invalide : défaut


def test_two_autoplay_keys_are_independent(tmp_path):
    cfg = _cfg(tmp_path, prefs={"explorer_autoplay": False})
    assert cfg.autoplay is True and cfg.explorer_autoplay is False


# ---------------------------------------------------------------------------
# Projet : dossiers de l'appli et de l'utilisateur (P8)
# ---------------------------------------------------------------------------

def test_app_dirs_default_under_base_dir(tmp_path):
    cfg = _cfg(tmp_path)
    base = str(tmp_path / "app")
    assert cfg.app_projects_dir == os.path.join(base, "projects")
    assert cfg.app_banks_dir == os.path.join(base, "banks")


def test_app_dirs_absolute_relative_and_home(tmp_path):
    cfg = _cfg(tmp_path, prefs={"app_projects_dir": "/opt/demos",
                                "app_banks_dir": "lib/banks"})
    assert cfg.app_projects_dir == "/opt/demos"
    assert cfg.app_banks_dir == os.path.join(str(tmp_path / "app"), "lib/banks")
    cfg = _cfg(tmp_path, prefs={"app_banks_dir": "~/b"})
    assert cfg.app_banks_dir == os.path.expanduser("~/b")


def test_user_banks_dir_defaults_to_parent_of_projects(tmp_path):
    cfg = _cfg(tmp_path, {"projects_dir": "/data/gb/PROJECTS"})
    assert cfg.user_banks_dir == "/data/gb"
    cfg = _cfg(tmp_path, {"projects_dir": "/data/gb/PROJECTS/"})
    assert cfg.user_banks_dir == "/data/gb"


def test_user_banks_dir_set(tmp_path):
    cfg = _cfg(tmp_path, {"projects_dir": "/data/gb/PROJECTS"}, {"user_banks_dir": "/mes/banques"})
    assert cfg.user_banks_dir == "/mes/banques"


def test_kits_patches_samples_under_user_banks_dir(tmp_path):
    cfg = _cfg(tmp_path, prefs={"user_banks_dir": "/u"})
    assert cfg.kits_dir == "/u/KITS"
    assert cfg.patches_dir == "/u/PATCHS"
    assert cfg.samples_dir == "/u/SAMPLES"


def test_explicit_kits_dir_still_wins(tmp_path):
    cfg = _cfg(tmp_path, {"kits_dir": "/ailleurs/KITS"}, {"user_banks_dir": "/u"})
    assert cfg.kits_dir == "/ailleurs/KITS"
    assert cfg.patches_dir == "/u/PATCHS"


def test_banks_folders_used_when_present(tmp_path):
    user = tmp_path / "user"
    os.makedirs(user / "banks" / "sf2")
    os.makedirs(user / "banks" / "sfz")
    cfg = _cfg(tmp_path, prefs={"user_banks_dir": str(user)})
    assert cfg.soundfonts_dir == str(user / "banks" / "sf2")
    assert cfg.sfz_dir == str(user / "banks" / "sfz")
    assert cfg.gm_soundfont == str(user / "banks" / "sf2" / "FluidR3_GM.sf2")


def test_banks_subfolders_are_lowercase():
    assert (AppConfig.BANKS_SUBDIR, AppConfig.SF2_SUBDIR, AppConfig.SFZ_SUBDIR) == \
        ("banks", "sf2", "sfz")


def test_old_folders_until_banks_exist(tmp_path):
    cfg = _cfg(tmp_path, {"projects_dir": str(tmp_path / "gb" / "PROJECTS")})
    assert cfg.soundfonts_dir == "/usr/share/sounds/sf2"
    assert cfg.sfz_dir == str(tmp_path / "gb" / "media" / "sfz")
    assert cfg.legacy_sfz_dir == cfg.sfz_dir


def test_only_sf2_folder_present(tmp_path):
    gb = tmp_path / "gb"
    os.makedirs(gb / "banks" / "sf2")
    cfg = _cfg(tmp_path, {"projects_dir": str(gb / "PROJECTS")})
    assert cfg.soundfonts_dir == str(gb / "banks" / "sf2")
    assert cfg.sfz_dir == str(gb / "media" / "sfz")


def test_explicit_soundfonts_and_sfz_dirs_still_win(tmp_path):
    user = tmp_path / "user"
    os.makedirs(user / "banks" / "sf2")
    os.makedirs(user / "banks" / "sfz")
    cfg = _cfg(tmp_path, {"soundfonts_dir": "/opt/sf2", "sfz_dir": "/opt/sfz"},
               {"user_banks_dir": str(user)})
    assert cfg.soundfonts_dir == "/opt/sf2"
    assert cfg.sfz_dir == "/opt/sfz"


# ---------------------------------------------------------------------------
# Fichiers déplacés : relocate (P9)
# ---------------------------------------------------------------------------

def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    return str(path)


@pytest.fixture
def moved(tmp_path):
    """Parent gb avec banks/sf2 et banks/sfz remplis ; anciens dossiers :
    /usr/share/sounds/sf2 (système) et gb/media/sfz (absent, déplacé)."""
    gb = tmp_path / "gb"
    sf2 = _touch(gb / "banks" / "sf2" / "Copie.sf2")
    sfz = _touch(gb / "banks" / "sfz" / "Cello" / "Programs" / "01.sfz")
    top = _touch(gb / "banks" / "sfz" / "Seul.sfz")
    cfg = _cfg(tmp_path, {"projects_dir": str(gb / "PROJECTS")})
    return SimpleNamespace(cfg=cfg, gb=gb, sf2=sf2, sfz=sfz, top=top)


def test_relocate_sfz_under_old_folder(moved):
    old = str(moved.gb / "media" / "sfz" / "Cello" / "Programs" / "01.sfz")
    assert moved.cfg.relocate(old) == moved.sfz


def test_relocate_soundfont_under_system_folder(moved):
    assert moved.cfg.relocate("/usr/share/sounds/sf2/Copie.sf2") == moved.sf2


def test_relocate_prefers_copy_even_if_old_exists(tmp_path, monkeypatch):
    # SF2 copiés : l'original du système existe encore, la copie l'emporte
    system = tmp_path / "system_sf2"
    old = _touch(system / "GM.sf2")
    monkeypatch.setattr(AppConfig, "SOUNDFONTS_DIR_DEFAULT", str(system))
    gb = tmp_path / "gb"
    new = _touch(gb / "banks" / "sf2" / "GM.sf2")
    cfg = _cfg(tmp_path, {"projects_dir": str(gb / "PROJECTS")})
    assert cfg.relocate(old) == new


def test_relocate_keeps_old_when_no_copy(tmp_path, monkeypatch):
    system = tmp_path / "system_sf2"
    old = _touch(system / "Seule.sf2")
    monkeypatch.setattr(AppConfig, "SOUNDFONTS_DIR_DEFAULT", str(system))
    gb = tmp_path / "gb"
    os.makedirs(gb / "banks" / "sf2")
    cfg = _cfg(tmp_path, {"projects_dir": str(gb / "PROJECTS")})
    assert cfg.relocate(old) == old


def test_relocate_existing_file_elsewhere_unchanged(moved, tmp_path):
    other = _touch(tmp_path / "perso" / "Copie.sf2")
    assert moved.cfg.relocate(other) == other


def test_relocate_missing_by_name(moved):
    assert moved.cfg.relocate("/disparu/Copie.sf2") == moved.sf2
    assert moved.cfg.relocate("/disparu/COPIE.SF2") == "/disparu/COPIE.SF2"   # nom exact
    assert moved.cfg.relocate("/disparu/Seul.sfz") == moved.top


def test_relocate_sf3_searched_in_soundfonts(moved):
    sf3 = _touch(moved.gb / "banks" / "sf2" / "Petit.sf3")
    assert moved.cfg.relocate("/disparu/Petit.sf3") == sf3


def test_relocate_not_found_unchanged(moved):
    assert moved.cfg.relocate("/disparu/Rien.sf2") == "/disparu/Rien.sf2"
    old = str(moved.gb / "media" / "sfz" / "Absent" / "x.sfz")
    assert moved.cfg.relocate(old) == old


@pytest.mark.parametrize("value", [None, "", 3])
def test_relocate_invalid_unchanged(moved, value):
    assert moved.cfg.relocate(value) == value


def test_relocate_when_old_and_new_are_the_same(tmp_path):
    # pas encore rangé (pas de banks/) : rien à déplacer
    gb = tmp_path / "gb"
    old = str(gb / "media" / "sfz" / "x.sfz")
    cfg = _cfg(tmp_path, {"projects_dir": str(gb / "PROJECTS")})
    assert cfg.relocate(old) == old


# ---------------------------------------------------------------------------
# ProjectMixin._relocate_rack_files (P9)
# ---------------------------------------------------------------------------

from ui.mw_project import ProjectMixin


def _window(cfg, rack):
    return SimpleNamespace(_cfg=cfg, _rack=rack)


def test_rack_files_relocated(moved):
    rack = Rack()
    rack.set_bank_file(0, "/usr/share/sounds/sf2/Copie.sf2")
    rack.set_bank_file(2, "/disparu/Rien.sf2")
    rack.set_slot(5, InstrumentType.SFZ, "Cello",
                  {"sfz_source": str(moved.gb / "media" / "sfz" / "Cello" / "Programs" / "01.sfz")})
    rack.set_slot(6, InstrumentType.SFZ, "Ancien", {"sfz_file": "/disparu/Seul.sfz"})
    ProjectMixin._relocate_rack_files(_window(moved.cfg, rack))
    assert rack.bank_files == [moved.sf2, None, "/disparu/Rien.sf2", None]
    assert rack.get_slot(5).config["sfz_source"] == moved.sfz
    assert rack.get_slot(6).config["sfz_file"] == moved.top


def test_relative_sfz_source_left_alone(moved):
    rack = Rack()
    rack.set_slot(3, InstrumentType.SFZ, "Rel", {"sfz_source": "Cello/Programs/01.sfz"})
    ProjectMixin._relocate_rack_files(_window(moved.cfg, rack))
    assert rack.get_slot(3).config["sfz_source"] == "Cello/Programs/01.sfz"


def test_non_sfz_slot_config_untouched(moved):
    rack = Rack()
    rack.set_slot(2, InstrumentType.KIT, "Kit", {"kit": "/disparu/Seul.sfz"})
    ProjectMixin._relocate_rack_files(_window(moved.cfg, rack))
    assert rack.get_slot(2).config["kit"] == "/disparu/Seul.sfz"


def test_relocated_config_is_a_new_dict(moved):
    rack = Rack()
    config = {"sfz_source": "/disparu/Seul.sfz"}
    rack.set_slot(4, InstrumentType.SFZ, "S", config)
    before = rack.get_slot(4).config
    ProjectMixin._relocate_rack_files(_window(moved.cfg, rack))
    assert before == {"sfz_source": "/disparu/Seul.sfz"}      # pas modifié en place
    assert rack.get_slot(4).config["sfz_source"] == moved.top


def test_bank_files_list_replaced_not_mutated(moved):
    rack = Rack()
    rack.set_bank_file(0, "/usr/share/sounds/sf2/Copie.sf2")
    before = rack.bank_files
    ProjectMixin._relocate_rack_files(_window(moved.cfg, rack))
    assert before[0] == "/usr/share/sounds/sf2/Copie.sf2"     # instantané d'Undo intact
    assert rack.bank_files[0] == moved.sf2


def test_window_without_config_does_nothing():
    rack = Rack()
    rack.set_bank_file(0, "/disparu/Rien.sf2")
    ProjectMixin._relocate_rack_files(SimpleNamespace(_rack=rack))
    assert rack.bank_files[0] == "/disparu/Rien.sf2"
