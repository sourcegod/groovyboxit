#python3
"""
    File: tests/test_app_config.py
    Clés de data/config.json du slot Banque (Phase 7 étape 17c1,
    docs/DESIGN.md § 17a1 D7, D17, écart de gain de 17b1) :
    soundfonts_dir, gm_soundfont, midi_bank_select, fluidsynth_gain —
    défauts, chemins absolus et relatifs, valeurs invalides, bornes. Slot
    Synth SFZ et moteurs optionnels (Phase 8 étape 7c1, § 7a2 Z7, Z13) :
    sfz_dir, sfizz_gain, fluidsynth / sfizz.
    Les clés master_volume / master_pan sont testées dans
    test_master_mix.py. Depuis la Phase 8 étape 10b1, les anciens dossiers
    par défaut (/usr/share/sounds/sf2, media/sfz) ne servent que si
    banks/sf2 / banks/sfz manquent : ces tests placent les banques de
    l'utilisateur dans un dossier temporaire (le vrai /home/com/groovybox/banks
    existe) ; les nouveaux défauts sont testés dans test_preferences.py.
    Date: Mon, 26/10/2026
    Author: Coolbrother
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from app_config import AppConfig


def _cfg(tmp_path, data=None):
    if data is not None:
        os.makedirs(tmp_path / "data", exist_ok=True)
        (tmp_path / "data" / "config.json").write_text(json.dumps(data), encoding="utf-8")
    return AppConfig(str(tmp_path))


# ---------------------------------------------------------------------------
# soundfonts_dir / gm_soundfont (D7)
# ---------------------------------------------------------------------------

def _no_banks(tmp_path, data=None):
    """Banques de l'utilisateur dans un dossier sans banks/ (10c1)."""
    return {"user_banks_dir": str(tmp_path / "user"), **(data or {})}


def test_soundfont_defaults_without_file(tmp_path):
    cfg = _cfg(tmp_path, _no_banks(tmp_path))
    assert cfg.soundfonts_dir == "/usr/share/sounds/sf2"
    assert cfg.gm_soundfont == "/usr/share/sounds/sf2/FluidR3_GM.sf2"


@pytest.mark.parametrize("value", ["", "   ", None, 3])
def test_empty_or_invalid_soundfonts_dir_gives_default(tmp_path, value):
    cfg = _cfg(tmp_path, _no_banks(tmp_path, {"soundfonts_dir": value}))
    assert cfg.soundfonts_dir == "/usr/share/sounds/sf2"


def test_absolute_soundfonts_dir(tmp_path):
    assert _cfg(tmp_path, {"soundfonts_dir": "/opt/sf2"}).soundfonts_dir == "/opt/sf2"


def test_relative_soundfonts_dir_from_base_dir(tmp_path):
    cfg = _cfg(tmp_path, {"soundfonts_dir": "SOUNDFONTS"})
    assert cfg.soundfonts_dir == os.path.join(str(tmp_path), "SOUNDFONTS")


def test_gm_soundfont_relative_to_soundfonts_dir(tmp_path):
    cfg = _cfg(tmp_path, {"soundfonts_dir": "/opt/sf2", "gm_soundfont": "GeneralUser_GS.sf2"})
    assert cfg.gm_soundfont == "/opt/sf2/GeneralUser_GS.sf2"


def test_gm_soundfont_absolute(tmp_path):
    cfg = _cfg(tmp_path, {"gm_soundfont": "/home/x/mon.sf2"})
    assert cfg.gm_soundfont == "/home/x/mon.sf2"


def test_gm_soundfont_default_follows_soundfonts_dir(tmp_path):
    cfg = _cfg(tmp_path, {"soundfonts_dir": "/opt/sf2"})
    assert cfg.gm_soundfont == "/opt/sf2/FluidR3_GM.sf2"


# ---------------------------------------------------------------------------
# midi_bank_select (D17)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("gs", "gs"), ("mma", "mma"), ("MMA", "mma"), (" mma ", "mma"),
    ("xg", "gs"), ("", "gs"), (None, "gs"), (1, "gs"),
])
def test_midi_bank_select(tmp_path, value, expected):
    assert _cfg(tmp_path, {"midi_bank_select": value}).midi_bank_select == expected


def test_midi_bank_select_default(tmp_path):
    assert _cfg(tmp_path).midi_bank_select == "gs"


# ---------------------------------------------------------------------------
# fluidsynth_gain (écart de 17b1 ; défaut 0.4 depuis la Phase 7 étape 18d4)
# ---------------------------------------------------------------------------

def test_fluidsynth_gain_default(tmp_path):
    assert _cfg(tmp_path).fluidsynth_gain == 0.4


@pytest.mark.parametrize("value, expected", [
    (0.6, 0.6), (2, 2.0), (0, 0.0), (15, 10.0), (-1, 0.0),
])
def test_fluidsynth_gain_read_and_clamped(tmp_path, value, expected):
    assert _cfg(tmp_path, {"fluidsynth_gain": value}).fluidsynth_gain == expected


@pytest.mark.parametrize("bad", ["0.5", None, True, [1]])
def test_fluidsynth_gain_invalid_gives_default(tmp_path, bad):
    assert _cfg(tmp_path, {"fluidsynth_gain": bad}).fluidsynth_gain == 0.4


# ---------------------------------------------------------------------------
# sfz_dir, sfizz_gain, moteurs optionnels (Phase 8 étape 7c1, docs/DESIGN.md
# § 7a2 Z7, Z13, avancement 7b1)
# ---------------------------------------------------------------------------

def test_sfz_dir_default_next_to_projects_dir(tmp_path):
    # sans banks/sfz : l'ancien media/sfz, à côté du dossier des projets
    cfg = _cfg(tmp_path, {"projects_dir": str(tmp_path / "gb" / "PROJECTS")})
    assert cfg.sfz_dir == str(tmp_path / "gb" / "media" / "sfz")


def test_sfz_dir_default_follows_projects_dir(tmp_path):
    cfg = _cfg(tmp_path, {"projects_dir": "/data/gb/PROJECTS"})
    assert cfg.sfz_dir == "/data/gb/media/sfz"


def test_sfz_dir_absolute(tmp_path):
    assert _cfg(tmp_path, {"sfz_dir": "/srv/sfz"}).sfz_dir == "/srv/sfz"


def test_sfz_dir_relative_to_base_dir(tmp_path):
    assert _cfg(tmp_path, {"sfz_dir": "instruments/sfz"}).sfz_dir == \
        os.path.join(str(tmp_path), "instruments/sfz")


@pytest.mark.parametrize("bad", ["", "   ", None, 3])
def test_sfz_dir_empty_or_invalid_gives_default(tmp_path, bad):
    cfg = _cfg(tmp_path, {"projects_dir": str(tmp_path / "gb" / "PROJECTS"), "sfz_dir": bad})
    assert cfg.sfz_dir == str(tmp_path / "gb" / "media" / "sfz")


def test_sfizz_gain_default(tmp_path):
    # 1.5 depuis l'essai de 7d1 (plus agréable et plus clair que 1.0)
    assert _cfg(tmp_path).sfizz_gain == 1.5


@pytest.mark.parametrize("value, expected", [
    (1.5, 1.5), (2, 2.0), (0, 0.0), (15, 10.0), (-1, 0.0),
])
def test_sfizz_gain_read_and_clamped(tmp_path, value, expected):
    assert _cfg(tmp_path, {"sfizz_gain": value}).sfizz_gain == expected


@pytest.mark.parametrize("bad", ["1.5", None, True, [1]])
def test_sfizz_gain_invalid_gives_default(tmp_path, bad):
    assert _cfg(tmp_path, {"sfizz_gain": bad}).sfizz_gain == 1.5


def test_engines_enabled_by_default(tmp_path):
    cfg = _cfg(tmp_path)
    assert cfg.fluidsynth_enabled and cfg.sfizz_enabled


def test_engines_disabled_by_config(tmp_path):
    cfg = _cfg(tmp_path, {"fluidsynth": False, "sfizz": False})
    assert not cfg.fluidsynth_enabled and not cfg.sfizz_enabled


@pytest.mark.parametrize("bad", ["false", 0, None, "no"])
def test_engine_switch_needs_a_real_boolean(tmp_path, bad):
    # Seul false coupe un moteur : une valeur douteuse le laisse actif.
    cfg = _cfg(tmp_path, {"fluidsynth": bad, "sfizz": bad})
    assert cfg.fluidsynth_enabled and cfg.sfizz_enabled
