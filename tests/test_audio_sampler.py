#python3
"""
    File: tests/test_audio_sampler.py
    Tests unitaires de AudioSampler : modes one-shot/loop/gate, zero-crossing,
    crossfade FluidSynth-style, ADSR, pitch shifting (rubberband + stubs).
    Date: Thu, 29/05/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
from audio_sampler import AudioSampler, PlayMode

SR = 44100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sine(freq=440.0, duration_s=2.0, sr=SR, amp=0.5):
    """Génère un sinus float32 mono."""
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    return (np.sin(2 * np.pi * freq * t) * amp).astype(np.float32)


def _make(duration_s=2.0, freq=440.0):
    """AudioSampler sinus stéréo."""
    return AudioSampler(_sine(freq=freq, duration_s=duration_s), SR)


# ---------------------------------------------------------------------------
# __init__ — normalisation des données
# ---------------------------------------------------------------------------

def test_init_mono_becomes_stereo():
    mono = _sine()
    s    = AudioSampler(mono, SR)
    assert s.data.ndim == 2
    assert s.data.shape[1] == 2
    print("  init mono → stéréo (N,2) : OK")


def test_init_stereo_unchanged_shape():
    data = np.zeros((1000, 2), dtype=np.float32)
    s    = AudioSampler(data, SR)
    assert s.data.shape == (1000, 2)
    print("  init stéréo → shape inchangée : OK")


def test_init_single_channel_becomes_stereo():
    data = np.zeros((1000, 1), dtype=np.float32)
    s    = AudioSampler(data, SR)
    assert s.data.shape[1] == 2
    print("  init (N,1) → stéréo (N,2) : OK")


def test_init_dtype_float32():
    data = np.zeros(1000, dtype=np.float64)
    s    = AudioSampler(data, SR)
    assert s.data.dtype == np.float32
    print("  init float64 → converti float32 : OK")


def test_init_default_mode_oneshot():
    s = _make()
    assert s.mode == PlayMode.ONESHOT
    print("  mode par défaut == ONESHOT : OK")


def test_init_default_not_looping():
    s = _make()
    assert not s.is_looping
    print("  is_looping par défaut == False : OK")


# ---------------------------------------------------------------------------
# set_mode
# ---------------------------------------------------------------------------

def test_set_mode_loop():
    s = _make()
    s.set_mode(PlayMode.LOOP)
    assert s.mode == PlayMode.LOOP
    print("  set_mode(LOOP) : OK")


def test_set_mode_gate():
    s = _make()
    s.set_mode(PlayMode.GATE)
    assert s.mode == PlayMode.GATE
    print("  set_mode(GATE) : OK")


def test_set_mode_invalid_raises():
    s = _make()
    try:
        s.set_mode("unknown")
        assert False, "devrait lever ValueError"
    except ValueError:
        pass
    print("  set_mode inconnu → ValueError : OK")


# ---------------------------------------------------------------------------
# set_loop / clear_loop
# ---------------------------------------------------------------------------

def test_set_loop_activates_looping():
    s = _make()
    s.set_loop(0.5, 1.5)
    assert s.is_looping
    assert s._loop_start == 0.5
    assert s._loop_end   == 1.5
    print("  set_loop active is_looping : OK")


def test_set_loop_crossfade_ms():
    s = _make()
    s.set_loop(0.5, 1.5, crossfade_ms=20.0)
    assert s._crossfade_ms == 20.0
    print("  set_loop crossfade_ms stocké : OK")


def test_set_loop_negative_crossfade_clamped():
    s = _make()
    s.set_loop(0.5, 1.5, crossfade_ms=-5.0)
    assert s._crossfade_ms == 0.0
    print("  crossfade_ms négatif clampé à 0 : OK")


def test_clear_loop_resets():
    s = _make()
    s.set_loop(0.5, 1.5)
    s.clear_loop()
    assert not s.is_looping
    assert s._loop_start is None
    assert s._loop_end   is None
    print("  clear_loop réinitialise is_looping : OK")


# ---------------------------------------------------------------------------
# set_adsr
# ---------------------------------------------------------------------------

def test_set_adsr_values_stored():
    s = _make()
    s.set_adsr(attack_ms=10, decay_ms=50, sustain=0.7, release_ms=80)
    assert s._attack_ms  == 10.0
    assert s._decay_ms   == 50.0
    assert abs(s._sustain - 0.7) < 1e-6
    assert s._release_ms == 80.0
    print("  set_adsr valeurs stockées : OK")


def test_set_adsr_sustain_clamped_above():
    s = _make()
    s.set_adsr(sustain=1.5)
    assert s._sustain == 1.0
    print("  sustain > 1.0 clampé à 1.0 : OK")


def test_set_adsr_sustain_clamped_below():
    s = _make()
    s.set_adsr(sustain=-0.1)
    assert s._sustain == 0.0
    print("  sustain < 0.0 clampé à 0.0 : OK")


# ---------------------------------------------------------------------------
# snap_to_zero_crossing
# ---------------------------------------------------------------------------

def test_snap_nearest_finds_crossing():
    s   = _make(freq=440.0)
    pos = SR // 2
    zc  = s.snap_to_zero_crossing(pos, window=512, direction="nearest")
    assert abs(zc - pos) < 256
    print(f"  snap nearest : {pos} → {zc} (écart {abs(zc-pos)}) : OK")


def test_snap_before_le_pos():
    s   = _make(freq=440.0)
    pos = SR // 2
    zc  = s.snap_to_zero_crossing(pos, direction="before")
    assert zc <= pos
    print(f"  snap before ≤ pos : OK")


def test_snap_after_ge_pos():
    s   = _make(freq=440.0)
    pos = SR // 2
    zc  = s.snap_to_zero_crossing(pos, direction="after")
    assert zc >= pos
    print(f"  snap after ≥ pos : OK")


def test_snap_no_crossing_returns_pos():
    data = np.ones((1000, 2), dtype=np.float32)   # signal constant → pas de passage
    s    = AudioSampler(data, SR)
    zc   = s.snap_to_zero_crossing(500, window=100)
    assert zc == 500
    print("  snap sans passage à zéro → pos inchangé : OK")


# ---------------------------------------------------------------------------
# _apply_crossfade
# ---------------------------------------------------------------------------

def test_crossfade_shape_preserved():
    s    = _make()
    data = s.data.copy()
    ls   = SR // 2
    le   = SR
    out  = s._apply_crossfade(data, ls, le)
    assert out.shape == data.shape
    print("  crossfade : shape préservée : OK")


def test_crossfade_modifies_end_region():
    s    = _make()
    data = s.data.copy()
    ls, le = SR // 2, SR
    out  = s._apply_crossfade(data, ls, le)
    xf_len = int(s._crossfade_ms / 1000.0 * SR)
    region_orig = data[le - xf_len : le]
    region_out  = out[le - xf_len : le]
    assert not np.allclose(region_orig, region_out)
    print("  crossfade : région de transition modifiée : OK")


def test_crossfade_too_short_returns_unchanged():
    s    = _make(duration_s=0.1)
    data = s.data.copy()
    out  = s._apply_crossfade(data, ls=1, le=2)   # trop court → xf_len < 2
    assert np.array_equal(data, out)
    print("  crossfade trop court → données inchangées : OK")


# ---------------------------------------------------------------------------
# _apply_adsr
# ---------------------------------------------------------------------------

def test_adsr_attack_starts_near_zero():
    s = _make()
    s.set_adsr(attack_ms=100, sustain=1.0)
    data = np.ones((SR * 2, 2), dtype=np.float32)
    out  = s._apply_adsr(data)
    assert out[0, 0] < 0.01
    print("  ADSR attack : premier échantillon ≈ 0 : OK")


def test_adsr_after_attack_near_one():
    s = _make()
    s.set_adsr(attack_ms=10, decay_ms=0, sustain=1.0, release_ms=0)
    data = np.ones((SR * 2, 2), dtype=np.float32)
    out  = s._apply_adsr(data)
    a_n  = int(0.01 * SR)
    assert abs(out[a_n + 10, 0] - 1.0) < 0.02
    print("  ADSR après attack ≈ 1.0 : OK")


def test_adsr_sustain_level():
    s = _make()
    s.set_adsr(attack_ms=0, decay_ms=10, sustain=0.6, release_ms=0)
    data = np.ones((SR * 2, 2), dtype=np.float32)
    out  = s._apply_adsr(data, apply_release=False)
    d_end = int(0.01 * SR)
    mid   = d_end + (len(out) - d_end) // 2
    assert abs(out[mid, 0] - 0.6) < 0.02
    print("  ADSR sustain niveau 0.6 : OK")


def test_adsr_release_ends_near_zero():
    s = _make()
    s.set_adsr(release_ms=100, sustain=1.0)
    data = np.ones((SR * 2, 2), dtype=np.float32)
    out  = s._apply_adsr(data, apply_release=True)
    assert out[-1, 0] < 0.01
    print("  ADSR release : dernier échantillon ≈ 0 : OK")


def test_adsr_no_release_last_sample_not_zero():
    s = _make()
    s.set_adsr(release_ms=500, sustain=0.8)
    data = np.ones((SR * 2, 2), dtype=np.float32)
    out  = s._apply_adsr(data, apply_release=False)
    assert out[-1, 0] > 0.5
    print("  ADSR sans release : dernier échantillon ≠ 0 : OK")


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

def test_render_oneshot_full():
    s   = _make(duration_s=1.0)
    buf = s.render()
    assert buf.shape == (SR, 2)
    assert buf.dtype == np.float32
    print("  render ONESHOT complet : shape (SR,2) : OK")


def test_render_oneshot_trimmed():
    s   = _make(duration_s=2.0)
    buf = s.render(duration_ms=500)
    assert buf.shape == (SR // 2, 2)
    print("  render ONESHOT 500ms : shape (SR//2,2) : OK")


def test_render_loop_longer_than_source():
    s = _make(duration_s=2.0)
    s.set_mode(PlayMode.LOOP)
    s.set_loop(0.5, 1.5)
    buf = s.render()
    assert len(buf) > len(s.data)
    print(f"  render LOOP > source ({len(buf)} > {len(s.data)}) : OK")


def test_render_loop_float32_stereo():
    s = _make()
    s.set_mode(PlayMode.LOOP)
    s.set_loop(0.5, 1.5)
    buf = s.render()
    assert buf.dtype == np.float32
    assert buf.ndim == 2 and buf.shape[1] == 2
    print("  render LOOP float32 stéréo : OK")


def test_render_gate_no_release():
    s = _make()
    s.set_mode(PlayMode.GATE)
    s.set_loop(0.5, 1.5)
    s.set_adsr(release_ms=500, sustain=1.0)
    # Remplacer data par signal constant pour isoler l'enveloppe
    s.data = np.ones((SR * 2, 2), dtype=np.float32)
    buf = s.render()
    assert buf[-1, 0] > 0.5   # release non appliqué
    print("  render GATE : release non appliqué (dernier > 0.5) : OK")


def test_render_oneshot_without_loop_uses_oneshot_path():
    s = _make(duration_s=1.0)
    s.set_loop(0.2, 0.8)     # loop configuré mais mode = ONESHOT
    buf = s.render()
    assert buf.shape == (SR, 2)   # durée naturelle, pas de sustain
    print("  render ONESHOT ignore les loop points : OK")


# ---------------------------------------------------------------------------
# pitch_shift
# ---------------------------------------------------------------------------

def test_pitch_shift_zero_returns_clone():
    s   = _make()
    s2  = s.pitch_shift(0)
    assert np.array_equal(s.data, s2.data)
    print("  pitch_shift(0) → clone identique : OK")


def test_pitch_shift_clone_preserves_mode():
    s = _make()
    s.set_mode(PlayMode.GATE)
    s.set_loop(0.5, 1.5)
    s2 = s.pitch_shift(0)
    assert s2.mode        == PlayMode.GATE
    assert s2.is_looping  == True
    assert s2._loop_start == 0.5
    assert s2._loop_end   == 1.5
    print("  pitch_shift clone préserve mode/loop : OK")


def test_pitch_shift_rubberband_same_sr():
    s  = _make(duration_s=0.5)
    s2 = s.pitch_shift(+7, method="rubberband")
    assert s2.samplerate == SR
    print("  pitch_shift rubberband samplerate inchangé : OK")


def test_pitch_shift_rubberband_same_shape():
    s  = _make(duration_s=0.5)
    s2 = s.pitch_shift(-12, method="rubberband")
    assert s2.data.ndim == 2 and s2.data.shape[1] == 2
    print("  pitch_shift rubberband shape stéréo : OK")


def test_pitch_shift_wsola_not_implemented():
    s = _make(duration_s=0.2)
    try:
        s.pitch_shift(+3, method="wsola")
        assert False
    except NotImplementedError:
        pass
    print("  pitch_shift wsola → NotImplementedError : OK")


def test_pitch_shift_phase_vocoder_not_implemented():
    s = _make(duration_s=0.2)
    try:
        s.pitch_shift(+3, method="phase_vocoder")
        assert False
    except NotImplementedError:
        pass
    print("  pitch_shift phase_vocoder → NotImplementedError : OK")


def test_pitch_shift_unknown_method_raises():
    s = _make(duration_s=0.2)
    try:
        s.pitch_shift(+3, method="unknown")
        assert False
    except ValueError:
        pass
    print("  pitch_shift méthode inconnue → ValueError : OK")


# ---------------------------------------------------------------------------
# Propriétés et __repr__
# ---------------------------------------------------------------------------

def test_duration_s():
    s = _make(duration_s=1.5)
    assert abs(s.duration_s - 1.5) < 0.01
    print(f"  duration_s ≈ 1.5s : OK")


def test_repr_oneshot():
    s = _make()
    r = repr(s)
    assert "oneshot" in r and "dur=" in r
    print("  repr ONESHOT contient mode et dur : OK")


def test_repr_loop():
    s = _make()
    s.set_mode(PlayMode.LOOP)
    s.set_loop(0.5, 1.5, crossfade_ms=10)
    r = repr(s)
    assert "loop" in r and "0.500" in r and "1.500" in r
    print("  repr LOOP contient loop points : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_audio_sampler ===")
    # init
    test_init_mono_becomes_stereo()
    test_init_stereo_unchanged_shape()
    test_init_single_channel_becomes_stereo()
    test_init_dtype_float32()
    test_init_default_mode_oneshot()
    test_init_default_not_looping()
    # set_mode
    test_set_mode_loop()
    test_set_mode_gate()
    test_set_mode_invalid_raises()
    # set_loop / clear_loop
    test_set_loop_activates_looping()
    test_set_loop_crossfade_ms()
    test_set_loop_negative_crossfade_clamped()
    test_clear_loop_resets()
    # set_adsr
    test_set_adsr_values_stored()
    test_set_adsr_sustain_clamped_above()
    test_set_adsr_sustain_clamped_below()
    # snap_to_zero_crossing
    test_snap_nearest_finds_crossing()
    test_snap_before_le_pos()
    test_snap_after_ge_pos()
    test_snap_no_crossing_returns_pos()
    # _apply_crossfade
    test_crossfade_shape_preserved()
    test_crossfade_modifies_end_region()
    test_crossfade_too_short_returns_unchanged()
    # _apply_adsr
    test_adsr_attack_starts_near_zero()
    test_adsr_after_attack_near_one()
    test_adsr_sustain_level()
    test_adsr_release_ends_near_zero()
    test_adsr_no_release_last_sample_not_zero()
    # render
    test_render_oneshot_full()
    test_render_oneshot_trimmed()
    test_render_loop_longer_than_source()
    test_render_loop_float32_stereo()
    test_render_gate_no_release()
    test_render_oneshot_without_loop_uses_oneshot_path()
    # pitch_shift
    test_pitch_shift_zero_returns_clone()
    test_pitch_shift_clone_preserves_mode()
    test_pitch_shift_rubberband_same_sr()
    test_pitch_shift_rubberband_same_shape()
    test_pitch_shift_wsola_not_implemented()
    test_pitch_shift_phase_vocoder_not_implemented()
    test_pitch_shift_unknown_method_raises()
    # propriétés
    test_duration_s()
    test_repr_oneshot()
    test_repr_loop()
    print("Tous les tests : OK")
