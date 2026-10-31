#python3
"""
    File: tests/test_mixer.py
    Tests de Mixer (Phase 8 étape 1c1, docs/DESIGN.md § Phase 8 étape 1a,
    W7) : mélange sans carte son, sans écrêtage, volume global, sources
    externes, voix qui avancent d'un appel à l'autre, découpage en blocs
    sans effet sur le résultat, callback du driver = mix puis écrêtage.
    Le Mixer est un prototype, cible C/C++ : ces tests fixent le
    comportement observable (contenu des tampons), référence de la
    version native.
    Date: Sat, 31/10/2026
    Author: Coolbrother
"""
import sys
import os
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest
import soundfile as sf

import sound_device_driver
from sound_device_driver import Mixer, SoundDeviceDriver, SdSound


def _const(value, n=1000):
    return SdSound(np.full((n, 2), value, dtype=np.float32), Mixer.SAMPLERATE)


def _ramp(n=2000):
    """Rampe stéréo distincte par canal : révèle tout décalage d'échantillon."""
    x = np.linspace(-0.8, 0.8, n, dtype=np.float32)
    return SdSound(np.column_stack([x, -x * 0.5]).astype(np.float32), Mixer.SAMPLERATE)


def _mix(m, frames=512):
    out = np.zeros((frames, 2), dtype=np.float32)
    m.mix(out)
    return out


# ---------------------------------------------------------------------------
# Sans carte son
# ---------------------------------------------------------------------------

def test_mixer_opens_no_stream(monkeypatch):
    def no_stream(*a, **k):
        raise AssertionError("flux PortAudio ouvert")
    monkeypatch.setattr(sound_device_driver.sd, "OutputStream", no_stream)
    m = Mixer()
    assert not hasattr(m, "_stream")
    m.play(_const(0.5))
    assert np.allclose(_mix(m), 0.5)


def test_mixer_defaults_and_constants():
    m = Mixer()
    assert m.samplerate == 44100
    assert Mixer.BLOCKSIZE == 512
    assert m.voice_count() == 0
    # SynthEngine lit driver.LFO_DEPTH_MAX : présent sur le Mixer
    assert Mixer.LFO_DEPTH_MAX == pytest.approx(2.0 ** (2.0 / 12.0) - 1.0)


def test_mixer_custom_samplerate():
    assert Mixer(48000).samplerate == 48000


def test_driver_is_a_mixer():
    assert issubclass(SoundDeviceDriver, Mixer)


# ---------------------------------------------------------------------------
# mix(out)
# ---------------------------------------------------------------------------

def test_mix_silence_without_voices():
    assert np.all(_mix(Mixer()) == 0.0)


def test_mix_overwrites_out():
    m = Mixer()
    out = np.full((256, 2), 0.7, dtype=np.float32)
    m.mix(out)
    assert np.all(out == 0.0)


def test_mix_keeps_shape_and_dtype():
    out = np.zeros((100, 2), dtype=np.float32)
    Mixer().mix(out)
    assert out.shape == (100, 2) and out.dtype == np.float32


def test_mix_does_not_clip():
    m = Mixer()
    m.play(_const(0.9))
    m.play(_const(0.9))
    assert np.allclose(_mix(m), 1.8)


def test_mix_negative_peak_not_clipped():
    m = Mixer()
    m.play(_const(-0.8))
    m.play(_const(-0.8))
    assert np.allclose(_mix(m), -1.6)


def test_mix_master_volume_int_and_float():
    m = Mixer()
    m.set_master_volume(50)
    m.play(_const(0.9, n=2000))
    m.play(_const(0.9, n=2000))
    assert np.allclose(_mix(m), 0.9)
    m.set_master_volume(0.25)
    assert np.allclose(_mix(m), 0.45)


def test_mix_pan_hard_left_and_right():
    m = Mixer()
    m.play(_const(0.5), vol=1.0, pan=-100)
    out = _mix(m)
    assert np.allclose(out[:, 0], 0.5) and np.allclose(out[:, 1], 0.0)
    m.stop_all()
    m.play(_const(0.5), vol=1.0, pan=100)
    out = _mix(m)
    assert np.allclose(out[:, 0], 0.0) and np.allclose(out[:, 1], 0.5)


def test_mix_render_source_before_master_volume_not_clipped():
    m = Mixer()
    m.set_master_volume(0.5)
    m.add_render_source(lambda mix: mix.__iadd__(1.5))
    m.add_render_source(lambda mix: mix.__iadd__(1.5))
    assert np.allclose(_mix(m), 1.5)


def test_mix_render_source_receives_block_size():
    m = Mixer()
    seen = []
    m.add_render_source(lambda mix: seen.append(mix.shape))
    _mix(m, 37)
    assert seen == [(37, 2)]


# ---------------------------------------------------------------------------
# Les voix avancent d'un appel à l'autre
# ---------------------------------------------------------------------------

def test_one_shot_voice_consumed_across_calls():
    m = Mixer()
    m.play(_const(0.5, n=600))
    first = _mix(m, 512)
    assert np.allclose(first, 0.5)
    assert m.voice_count() == 1
    second = _mix(m, 512)
    # 88 échantillons restants (le dernier sans voisin d'interpolation)
    assert np.allclose(second[:87], 0.5)
    assert np.all(second[100:] == 0.0)
    assert m.voice_count() == 0


def test_one_shot_split_blocks_equal_single_block():
    """Découper le mélange en blocs de tailles quelconques (rendu jusqu'à un
    événement) donne exactement le même signal qu'un seul bloc."""
    whole, split = Mixer(), Mixer()
    for m in (whole, split):
        m.play(_ramp(), vol=0.8, pan=30)
        m.play(_ramp(1500), vol=0.5, pan=-60, phase_incr=1.25)
    ref = _mix(whole, 2000)
    parts = [_mix(split, n) for n in (1, 300, 512, 7, 680, 500)]
    assert np.allclose(np.concatenate(parts), ref, atol=1e-6)


def test_loop_voice_split_blocks_equal_single_block():
    data = np.sin(np.linspace(0, 40 * np.pi, 3000)).astype(np.float32) * 0.5
    snd = SdSound(np.column_stack([data, data]), Mixer.SAMPLERATE,
                  loop_start=1000, loop_end=2800, xf_samples=32)
    whole, split = Mixer(), Mixer()
    for m in (whole, split):
        m.play(snd, vol=0.9, phase_incr=1.1)
    ref = _mix(whole, 6000)
    parts = [_mix(split, n) for n in (512, 1, 2000, 333, 3154)]
    assert np.allclose(np.concatenate(parts), ref, atol=1e-6)
    assert split.loop_voice_count() == 1


def test_loop_voice_release_ends_voice():
    data = np.full((3000, 2), 0.5, dtype=np.float32)
    snd = SdSound(data, Mixer.SAMPLERATE, loop_start=1000, loop_end=2800)
    m = Mixer()
    m.play(snd)
    _mix(m, 512)
    m.stop_sound(snd)
    rel = int(Mixer.RELEASE_MS / 1000 * Mixer.SAMPLERATE)
    out = _mix(m, rel + 100)
    assert out[0, 0] == pytest.approx(0.5, abs=1e-3)
    assert np.all(out[rel:] == 0.0)
    assert m.loop_voice_count() == 0


def test_stop_all_silences_next_block():
    m = Mixer()
    m.play(_const(0.5))
    m.stop_all()
    assert np.all(_mix(m) == 0.0)


def test_play_from_another_thread_while_mixing():
    m = Mixer()
    t = threading.Thread(target=lambda: [m.play(_const(0.01, n=100)) for _ in range(200)])
    t.start()
    for _ in range(50):
        _mix(m, 64)
    t.join()
    _mix(m, 200)
    assert m.voice_count() == 0


# ---------------------------------------------------------------------------
# Chargement sur le Mixer (les moteurs l'utilisent comme driver)
# ---------------------------------------------------------------------------

def test_mixer_load_wav(tmp_path):
    path = str(tmp_path / "s.wav")
    sf.write(path, np.full(441, 0.25, dtype=np.float32), 44100)   # mono
    snd = Mixer().load(path)
    assert snd.data.shape == (441, 2)
    assert snd.data[0, 0] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Callback du driver : mix(), puis écrêtage à ±1
# ---------------------------------------------------------------------------

def _bare_driver():
    """Driver sans flux PortAudio, construit par Mixer.__init__."""
    d = SoundDeviceDriver.__new__(SoundDeviceDriver)
    Mixer.__init__(d)
    return d


def test_driver_callback_is_mix_then_clip():
    d, m = _bare_driver(), Mixer()
    for x in (d, m):
        x.set_master_volume(80)
        x.play(_ramp(), vol=1.0)
        x.play(_const(0.9, n=2000))
    out = np.zeros((512, 2), dtype=np.float32)
    d._callback(out, 512, None, None)
    assert np.allclose(out, np.clip(_mix(m), -1.0, 1.0))
    assert out.max() <= 1.0 and out.min() >= -1.0
