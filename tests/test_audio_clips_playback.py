#python3
"""
    File: tests/test_audio_clips_playback.py
    Lecture des clips audio (Phase 8 étape 14d1, docs/DESIGN.md § 14a A9,
    A13 et essais) : événements (AUDIO_TAPE_EVENT, clips déjà commencés,
    rappels « clip en cours ») ; TrackAudioMixin sur un vrai TrackRouter et
    un Mixer (piste audio seulement, volume × gain, pan, Mute, Solo, départ
    au milieu, pas de relance d'un clip qui sonne, nouveau départ, coupures,
    fichier introuvable, cache, mono, rééchantillonnage, render_copy) ;
    DrumPlayer (événements de la mesure, décompte, répartition, saut de
    position) ; rendu WAV et stems ; branchement de la vraie fenêtre.
    Prototype Python, cible C/C++ : les tests fixent le comportement
    observable (positions à l'échantillon, contenu des tampons).
    Date: Sun, 15/11/2026
    Author: Coolbrother
"""
import sys
import os
import json
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest
import soundfile as sf
import wx

from pattern import Pattern, TapeEvent, ETYPE_AUDIO, ETYPE_GRID
from rack import Rack
from track_router import TrackRouter
from voice_manager import VoiceManager
from player import tape_events as te
from player.drum_player import DrumPlayer
from audio import audio_export as ax
from audio import audio_takes as at
from audio.sound_device_driver import Mixer

SR = 44100


class _Snd:
    pad_notes, gm_note_map = [], {}

    def __getattr__(self, name):
        return lambda *a, **k: None

    def render_copy(self, driver):
        return _Snd()


def _wav(path, seconds=1.0, value=0.5, sr=SR, channels=1):
    n = int(sr * seconds)
    data = np.full((n, channels) if channels > 1 else n, value, np.float32)
    at.write_take(str(path), data, sr)
    return str(path)


def _clip(rel, time=0, gain=1.0):
    return TapeEvent(ETYPE_AUDIO, payload={"file": rel, "gain": gain}, time=time)


@pytest.fixture
def env(tmp_path):
    mix = Mixer(SR)
    statuses = []
    r = TrackRouter(Rack(), "/fake", _Snd(), statuses.append, driver=mix,
                    schedule=lambda *a: None)
    r.audio_resolver = lambda rel: str(tmp_path / rel)
    r._track_kinds[1] = "audio"
    _wav(tmp_path / "voix.wav", seconds=1.0, value=0.5)
    return SimpleNamespace(r=r, mix=mix, statuses=statuses, tmp=tmp_path)


def _level(voice):
    return voice.vol_l, voice.vol_r


# ---------------------------------------------------------------------------
# Événements
# ---------------------------------------------------------------------------

def test_clip_event_and_its_data():
    c = _clip("Audios/v.wav", time=4, gain=0.5)
    (t, marker, data, vel), = te.tape_events([[], [c]], 0, 15, lambda s: s * 0.125)
    assert (t, marker, data, vel) == (0.5, te.AUDIO_TAPE_EVENT, (1, "Audios/v.wav", 0.5, c.id, 0.0), 0)
    assert te.AUDIO_TAPE_EVENT == -10


def test_clip_data_defaults():
    ev = TapeEvent(ETYPE_AUDIO, payload={}, time=0)
    assert te.audio_clip_data(3, ev, 1.5) == (3, "", 1.0, ev.id, 1.5)


def test_clip_outside_the_window_or_already_passed():
    c = _clip("v", time=20)
    assert te.tape_events([[c]], 0, 15, lambda s: s) == []
    assert te.tape_events([[_clip("v", time=2)]], 0, 15, lambda s: s, min_sec=3) == []


def test_clips_under_way():
    started, later = _clip("a", time=2), _clip("b", time=10)
    evs = te.audio_clips_under_way([[started, later]], 0, 15, lambda s: s * 0.1, elapsed=0.5)
    (t, marker, data, _), = evs
    assert t == 0.5 and data[1] == "a" and data[4] == pytest.approx(0.3)


def test_resyncs_every_quarter_second():
    evs = te.audio_clip_resyncs([[_clip("a", time=0)]], 0, 63, lambda s: s * 0.125,
                                elapsed=0.6, end_sec=8.0, duration_of=lambda f: 2.0)
    assert [round(e[0], 2) for e in evs] == [0.75, 1.0, 1.25, 1.5, 1.75]
    assert [round(e[2][4], 2) for e in evs] == [0.75, 1.0, 1.25, 1.5, 1.75]
    assert te.AUDIO_RESYNC_SECS == 0.25


def test_resyncs_stop_at_the_end_of_the_window():
    evs = te.audio_clip_resyncs([[_clip("a", time=0)]], 0, 63, lambda s: s * 0.125,
                                elapsed=0.0, end_sec=0.6, duration_of=lambda f: 5.0)
    assert [round(e[0], 2) for e in evs] == [0.25, 0.5]


def test_no_resync_without_known_duration():
    assert te.audio_clip_resyncs([[_clip("a")]], 0, 63, lambda s: s, 0.0, 8.0,
                                 lambda f: 0.0) == []


def test_play_event_sends_the_clip_to_the_router():
    seen = []
    router = SimpleNamespace(on_audio_clip=lambda *a: seen.append(a))
    te.play_event(router, None, 0, te.AUDIO_TAPE_EVENT, (1, "v", 0.8, 5, 0.25), 0)
    assert seen == [(1, "v", 0.8, 5, 0.25)]


# ---------------------------------------------------------------------------
# Routeur : lecture d'un clip
# ---------------------------------------------------------------------------

def test_clip_played_on_an_audio_track(env):
    v = env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1)
    assert v is not None and env.mix.voice_count() == 1
    assert v.pos == 0.0 and v.data.shape == (SR, 2)            # mono → stéréo


def test_not_on_a_midi_track(env):
    assert env.r.on_audio_clip(2, "voix.wav", 1.0, clip_id=1) is None
    env.r._track_kinds[1] = "midi"
    assert env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1) is None


def test_volume_gain_and_pan(env):
    env.r._track_volumes[1] = 50
    env.r._track_pans[1] = -100
    v = env.r.on_audio_clip(1, "voix.wav", 0.8, clip_id=1)
    assert _level(v) == pytest.approx((0.4, 0.0))       # 0,8 × 50 %, tout à gauche


def test_muted_or_outside_solo(env):
    env.r._track_mutes[1] = True
    assert env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1) is None
    env.r._track_mutes[1] = False
    env.r._track_solos[3] = True
    assert env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1) is None


def test_no_driver(env):
    env.r._driver = None
    assert env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1) is None


def test_start_in_the_middle(env):
    v = env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1, offset=0.25)
    assert v.pos == SR // 4


def test_offset_beyond_the_end(env):
    assert env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1, offset=1.5) is None


def test_clip_under_way_not_restarted(env):
    first = env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1)
    assert env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1, offset=0.3) is None
    assert env.mix.voice_count() == 1 and env.r._clip_voices[1][1] is first


def test_new_start_replaces_the_old_voice(env):
    first = env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1)
    second = env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1, offset=0.0)
    assert second is not first and env.mix.voice_count() == 1


def test_stopped_clip_resumed_by_a_resync(env):
    env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1)
    env.r.stop_audio_clips(1)                                  # Mute
    v = env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1, offset=0.5)
    assert v is not None and v.pos == SR // 2


def test_finished_voice_no_longer_counts(env):
    v = env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1)
    out = np.zeros((SR + 512, 2), np.float32)
    env.mix.mix(out)                                           # le clip se termine
    assert not env.r._voice_alive(v)
    assert env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1, offset=0.2) is not None


def test_two_clips_two_voices(env):
    env.r._track_kinds[2] = "audio"
    env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1)
    env.r.on_audio_clip(2, "voix.wav", 1.0, clip_id=2)
    assert env.mix.voice_count() == 2


# ---------------------------------------------------------------------------
# Coupures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cut", ["stop_audio_clips", "cut_all_notes", "on_play_stop",
                                 "stop_all_sounds", "panic"])
def test_cuts_stop_every_clip(env, cut):
    env.r._track_kinds[2] = "audio"
    env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1)
    env.r.on_audio_clip(2, "voix.wav", 1.0, clip_id=2)
    getattr(env.r, cut)()
    assert env.mix.voice_count() == 0 and env.r._clip_voices == {}


def test_cut_one_track(env):
    env.r._track_kinds[2] = "audio"
    env.r.on_audio_clip(1, "voix.wav", 1.0, clip_id=1)
    env.r.on_audio_clip(2, "voix.wav", 1.0, clip_id=2)
    env.r.cut_track_notes(1)
    assert list(env.r._clip_voices) == [2] and env.mix.voice_count() == 1


def test_stop_without_init_is_harmless():
    r = TrackRouter.__new__(TrackRouter)
    r._driver = None
    r.stop_audio_clips()


# ---------------------------------------------------------------------------
# Fichiers
# ---------------------------------------------------------------------------

def test_missing_file_reported_once(env):
    assert env.r.on_audio_clip(1, "absent.wav", 1.0, clip_id=1) is None
    env.r.on_audio_clip(1, "absent.wav", 1.0, clip_id=1)
    assert env.statuses == ["Prise audio introuvable : absent.wav"]
    assert env.r.clip_duration_secs("absent.wav") == 0.0


def test_unreadable_file_reported(env):
    (env.tmp / "faux.wav").write_text("pas un wav")
    assert env.r.on_audio_clip(1, "faux.wav", 1.0, clip_id=1) is None
    assert env.statuses == ["Prise audio introuvable : faux.wav"]


def test_file_read_once_then_reloaded_when_changed(env):
    a = env.r.clip_sound("voix.wav")
    assert env.r.clip_sound("voix.wav") is a
    time.sleep(0.01)
    _wav(env.tmp / "voix.wav", seconds=0.5, value=0.25)
    os.utime(env.tmp / "voix.wav", (time.time() + 5, time.time() + 5))
    b = env.r.clip_sound("voix.wav")
    assert b is not a and len(b.data) == SR // 2


def test_stereo_kept_and_resampled(env):
    _wav(env.tmp / "st.wav", seconds=1.0, value=0.3, sr=22050, channels=2)
    s = env.r.clip_sound("st.wav")
    assert s.samplerate == SR and s.data.shape == (SR, 2)
    assert env.r.clip_duration_secs("st.wav") == pytest.approx(1.0)


def test_resolver_or_raw_path(env):
    env.r.audio_resolver = None
    assert env.r.clip_sound(str(env.tmp / "voix.wav")) is not None


def test_render_copy_keeps_kinds_resolver_and_cache(env):
    env.r.clip_sound("voix.wav")
    copy = env.r.render_copy(Mixer(SR), schedule=lambda *a: None)
    assert copy._track_kinds[1] == "audio" and copy.audio_resolver is env.r.audio_resolver
    assert copy._clip_cache is env.r._clip_cache
    assert copy.on_audio_clip(1, "voix.wav", 1.0, clip_id=1) is not None


# ---------------------------------------------------------------------------
# DrumPlayer
# ---------------------------------------------------------------------------

class _S:
    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def player():
    p = DrumPlayer(_S())
    p.start_thread = p.stop_thread = lambda: None
    return p


def test_measure_events_include_clips_under_way_and_resyncs(player):
    c = _clip("a", time=0)
    player._pattern._tape[1].append(c)
    player.playing = True
    player._clip_duration_cb = lambda f: 2.0
    total = player._pattern._num_bars * player._pattern._num_steps
    evs = player._build_measure_events(0, total - 1, total, player._pattern._num_bars, 0.6)
    clips = [e for e in evs if e[1] == te.AUDIO_TAPE_EVENT]
    assert clips[0][0] == 0.6 and clips[0][2][4] == pytest.approx(0.6)     # en cours
    assert [round(e[0], 2) for e in clips[1:]] == [0.75, 1.0, 1.25, 1.5, 1.75]


def test_no_clip_during_the_count_in(player):
    player._pattern._tape[1].append(_clip("a", time=0))
    player.playing = True
    player._count_in = 1
    player._clip_duration_cb = lambda f: 2.0
    total = player._pattern._num_steps
    evs = player._build_measure_events(0, total - 1, total, 1, 0.5)
    assert [e for e in evs if e[1] == te.AUDIO_TAPE_EVENT and e[2][4] > 0] == []


def test_no_resync_without_duration_callback(player):
    player._pattern._tape[1].append(_clip("a", time=0))
    player.playing = True
    total = player._pattern._num_bars * player._pattern._num_steps
    evs = player._build_measure_events(0, total - 1, total, player._pattern._num_bars, 0.6)
    assert len([e for e in evs if e[1] == te.AUDIO_TAPE_EVENT]) == 1         # « en cours » seul


def test_dispatch_calls_the_clip_callback(player):
    seen = []
    player._on_audio_clip_cb = lambda *a: seen.append(a)
    player._dispatch_event(te.AUDIO_TAPE_EVENT, (1, "a", 1.0, 9, 0.0), 0, 0.0)
    assert seen == [(1, "a", 1.0, 9, 0.0)]
    player._on_audio_clip_cb = None
    player._dispatch_event(te.AUDIO_TAPE_EVENT, (1, "a", 1.0, 9, 0.0), 0, 0.0)


def test_seek_cuts_clips_only_while_playing(player):
    calls = []
    player._on_seek_cb = lambda: calls.append(1)
    player.navigate_bar(1)
    assert calls == []
    player.playing = True
    player.navigate_bar(1)
    player.navigate_bar(-1)
    player.goto_start()
    player.goto_end()
    player.move_by_beats(1)
    assert calls == [1, 1, 1, 1, 1]


# ---------------------------------------------------------------------------
# Rendu WAV et stems
# ---------------------------------------------------------------------------

def _render(env, pattern, **kw):
    return ax.render_pattern(pattern, pattern.tempo_map(), env.r, VoiceManager(),
                             end=ax.END_LOOP, **kw)


def _rms(data, a, b):
    seg = data[int(a * SR):int(b * SR), 0]
    return float(np.sqrt(np.mean(seg ** 2)))


def test_render_places_the_clip_at_its_step(env):
    _wav(env.tmp / "court.wav", seconds=0.4, value=0.5)
    p = Pattern()
    p._bpm = 120
    p._tape[1].append(_clip("court.wav", time=4))                # pas 4 = 0,5 s
    d = _render(env, p).data
    assert _rms(d, 0.0, 0.48) == 0.0
    assert _rms(d, 0.52, 0.88) == pytest.approx(0.5, abs=0.02)
    assert _rms(d, 0.92, 1.9) == 0.0


def test_render_follows_gain_and_mute(env):
    _wav(env.tmp / "court.wav", seconds=0.4, value=0.5)
    p = Pattern()
    p._bpm = 120
    p._tape[1].append(_clip("court.wav", time=4, gain=0.5))
    assert _rms(_render(env, p).data, 0.52, 0.88) == pytest.approx(0.25, abs=0.02)
    env.r._track_mutes[1] = True
    assert float(np.abs(_render(env, p).data).max()) == 0.0


def test_render_stems_keep_or_drop_the_audio_track(env):
    _wav(env.tmp / "court.wav", seconds=0.4, value=0.5)
    p = Pattern()
    p._bpm = 120
    p._tape[1].append(_clip("court.wav", time=4))
    assert float(np.abs(_render(env, p, tracks={1}).data).max()) > 0.4
    assert float(np.abs(_render(env, p, tracks={0}).data).max()) == 0.0


def test_render_ignores_clips_on_a_midi_track(env):
    _wav(env.tmp / "court.wav", seconds=0.4, value=0.5)
    p = Pattern()
    p._tape[2].append(_clip("court.wav", time=0))
    assert float(np.abs(_render(env, p).data).max()) == 0.0


# ---------------------------------------------------------------------------
# Vraie fenêtre principale : branchement
# ---------------------------------------------------------------------------

_APP = None


def test_real_main_window_wiring(isolated_preferences, monkeypatch):
    """Une seule vraie MainWindow (clients ALSA)."""
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)
    from ui.main_window import MainWindow
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    win = None
    try:
        win = MainWindow(no_fluidsynth=True, no_sfizz=True)
        p, r = win._player, win._router
        assert p._on_audio_clip_cb == r.on_audio_clip
        assert p._clip_duration_cb == r.clip_duration_secs
        assert p._on_seek_cb == r.stop_audio_clips
        win._project_path = "/proj/Chanson/Chanson.gvp"
        assert r.audio_resolver("Audios/a.wav") == "/proj/Chanson/Audios/a.wav"
    finally:
        if win is not None:
            win._router.wait_loaded()
            win._close_midi_devices()
            win._audio_driver.close()
            win.Destroy()
