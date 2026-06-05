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


# ---------------------------------------------------------------------------
# set_mod_wheel — sans WAV (mock driver)
# ---------------------------------------------------------------------------

import numpy as _np
from sound_device_driver import _Voice as _SddVoice

class _MockDriver:
    """Driver minimal pour tester set_mod_wheel sans PortAudio ni WAV."""
    LFO_DEPTH_MAX = SoundDeviceDriver.LFO_DEPTH_MAX
    def play(self, *a, **kw): return None
    def stop_voice(self, v): pass


def _make_engine_mock():
    eng = SynthEngine.__new__(SynthEngine)
    eng._driver          = _MockDriver()
    eng.pitch_bend       = 0
    eng.pitch_bend_range = 2
    eng.mod_wheel        = 0
    eng.sustain          = False
    eng._sustained_notes = set()
    eng._active_voices   = {}
    eng._samples         = []
    eng._raw_cache       = {}
    eng._cache           = {}
    eng._loop_cache      = {}
    return eng


def test_set_mod_wheel_stores_value():
    eng = _make_engine_mock()
    eng.set_mod_wheel(64)
    assert eng.mod_wheel == 64
    print("  set_mod_wheel stocke mod_wheel : OK")


def test_set_mod_wheel_propagates_to_active_voices():
    eng  = _make_engine_mock()
    data = _np.zeros((100, 2), dtype=_np.float32)
    v1   = _SddVoice(data, 0.8, 0.8)
    v2   = _SddVoice(data, 0.8, 0.8)
    eng._active_voices = {60: v1, 64: v2}

    eng.set_mod_wheel(127)
    expected = 127 / 127.0 * SoundDeviceDriver.LFO_DEPTH_MAX
    assert abs(v1.lfo_depth - expected) < 1e-9
    assert abs(v2.lfo_depth - expected) < 1e-9
    print(f"  set_mod_wheel(127) → lfo_depth={expected:.5f} sur toutes les voix actives : OK")


def test_set_mod_wheel_zero_disables_lfo():
    eng  = _make_engine_mock()
    data = _np.zeros((100, 2), dtype=_np.float32)
    v    = _SddVoice(data, 0.8, 0.8, lfo_depth=0.05)
    eng._active_voices = {60: v}

    eng.set_mod_wheel(0)
    assert v.lfo_depth == 0.0
    assert eng.mod_wheel == 0
    print("  set_mod_wheel(0) → lfo_depth=0.0 : OK")


def test_set_mod_wheel_midrange():
    eng  = _make_engine_mock()
    data = _np.zeros((100, 2), dtype=_np.float32)
    v    = _SddVoice(data, 0.8, 0.8)
    eng._active_voices = {60: v}

    eng.set_mod_wheel(64)
    expected = 64 / 127.0 * SoundDeviceDriver.LFO_DEPTH_MAX
    assert abs(v.lfo_depth - expected) < 1e-9
    print(f"  set_mod_wheel(64) → lfo_depth={expected:.5f} (interpolation linéaire) : OK")


def test_set_mod_wheel_no_active_voices_is_safe():
    eng = _make_engine_mock()
    eng._active_voices = {}
    try:
        eng.set_mod_wheel(100)
        print("  set_mod_wheel sans voix actives → no-op sans plantage : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"


def test_set_mod_wheel_none_voice_skipped():
    eng = _make_engine_mock()
    eng._active_voices = {60: None}
    try:
        eng.set_mod_wheel(80)
        print("  set_mod_wheel avec voix=None → ignorée sans plantage : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"


# ---------------------------------------------------------------------------
# stop_all_voices — sans WAV (mock driver)
# ---------------------------------------------------------------------------

class _TrackingMockDriver(_MockDriver):
    """_MockDriver qui enregistre les appels stop_voice/stop_sound."""
    def __init__(self):
        self.stopped_voices = []
        self.stopped_sounds = []
    def stop_voice(self, v):
        self.stopped_voices.append(v)
    def stop_sound(self, s):
        self.stopped_sounds.append(s)


def _make_engine_tracking():
    eng = SynthEngine.__new__(SynthEngine)
    eng._driver          = _TrackingMockDriver()
    eng.pitch_bend       = 0
    eng.pitch_bend_range = 2
    eng.mod_wheel        = 0
    eng.sustain          = False
    eng._sustained_notes = set()
    eng._active_voices   = {}
    eng._samples         = []
    eng._raw_cache       = {}
    eng._cache           = {}
    eng._loop_cache      = {}
    return eng


def test_stop_all_voices_stops_each_voice():
    eng  = _make_engine_tracking()
    data = _np.zeros((100, 2), dtype=_np.float32)
    v1   = _SddVoice(data, 0.8, 0.8)
    v2   = _SddVoice(data, 0.8, 0.8)
    eng._active_voices = {60: v1, 64: v2}

    eng.stop_all_voices()
    assert v1 in eng._driver.stopped_voices
    assert v2 in eng._driver.stopped_voices
    print("  stop_all_voices → stop_voice appelé pour chaque voix : OK")


def test_stop_all_voices_clears_active_voices():
    eng  = _make_engine_tracking()
    data = _np.zeros((100, 2), dtype=_np.float32)
    eng._active_voices = {60: _SddVoice(data, 0.8, 0.8)}

    eng.stop_all_voices()
    assert eng._active_voices == {}
    print("  stop_all_voices → _active_voices vidé : OK")


def test_stop_all_voices_stops_loop_cache():
    eng        = _make_engine_tracking()
    mock_sound = object()   # objet opaque représentant un SdSound
    eng._loop_cache = {60: mock_sound}

    eng.stop_all_voices()
    assert mock_sound in eng._driver.stopped_sounds
    assert eng._loop_cache == {}
    print("  stop_all_voices → loop_cache arrêté et vidé : OK")


def test_stop_all_voices_empty_is_safe():
    eng = _make_engine_tracking()
    try:
        eng.stop_all_voices()
        print("  stop_all_voices sans voix actives → no-op sans plantage : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"


def test_stop_all_voices_none_voice_skipped():
    eng = _make_engine_tracking()
    eng._active_voices = {60: None}
    try:
        eng.stop_all_voices()
        assert eng._active_voices == {}
        assert eng._driver.stopped_voices == []
        print("  stop_all_voices avec voix=None → ignorée, dict vidé : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"


# ---------------------------------------------------------------------------
# sustain (CC#64) — sans WAV (mock driver)
# ---------------------------------------------------------------------------

def test_stop_deferred_when_sustain_on():
    eng  = _make_engine_tracking()
    data = _np.zeros((100, 2), dtype=_np.float32)
    v    = _SddVoice(data, 0.8, 0.8)
    eng._active_voices = {60: v}
    eng.sustain = True
    eng.stop(60)
    assert 60 in eng._sustained_notes, "note doit être en attente"
    assert 60 in eng._active_voices,   "voix encore active"
    assert eng._driver.stopped_voices == [], "stop_voice pas encore appelé"
    print("  stop avec sustain=True → note mise en attente, voix toujours active : OK")


def test_stop_immediate_when_sustain_off():
    eng  = _make_engine_tracking()
    data = _np.zeros((100, 2), dtype=_np.float32)
    v    = _SddVoice(data, 0.8, 0.8)
    eng._active_voices = {60: v}
    eng.stop(60)
    assert 60 not in eng._active_voices
    assert v in eng._driver.stopped_voices
    assert eng._sustained_notes == set()
    print("  stop avec sustain=False → voix coupée immédiatement : OK")


def test_release_sustain_stops_deferred_notes():
    eng  = _make_engine_tracking()
    data = _np.zeros((100, 2), dtype=_np.float32)
    v    = _SddVoice(data, 0.8, 0.8)
    eng._active_voices = {60: v}
    eng.sustain = True
    eng.stop(60)
    # Relâchement pédale
    eng.sustain = False
    eng.release_sustain()
    assert eng._sustained_notes == set()
    assert v in eng._driver.stopped_voices
    print("  release_sustain → notes en attente coupées : OK")


def test_release_sustain_empty_is_safe():
    eng = _make_engine_tracking()
    try:
        eng.release_sustain()
        print("  release_sustain sans notes en attente → no-op sans plantage : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"


def test_stop_all_voices_clears_sustained_notes():
    eng = _make_engine_tracking()
    eng._sustained_notes = {60, 64}
    eng.stop_all_voices()
    assert eng._sustained_notes == set()
    print("  stop_all_voices → _sustained_notes vidé : OK")


# ---------------------------------------------------------------------------
# reset_all_controls — sans WAV (mock driver)
# ---------------------------------------------------------------------------

def test_reset_all_controls_zeroes_pitch_bend():
    eng = _make_engine_mock()
    eng.pitch_bend = 4096
    eng.reset_all_controls()
    assert eng.pitch_bend == 0
    print("  reset_all_controls → pitch_bend=0 : OK")


def test_reset_all_controls_applies_pitch_bend_to_voices():
    eng  = _make_engine_mock()
    data = _np.zeros((100, 2), dtype=_np.float32)
    v    = _SddVoice(data, 0.8, 0.8)
    v.phase_incr = 1.5
    eng._active_voices = {60: v}
    eng.pitch_bend = 4096
    eng.reset_all_controls()
    assert abs(v.phase_incr - 1.0) < 1e-9, "phase_incr doit revenir à 1.0 (bend=0)"
    print("  reset_all_controls → phase_incr voix actives = 1.0 : OK")


def test_reset_all_controls_zeroes_mod_wheel():
    eng = _make_engine_mock()
    eng.set_mod_wheel(100)
    eng.reset_all_controls()
    assert eng.mod_wheel == 0
    print("  reset_all_controls → mod_wheel=0 : OK")


def test_reset_all_controls_clears_lfo_on_voices():
    eng  = _make_engine_mock()
    data = _np.zeros((100, 2), dtype=_np.float32)
    v    = _SddVoice(data, 0.8, 0.8, lfo_depth=0.05)
    eng._active_voices = {60: v}
    eng.set_mod_wheel(80)
    eng.reset_all_controls()
    assert v.lfo_depth == 0.0
    print("  reset_all_controls → lfo_depth voix actives = 0.0 : OK")


def test_reset_all_controls_no_active_voices_is_safe():
    eng = _make_engine_mock()
    eng.pitch_bend = 2000
    eng.mod_wheel  = 64
    try:
        eng.reset_all_controls()
        assert eng.pitch_bend == 0
        assert eng.mod_wheel  == 0
        print("  reset_all_controls sans voix actives → no-op sans plantage : OK")
    except Exception as e:
        assert False, f"Exception inattendue : {e}"


def test_reset_all_controls_clears_sustain():
    eng = _make_engine_mock()
    eng.sustain = True
    eng._sustained_notes = {60, 64}
    eng.reset_all_controls()
    assert eng.sustain is False
    assert eng._sustained_notes == set()
    print("  reset_all_controls → sustain=False et notes en attente vidées : OK")


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

    # Tests set_mod_wheel — pas de WAV requis
    test_set_mod_wheel_stores_value()
    test_set_mod_wheel_propagates_to_active_voices()
    test_set_mod_wheel_zero_disables_lfo()
    test_set_mod_wheel_midrange()
    test_set_mod_wheel_no_active_voices_is_safe()
    test_set_mod_wheel_none_voice_skipped()
    print("Tests set_mod_wheel : OK")

    # Tests stop_all_voices — pas de WAV requis
    test_stop_all_voices_stops_each_voice()
    test_stop_all_voices_clears_active_voices()
    test_stop_all_voices_stops_loop_cache()
    test_stop_all_voices_empty_is_safe()
    test_stop_all_voices_none_voice_skipped()
    print("Tests stop_all_voices : OK")

    # Tests sustain (CC#64) — pas de WAV requis
    test_stop_deferred_when_sustain_on()
    test_stop_immediate_when_sustain_off()
    test_release_sustain_stops_deferred_notes()
    test_release_sustain_empty_is_safe()
    test_stop_all_voices_clears_sustained_notes()
    print("Tests sustain (CC#64) : OK")

    # Tests reset_all_controls — pas de WAV requis
    test_reset_all_controls_zeroes_pitch_bend()
    test_reset_all_controls_applies_pitch_bend_to_voices()
    test_reset_all_controls_zeroes_mod_wheel()
    test_reset_all_controls_clears_lfo_on_voices()
    test_reset_all_controls_no_active_voices_is_safe()
    test_reset_all_controls_clears_sustain()
    print("Tests reset_all_controls : OK")
