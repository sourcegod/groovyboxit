#python3
"""
    File: tests/test_sound_manager.py
    Tests unitaires de SoundManager avec PygameDriver (défaut) et
    SoundDeviceDriver. Vérifie que les deux backends donnent le même
    comportement observable : chargement, note_map, play, stop, volume.
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

def test_default_driver_is_pygame():
    sm = SoundManager(list(MEDIA16), CLICK1, CLICK2)
    assert isinstance(sm._driver, PygameDriver)
    print("  driver par défaut == PygameDriver : OK")


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
    test_default_driver_is_pygame()
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
