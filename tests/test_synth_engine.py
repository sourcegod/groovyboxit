#python3
"""
    File: test_synth_engine.py
    Test du SynthEngine avec un vrai fichier WAV :
    chargement de patch, pitch shifting, cache, lecture via SoundDeviceDriver.
    WAV source : /home/com/audiotest/a440.wav  (La4, MIDI 69, 440 Hz)
    Date: Fri, 16/05/2026
    Author: Coolbrother
"""
import sys
import os
import json
import shutil
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import soundfile as sf
from sound_device_driver import SoundDeviceDriver, SdSound
from synth_engine import (
    SynthEngine, scale_midi_notes, midi_to_note_name, note_name_to_midi,
)

WAV_SRC   = "/home/com/audiotest/a440.wav"   # La4 = MIDI 69
ROOT_NOTE = "A4"                             # note racine du fichier


def _make_temp_patch(wav_src, root_note):
    """Crée un répertoire patch temporaire avec le WAV fourni."""
    patch_dir = tempfile.mkdtemp(prefix="grv_test_patch_")
    dst       = os.path.join(patch_dir, f"{root_note}.wav")
    shutil.copy(wav_src, dst)
    meta = {
        "name":       "TestPatch",
        "loop":       False,
        "loop_start": None,
        "loop_end":   None,
        "samples":    [{"file": f"{root_note}.wav", "root": root_note}],
    }
    with open(os.path.join(patch_dir, "patch.json"), "w") as f:
        json.dump(meta, f)
    return patch_dir


def test_wav_info():
    assert os.path.exists(WAV_SRC), f"Fichier introuvable : {WAV_SRC}"
    data, sr = sf.read(WAV_SRC)
    print(f"  WAV: shape={data.shape}  sr={sr} Hz")
    assert sr > 0 and len(data) > 0
    print("  lecture WAV : OK")


def test_load_patch(engine, patch_dir):
    patch_name = os.path.basename(patch_dir)
    engine.load_patch(patch_name)
    assert engine.is_loaded()
    assert engine._patch_name == "TestPatch"
    assert len(engine._samples) == 1
    assert engine._samples[0]["root_midi"] == note_name_to_midi(ROOT_NOTE)
    assert isinstance(engine._samples[0]["sampler"], __import__("audio_sampler").AudioSampler)
    print(f"  load_patch : OK  ({engine})")


def test_precompute_scale(engine):
    notes = scale_midi_notes("major", note_name_to_midi("C4"), 16)
    print(f"  pré-calcul gamme majeure C4 ({len(notes)} notes)...")
    engine.precompute(notes)
    assert len(engine._cache) == 16
    for n in notes:
        assert (n, 500) in engine._cache, f"Note {midi_to_note_name(n)} absente du cache"
    print("  precompute (16 notes) : OK")


def test_get_sound(engine):
    midi  = note_name_to_midi("C4")
    sound = engine.get_sound(midi)
    assert sound is not None
    assert isinstance(sound, SdSound)
    # 2e appel → depuis le cache
    sound2 = engine.get_sound(midi)
    assert sound is sound2, "Le 2e appel doit retourner le même objet (cache)"
    print("  get_sound + cache : OK")


def test_pitch_shift_steps(engine):
    root_midi = note_name_to_midi(ROOT_NOTE)
    for delta in (-12, -7, 0, 5, 12):
        target = root_midi + delta
        sound  = engine.get_sound(target)
        assert sound is not None, f"Pas de son pour MIDI {target} ({delta:+d} demi-tons)"
    print("  pitch_shift ±12 demi-tons : OK")


def test_clear_cache(engine):
    engine.clear_cache()
    assert len(engine._cache) == 0
    print("  clear_cache : OK")


if __name__ == "__main__":
    print("=== test_synth_engine ===")

    if not os.path.exists(WAV_SRC):
        print(f"SKIP : fichier WAV introuvable ({WAV_SRC})")
        sys.exit(0)

    drv       = SoundDeviceDriver()
    patch_dir = _make_temp_patch(WAV_SRC, ROOT_NOTE)
    try:
        engine = SynthEngine(os.path.dirname(patch_dir), driver=drv)

        test_wav_info()
        test_load_patch(engine, patch_dir)
        test_precompute_scale(engine)
        test_get_sound(engine)
        test_pitch_shift_steps(engine)
        test_clear_cache(engine)

        print("Tous les tests : OK")
    finally:
        shutil.rmtree(patch_dir, ignore_errors=True)
        drv.close()
