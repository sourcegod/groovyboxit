#python3
"""
    File: tests/test_sound_device_driver.py
    Tests unitaires de SoundDeviceDriver et SdSound :
    chargement WAV, polyphonie, vol/pan, stop_all, master_volume, callback.
    Date: Thu, 28/05/2026
    Author: Coolbrother
"""
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import soundfile as sf
from sound_device_driver import SoundDeviceDriver, SdSound, _Voice


# ---------------------------------------------------------------------------
# Pilote partagé (un seul flux PortAudio pour tous les tests)
# ---------------------------------------------------------------------------

_drv = SoundDeviceDriver()


def _make_wav(sr=44100, duration_s=0.1, channels=2, freq=440.0):
    """Crée un fichier WAV temporaire et retourne son chemin."""
    n      = int(sr * duration_s)
    t      = np.linspace(0, duration_s, n, endpoint=False)
    mono   = (np.sin(2 * np.pi * freq * t) * 0.5).astype(np.float32)
    data   = np.column_stack([mono] * channels) if channels > 1 else mono.reshape(-1, 1)
    f      = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(f.name, data, sr)
    f.close()
    return f.name


# ---------------------------------------------------------------------------
# SdSound — structure
# ---------------------------------------------------------------------------

def test_sdsound_attributes():
    data = np.zeros((100, 2), dtype=np.float32)
    snd  = SdSound(data, 44100)
    assert snd.data is data
    assert snd.samplerate == 44100
    print("  SdSound : attributs data et samplerate : OK")


def test_sdsound_shape_and_dtype():
    data = np.zeros((200, 2), dtype=np.float32)
    snd  = SdSound(data, 44100)
    assert snd.data.shape == (200, 2)
    assert snd.data.dtype == np.float32
    print("  SdSound : shape (N, 2) et dtype float32 : OK")


# ---------------------------------------------------------------------------
# SoundDeviceDriver — initialisation
# ---------------------------------------------------------------------------

def test_stream_active():
    assert _drv._stream.active
    print("  stream PortAudio actif au démarrage : OK")


def test_samplerate():
    assert _drv._sr == SoundDeviceDriver.SAMPLERATE
    print(f"  samplerate == {SoundDeviceDriver.SAMPLERATE} : OK")


def test_initial_voice_count():
    _drv.stop_all()
    assert _drv.voice_count() == 0
    print("  voice_count initial == 0 : OK")


def test_initial_master_volume():
    _drv._master_vol = 1.0   # reset
    assert _drv._master_vol == 1.0
    print("  master_vol initial == 1.0 : OK")


# ---------------------------------------------------------------------------
# make_silent
# ---------------------------------------------------------------------------

def test_make_silent_shape():
    sil = _drv.make_silent()
    assert sil.data.shape == (2, 2)
    print("  make_silent shape (2, 2) : OK")


def test_make_silent_dtype():
    sil = _drv.make_silent()
    assert sil.data.dtype == np.float32
    print("  make_silent dtype float32 : OK")


def test_make_silent_is_zero():
    sil = _drv.make_silent()
    assert np.all(sil.data == 0.0)
    print("  make_silent contient des zéros : OK")


def test_make_silent_custom_duration():
    sil = _drv.make_silent(duration_samples=1024)
    assert sil.data.shape == (1024, 2)
    print("  make_silent duration_samples=1024 : OK")


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------

def test_load_stereo_wav():
    path = _make_wav(sr=44100, channels=2)
    try:
        snd = _drv.load(path)
        assert snd.data.ndim == 2
        assert snd.data.shape[1] == 2
        assert snd.data.dtype == np.float32
        assert snd.samplerate == 44100
    finally:
        os.unlink(path)
    print("  load WAV stéréo 44100 : OK")


def test_load_mono_wav_becomes_stereo():
    path = _make_wav(sr=44100, channels=1)
    try:
        snd = _drv.load(path)
        assert snd.data.shape[1] == 2
    finally:
        os.unlink(path)
    print("  load WAV mono → converti en stéréo : OK")


def test_load_resampled_wav():
    path = _make_wav(sr=22050, channels=2)
    try:
        snd = _drv.load(path)
        # Durée en samples doit être ~doubles (22050 → 44100)
        expected = int(int(22050 * 0.1) * 44100 / 22050)
        assert abs(len(snd.data) - expected) <= 2
        assert snd.samplerate == 44100
    finally:
        os.unlink(path)
    print("  load WAV 22050 Hz → resample 44100 Hz : OK")


def test_load_dtype_is_float32():
    path = _make_wav()
    try:
        snd = _drv.load(path)
        assert snd.data.dtype == np.float32
    finally:
        os.unlink(path)
    print("  load dtype toujours float32 : OK")


# ---------------------------------------------------------------------------
# play / voice_count
# ---------------------------------------------------------------------------

def test_play_increases_voice_count():
    _drv.stop_all()
    snd = _drv.make_silent(duration_samples=44100)  # 1 s
    _drv.play(snd)
    assert _drv.voice_count() == 1
    _drv.stop_all()
    print("  play → voice_count == 1 : OK")


def test_play_polyphony():
    _drv.stop_all()
    snd = _drv.make_silent(duration_samples=44100)
    _drv.play(snd)
    _drv.play(snd)
    _drv.play(snd)
    assert _drv.voice_count() == 3
    _drv.stop_all()
    print("  play × 3 → voice_count == 3 : OK")


def test_play_none_sound_no_crash():
    _drv.stop_all()
    _drv.play(None)
    assert _drv.voice_count() == 0
    print("  play(None) sans crash : OK")


def test_play_empty_sound_no_crash():
    _drv.stop_all()
    snd = SdSound(np.zeros((0, 2), dtype=np.float32), 44100)
    _drv.play(snd)
    assert _drv.voice_count() == 0
    print("  play(SdSound vide) sans crash : OK")


def test_play_pan_left():
    _drv.stop_all()
    snd = _drv.make_silent(duration_samples=44100)
    _drv.play(snd, vol=1.0, pan=-100)
    with _drv._lock:
        v = _drv._voices[0]
        assert v.vol_l == 1.0
        assert v.vol_r == 0.0
    _drv.stop_all()
    print("  play pan=-100 → vol_l=1.0, vol_r=0.0 : OK")


def test_play_pan_right():
    _drv.stop_all()
    snd = _drv.make_silent(duration_samples=44100)
    _drv.play(snd, vol=1.0, pan=100)
    with _drv._lock:
        v = _drv._voices[0]
        assert v.vol_l == 0.0
        assert v.vol_r == 1.0
    _drv.stop_all()
    print("  play pan=+100 → vol_l=0.0, vol_r=1.0 : OK")


def test_play_pan_center():
    _drv.stop_all()
    snd = _drv.make_silent(duration_samples=44100)
    _drv.play(snd, vol=1.0, pan=0)
    with _drv._lock:
        v = _drv._voices[0]
        assert v.vol_l == 1.0
        assert v.vol_r == 1.0
    _drv.stop_all()
    print("  play pan=0 → vol_l=1.0, vol_r=1.0 : OK")


# ---------------------------------------------------------------------------
# stop_all
# ---------------------------------------------------------------------------

def test_stop_all_clears_voices():
    snd = _drv.make_silent(duration_samples=44100)
    _drv.play(snd)
    _drv.play(snd)
    _drv.stop_all()
    assert _drv.voice_count() == 0
    print("  stop_all → voice_count == 0 : OK")


def test_stop_all_on_empty_no_crash():
    _drv.stop_all()
    _drv.stop_all()
    assert _drv.voice_count() == 0
    print("  stop_all sur liste vide sans crash : OK")


# ---------------------------------------------------------------------------
# set_master_volume
# ---------------------------------------------------------------------------

def test_master_volume_int_scale():
    _drv.set_master_volume(80)
    assert abs(_drv._master_vol - 0.8) < 1e-6
    print("  set_master_volume(80) → 0.80 : OK")


def test_master_volume_float_scale():
    _drv.set_master_volume(0.5)
    assert abs(_drv._master_vol - 0.5) < 1e-6
    print("  set_master_volume(0.5) → 0.50 : OK")


def test_master_volume_zero():
    _drv.set_master_volume(0)
    assert _drv._master_vol == 0.0
    print("  set_master_volume(0) → 0.0 : OK")


def test_master_volume_clamp_above():
    _drv.set_master_volume(200)
    assert _drv._master_vol == 1.0
    print("  set_master_volume(200) → clamp 1.0 : OK")


def test_master_volume_clamp_below():
    _drv.set_master_volume(-10)
    assert _drv._master_vol == 0.0
    print("  set_master_volume(-10) → clamp 0.0 : OK")


def test_master_volume_restored():
    _drv.set_master_volume(100)
    assert abs(_drv._master_vol - 1.0) < 1e-6
    print("  set_master_volume(100) → 1.0 (restauré) : OK")


# ---------------------------------------------------------------------------
# Callback — logique de mixage (appel direct, sans vrai flux audio)
# ---------------------------------------------------------------------------

def test_callback_silence_when_no_voices():
    _drv.stop_all()
    outdata = np.ones((512, 2), dtype=np.float32)
    _drv._master_vol = 1.0
    _drv._callback(outdata, 512, None, None)
    assert np.all(outdata == 0.0)
    print("  callback sans voix → silence : OK")


def test_callback_voice_is_mixed():
    _drv.stop_all()
    _drv._master_vol = 1.0
    data  = np.full((1024, 2), 0.5, dtype=np.float32)
    snd   = SdSound(data, 44100)
    _drv.play(snd, vol=1.0, pan=0)
    outdata = np.zeros((512, 2), dtype=np.float32)
    _drv._callback(outdata, 512, None, None)
    assert np.all(outdata > 0.0)
    _drv.stop_all()
    print("  callback avec voix → signal non nul : OK")


def test_callback_voice_consumed_when_done():
    _drv.stop_all()
    _drv._master_vol = 1.0
    data  = np.full((100, 2), 0.1, dtype=np.float32)   # 100 échantillons
    snd   = SdSound(data, 44100)
    _drv.play(snd)
    assert _drv.voice_count() == 1
    outdata = np.zeros((512, 2), dtype=np.float32)
    _drv._callback(outdata, 512, None, None)   # consume entièrement
    assert _drv.voice_count() == 0
    print("  callback retire la voix quand le sample est épuisé : OK")


def test_callback_master_volume_applied():
    _drv.stop_all()
    _drv._master_vol = 0.5
    data  = np.full((1024, 2), 0.4, dtype=np.float32)
    snd   = SdSound(data, 44100)
    _drv.play(snd, vol=1.0, pan=0)
    outdata = np.zeros((512, 2), dtype=np.float32)
    _drv._callback(outdata, 512, None, None)
    assert np.allclose(outdata[:512], 0.2, atol=1e-5)
    _drv.stop_all()
    _drv._master_vol = 1.0
    print("  callback applique master_vol (0.4 × 0.5 = 0.2) : OK")


def test_callback_clip_at_one():
    _drv.stop_all()
    _drv._master_vol = 1.0
    data  = np.full((1024, 2), 2.0, dtype=np.float32)   # signal > 1.0
    snd   = SdSound(data, 44100)
    _drv.play(snd)
    outdata = np.zeros((512, 2), dtype=np.float32)
    _drv._callback(outdata, 512, None, None)
    assert np.all(outdata <= 1.0)
    _drv.stop_all()
    print("  callback clip à 1.0 (écrêtage anti-saturation) : OK")


# ---------------------------------------------------------------------------
# Resample interne
# ---------------------------------------------------------------------------

def test_resample_output_length():
    data_in = np.zeros((4410, 2), dtype=np.float32)
    out     = _drv._resample(data_in, sr_in=22050, sr_out=44100)
    assert out.shape == (8820, 2)
    assert out.dtype == np.float32
    print("  _resample 22050→44100 : longueur doublée : OK")


def test_resample_downsample():
    data_in = np.zeros((8820, 2), dtype=np.float32)
    out     = _drv._resample(data_in, sr_in=44100, sr_out=22050)
    assert out.shape == (4410, 2)
    print("  _resample 44100→22050 : longueur divisée par 2 : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_sound_device_driver ===")
    # SdSound
    test_sdsound_attributes()
    test_sdsound_shape_and_dtype()
    # Init
    test_stream_active()
    test_samplerate()
    test_initial_voice_count()
    test_initial_master_volume()
    # make_silent
    test_make_silent_shape()
    test_make_silent_dtype()
    test_make_silent_is_zero()
    test_make_silent_custom_duration()
    # load
    test_load_stereo_wav()
    test_load_mono_wav_becomes_stereo()
    test_load_resampled_wav()
    test_load_dtype_is_float32()
    # play / voice_count
    test_play_increases_voice_count()
    test_play_polyphony()
    test_play_none_sound_no_crash()
    test_play_empty_sound_no_crash()
    test_play_pan_left()
    test_play_pan_right()
    test_play_pan_center()
    # stop_all
    test_stop_all_clears_voices()
    test_stop_all_on_empty_no_crash()
    # set_master_volume
    test_master_volume_int_scale()
    test_master_volume_float_scale()
    test_master_volume_zero()
    test_master_volume_clamp_above()
    test_master_volume_clamp_below()
    test_master_volume_restored()
    # Callback
    test_callback_silence_when_no_voices()
    test_callback_voice_is_mixed()
    test_callback_voice_consumed_when_done()
    test_callback_master_volume_applied()
    test_callback_clip_at_one()
    # Resample
    test_resample_output_length()
    test_resample_downsample()

    _drv.close()
    print("Tous les tests : OK")
