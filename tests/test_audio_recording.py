#python3
"""
    File: tests/test_audio_recording.py
    Enregistrement d'une prise audio simple (Phase 8 étape 14f1, docs/DESIGN.md
    § Phase 8 étape 14f1 — point préalable, R3, R4, § 14a A4, A7, A12) :
    datation (capture_time) et placement (place_take, bars_for) ;
    AudioRecorder sur un flux factice (WAV 24 bits, datation du premier bloc,
    erreurs) ; latence de sortie du pilote, compensation des Préférences,
    projet sans nom, canaux de l'entrée ; Pattern.set_bar_count et noms de
    piste ; lecteur (armement, ancre, fin de prise, allongement du pattern,
    fin de boucle) ; AudioRecMixin (projet sans nom, entrée de la piste, prise
    posée, prise vide, Undo) ; libellé d'une piste audio ; vraie fenêtre
    principale (R, Espace, Ctrl+Z).
    Prototype Python, cible C/C++ : les tests fixent le comportement
    observable (positions, échantillons, fichiers).
    Date: Mon, 16/11/2026
    Author: Coolbrother
"""
import sys
import os
import json
import time
import threading
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest
import soundfile as sf
import wx

from pattern import Pattern, TapeEvent, ETYPE_AUDIO, ETYPE_GRID, TRACK_AUDIO
from app_config import AppConfig
from audio import audio_recorder as ar
from audio import audio_takes as at
from audio.sound_device_driver import SoundDeviceDriver
from devices import audio_device
from player.drum_player import DrumPlayer
from ui.mw_audio_rec import AudioRecMixin
from ui.mw_tracks import TrackMixin

SR = 44100


# ---------------------------------------------------------------------------
# Datation et placement
# ---------------------------------------------------------------------------

def test_capture_time_from_the_card_times():
    # bloc capté 0,02 s avant l'heure du flux : 0,02 s avant maintenant
    assert ar.capture_time(10.0, 500.02, 500.0, 512, SR) == pytest.approx(9.98)


@pytest.mark.parametrize("stream_time, adc_time", [(0.0, 0.0), (5.0, 0.0), (0.0, 5.0), (4.0, 5.0)])
def test_capture_time_without_usable_card_times(stream_time, adc_time):
    # durée du bloc + latence d'entrée annoncée
    t = ar.capture_time(10.0, stream_time, adc_time, 441, SR, in_latency=0.05)
    assert t == pytest.approx(10.0 - 0.01 - 0.05)


def _clock(step_secs=0.125):
    return (lambda st: st * step_secs), (lambda s: s / step_secs)


def test_place_take_skips_what_precedes_the_start():
    secs, steps = _clock()
    # captée 0,1 s avant le début effectif : 4410 échantillons sautés
    assert ar.place_take(9.9, 2 * SR, SR, 10.0, 10.0, 0, secs, steps) == \
        (0.0, 4410, 2 * SR - 4410, pytest.approx(15.2))


def test_place_take_after_the_start():
    secs, steps = _clock()
    step, start, length, end = ar.place_take(10.5, SR, SR, 10.0, 10.0, 0, secs, steps)
    assert (step, start, length, end) == (pytest.approx(4.0), 0, SR, pytest.approx(12.0))


def test_place_take_relative_to_the_window_start():
    secs, steps = _clock()
    # fenêtre qui commence au pas 16 (mesure 2), ancrée à 20 s
    step, *_ = ar.place_take(20.25, SR, SR, 20.0, 20.0, 16, secs, steps)
    assert step == pytest.approx(18.0)


def test_place_take_stops_at_the_end_of_the_loop_window():
    secs, steps = _clock()
    step, start, length, end = ar.place_take(10.5, 4 * SR, SR, 10.0, 10.0, 0, secs, steps,
                                             window_end=12.0)
    assert (start, length, end) == (0, int(1.5 * SR), pytest.approx(16.0))


@pytest.mark.parametrize("heard_at, frames, window_end", [
    (9.0, SR // 2, None),          # tout avant le début effectif
    (10.0, 0, None),               # rien de capté
    (12.5, SR, 12.0),              # captée après la fin de la boucle
])
def test_place_take_nothing_left(heard_at, frames, window_end):
    secs, steps = _clock()
    assert ar.place_take(heard_at, frames, SR, 10.0, 10.0, 0, secs, steps, window_end) is None


def test_place_take_follows_the_tempo_map():
    p = Pattern()
    p._bpm = 120
    p._tempo_changes = [(16, 60.0)]                 # mesure 2 deux fois plus lente
    tm = p.tempo_map()
    # 2 s après le début : la mesure 1 dure 2 s → pas 16 ; 3 s → 16 + 1 s à 60 BPM = 20
    step, _, length, end = ar.place_take(12.0, SR, SR, 10.0, 10.0, 0, tm.secs, tm.steps)
    assert step == pytest.approx(16.0) and end == pytest.approx(20.0)


@pytest.mark.parametrize("end_step, bars", [(0, 1), (16, 1), (16.01, 2), (31.9, 2), (48, 3)])
def test_bars_for(end_step, bars):
    assert ar.bars_for(end_step, 16) == bars


# ---------------------------------------------------------------------------
# AudioRecorder sur un flux factice
# ---------------------------------------------------------------------------

class FakeStream:
    """Flux d'entrée factice : start() livre les blocs donnés au callback
    (dans le fil appelant), avec des heures de carte."""
    instances = []

    def __init__(self, callback, samplerate, channels, device=None, dtype=None,
                 blocks=(), times=(100.02, 100.0), status=None, latency=0.01):
        self.callback, self.samplerate, self.channels = callback, samplerate, channels
        self.device, self.dtype = device, dtype
        self.blocks, self.times, self.status, self.latency = blocks, times, status, latency
        self.calls = []
        FakeStream.instances.append(self)

    def start(self):
        self.calls.append("start")
        for i, block in enumerate(self.blocks):
            cur, adc = self.times
            self.callback(block, len(block),
                          SimpleNamespace(currentTime=cur + i, inputBufferAdcTime=adc + i),
                          self.status if i == 0 else None)

    def stop(self):
        self.calls.append("stop")

    def close(self):
        self.calls.append("close")


def _recorder(**stream_kw):
    FakeStream.instances.clear()
    return ar.AudioRecorder(stream_factory=lambda **kw: FakeStream(**kw, **stream_kw),
                            clock=lambda: 50.0)


def test_recorder_writes_a_24_bit_wav(tmp_path):
    blocks = [np.full((512, 2), 0.25, np.float32), np.full((256, 2), -0.5, np.float32)]
    rec = _recorder(blocks=blocks)
    path = str(tmp_path / "take.wav")
    rec.start(path, device=3, samplerate=SR, channels=2)
    assert rec.active
    res = rec.stop()
    assert not rec.active
    info = sf.info(path)
    assert (info.subtype, info.channels, info.samplerate) == ("PCM_24", 2, SR)
    data, _ = sf.read(path, dtype="float32")
    assert len(data) == res.frames == 768
    assert data[0, 0] == pytest.approx(0.25, abs=1e-6)
    assert data[-1, 1] == pytest.approx(-0.5, abs=1e-6)
    assert (res.path, res.samplerate, res.channels) == (path, SR, 2)
    stream = FakeStream.instances[0]
    assert (stream.device, stream.samplerate, stream.channels, stream.dtype) == (3, SR, 2, "float32")
    assert stream.calls == ["start", "stop", "close"]


def test_recorder_dates_the_first_block_only(tmp_path):
    blocks = [np.zeros((512, 1), np.float32)] * 3
    rec = _recorder(blocks=blocks)
    rec.start(str(tmp_path / "t.wav"), samplerate=SR, channels=1)
    # horloge du lecteur 50 s, bloc capté 0,02 s avant l'heure du flux
    assert rec.stop().t0 == pytest.approx(49.98)


def test_recorder_without_card_times_uses_the_input_latency(tmp_path):
    rec = _recorder(blocks=[np.zeros((441, 1), np.float32)], times=(0.0, 0.0), latency=0.03)
    rec.start(str(tmp_path / "t.wav"), samplerate=SR, channels=1)
    assert rec.stop().t0 == pytest.approx(50.0 - 0.01 - 0.03)


def test_recorder_nothing_captured(tmp_path):
    rec = _recorder()
    rec.start(str(tmp_path / "t.wav"), samplerate=SR, channels=1)
    res = rec.stop()
    assert res.frames == 0 and res.t0 is None


def test_recorder_keeps_the_stream_anomalies(tmp_path):
    rec = _recorder(blocks=[np.zeros((64, 1), np.float32)], status="input overflow")
    rec.start(str(tmp_path / "t.wav"), samplerate=SR, channels=1)
    rec.stop()
    assert rec.errors == ["input overflow"]


def test_recorder_start_failure_leaves_nothing_open(tmp_path):
    def refuse(**kw):
        raise RuntimeError("périphérique occupé")
    rec = ar.AudioRecorder(stream_factory=refuse)
    path = str(tmp_path / "t.wav")
    with pytest.raises(RuntimeError):
        rec.start(path, samplerate=SR, channels=1)
    assert not rec.active and rec._thread is None and rec._file is None
    sf.info(path)                                   # fichier fermé, lisible


def test_recorder_stream_lost_during_the_take(tmp_path):
    rec = _recorder(blocks=[np.zeros((64, 1), np.float32)])
    rec.start(str(tmp_path / "t.wav"), samplerate=SR, channels=1)
    def lost():
        raise RuntimeError("carte débranchée")
    FakeStream.instances[0].stop = lost
    assert rec.stop().frames == 64
    assert rec.errors == ["carte débranchée"]


def test_recorder_writes_in_its_own_thread(tmp_path):
    """Le callback ne fait que copier : l'écriture se fait dans un autre fil."""
    threads = []
    rec = _recorder(blocks=[np.zeros((64, 1), np.float32)])
    write = rec._write_loop
    def spy():
        threads.append(threading.current_thread())
        write()
    rec._write_loop = spy
    rec.start(str(tmp_path / "t.wav"), samplerate=SR, channels=1)
    rec.stop()
    assert threads and threads[0] is not threading.current_thread()


# ---------------------------------------------------------------------------
# Pilote, Préférences, projet sans nom, canaux de l'entrée
# ---------------------------------------------------------------------------

def _driver(stream):
    d = SoundDeviceDriver.__new__(SoundDeviceDriver)
    d._stream = stream
    return d


def test_driver_output_latency():
    assert _driver(SimpleNamespace(latency=0.046)).output_latency == pytest.approx(0.046)
    assert _driver(None).output_latency == 0.0
    assert _driver(SimpleNamespace()).output_latency == 0.0


def _cfg(tmp_path, data):
    os.makedirs(tmp_path / "data", exist_ok=True)
    (tmp_path / "data" / "config.json").write_text(json.dumps(data), encoding="utf-8")
    return AppConfig(str(tmp_path))


@pytest.mark.parametrize("value, expected", [
    (None, 0), (35, 35), (-20, -20), (5000, 1000), (-5000, -1000), ("x", 0), (True, 0)])
def test_audio_latency_ms(tmp_path, isolated_preferences, value, expected):
    data = {} if value is None else {"audio_latency_ms": value}
    assert _cfg(tmp_path, data).audio_latency_ms == expected


@pytest.mark.parametrize("name, unnamed", [
    ("/p/noname_001.gvp", True), ("/p/noname_042.gvp", True),
    ("/p/Chanson.gvp", False), ("/p/noname_1.gvp", False), ("/p/noname_001_bis.gvp", False),
    ("/p/Chanson/Chanson.gvp", False)])
def test_project_is_unnamed(name, unnamed):
    assert at.is_unnamed(name) is unnamed


@pytest.mark.parametrize("max_in, channels", [(1, 1), (2, 2), (8, 2), (0, 1)])
def test_input_channels(monkeypatch, max_in, channels):
    monkeypatch.setattr(audio_device.sd, "query_devices",
                        lambda *a, **k: {"max_input_channels": max_in})
    assert audio_device.input_channels(4) == channels
    assert audio_device.input_channels(None) == channels


def test_input_channels_unknown_device(monkeypatch):
    def refuse(*a, **k):
        raise ValueError("pas de périphérique")
    monkeypatch.setattr(audio_device.sd, "query_devices", refuse)
    assert audio_device.input_channels(99) == 1


# ---------------------------------------------------------------------------
# Pattern : nombre de mesures, noms de piste
# ---------------------------------------------------------------------------

def test_set_bar_count_keeps_the_events_and_their_ids():
    p = Pattern()
    clip = TapeEvent(ETYPE_AUDIO, payload={"file": "a.wav", "gain": 1.0}, time=3.5)
    p._tape[1].append(clip)
    assert p.set_bar_count(p._num_bars + 1) == 2
    assert p._tape[1][0] is clip                     # même événement : pas relancé
    assert p.set_bar_count(0) == 1
    assert p.set_bar_count(10 ** 6) == Pattern.MAX_BARS


def test_track_names_saved_and_loaded():
    p = Pattern()
    assert p._track_names == [""] * p._num_tracks
    p._track_names = ["Voix"] + [""] * (p._num_tracks - 1)
    q = Pattern()
    q.from_dict(json.loads(json.dumps(p.to_dict())))
    assert q._track_names[0] == "Voix" and len(q._track_names) == q._num_tracks


def test_track_names_absent_from_old_projects():
    p = Pattern()
    d = p.to_dict()
    del d["track_names"]
    q = Pattern()
    q.from_dict(d)
    assert q._track_names == [""] * q._num_tracks


def test_track_names_copied_in_to_dict():
    """L'état gardé par l'Undo (to_dict) ne change pas avec la liste."""
    p = Pattern()
    d = p.to_dict()
    p._track_names[0] = "Voix"
    assert d["track_names"][0] == ""


# ---------------------------------------------------------------------------
# Lecteur : armement, ancre, fin de prise, allongement
# ---------------------------------------------------------------------------

class _S:
    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def player():
    p = DrumPlayer(_S())
    p.start_thread = p.stop_thread = lambda: None
    p._pattern._looping = False                      # boucle active par défaut
    p.takes = []
    p._on_audio_take_end_cb = p.takes.append
    return p


def test_arm_while_playing_anchors_now(player):
    player.playing = True
    player._measure_start = 7.0
    player._cur_lp_start = 0
    player.arm_audio_take()
    take = player._audio_take
    m, lp, t_start, window_end = take["anchor"]
    assert (m, lp, window_end) == (7.0, 0, None)
    assert t_start == take["t_arm"]
    assert take["bars"] == player._pattern._num_bars


def test_arm_while_stopped_waits_for_the_playback(player):
    player.arm_audio_take()
    assert player._audio_take["anchor"] is None


def test_anchor_set_once(player):
    player.arm_audio_take()
    player._set_audio_anchor(1.0, 0, 1.0)
    player._set_audio_anchor(5.0, 0, 5.0)
    assert player._audio_take["anchor"][0] == 1.0


def test_anchor_without_take_is_ignored(player):
    player._set_audio_anchor(1.0, 0, 1.0)
    assert player._audio_take is None


def test_loop_over_the_whole_pattern_ends_the_take_at_its_end(player):
    """Boucle sans points de boucle (essai de 14f1 : _cur_loop_steps vaut 0)."""
    pat = player._pattern
    pat._looping, pat._loop_start, pat._loop_end = True, None, None
    pat.set_bar_count(2)
    player.set_bpm(120)
    player._cur_loop_steps = 0
    player.arm_audio_take()
    player._set_audio_anchor(10.0, 0, 10.0)
    assert player._audio_take["anchor"][3] == pytest.approx(10.0 + 4.0)    # 2 mesures à 120


def test_loop_points_end_the_take_at_the_loop_end(player):
    pat = player._pattern
    pat._looping = True
    player.set_bpm(120)
    player._cur_loop_steps = 8                       # deux temps
    player.arm_audio_take()
    player._set_audio_anchor(10.0, 4, 10.0)
    assert player._audio_take["anchor"][3] == pytest.approx(11.0)


def test_count_in_resets_the_anchor(player):
    player.playing = True
    player._measure_start = 7.0
    player.arm_audio_take()
    assert player._audio_take["anchor"] is not None
    player.record_pattern_with_count_in(1)
    assert player._audio_take["anchor"] is None      # pris après le décompte


@pytest.mark.parametrize("stop", ["stop_record", "stop_pattern", "pause_pattern", "stop_all"])
def test_every_stop_ends_the_take_once(player, stop):
    player.playing = player.recording = True
    player._measure_start = time.perf_counter()
    player.sound_man = _S()
    player.arm_audio_take()
    take = player._audio_take
    getattr(player, stop)()
    assert player.takes == [take] and player._audio_take is None
    getattr(player, stop)()
    assert player.takes == [take]                    # une seule fois


def test_stop_without_take_calls_nothing(player):
    player.recording = True
    player.stop_record()
    assert player.takes == []


def test_extend_for_the_take(player):
    bars = []
    player._on_bars_changed_cb = lambda: bars.append(player._pattern._num_bars)
    clip = TapeEvent(ETYPE_AUDIO, payload={"file": "a.wav"}, time=0)
    player._pattern._tape[0].append(clip)
    player.recording = True
    player.arm_audio_take()
    n = player._pattern._num_bars
    assert player._extend_for_audio_take() is True
    assert player._pattern._num_bars == n + 1 and bars == [n + 1]
    assert player._pattern._tape[0][0] is clip


@pytest.mark.parametrize("case", ["no_take", "not_recording", "looping", "max_bars"])
def test_no_extension(player, case):
    player.recording = case != "not_recording"
    if case != "no_take":
        player.arm_audio_take()
    if case == "looping":
        player._pattern._looping = True
    if case == "max_bars":
        player._pattern.set_bar_count(Pattern.MAX_BARS)
    n = player._pattern._num_bars
    assert player._extend_for_audio_take() is False
    assert player._pattern._num_bars == n


def _measure_end(player):
    secs = player._pattern._num_bars * 4 * 60.0 / player.bpm
    start = time.perf_counter() - secs - 0.01        # fin de fenêtre déjà passée : pas d'attente
    return start, player._on_measure_end(start, secs, 0)


def test_measure_end_extends_the_pattern_and_keeps_playing(player):
    player.playing = player.recording = True
    player._pattern._looping = False
    player.arm_audio_take()
    n = player._pattern._num_bars
    start, returned = _measure_end(player)
    assert player._pattern._num_bars == n + 1
    assert player.playing and returned == start      # la fenêtre garde son début


def test_measure_end_without_take_pauses_as_before(player):
    player.playing = True
    player._pattern._looping = False
    player._play_stopped = lambda: None
    n = player._pattern._num_bars
    _measure_end(player)
    assert player._pattern._num_bars == n and not player.playing


def test_thread_anchors_the_take_when_playback_starts():
    """Vrai fil de lecture : la prise armée à l'arrêt est ancrée au premier
    tour de lecture enregistrée."""
    p = DrumPlayer(_S())
    p._pattern._looping = False
    p.set_bpm(240)
    p.arm_audio_take()
    p.recording = True
    p.play_pattern()
    try:
        deadline = time.time() + 2.0
        while p._audio_take["anchor"] is None and time.time() < deadline:
            time.sleep(0.01)
        m, lp, t_start, window_end = p._audio_take["anchor"]
        assert lp == 0 and window_end is None and t_start >= p._audio_take["t_arm"]
        assert m == pytest.approx(p._measure_start, abs=1.0)
    finally:
        p.stop_all()


# ---------------------------------------------------------------------------
# AudioRecMixin sur une fenêtre factice
# ---------------------------------------------------------------------------

class FakeRecorder:
    """Enregistreur factice : stop() rend la prise donnée."""
    def __init__(self, frames=2 * SR, t0=100.0, fail=None, errors=()):
        self.frames, self.t0, self.fail, self.errors = frames, t0, fail, list(errors)
        self.started = None

    def start(self, path, device=None, samplerate=SR, channels=1):
        open(path, "wb").close()
        if self.fail:
            raise self.fail
        self.started = (path, device, samplerate, channels)

    def stop(self):
        return ar.TakeResult(self.started[0] if self.started else "", self.frames,
                             self.t0, SR, self.started[3] if self.started else 1)


class RecWin(AudioRecMixin):
    def __init__(self, tmp_path, project="Chanson.gvp", inputs=(), latency_ms=0,
                 out_latency=0.0, recorder=None):
        self.statuses, self.beeps, self.saved_as = [], 0, []
        self._project_path = str(tmp_path / project)
        self._audio_dir = ""
        self._cur_pattern_idx = 0
        self._cfg = SimpleNamespace(audio_hostapi="ALSA", audio_inputs=list(inputs),
                                    audio_latency_ms=latency_ms)
        self._audio_driver = SimpleNamespace(samplerate=SR, output_latency=out_latency)
        self._router = SimpleNamespace(_track_kinds=["midi"] * 16, _track_audio_ins=[""] * 16)
        self._router._track_kinds[2] = TRACK_AUDIO
        p = DrumPlayer(_S())
        p.start_thread = p.stop_thread = lambda: None
        p._cur_track = 2
        p._pattern._looping = False
        p._pattern.set_bar_count(4)                  # 8 s
        p.set_bpm(120)                               # un pas = 0,125 s
        self._player = p
        self.recorder = recorder or FakeRecorder()
        self._audio_recorder_factory = lambda: self.recorder
        self.save_as_result = True
        self._init_audio_rec()

    def _show_status(self, msg):     self.statuses.append(msg)
    def _alert_beep(self):           self.beeps += 1
    def _update_title(self):         pass
    def _refresh_track_list(self):   pass

    def _save_project_as(self):
        self.saved_as.append(self._project_path)
        if self.save_as_result:
            self._project_path = os.path.join(os.path.dirname(self._project_path), "Nommé.gvp")
        return self.save_as_result


@pytest.fixture
def devices(monkeypatch):
    """Périphériques d'entrée : micro (1), carte (2) ; défaut « Défaut système »."""
    found = {"micro": 1, "carte": 2}
    monkeypatch.setattr(audio_device, "find_device", lambda name, api, kind: found.get(name))
    monkeypatch.setattr(audio_device, "default_device", lambda api, kind: "Défaut système")
    monkeypatch.setattr(audio_device, "input_channels", lambda idx: 2 if idx == 2 else 1)
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))


def test_audio_track_detection(tmp_path, devices):
    win = RecWin(tmp_path)
    assert win._cur_track_is_audio()
    win._player._cur_track = 0
    assert not win._cur_track_is_audio()


def test_prepare_opens_the_take_and_arms_the_player(tmp_path, devices):
    win = RecWin(tmp_path)
    win._router._track_audio_ins[2] = "carte"
    assert win._audio_rec_prepare() is True
    path, device, sr, channels = win.recorder.started
    assert path == str(tmp_path / "Audios" / "Chanson_pattern01_piste03_take_001.wav")
    assert (device, sr, channels) == (2, SR, 2)                # stéréo selon l'entrée (A7)
    assert win._audio_rec[:2] == (2, "Audios/Chanson_pattern01_piste03_take_001.wav")
    assert win._player._audio_take is not None
    assert win._audio_rec_note == "Prise audio piste 3 — carte"
    assert win._audio_rec_prepare() is True                    # déjà ouverte : rien de plus


@pytest.mark.parametrize("track_in, inputs, device, name, note", [
    ("carte", ["micro"], 2, "carte", ""),                      # entrée de la piste
    ("", ["micro", "carte"], 1, "micro", ""),                  # première cochée (R4)
    ("", [], None, "Défaut système", ""),                      # défaut du système
    ("absente", [], None, "Défaut système",
     "entrée « absente » introuvable, Défaut système à la place"),
])
def test_input_of_the_track(tmp_path, devices, track_in, inputs, device, name, note):
    win = RecWin(tmp_path, inputs=inputs)
    win._router._track_audio_ins[2] = track_in
    assert win._audio_input_for(2) == (device, name, note)
    win._audio_rec_prepare()
    assert win._audio_rec_note.endswith(name + (f" ({note})" if note else ""))


def test_unnamed_project_asks_a_name_first(tmp_path, devices):
    win = RecWin(tmp_path, project="noname_003.gvp")
    assert win._audio_rec_prepare() is True
    assert win.saved_as == [str(tmp_path / "noname_003.gvp")]
    assert os.path.basename(win.recorder.started[0]).startswith("Nommé_pattern01_piste03")


def test_unnamed_project_cancelled_means_no_take(tmp_path, devices):
    win = RecWin(tmp_path, project="noname_003.gvp")
    win.save_as_result = False
    assert win._audio_rec_prepare() is False
    assert win.recorder.started is None and win._audio_rec is None
    assert win._player._audio_take is None
    assert win.statuses[-1] == "Prise audio annulée : projet sans nom"


def test_refused_input_beeps_and_removes_the_file(tmp_path, devices):
    win = RecWin(tmp_path, recorder=FakeRecorder(fail=RuntimeError("occupé")))
    assert win._audio_rec_prepare() is False
    assert win.beeps == 1 and "ERREUR prise audio" in win.statuses[-1]
    assert win._audio_rec is None and win._player._audio_take is None
    assert os.listdir(tmp_path / "Audios") == []


def _record(win, anchor=(99.0, 0, 100.0, None)):
    """Prise ouverte, ancrée, puis arrêtée par le lecteur."""
    win._audio_rec_prepare()
    win._player._audio_take["anchor"] = anchor
    win._player.recording = True
    win._player.stop_record()


def test_finished_take_becomes_a_clip(tmp_path, devices):
    win = RecWin(tmp_path, recorder=FakeRecorder(frames=2 * SR, t0=100.0))
    _record(win)                                     # ancre : pas 0 à 99 s, début à 100 s
    (t, clip), = win._player._pattern.audio_clips()
    assert t == 2 and clip.time == pytest.approx(8.0)            # 1 s après le pas 0
    assert clip.payload == {"file": "Audios/Chanson_pattern01_piste03_take_001.wav",
                            "gain": 1.0, "length": 2 * SR}
    assert win._audio_rec is None
    assert win.statuses[-1] == ("Prise audio piste 3 : Chanson_pattern01_piste03_take_001.wav, "
                                "2.0 s, mesure 1")


def test_latency_compensation(tmp_path, devices):
    # capture à 100 s, entendu 0,05 + 0,05 s plus tôt
    win = RecWin(tmp_path, out_latency=0.05, latency_ms=50,
                 recorder=FakeRecorder(frames=SR, t0=100.0))
    _record(win, anchor=(99.0, 0, 99.0, None))
    (_, clip), = win._player._pattern.audio_clips()
    assert clip.time == pytest.approx(0.9 / 0.125)


def test_preroll_skipped_by_start(tmp_path, devices):
    win = RecWin(tmp_path, recorder=FakeRecorder(frames=SR, t0=99.5))
    _record(win, anchor=(100.0, 0, 100.0, None))     # captée 0,5 s avant le début
    (_, clip), = win._player._pattern.audio_clips()
    assert clip.time == pytest.approx(0.0)
    assert clip.payload["start"] == SR // 2 and clip.payload["length"] == SR // 2


def test_take_longer_than_the_pattern_keeps_the_needed_bars(tmp_path, devices):
    win = RecWin(tmp_path, recorder=FakeRecorder(frames=5 * SR, t0=100.0))
    win._player._pattern.set_bar_count(1)            # 2 s à 120 BPM
    _record(win, anchor=(100.0, 0, 100.0, None))
    assert win._player._pattern._num_bars == 3       # 5 s → 3 mesures
    assert win.statuses[-1].endswith("pattern : 3 mesures")


def test_pattern_brought_back_to_the_needed_bars(tmp_path, devices):
    """Allongé pendant la prise, ramené aux mesures nécessaires au Stop."""
    win = RecWin(tmp_path, recorder=FakeRecorder(frames=SR, t0=100.0))
    win._player._pattern.set_bar_count(2)
    win._audio_rec_prepare()
    win._player._pattern.set_bar_count(5)            # mesures ajoutées en lecture
    win._player._audio_take["anchor"] = (100.0, 0, 100.0, None)
    win._player.stop_record()
    assert win._player._pattern._num_bars == 2


@pytest.mark.parametrize("anchor, frames, t0", [
    (None, SR, 100.0),                               # arrêtée pendant le décompte
    ((100.0, 0, 100.0, None), 0, None),              # rien de capté
    ((100.0, 0, 100.0, None), SR, 90.0),             # tout avant le début
])
def test_empty_take_leaves_nothing(tmp_path, devices, anchor, frames, t0):
    win = RecWin(tmp_path, recorder=FakeRecorder(frames=frames, t0=t0))
    win._player._pattern.set_bar_count(2)
    win._audio_rec_prepare()
    win._player._pattern.set_bar_count(4)
    win._player._audio_take["anchor"] = anchor
    win._player.stop_record()
    assert win._player._pattern.audio_clips() == []
    assert win._player._pattern._num_bars == 2
    assert os.listdir(tmp_path / "Audios") == []
    assert win.statuses[-1] == "Prise audio vide : rien d'enregistré"


def test_stream_anomalies_announced(tmp_path, devices):
    win = RecWin(tmp_path, recorder=FakeRecorder(errors=["overflow", "overflow"]))
    _record(win)
    assert win.statuses[-1].endswith("2 anomalie(s) du flux d'entrée")


def test_take_end_from_another_thread_goes_through_call_after(tmp_path, monkeypatch):
    win = RecWin(tmp_path)
    later = []
    monkeypatch.setattr(wx, "IsMainThread", lambda: False)
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a: later.append((fn, a)))
    win._on_audio_take_end({"anchor": None})
    assert later and later[0][0] == win._on_audio_take_end


def test_finish_without_open_take_does_nothing(tmp_path):
    win = RecWin(tmp_path)
    assert win._finish_audio_take({"anchor": None}) is None


# ---------------------------------------------------------------------------
# Libellé d'une piste audio et noms de piste
# ---------------------------------------------------------------------------

def _label_win(kinds, names=None, pad_name="HH Closed"):
    vm = SimpleNamespace(get_name=lambda i: pad_name)
    p = Pattern()
    if names:
        p._track_names = list(names) + [""] * (16 - len(names))
    win = SimpleNamespace(
        _router=SimpleNamespace(_track_kinds=kinds, slot_for_track=lambda i: 0,
                                bank_preset_name=lambda i: "", slot_name=lambda i: "TR-707",
                                rack_mode=False, _track_mutes=[False] * 16,
                                _track_solos=[False] * 16),
        _rack=SimpleNamespace(get_slot=lambda i: SimpleNamespace(type=None)),
        _track_editor=SimpleNamespace(is_selected=lambda i: False),
        _player=SimpleNamespace(voice_manager=vm, _cur_track=0, recording=False),
        _pattern_list=[p], _cur_pattern_idx=0)
    win._track_name = lambda i: TrackMixin._track_name(win, i)
    return win


def test_audio_track_label_has_its_rank_and_no_pad_name():
    kinds = ["midi"] * 16
    kinds[4] = kinds[7] = TRACK_AUDIO
    win = _label_win(kinds)
    assert TrackMixin._track_label(win, 4) == "  Track_05 - Audio 1"
    assert TrackMixin._track_label(win, 7) == "  Track_08 - Audio 2"
    assert TrackMixin._track_label(win, 0) == "  Track_01 (HH Closed) - Slot_01 - TR-707"


def test_track_name_shown_on_audio_and_midi_tracks():
    kinds = ["midi"] * 16
    kinds[1] = TRACK_AUDIO
    win = _label_win(kinds, names=["Basse", "Voix"])
    assert TrackMixin._track_label(win, 1) == "  Track_02 (Voix) - Audio 1"
    assert TrackMixin._track_label(win, 0) == "  Track_01 (Basse) - Slot_01 - TR-707"


# ---------------------------------------------------------------------------
# Vraie fenêtre principale
# ---------------------------------------------------------------------------

class LiveStream:
    """Flux d'entrée factice qui livre des blocs en temps réel."""
    def __init__(self, callback, samplerate, channels, **kw):
        self.cb, self.sr, self.ch, self.latency = callback, samplerate, channels, 0.0
        self.run = False

    def start(self):
        self.run = True
        def go():
            while self.run:
                now = time.perf_counter()
                self.cb(np.full((512, self.ch), 0.3, np.float32), 512,
                        SimpleNamespace(currentTime=now, inputBufferAdcTime=now - 512 / self.sr),
                        None)
                time.sleep(512 / self.sr)
        self.thread = threading.Thread(target=go, daemon=True)
        self.thread.start()

    def stop(self):
        self.run = False
        self.thread.join()

    def close(self):
        pass


class _Key:
    def __init__(self, key, ukey=0, ctrl=False, shift=False):
        self.k, self.u, self.c, self.s = key, ukey, ctrl, shift
    def GetKeyCode(self):    return self.k
    def GetUnicodeKey(self): return self.u
    def ControlDown(self):   return self.c
    def ShiftDown(self):     return self.s
    def AltDown(self):       return False
    def Skip(self):          pass


_APP = None


def test_real_main_window_records_a_take(isolated_preferences, monkeypatch, tmp_path):
    """Une seule vraie MainWindow (clients ALSA) : R, prise posée, Ctrl+Z ;
    R puis Espace ; noms de piste par F2 et Undo."""
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)
    from ui.main_window import MainWindow
    from ui import mw_tracks
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    win = None
    try:
        win = MainWindow(no_fluidsynth=True, no_sfizz=True)
        win._router.wait_loaded()
        p = win._player
        assert p._on_audio_take_end_cb == win._on_audio_take_end
        win._audio_recorder_factory = lambda: ar.AudioRecorder(
            stream_factory=lambda **kw: LiveStream(**kw))
        win._project_path = str(tmp_path / "Chanson.gvp")
        win._audio_dir = ""
        win._router._track_kinds[3] = TRACK_AUDIO
        p._cur_track = 3
        pat = p._pattern
        pat._looping = False
        p.set_bpm(240)
        pat.set_bar_count(1)                         # 1 s
        km = win._key_manager

        def press(key, ukey=0, **kw):
            km.handle(_Key(key, ukey, **kw))
            win._take_end_if_idle()

        # R … R : prise posée, pattern allongé au-delà d'une mesure
        press(ord('R'))
        assert p.recording and win._audio_rec is not None
        time.sleep(1.5)
        press(ord('R'))
        assert not p.recording and win._audio_rec is None
        (t, clip), = pat.audio_clips()
        assert t == 3 and clip.payload["file"] == "Audios/Chanson_pattern01_piste04_take_001.wav"
        assert pat._num_bars == 2
        assert os.path.exists(tmp_path / "Audios" / "Chanson_pattern01_piste04_take_001.wav")
        assert win._track_list.GetString(3).endswith("- Audio 1")

        # Ctrl+Z : plus de clip, une mesure ; le fichier reste
        win._undo_action()
        assert win._player._pattern.audio_clips() == []
        assert win._player._pattern._num_bars == 1
        assert os.path.exists(tmp_path / "Audios" / "Chanson_pattern01_piste04_take_001.wav")

        # R puis Espace : enregistrement, lecture et métronome arrêtés, prise gardée
        p.stop_all()
        press(ord('R'))
        time.sleep(0.4)
        press(wx.WXK_SPACE, ord(' '))
        assert not p.recording and not p.playing and not p.clicking
        assert len(win._player._pattern.audio_clips()) == 1

        # F2 sur la piste audio, Undo, Redo
        class Dlg:
            def __init__(self, *a): pass
            def ShowModal(self): return wx.ID_OK
            def GetValue(self):  return "Voix"
            def Destroy(self):   pass
        monkeypatch.setattr(mw_tracks.wx, "TextEntryDialog", Dlg)
        win._rename_track()
        assert win._track_list.GetString(3).strip() == "Track_04 (Voix) - Audio 1"
        win._undo_action()
        assert win._track_list.GetString(3).strip() == "Track_04 - Audio 1"
        win._redo_action()
        assert win._track_list.GetString(3).strip() == "Track_04 (Voix) - Audio 1"
    finally:
        if win is not None:
            win._player.stop_all()
            win._router.wait_loaded()
            win._close_midi_devices()
            win._audio_driver.close()
            win.Destroy()
