#python3
"""
    File: tests/test_pygame_driver.py
    Tests unitaires de PygameDriver : chargement WAV, silence, lecture,
    volume, stop_all. Vérifie les types retournés et l'absence de crash.
    Date: Thu, 28/05/2026
    Author: Coolbrother
"""
import sys
import os
import glob

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pygame
from pygame_driver import PygameDriver

MEDIA_DIR = os.path.join(os.path.dirname(__file__), "..", "media")
WAVS      = sorted(glob.glob(os.path.join(MEDIA_DIR, "*.wav")))
WAV1      = WAVS[0]   # media/1.wav (ou premier trouvé)

# Pilote partagé (pygame.init() appelé une seule fois)
_drv = PygameDriver()


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------

def test_load_returns_pygame_sound():
    snd = _drv.load(WAV1)
    assert isinstance(snd, pygame.mixer.Sound)
    print("  load → pygame.Sound : OK")


def test_load_different_files_different_objects():
    snd1 = _drv.load(WAVS[0])
    snd2 = _drv.load(WAVS[1])
    assert snd1 is not snd2
    print("  load fichiers différents → objets distincts : OK")


def test_load_same_file_twice_no_crash():
    snd1 = _drv.load(WAV1)
    snd2 = _drv.load(WAV1)
    assert isinstance(snd1, pygame.mixer.Sound)
    assert isinstance(snd2, pygame.mixer.Sound)
    print("  load même fichier deux fois sans crash : OK")


# ---------------------------------------------------------------------------
# make_silent
# ---------------------------------------------------------------------------

def test_make_silent_returns_pygame_sound():
    sil = _drv.make_silent()
    assert isinstance(sil, pygame.mixer.Sound)
    print("  make_silent → pygame.Sound : OK")


def test_make_silent_two_calls_independent():
    s1 = _drv.make_silent()
    s2 = _drv.make_silent()
    assert s1 is not s2
    print("  make_silent deux appels → objets indépendants : OK")


# ---------------------------------------------------------------------------
# play
# ---------------------------------------------------------------------------

def test_play_no_crash():
    snd = _drv.load(WAV1)
    _drv.play(snd)
    _drv.stop_all()
    print("  play sans vol/pan → pas de crash : OK")


def test_play_with_vol_no_crash():
    snd = _drv.load(WAV1)
    _drv.play(snd, vol=0.5)
    _drv.stop_all()
    print("  play vol=0.5 → pas de crash : OK")


def test_play_pan_left_no_crash():
    snd = _drv.load(WAV1)
    _drv.play(snd, vol=1.0, pan=-100)
    _drv.stop_all()
    print("  play pan=-100 → pas de crash : OK")


def test_play_pan_right_no_crash():
    snd = _drv.load(WAV1)
    _drv.play(snd, vol=1.0, pan=100)
    _drv.stop_all()
    print("  play pan=+100 → pas de crash : OK")


def test_play_silent_no_crash():
    sil = _drv.make_silent()
    _drv.play(sil)
    _drv.stop_all()
    print("  play sound silencieux → pas de crash : OK")


# ---------------------------------------------------------------------------
# set_sound_volume
# ---------------------------------------------------------------------------

def test_set_sound_volume_no_crash():
    snd = _drv.load(WAV1)
    _drv.set_sound_volume(snd, 0.5)
    print("  set_sound_volume(0.5) → pas de crash : OK")


def test_set_sound_volume_zero():
    snd = _drv.load(WAV1)
    _drv.set_sound_volume(snd, 0.0)
    print("  set_sound_volume(0.0) → pas de crash : OK")


def test_set_sound_volume_one():
    snd = _drv.load(WAV1)
    _drv.set_sound_volume(snd, 1.0)
    print("  set_sound_volume(1.0) → pas de crash : OK")


# ---------------------------------------------------------------------------
# set_master_volume (no-op pour pygame)
# ---------------------------------------------------------------------------

def test_set_master_volume_no_crash():
    _drv.set_master_volume(80)
    _drv.set_master_volume(0)
    _drv.set_master_volume(100)
    print("  set_master_volume → no-op sans crash : OK")


# ---------------------------------------------------------------------------
# stop_all
# ---------------------------------------------------------------------------

def test_stop_all_no_crash():
    snd = _drv.load(WAV1)
    _drv.play(snd)
    _drv.stop_all()
    print("  stop_all → pas de crash : OK")


def test_stop_all_on_silence_no_crash():
    _drv.stop_all()
    _drv.stop_all()
    print("  stop_all sans sons actifs → pas de crash : OK")


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------

def test_close_no_crash():
    _drv.close()
    print("  close → no-op sans crash : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_pygame_driver ===")
    test_load_returns_pygame_sound()
    test_load_different_files_different_objects()
    test_load_same_file_twice_no_crash()
    test_make_silent_returns_pygame_sound()
    test_make_silent_two_calls_independent()
    test_play_no_crash()
    test_play_with_vol_no_crash()
    test_play_pan_left_no_crash()
    test_play_pan_right_no_crash()
    test_play_silent_no_crash()
    test_set_sound_volume_no_crash()
    test_set_sound_volume_zero()
    test_set_sound_volume_one()
    test_set_master_volume_no_crash()
    test_stop_all_no_crash()
    test_stop_all_on_silence_no_crash()
    test_close_no_crash()
    print("Tous les tests : OK")
