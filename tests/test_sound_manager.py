#python3
"""
    File: tests/test_sound_manager.py
    Tests unitaires de SoundManager avec SoundDeviceDriver (défaut) et
    PygameDriver (optionnel). Vérifie que les deux backends donnent le même
    comportement observable : chargement, note_map, play, stop, volume.
    Notes des pads et correspondance GM du kit (Phase 7 étape 11e1).
    Date: Thu, 28/05/2026
    Author: Coolbrother
"""
import sys
import os
import glob
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pygame
from pygame_driver      import PygameDriver
from sound_device_driver import SoundDeviceDriver, SdSound
from sound_manager      import SoundManager

MEDIA_DIR = os.path.join(os.path.dirname(__file__), "..", "media")
WAVS      = sorted(glob.glob(os.path.join(MEDIA_DIR, "*.wav")))
MEDIA16   = (WAVS * 2)[:16]   # 16 chemins WAV (on boucle si < 16)
CLICK1    = WAVS[0]
CLICK2    = WAVS[1]

# Drivers partagés
_pygame_drv = PygameDriver()
_sd_drv     = SoundDeviceDriver()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_sm(driver):
    return SoundManager(list(MEDIA16), CLICK1, CLICK2, driver=driver)


def make_kit_json(wav_paths):
    """Crée un kit JSON temporaire pointant vers les WAVs donnés."""
    pads = []
    for i, path in enumerate(wav_paths[:16], start=1):
        pads.append({
            "pad":      i,
            "note":     35 + i - 1,
            "filename": path,
            "label":    f"Pad {i:02d}",
        })
    meta = {"name": "TestKit", "pads": pads}
    f = tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    )
    json.dump(meta, f)
    f.close()
    return f.name


# ---------------------------------------------------------------------------
# Initialisation — driver par défaut
# ---------------------------------------------------------------------------

def test_default_driver_is_sounddevice():
    sm = SoundManager(list(MEDIA16), CLICK1, CLICK2)
    assert isinstance(sm._driver, SoundDeviceDriver)
    sm._driver.close()
    print("  driver par défaut == SoundDeviceDriver : OK")


def test_click_sounds_loaded():
    sm = make_sm(_pygame_drv)
    assert sm.sound_click1 is not None
    assert sm.sound_click2 is not None
    print("  click1/click2 chargés à l'init : OK")


# ---------------------------------------------------------------------------
# Tests communs — exécutés pour les deux backends
# ---------------------------------------------------------------------------

def _test_load_sounds(driver, tag):
    sm = make_sm(driver)
    sm.load_sounds()
    assert len(sm.drum_sounds) == 16
    print(f"  [{tag}] load_sounds → 16 sons : OK")


def _test_load_pad_sound(driver, tag):
    sm = make_sm(driver)
    sm.load_sounds()
    sm.load_pad_sound(0, WAVS[2])
    assert sm.drum_sounds[0] is not None
    # Le slot 0 est bien différent des autres (rechargé)
    assert sm.drum_sounds[0] is not sm.drum_sounds[1]
    print(f"  [{tag}] load_pad_sound → drum_sounds[0] mis à jour : OK")


def _test_load_pad_sound_extends_list(driver, tag):
    sm = make_sm(driver)
    sm.load_pad_sound(20, WAVS[0])   # index > 16 : doit étendre la liste
    assert len(sm.drum_sounds) >= 21
    assert sm.drum_sounds[20] is not None
    print(f"  [{tag}] load_pad_sound index>16 → liste étendue : OK")


def _test_silent_sound_not_none(driver, tag):
    sm = make_sm(driver)
    sil = sm._silent_sound()
    assert sil is not None
    print(f"  [{tag}] _silent_sound() not None : OK")


def _test_load_kit_labels(driver, tag):
    kit_path = make_kit_json(WAVS[:8])
    try:
        sm = make_sm(driver)
        labels, wav_paths = sm.load_kit(kit_path)
        assert len(labels)    == 16
        assert len(wav_paths) == 16
        assert labels[0] == "Pad 01"
    finally:
        os.unlink(kit_path)
    print(f"  [{tag}] load_kit → 16 labels : OK")


def _test_load_kit_populates_drum_sounds(driver, tag):
    kit_path = make_kit_json(WAVS[:8])
    try:
        sm = make_sm(driver)
        sm.load_kit(kit_path)
        assert len(sm.drum_sounds) == 16
        assert all(s is not None for s in sm.drum_sounds)
    finally:
        os.unlink(kit_path)
    print(f"  [{tag}] load_kit → drum_sounds[16] non nuls : OK")


def _test_load_kit_populates_note_map(driver, tag):
    kit_path = make_kit_json(WAVS[:8])
    try:
        sm = make_sm(driver)
        sm.load_kit(kit_path)
        assert len(sm.note_map) >= 8    # autant de sons que de pads avec "note"
        assert 35 in sm.note_map        # première note GM drums
    finally:
        os.unlink(kit_path)
    print(f"  [{tag}] load_kit → note_map peuplé : OK")


def _test_play_sound_no_crash(driver, tag):
    sm = make_sm(driver)
    sm.load_sounds()
    sm.play_sound(0)
    sm.play_sound(0, volume_factor=0.5, pan=-50)
    sm.stop_all()
    print(f"  [{tag}] play_sound → pas de crash : OK")


def _test_play_note_valid_no_crash(driver, tag):
    kit_path = make_kit_json(WAVS[:8])
    try:
        sm = make_sm(driver)
        sm.load_kit(kit_path)
        sm.play_note(35)              # note GM valide dans le kit
        sm.play_note(35, volume_factor=0.7, pan=30)
        sm.stop_all()
    finally:
        os.unlink(kit_path)
    print(f"  [{tag}] play_note note valide → pas de crash : OK")


def _test_play_note_invalid_no_crash(driver, tag):
    sm = make_sm(driver)
    sm.load_sounds()
    sm.play_note(999)    # note absente du note_map → silent
    print(f"  [{tag}] play_note note invalide → pas de crash : OK")


def _test_play_metronome_no_crash(driver, tag):
    sm = make_sm(driver)
    sm.play_metronome(0)   # click1
    sm.play_metronome(1)   # click2
    sm.stop_all()
    print(f"  [{tag}] play_metronome beat 0/1 → pas de crash : OK")


def _test_stop_all_no_crash(driver, tag):
    sm = make_sm(driver)
    sm.load_sounds()
    sm.play_sound(0)
    sm.stop_all()
    sm.stop_all()   # double appel
    print(f"  [{tag}] stop_all → pas de crash : OK")


def _test_set_volume_no_crash(driver, tag):
    sm = make_sm(driver)
    sm.load_sounds()
    sm.set_volume(80)
    sm.set_volume(0)
    sm.set_volume(100)
    print(f"  [{tag}] set_volume → pas de crash : OK")


def _test_shift_kit_returns_labels(driver, tag):
    kit_path = make_kit_json(WAVS[:16])
    try:
        sm = make_sm(driver)
        sm.load_kit(kit_path)
        labels = sm.shift_kit(1)
        assert len(labels) == 16
    finally:
        os.unlink(kit_path)
    print(f"  [{tag}] shift_kit → 16 labels retournés : OK")


# ---------------------------------------------------------------------------
# pad_notes et gm_note_map (Phase 7 étape 11e1, docs/DESIGN.md § 11a1 D1/D2)
# ---------------------------------------------------------------------------

# Extrait de la TR-707 : pads rangés à partir de la note 35, sans base_note
# (kit_base retombe sur 36) ; pad 16 sans note ni son.
TR_707_PADS = [
    (1, 35, "Kick 2"), (2, 36, "Kick 1"), (3, 37, "Rimshot"),
    (4, 38, "Snare 1"), (5, 39, "Hand Clap"), (6, 40, "Snare 2"),
    (7, 41, "Tom Low"), (8, 42, "HH Closed"), (9, 43, "Tom Mid"),
    (10, 44, "HH Open"), (11, 45, "Tom Hi"), (12, 46, "Crash"),
    (13, 47, "Ride"), (14, 48, "Tambourine"), (15, 49, "Cowbell"),
]


def _write_kit(tmp_path, pads, **meta):
    path = tmp_path / "kit.json"
    path.write_text(json.dumps({"name": "Kit", **meta, "pads": pads}),
                    encoding="utf-8")
    return str(path)


def _tr_707_kit(tmp_path):
    pads = [{"pad": p, "note": n, "filename": WAVS[p % len(WAVS)], "label": l}
            for p, n, l in TR_707_PADS]
    pads.append({"pad": 16, "filename": "", "label": "---"})
    return _write_kit(tmp_path, pads)


def test_pad_notes_default_before_any_kit():
    sm = make_sm(_sd_drv)
    assert sm.pad_notes == list(range(36, 52))
    assert sm.gm_note_map == {}


def test_pad_notes_follow_pad_entries(tmp_path):
    # D1 : la note du son du pad, pas kit_base + pad
    sm = make_sm(_sd_drv)
    sm.load_kit(_tr_707_kit(tmp_path))
    assert sm.kit_base == 36
    assert sm.pad_notes[:15] == list(range(35, 50))


def test_pad_notes_pad_without_note_falls_back_on_kit_base(tmp_path):
    sm = make_sm(_sd_drv)
    sm.load_kit(_tr_707_kit(tmp_path))
    assert sm.pad_notes[15] == 36 + 15


def test_pad_notes_missing_pad_entry_uses_base_note(tmp_path):
    pads = [{"pad": 1, "note": 60, "filename": WAVS[0], "label": "Cowbell"}]
    sm = make_sm(_sd_drv)
    sm.load_kit(_write_kit(tmp_path, pads, base_note=40))
    assert len(sm.pad_notes) == 16
    assert sm.pad_notes[0] == 60
    assert sm.pad_notes[1:] == list(range(41, 56))


def test_pad_notes_after_shift_kit(tmp_path):
    pads = [{"note": n, "filename": WAVS[n % len(WAVS)], "label": f"S{n}"}
            for n in range(36, 70)]
    sm = make_sm(_sd_drv)
    sm.load_kit(_write_kit(tmp_path, pads, base_note=36))
    sm.shift_kit(8)
    assert sm.pad_notes == list(range(44, 60))
    sm.shift_kit(-8)
    assert sm.pad_notes == list(range(36, 52))


def test_pad_notes_and_gm_map_reset_by_load_sounds(tmp_path):
    sm = make_sm(_sd_drv)
    sm.load_kit(_tr_707_kit(tmp_path))
    # load_kit remplace media_lst par les chemins du kit ('' pour le pad 16) :
    # on remet les WAV de media/ avant de recharger les sons par défaut
    sm.media_lst = list(MEDIA16)
    sm.load_sounds()
    assert sm.pad_notes == list(range(36, 52))
    assert sm.gm_note_map == {}


def test_gm_map_guessed_from_labels(tmp_path):
    # Tableau de docs/DESIGN.md § 11a1 D3
    sm = make_sm(_sd_drv)
    sm.load_kit(_tr_707_kit(tmp_path))
    assert sm.gm_note_map == {
        35: 35, 36: 36, 37: 37, 38: 38, 39: 39, 40: 40, 41: 41, 42: 42,
        43: 47, 44: 46, 45: 50, 46: 49, 47: 51, 48: 54, 49: 56,
    }


def test_gm_map_unknown_label_absent(tmp_path):
    # Pad 16 « --- » (note 51 par défaut) : aucune correspondance
    sm = make_sm(_sd_drv)
    sm.load_kit(_tr_707_kit(tmp_path))
    assert 51 not in sm.gm_note_map


def test_gm_map_gm_note_overrides_guess(tmp_path):
    pads = [{"pad": 1, "note": 49, "filename": WAVS[0], "label": "Cowbell",
             "gm_note": 67}]
    sm = make_sm(_sd_drv)
    sm.load_kit(_write_kit(tmp_path, pads))
    assert sm.gm_note_map[49] == 67


def test_gm_map_gm_note_overrides_gm_kit(tmp_path):
    pads = [{"pad": 1, "note": 49, "filename": WAVS[0], "label": "Crash 1",
             "gm_note": 57}]
    sm = make_sm(_sd_drv)
    sm.load_kit(_write_kit(tmp_path, pads, gm=True))
    assert sm.gm_note_map[49] == 57


def test_gm_map_gm_note_on_unknown_label(tmp_path):
    pads = [{"pad": 1, "note": 90, "filename": WAVS[0], "label": "Zap",
             "gm_note": 81}]
    sm = make_sm(_sd_drv)
    sm.load_kit(_write_kit(tmp_path, pads))
    assert sm.gm_note_map[90] == 81


def test_gm_map_invalid_gm_note_ignored(tmp_path):
    # Hors 35-81, pas entier ou booléen : on passe à la règle suivante
    pads = [
        {"note": 49, "filename": WAVS[0], "label": "Cowbell", "gm_note": 20},
        {"note": 46, "filename": WAVS[0], "label": "HH Open", "gm_note": "50"},
        {"note": 48, "filename": WAVS[0], "label": "Tambourine", "gm_note": True},
        {"note": 90, "filename": WAVS[0], "label": "Zap", "gm_note": 82},
    ]
    sm = make_sm(_sd_drv)
    sm.load_kit(_write_kit(tmp_path, pads))
    assert sm.gm_note_map[49] == 56
    assert sm.gm_note_map[46] == 46
    assert sm.gm_note_map[48] == 54
    assert 90 not in sm.gm_note_map


def test_gm_map_gm_kit_is_identity(tmp_path):
    # "gm": true : chaque note reste telle quelle, même un libellé trompeur
    pads = [{"pad": 1, "note": 49, "filename": WAVS[0], "label": "Cowbell"},
            {"note": 90, "filename": WAVS[0], "label": "Zap"}]
    sm = make_sm(_sd_drv)
    sm.load_kit(_write_kit(tmp_path, pads, gm=True))
    assert sm.gm_note_map[49] == 49
    assert sm.gm_note_map[90] == 90


def test_gm_map_gm_key_must_be_true(tmp_path):
    # "gm": "yes" ou 1 ne vaut pas "gm": true : devinette
    for value in ("yes", 1):
        pads = [{"pad": 1, "note": 49, "filename": WAVS[0], "label": "Cowbell"}]
        sm = make_sm(_sd_drv)
        sm.load_kit(_write_kit(tmp_path, pads, gm=value))
        assert sm.gm_note_map[49] == 56, value


def test_gm_map_covers_notes_without_sound(tmp_path):
    # La correspondance ne dépend pas du fichier son
    pads = [{"pad": 1, "note": 49, "filename": "absent.wav", "label": "Cowbell"}]
    sm = make_sm(_sd_drv)
    sm.load_kit(_write_kit(tmp_path, pads))
    assert 49 not in sm.note_map
    assert sm.gm_note_map[49] == 56


def test_gm_map_pad_without_note_mapped_on_its_pad_note(tmp_path):
    pads = [{"pad": 3, "filename": WAVS[0], "label": "Cowbell"}]
    sm = make_sm(_sd_drv)
    sm.load_kit(_write_kit(tmp_path, pads, base_note=60))
    assert sm.pad_notes[2] == 62
    assert sm.gm_note_map[62] == 56


def test_gm_map_pad_without_note_does_not_override_note_entry(tmp_path):
    # Le pad 1 sans note retombe sur 36, déjà portée par une entrée : elle gagne
    pads = [{"pad": 1, "filename": WAVS[0], "label": "Cowbell"},
            {"note": 36, "filename": WAVS[1], "label": "Kick"}]
    sm = make_sm(_sd_drv)
    sm.load_kit(_write_kit(tmp_path, pads))
    assert sm.pad_notes[0] == 36
    assert sm.gm_note_map[36] == 36


def test_gm_map_reset_between_kits(tmp_path):
    sm = make_sm(_sd_drv)
    sm.load_kit(_tr_707_kit(tmp_path))
    pads = [{"pad": 1, "note": 60, "filename": WAVS[0], "label": "Hi Bongo"}]
    sm.load_kit(_write_kit(tmp_path, pads))
    assert sm.gm_note_map == {60: 60}


def test_repo_gm_kit_is_gm_identity():
    # data/kits/gm.json porte "gm": true (Phase 7 étape 11d1)
    path = os.path.join(os.path.dirname(__file__), "..", "data", "kits", "gm.json")
    with open(path, encoding="utf-8") as f:
        meta = json.load(f)
    assert meta.get("gm") is True
    sm = make_sm(_sd_drv)
    sm.load_kit(path)
    assert sm.gm_note_map == {n: n for n in range(35, 82)}
    assert sm.pad_notes == list(range(36, 52))


# ---------------------------------------------------------------------------
# Spécificité SoundDeviceDriver : voice_count observable
# ---------------------------------------------------------------------------

def test_sd_play_sound_increases_voice_count():
    sm = make_sm(_sd_drv)
    sm.load_sounds()
    _sd_drv.stop_all()
    # Jouer un son long (on remplace drum_sounds[0] par un SdSound long)
    long_snd = SdSound(
        __import__("numpy").zeros((44100, 2), dtype="float32"), 44100
    )
    sm.drum_sounds[0] = long_snd
    sm.play_sound(0)
    assert _sd_drv.voice_count() == 1
    _sd_drv.stop_all()
    print("  [SD] play_sound → voice_count == 1 : OK")


def test_sd_stop_all_clears_voice_count():
    sm = make_sm(_sd_drv)
    sm.load_sounds()
    _sd_drv.stop_all()
    long_snd = SdSound(
        __import__("numpy").zeros((44100, 2), dtype="float32"), 44100
    )
    sm.drum_sounds[0] = long_snd
    sm.play_sound(0)
    sm.play_sound(0)
    sm.stop_all()
    assert _sd_drv.voice_count() == 0
    print("  [SD] stop_all → voice_count == 0 : OK")


def test_sd_set_volume_updates_master_vol():
    sm = make_sm(_sd_drv)
    sm.set_volume(60)
    assert abs(_sd_drv._master_vol - 0.6) < 1e-6
    sm.set_volume(100)   # remettre à 1.0
    print("  [SD] set_volume(60) → master_vol == 0.6 : OK")


# ---------------------------------------------------------------------------
# Lancer tous les tests pour les deux backends
# ---------------------------------------------------------------------------

def _run_all_common(driver, tag):
    _test_load_sounds(driver, tag)
    _test_load_pad_sound(driver, tag)
    _test_load_pad_sound_extends_list(driver, tag)
    _test_silent_sound_not_none(driver, tag)
    _test_load_kit_labels(driver, tag)
    _test_load_kit_populates_drum_sounds(driver, tag)
    _test_load_kit_populates_note_map(driver, tag)
    _test_play_sound_no_crash(driver, tag)
    _test_play_note_valid_no_crash(driver, tag)
    _test_play_note_invalid_no_crash(driver, tag)
    _test_play_metronome_no_crash(driver, tag)
    _test_stop_all_no_crash(driver, tag)
    _test_set_volume_no_crash(driver, tag)
    _test_shift_kit_returns_labels(driver, tag)


if __name__ == "__main__":
    print("=== test_sound_manager ===")

    # Init
    test_default_driver_is_sounddevice()
    test_click_sounds_loaded()

    # Backend PygameDriver
    print("--- PygameDriver ---")
    _run_all_common(_pygame_drv, "PG")

    # Backend SoundDeviceDriver
    print("--- SoundDeviceDriver ---")
    _run_all_common(_sd_drv, "SD")

    # Spécificités SoundDeviceDriver
    test_sd_play_sound_increases_voice_count()
    test_sd_stop_all_clears_voice_count()
    test_sd_set_volume_updates_master_vol()

    _sd_drv.close()
    print("Tous les tests : OK")
