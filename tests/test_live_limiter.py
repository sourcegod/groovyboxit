#python3
"""
    File: tests/test_live_limiter.py
    Limiteur du mix à l'écoute et volume global jusqu'à 200 (Phase 8 étape
    8d1, docs/DESIGN.md § 8a L1-L9 ; avancement 8c1) : LiveLimiter comparé
    à un calcul échantillon par échantillon (seuil jamais dépassé, attaque
    immédiate, retour de 50 ms, état gardé entre des blocs de tailles
    diverses, stéréo liée, signal sous le seuil intact, mesure de la
    réduction) ; callback du pilote avec et sans limiteur ;
    set_master_volume (entier = %, réel = rapport, défaut « volume 1 = ×1 »
    corrigé, jusqu'à ×2) ; volume 0..200 du lecteur, de SoundManager, de la
    configuration ; annonce en dB ; clé live_limiter transmise au pilote
    par la vraie fenêtre principale ; export WAV à 200.
    Date: Sat, 07/11/2026
    Author: Coolbrother
"""
import sys
import os
import math
import json
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest
import wx

from audio.live_limiter import LiveLimiter, THRESHOLD_DB, RELEASE_S
from audio.sound_device_driver import Mixer, SoundDeviceDriver
from audio.sound_manager import SoundManager
from app_config import AppConfig
from player.drum_player import DrumPlayer
from ui.mw_project import ProjectMixin

SR = 44100
T = 10.0 ** (THRESHOLD_DB / 20.0)
EPS = 1e-6


def _reference(x, threshold=T, release_s=RELEASE_S, sr=SR):
    """Gain par échantillon, calculé naïvement :
    g[n] = min(demandé[n], 1 − (1 − g[n−1]) · c)."""
    c = math.exp(-1.0 / (release_s * sr))
    g, out = 1.0, np.empty(len(x))
    for i, p in enumerate(np.max(np.abs(x), axis=1)):
        req = min(1.0, threshold / p) if p > threshold else 1.0
        g = min(req, 1.0 - (1.0 - g) * c)
        out[i] = g
    return out


def _signal(seconds=1.0, seed=0):
    """Stéréo : sinus avec des bouffées au-dessus du seuil, une crête isolée."""
    t = np.arange(int(seconds * SR)) / SR
    left = np.sin(2 * np.pi * 220 * t) * (0.5 + 1.2 * (t % 0.25 < 0.05))
    right = np.sin(2 * np.pi * 330 * t) * 0.7
    x = np.stack([left, right], axis=1).astype(np.float32)
    x[len(x) // 2] = [3.0, -2.5]
    return x


def _process(lim, x, sizes):
    y = x.copy()
    pos, i = 0, 0
    while pos < len(y):
        n = int(sizes[i % len(sizes)])
        lim.process(y[pos:pos + n])
        pos += n
        i += 1
    return y


def _gain_of(x, y):
    peak = np.max(np.abs(x), axis=1)
    return np.where(peak > 0, np.max(np.abs(y), axis=1) / np.maximum(peak, 1e-30), 1.0)


# ---------------------------------------------------------------------------
# LiveLimiter
# ---------------------------------------------------------------------------

def test_constants_match_the_export_limiter():
    from audio import audio_export
    assert THRESHOLD_DB == audio_export.PEAK_DB == -0.3
    assert RELEASE_S == audio_export.RELEASE_S == 0.05


@pytest.mark.parametrize("sizes", [[512], [1], [4096], [7, 300, 1500, 1, 64]])
def test_matches_sample_by_sample_reference(sizes):
    x = _signal()
    y = _process(LiveLimiter(SR), x, sizes)
    assert np.max(np.abs(_gain_of(x, y) - _reference(x))) < 1e-4


def test_threshold_never_exceeded():
    rng = np.random.default_rng(3)
    x = (rng.standard_normal((SR, 2)) * 1.5).astype(np.float32)
    y = _process(LiveLimiter(SR), x, rng.integers(1, 2000, size=200))
    assert float(np.abs(y).max()) <= T


def test_immediate_attack_on_the_peak_sample():
    x = np.full((1000, 2), 0.2, np.float32)
    x[500] = [2.0, 0.5]
    lim = LiveLimiter(SR)
    y = x.copy()
    lim.process(y)
    assert np.all(y[:500] == x[:500])                      # avant : intact
    assert y[500, 0] == pytest.approx(T, rel=1e-5)          # sur la crête : au seuil
    assert lim.reduction_db(reset=False) == pytest.approx(20 * math.log10(T / 2.0), abs=1e-3)


def test_release_takes_50_ms():
    x = np.zeros((SR, 2), np.float32)
    x[0] = [2.0, 2.0]
    x[1:] = 0.1
    y = _process(LiveLimiter(SR), x, [512])
    g = _gain_of(x, y)
    g0 = T / 2.0
    tau = int(RELEASE_S * SR)
    assert g[tau] == pytest.approx(1 - (1 - g0) / math.e, abs=1e-4)
    assert g[5 * tau] == pytest.approx(1 - (1 - g0) * math.exp(-5), abs=1e-4)


def test_state_kept_across_blocks():
    x = _signal(0.5)
    whole = _process(LiveLimiter(SR), x, [len(x)])
    pieces = _process(LiveLimiter(SR), x, [3, 509, 1024, 17])
    assert np.allclose(whole, pieces, atol=1e-6)


def test_signal_under_threshold_is_untouched():
    x = (np.sin(np.arange(SR) / 10.0)[:, None] * [0.9, -0.95]).astype(np.float32)
    lim = LiveLimiter(SR)
    y = _process(lim, x, [512])
    assert np.array_equal(y, x)
    assert lim.reduction_db() == 0.0 and lim.gain == 1.0


def test_stereo_linked():
    x = np.full((200, 2), [0.3, 0.6], np.float32)
    x[100] = [0.5, 3.0]                       # crête sur la droite seulement
    y = x.copy()
    LiveLimiter(SR).process(y)
    ratio = y[100:150] / x[100:150]
    assert np.allclose(ratio[:, 0], ratio[:, 1])            # même gain sur les deux canaux


def test_silence_and_empty_block():
    lim = LiveLimiter(SR)
    z = np.zeros((512, 2), np.float32)
    assert lim.process(z) == 1.0 and not z.any()
    assert lim.process(np.zeros((0, 2), np.float32)) == 1.0


def test_process_in_place_keeps_float32_and_returns_lowest_gain():
    x = np.full((64, 2), 2.0, np.float32)
    lim = LiveLimiter(SR)
    low = lim.process(x)
    assert x.dtype == np.float32 and low == pytest.approx(T / 2.0, rel=1e-5)


def test_reduction_db_reset_and_reset():
    lim = LiveLimiter(SR)
    x = np.full((64, 2), 2.0, np.float32)
    lim.process(x)
    assert lim.reduction_db() < -6.0
    assert lim.reduction_db() == 0.0                         # remise à zéro par la lecture
    assert lim.gain < 1.0
    lim.reset()
    assert lim.gain == 1.0


def test_custom_threshold_and_release():
    lim = LiveLimiter(SR, threshold_db=-6.0, release_s=0.01)
    x = np.full((SR // 10, 2), 0.9, np.float32)
    y = x.copy()
    lim.process(y)
    assert float(np.abs(y).max()) <= 10 ** (-6 / 20)


# ---------------------------------------------------------------------------
# Pilote : callback avec et sans limiteur (L6)
# ---------------------------------------------------------------------------

def _bare_driver(limiter=True):
    d = SoundDeviceDriver.__new__(SoundDeviceDriver)
    Mixer.__init__(d)
    d._limiter = LiveLimiter(d.samplerate) if limiter else None
    d.add_render_source(lambda mix: mix.__iadd__(1.6))   # source trop forte
    return d


def _callback(d, frames=512):
    out = np.zeros((frames, 2), np.float32)
    d._callback(out, frames, None, None)
    return out


def test_callback_limits_the_mix():
    out = _callback(_bare_driver())
    assert float(out.max()) == pytest.approx(T, rel=1e-5)   # limité, pas écrêté


def test_callback_without_limiter_clips():
    out = _callback(_bare_driver(limiter=False))
    assert float(out.max()) == 1.0                          # écrêté net


def test_set_limiter_on_off():
    d = _bare_driver(limiter=False)
    assert d.limiter is None
    d.set_limiter(True)
    assert isinstance(d.limiter, LiveLimiter)
    first = d.limiter
    d.set_limiter(True)
    assert d.limiter is first                              # déjà actif : gardé
    d.set_limiter(False)
    assert d.limiter is None
    assert float(_callback(d).max()) == 1.0


def test_limiter_after_master_volume():
    d = _bare_driver()
    d.set_master_volume(200)                               # 1.6 × 2 : bien au-dessus
    out = _callback(d)
    assert float(out.max()) <= T


def test_mixer_mix_is_not_limited():
    # le Mixer de l'export garde son propre limiteur (à l'écriture)
    m = Mixer()
    m.add_render_source(lambda mix: mix.__iadd__(1.6))
    out = np.zeros((128, 2), np.float32)
    m.mix(out)
    assert float(out.max()) == pytest.approx(1.6)


# ---------------------------------------------------------------------------
# Volume global (L4, L7)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("vol, gain", [
    (1, 0.01),            # défaut corrigé : un entier est un pourcentage
    (0, 0.0), (80, 0.8), (100, 1.0), (150, 1.5), (200, 2.0), (250, 2.0), (-5, 0.0),
    (np.int64(150), 1.5),
    (1.0, 1.0), (0.5, 0.5), (1.5, 1.5), (3.0, 2.0),   # un réel est un rapport
])
def test_set_master_volume(vol, gain):
    m = Mixer()
    m.set_master_volume(vol)
    assert m._master_vol == pytest.approx(gain)


class _Driver:
    def __init__(self):
        self.master, self.sound = [], []

    def set_master_volume(self, v):
        self.master.append(v)

    def set_sound_volume(self, sound, v):
        self.sound.append(v)


def test_sound_manager_volume_up_to_200():
    sm = SoundManager.__new__(SoundManager)
    sm._driver = _Driver()
    sm.drum_sounds, sm.sound_click1, sm.sound_click2 = ["a", "b"], "c1", "c2"
    sm.set_volume(180)
    assert sm._driver.master == [180] and isinstance(sm._driver.master[0], int)
    assert set(sm._driver.sound) == {1.0}                  # pygame : plafond ×1
    sm.set_volume(50)
    assert sm._driver.sound[-1] == 0.5


def test_player_volume_up_to_200():
    seen = []
    player = types.SimpleNamespace(volume=100, VOLUME_MAX=DrumPlayer.VOLUME_MAX,
                                   sound_man=types.SimpleNamespace(set_volume=seen.append))
    DrumPlayer.set_volume(player, 200)
    DrumPlayer.set_volume(player, 201)                     # hors bornes : ignoré
    DrumPlayer.set_volume(player, -1)
    assert player.volume == 200 and seen == [200]


@pytest.mark.parametrize("vol, text", [
    (0, "0"), (80, "80"), (100, "100"), (101, "101 (+0,1 dB)"),
    (150, "150 (+3,5 dB)"), (200, "200 (+6,0 dB)"),
])
def test_master_volume_text(vol, text):
    assert ProjectMixin.master_volume_text(vol) == text


# ---------------------------------------------------------------------------
# Configuration (L3, L4)
# ---------------------------------------------------------------------------

def _cfg(tmp_path, data):
    os.makedirs(tmp_path / "data", exist_ok=True)
    (tmp_path / "data" / "config.json").write_text(json.dumps(data), encoding="utf-8")
    return AppConfig(str(tmp_path))


def test_live_limiter_key(tmp_path):
    assert _cfg(tmp_path, {}).live_limiter_enabled
    assert not _cfg(tmp_path, {"live_limiter": False}).live_limiter_enabled
    for bad in ("false", 0, None):
        assert _cfg(tmp_path, {"live_limiter": bad}).live_limiter_enabled   # seul false coupe


def test_master_volume_key_up_to_200(tmp_path):
    assert _cfg(tmp_path, {"master_volume": 170}).master_volume == 170
    assert _cfg(tmp_path, {"master_volume": 999}).master_volume == 200


# ---------------------------------------------------------------------------
# Vraie fenêtre principale : la clé live_limiter arrive au pilote
# ---------------------------------------------------------------------------

_APP = None


class _RecordingDriver(Mixer):
    """Remplace SoundDeviceDriver (pas de flux PortAudio) et retient
    l'argument limiter."""
    made = []

    def __init__(self, samplerate=Mixer.SAMPLERATE, blocksize=Mixer.BLOCKSIZE, limiter=True,
                 device=None):                      # sortie principale (Phase 8 étape 11b1)
        super().__init__(samplerate)
        self.limiter_arg = limiter
        self.device = device
        _RecordingDriver.made.append(self)

    def close(self):
        pass


@pytest.mark.parametrize("enabled", [True, False])
def test_main_window_passes_live_limiter_key(monkeypatch, enabled):
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)
    import ui.main_window as main_window
    monkeypatch.setattr(main_window, "SoundDeviceDriver", _RecordingDriver)
    monkeypatch.setattr(AppConfig, "live_limiter_enabled", property(lambda self: enabled))
    _RecordingDriver.made = []
    win = main_window.MainWindow(no_fluidsynth=True, no_sfizz=True)
    try:
        assert _RecordingDriver.made[0].limiter_arg is enabled
        assert win._volume_ctrl.GetMax() == 200
        assert win._set_master_volume_undo(180) == 180
        assert win._audio_driver._master_vol == pytest.approx(1.8)
    finally:
        win._router.wait_loaded()
        win.Destroy()


# ---------------------------------------------------------------------------
# Export WAV à un volume global de 200 (L9)
# ---------------------------------------------------------------------------

def test_export_session_uses_volume_200():
    from audio import audio_export as ax
    router = types.SimpleNamespace(
        bank_engine=None, sfz_engine=None,
        render_copy=lambda mixer, bank, schedule, status_cb=None, sfz_engine=None:
            types.SimpleNamespace(_slot_synths={}))
    session = ax._Session(router, SR, 200)
    assert session.mixer._master_vol == pytest.approx(2.0)
    session = ax._Session(router, SR, 1.0)                 # réel : rapport
    assert session.mixer._master_vol == pytest.approx(1.0)
