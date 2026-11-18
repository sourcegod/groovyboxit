#python3
"""
    File: tests/test_audio_loop_recording.py
    Prises audio en boucle (Phase 8 étape 14g2, docs/DESIGN.md § Phase 8
    étape 14g2, § 14f1 R1, R2, R5) : passages (pass_window, loop_passes) et
    découpe de Remplacer (carve) ; prise gardée en mémoire et passage rempli
    au fil des blocs (live_range) ; passages joués depuis la mémoire
    (pin_clip / unpin_clips, clip_file_info) ; rappels du lecteur (ancre,
    0,3 s avant chaque retour) ; AudioRecMixin : Overdub et Remplacer
    pendant la prise et au Stop, Stop juste après la pose d'un passage,
    piste muette dès le premier passage, nom demandé seulement à un projet
    jamais enregistré ; vraie fenêtre principale.
    Prototype Python, cible C/C++ : comportement observable (échantillons,
    positions, clips).
    Date: Mon, 16/11/2026
    Author: Coolbrother
"""
import sys
import os
import time
import threading
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest
import wx

from pattern import Pattern, TapeEvent, ETYPE_AUDIO, ETYPE_GRID, TRACK_AUDIO, clip_payload, \
    clip_window
from rack import Rack
from track_router import TrackRouter
from audio import audio_recorder as ar
from audio import audio_takes as at
from audio.sound_device_driver import Mixer
from player.drum_player import DrumPlayer
from ui.mw_audio_rec import AudioRecMixin

SR = 44100


# ---------------------------------------------------------------------------
# Passages
# ---------------------------------------------------------------------------

def test_first_pass_starts_at_the_effective_start():
    # entendu dès 9,9 s ; boucle de 2 s ancrée à 10 s, début effectif 10,5 s
    a, n, offset = ar.pass_window(0, 9.9, SR, 10.5, 10.0, 2.0)
    assert a == int(0.6 * SR) and n == int(1.5 * SR) and offset == pytest.approx(0.5)


def test_following_passes_start_at_the_loop_start():
    a, n, offset = ar.pass_window(2, 9.9, SR, 10.5, 10.0, 2.0)
    assert a == int(round(4.1 * SR)) and n == 2 * SR and offset == pytest.approx(0.0)


def test_loop_passes_follow_each_other_without_gap():
    passes = ar.loop_passes(9.95, int(6.5 * SR), SR, 10.0, 10.0, 2.0)
    assert [k for k, *_ in passes] == [0, 1, 2, 3]
    for (k, a, n, _), (_, a2, _, _) in zip(passes, passes[1:]):
        assert a + n == a2                           # ni trou ni chevauchement
    k, a, n, _ = passes[-1]
    assert a + n == int(6.5 * SR)                    # dernier borné à la prise


def test_loop_passes_of_an_empty_take():
    assert ar.loop_passes(10.0, 0, SR, 10.0, 10.0, 2.0) == []


@pytest.mark.parametrize("time, a, b, parts", [
    (0, 8, 16, [(0, 0, SR)]),                        # avant la plage
    (16, 0, 16, [(16, 0, SR)]),                      # après
    (0, 4, 16, [(0, 0, SR // 2)]),                   # fin coupée
    (0, 0, 4, [(4, SR // 2, SR // 2)]),              # début coupé
    (0, 2, 6, [(0, 0, SR // 4), (6, 3 * SR // 4, SR // 4)]),   # coupé en deux
    (0, 0, 8, []),                                   # entièrement couvert
    (0, 4, None, [(0, 0, SR // 2)]),                 # jusqu'à la fin
])
def test_carve(time, a, b, parts):
    # un pas = 0,125 s : le clip d'une seconde couvre 8 pas
    secs, steps = (lambda s: s * 0.125), (lambda t: t / 0.125)
    assert ar.carve(time, 0, SR, SR, a, b, secs, steps) == parts


def test_carve_drops_tiny_parts():
    secs, steps = (lambda s: s * 0.125), (lambda t: t / 0.125)
    tiny = ar.MIN_PART / SR / 0.125 / 2               # moitié de MIN_PART, en pas
    assert ar.carve(0, 0, SR, SR, tiny, None, secs, steps) == []
    assert ar.MIN_PART == 64


def test_carve_in_samples_of_the_file():
    secs, steps = (lambda s: s * 0.125), (lambda t: t / 0.125)
    # fichier à 22 050 Hz : la moitié d'une seconde = 11 025 échantillons
    assert ar.carve(0, 100, 22050, 22050, 4, None, secs, steps) == [(0, 100, 11025)]


# ---------------------------------------------------------------------------
# Prise gardée en mémoire
# ---------------------------------------------------------------------------

class ManualStream:
    """Flux d'entrée factice : les blocs sont poussés par le test."""
    def __init__(self, callback, samplerate, channels, **kw):
        self.callback, self.channels, self.latency = callback, channels, 0.0
        self.pos = 0

    def push(self, n, value=None):
        block = (np.arange(self.pos, self.pos + n, dtype=np.float32)[:, None] / 1e6
                 if value is None else np.full((n, 1), value, np.float32))
        block = np.repeat(block, self.channels, axis=1)
        self.callback(block, n, SimpleNamespace(currentTime=1.0, inputBufferAdcTime=1.0), None)
        self.pos += n

    def start(self): pass
    def stop(self):  pass
    def close(self): pass


@pytest.fixture
def live(tmp_path):
    holder = {}
    def factory(**kw):
        holder["s"] = ManualStream(**kw)
        return holder["s"]
    rec = ar.AudioRecorder(stream_factory=factory, clock=lambda: 50.0)
    rec.start(str(tmp_path / "t.wav"), samplerate=SR, channels=1)
    yield rec, holder["s"]
    if rec.active:
        rec.stop()


def test_live_range_of_captured_samples(live):
    rec, s = live
    s.push(1000)
    out = rec.live_range(200, 300)
    assert out.shape == (300, 2) and out.dtype == np.float32
    assert out[0, 0] == pytest.approx(200 / 1e6) and out[-1, 1] == pytest.approx(499 / 1e6)
    assert rec._taps == []                           # rien en attente


def test_live_range_filled_as_blocks_arrive(live):
    rec, s = live
    s.push(500)
    out = rec.live_range(300, 600)                   # 300…900 : 200 captés
    assert out[199, 0] == pytest.approx(499 / 1e6) and out[200, 0] == 0.0
    s.push(256)                                       # 500…756
    assert out[455, 0] == pytest.approx(755 / 1e6) and out[456, 0] == 0.0
    s.push(512)                                       # passage complet
    assert out[-1, 0] == pytest.approx(899 / 1e6)
    assert rec._taps == []


def test_live_range_entirely_in_the_future(live):
    rec, s = live
    s.push(100)
    out = rec.live_range(1000, 50)
    assert not out.any()
    s.push(2000)
    assert out[0, 0] == pytest.approx(1000 / 1e6) and out[-1, 0] == pytest.approx(1049 / 1e6)


def test_live_range_mono_to_stereo_and_empty(live):
    rec, s = live
    s.push(10, value=0.5)
    out = rec.live_range(0, 10)
    assert (out == 0.5).all()
    assert rec.live_range(0, 0).shape == (0, 2)


def test_recorder_exposes_t0_and_samplerate(live):
    rec, s = live
    assert rec.t0 is None and rec.samplerate == SR
    s.push(10)
    assert rec.t0 == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Routeur : passages joués depuis la mémoire
# ---------------------------------------------------------------------------

class _Snd:
    pad_notes, gm_note_map = [], {}

    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def router(tmp_path):
    mix = Mixer(SR)
    r = TrackRouter(Rack(), "/fake", _Snd(), lambda m: None, driver=mix,
                    schedule=lambda *a: None)
    r.audio_resolver = lambda rel: str(tmp_path / rel)
    r._track_kinds[1] = TRACK_AUDIO
    at.write_take(str(tmp_path / "f.wav"), np.full(SR, 0.25, np.float32), SR)
    return r


def test_pinned_pass_played_from_memory(router):
    data = np.full((SR // 2, 2), 0.7, np.float32)
    router.pin_clip("rec.wav", 1000, SR // 2, data)   # fichier pas encore fermé
    snd = router.clip_sound("rec.wav", 1000, SR // 2)
    assert np.shares_memory(snd.data, data)
    assert router.clip_duration_secs("rec.wav", 1000, SR // 2) == pytest.approx(0.5)
    v = router.on_audio_clip(1, "rec.wav", 1.0, clip_id=1, start=1000, length=SR // 2)
    assert v is not None and v.data[0, 0] == pytest.approx(0.7)


def test_pin_only_for_its_window(router):
    router.pin_clip("f.wav", 0, 100, np.zeros((100, 2), np.float32))
    assert len(router.clip_sound("f.wav", 0, 200).data) == 200     # autre fenêtre : fichier


def test_unpin_reads_the_file_again(router):
    router.pin_clip("f.wav", 0, 100, np.full((100, 2), 0.9, np.float32))
    router.pin_clip("g.wav", 0, 100, np.zeros((100, 2), np.float32))
    router.unpin_clips("f.wav")
    assert router.clip_sound("f.wav", 0, 100).data[0, 0] == pytest.approx(0.25, abs=1e-4)
    assert ("g.wav", 0, 100) in router._clip_pins


def test_clip_file_info(router):
    assert router.clip_file_info("f.wav") == (SR, SR)
    assert router.clip_file_info("absent.wav") is None


# ---------------------------------------------------------------------------
# Lecteur : rappels d'ancre et de retour de boucle
# ---------------------------------------------------------------------------

class _S:
    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def player():
    p = DrumPlayer(_S())
    p.start_thread = p.stop_thread = lambda: None
    return p


def test_anchor_callback(player):
    calls = []
    player._on_audio_anchor_cb = lambda: calls.append(1)
    player.arm_audio_take()
    player._set_audio_anchor(1.0, 0, 1.0)
    player._set_audio_anchor(2.0, 0, 2.0)
    assert calls == [1]


def _wrap_measure_end(player, looping=True, recording=True, count_in=0, anchor=True):
    """Fin de fenêtre dans 0,4 s : le rappel doit venir une fois, ≤ 0,3 s
    avant la fin."""
    calls = []
    player._on_audio_wrap_cb = lambda at: calls.append((at, at - time.perf_counter()))
    player._pattern._looping = looping
    player.recording = recording
    player.playing = True
    player._play_stopped = lambda: None
    player.arm_audio_take()
    now = time.perf_counter()
    if anchor:
        player._audio_take["anchor"] = (now - 1.6, 0, now - 1.6, now + 0.4 if looping else None)
    player._count_in = count_in
    secs = 2.0
    player._on_measure_end(now + 0.4 - secs, secs, 0)
    return calls, now + 0.4


@pytest.mark.audio
def test_wrap_callback_before_each_loop_end(player):
    calls, end = _wrap_measure_end(player)
    assert len(calls) == 1
    at, remaining = calls[0]
    assert at == pytest.approx(end)
    assert 0.0 <= remaining <= player.AUDIO_WRAP_LEAD + 0.02
    assert player.AUDIO_WRAP_LEAD == 0.3


@pytest.mark.audio
@pytest.mark.parametrize("case", ["no_loop", "not_recording", "no_anchor"])
def test_no_wrap_callback(player, case):
    calls, _ = _wrap_measure_end(player, looping=case != "no_loop",
                                 recording=case != "not_recording", anchor=case != "no_anchor")
    assert calls == []


# ---------------------------------------------------------------------------
# AudioRecMixin : Overdub et Remplacer
# ---------------------------------------------------------------------------

class FakeRecorder:
    samplerate = SR

    def __init__(self, frames, t0=100.0):
        self.frames, self.t0, self.errors = frames, t0, []
        self.started, self.ranges = None, []

    def start(self, path, device=None, samplerate=SR, channels=1):
        open(path, "wb").close()
        self.started = (path, device, samplerate, channels)

    def live_range(self, first, length):
        self.ranges.append((first, length))
        return np.zeros((length, 2), np.float32)

    def stop(self):
        return ar.TakeResult(self.started[0], self.frames, self.t0, SR, 1)


class FakeClipRouter:
    def __init__(self):
        self._track_kinds = ["midi"] * 16
        self._track_audio_ins = [""] * 16
        self.pins, self.unpinned, self.stopped = {}, [], []
        self.file_info = {"old.wav": (8 * SR, SR)}

    def pin_clip(self, rel, start, length, data): self.pins[(rel, start, length)] = data
    def unpin_clips(self, rel):                   self.unpinned.append(rel)
    def clip_file_info(self, rel):                return self.file_info.get(rel)
    def stop_audio_clips(self, track_idx=None):   self.stopped.append(track_idx)


class LoopWin(AudioRecMixin):
    """Piste 3 audio, 120 BPM (un pas = 0,125 s), pattern d'une mesure (2 s)."""
    def __init__(self, tmp_path, frames=5 * SR, t0=100.0, looping=True, bars=1):
        self.statuses = []
        self._project_path = str(tmp_path / "Chanson.gvp")
        self._audio_dir = ""
        self._cur_pattern_idx = 0
        self._cfg = SimpleNamespace(audio_hostapi="ALSA", audio_inputs=[], audio_latency_ms=0)
        self._audio_driver = SimpleNamespace(samplerate=SR, output_latency=0.0)
        self._router = FakeClipRouter()
        self._router._track_kinds[2] = TRACK_AUDIO
        p = DrumPlayer(_S())
        p.start_thread = p.stop_thread = lambda: None
        p._cur_track = 2
        p.set_bpm(120)
        p._pattern.set_bar_count(bars)
        p._pattern._looping = looping
        self._player = p
        self.recorder = FakeRecorder(frames, t0)
        self._audio_recorder_factory = lambda: self.recorder
        self._init_audio_rec()

    def _show_status(self, msg):   self.statuses.append(msg)
    def _alert_beep(self):         pass
    def _update_title(self):       pass
    def _refresh_track_list(self): pass
    def _save_project_as(self):    return True

    # --- raccourcis
    def open_take(self, replace=False, t_start=100.0, window_end=102.0):
        assert self._audio_rec_prepare(replace=replace)
        self._player._audio_take["anchor"] = (100.0, 0, t_start, window_end)
        self._on_audio_anchor()

    def stop(self):
        self._player.recording = True
        self._player.stop_record()

    def clips(self):
        return [(round(ev.time, 3), os.path.basename(ev.payload["file"]),
                 *clip_window(ev.payload)) for ev in self._player._pattern._tape[2]
                if ev.etype == ETYPE_AUDIO]


REL = "Audios/Chanson_pattern01_piste03_take_001.wav"
TAKE = os.path.basename(REL)


@pytest.fixture(autouse=True)
def _sync(monkeypatch):
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))


def test_prepare_replace_flag(tmp_path):
    win = LoopWin(tmp_path)
    assert win._audio_rec_prepare(replace=True)
    assert win._audio_rec["replace"] is True


def test_overdub_pass_becomes_a_clip_before_the_wrap(tmp_path):
    win = LoopWin(tmp_path)
    win.open_take()
    clip = win._on_audio_wrap(102.0)                 # fin du passage 0
    assert win.clips() == [(0.0, TAKE, 0, 2 * SR)]
    assert (REL, 0, 2 * SR) in win._router.pins       # joué depuis la mémoire
    assert win.recorder.ranges == [(0, 2 * SR)]
    assert win._on_audio_wrap(102.0) is None          # une seule fois par passage
    win._on_audio_wrap(104.0)
    assert win.clips() == [(0.0, TAKE, 0, 2 * SR), (0.0, TAKE, 2 * SR, 2 * SR)]
    assert clip is win._audio_rec["clips"][0]


@pytest.mark.parametrize("case", ["no_loop", "no_t0", "before_start", "no_take"])
def test_no_pass_posed(tmp_path, case):
    win = LoopWin(tmp_path, t0=None if case == "no_t0" else 100.0)
    if case != "no_take":
        win.open_take(window_end=None if case == "no_loop" else 102.0)
    at = 100.0 if case == "before_start" else 102.0
    assert win._on_audio_wrap(at) is None
    assert win.clips() == []


def test_overdub_stop_adds_the_last_pass_and_keeps_the_posed_ones(tmp_path):
    win = LoopWin(tmp_path, frames=5 * SR)           # 2 passages complets + 1 s
    win.open_take()
    first = win._on_audio_wrap(102.0)
    second = win._on_audio_wrap(104.0)
    win.stop()
    assert win.clips() == [(0.0, TAKE, 0, 2 * SR), (0.0, TAKE, 2 * SR, 2 * SR),
                           (0.0, TAKE, 4 * SR, SR)]
    tape = win._player._pattern._tape[2]
    assert tape[0] is first and tape[1] is second     # voix qui sonnent : pas relancées
    assert win._router.unpinned == [REL]
    assert win.statuses[-1] == f"Prise audio piste 3 : {TAKE}, 5.0 s, 3 passages"
    assert win._player._pattern._num_bars == 1        # en boucle : pas d'allongement


def test_overdub_keeps_the_older_clips(tmp_path):
    win = LoopWin(tmp_path, frames=2 * SR)
    old = TapeEvent(ETYPE_AUDIO, payload=clip_payload("old.wav", 1.0, 0, 2 * SR), time=0)
    win._player._pattern._tape[2].append(old)
    win.open_take()
    win.stop()
    assert win._player._pattern._tape[2][0] is old and len(win.clips()) == 2


def _old_clip(win, time=0, length=2 * SR):
    old = TapeEvent(ETYPE_AUDIO, payload=clip_payload("old.wav", 1.0, 0, length), time=time)
    win._player._pattern._tape[2].append(old)
    grid = TapeEvent(ETYPE_GRID, payload={"pad": 0, "vel": 90}, time=0)
    win._player._pattern._tape[2].append(grid)
    return old, grid


def test_replace_silences_the_track_from_the_start(tmp_path):
    win = LoopWin(tmp_path)
    old, grid = _old_clip(win)
    win._player._wakeup.clear()
    win.open_take(replace=True)
    assert win.clips() == []                          # la piste se tait dans la boucle
    assert grid in win._player._pattern._tape[2]      # autres événements gardés
    assert win._router.stopped == [2]                 # voix déjà lancées coupées
    assert win._player._wakeup.is_set()               # passage refait sans les clips
    assert win._audio_rec["base"] == [old]


def test_replace_silences_from_a_start_in_the_middle(tmp_path):
    win = LoopWin(tmp_path)
    _old_clip(win)
    win.open_take(replace=True, t_start=101.0)        # pas 8
    assert win.clips() == [(0.0, "old.wav", 0, SR)]


def test_replace_keeps_only_the_last_pass(tmp_path):
    win = LoopWin(tmp_path, frames=5 * SR)
    _old_clip(win)
    win.open_take(replace=True)
    win._on_audio_wrap(102.0)
    assert win.clips() == []                          # pendant : silence dans la boucle
    win._on_audio_wrap(104.0)
    win.stop()                                        # 3e passage : 1 s
    # le dernier passage (1 s) puis la fin du 2e passage
    assert sorted(win.clips()) == [(0.0, TAKE, 4 * SR, SR), (8.0, TAKE, 3 * SR, SR)]
    assert win.statuses[-1].endswith("3 passages (le dernier remplace)")


def test_replace_stop_just_after_a_pass_was_posed(tmp_path):
    """Stop dans les 0,3 s entre la pose du passage et le retour : seule la
    partie enregistrée remplace, la fin du passage précédent revient."""
    win = LoopWin(tmp_path, frames=int(3.5 * SR))
    win.open_take(replace=True)
    win._on_audio_wrap(102.0)                         # passage 0 posé
    win._on_audio_wrap(104.0)                         # passage 1 posé en entier…
    win.stop()                                        # … mais Stop à 1,5 s du passage 1
    assert sorted(win.clips()) == [(0.0, TAKE, 2 * SR, int(1.5 * SR)),
                                   (12.0, TAKE, int(1.5 * SR), SR // 2)]


def test_replace_without_loop_keeps_the_rest_of_the_old_clip(tmp_path):
    win = LoopWin(tmp_path, frames=SR, t0=101.0, looping=False, bars=4)   # captée 101 → 102 s
    _old_clip(win, length=4 * SR)
    win.open_take(replace=True, t_start=101.0, window_end=None)
    assert win.clips() == [(0.0, "old.wav", 0, SR)]   # silence après le départ
    win.stop()
    assert sorted(win.clips()) == [(0.0, "old.wav", 0, SR), (8.0, TAKE, 0, SR),
                                   (16.0, "old.wav", 2 * SR, 2 * SR)]


def test_replace_empty_take_gives_the_track_back(tmp_path):
    win = LoopWin(tmp_path, frames=0, t0=None)
    old, grid = _old_clip(win)
    win.open_take(replace=True)
    win.stop()
    assert win._player._pattern._tape[2] == [grid, old] or \
        set(map(id, win._player._pattern._tape[2])) == {id(grid), id(old)}
    assert win.statuses[-1] == "Prise audio vide : rien d'enregistré"


def test_replace_carves_clips_of_unknown_files_untouched(tmp_path):
    win = LoopWin(tmp_path, frames=2 * SR)
    lost = TapeEvent(ETYPE_AUDIO, payload=clip_payload("perdu.wav", 1.0), time=0)
    win._player._pattern._tape[2].append(lost)
    win.open_take(replace=True)
    assert lost in win._player._pattern._tape[2]      # fichier introuvable : gardé


def test_callbacks_after_the_take_are_ignored(tmp_path):
    win = LoopWin(tmp_path, frames=2 * SR)
    win.open_take()
    win.stop()
    assert win._on_audio_wrap(102.0) is None
    win._on_audio_anchor()                            # rien ne casse


# ---------------------------------------------------------------------------
# Nom du projet
# ---------------------------------------------------------------------------

def test_name_asked_only_for_a_project_never_saved(tmp_path):
    win = LoopWin(tmp_path)
    win._project_path = str(tmp_path / "noname_001.gvp")
    assert win._project_needs_name()
    open(win._project_path, "w").close()              # nom confirmé tel quel
    assert not win._project_needs_name()
    win._project_path = str(tmp_path / "Chanson.gvp")
    assert not win._project_needs_name()


def test_saved_noname_project_records_without_dialog(tmp_path):
    win = LoopWin(tmp_path)
    asked = []
    win._save_project_as = lambda: asked.append(1) or True
    win._project_path = str(tmp_path / "noname_001.gvp")
    open(win._project_path, "w").close()
    assert win._audio_rec_prepare()
    assert asked == []


# ---------------------------------------------------------------------------
# Vraie fenêtre principale
# ---------------------------------------------------------------------------

class LiveStream:
    def __init__(self, callback, samplerate, channels, **kw):
        self.cb, self.sr, self.ch, self.latency = callback, samplerate, channels, 0.0

    def start(self):
        self.run = True
        def go():
            while self.run:
                now = time.perf_counter()
                self.cb(np.full((512, self.ch), 0.2, np.float32), 512,
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
    def __init__(self, key, shift=False):
        self.k, self.s = key, shift
    def GetKeyCode(self):    return self.k
    def GetUnicodeKey(self): return 0
    def ControlDown(self):   return False
    def ShiftDown(self):     return self.s
    def AltDown(self):       return False
    def Skip(self):          pass


_APP = None


@pytest.mark.gui
@pytest.mark.audio
def test_real_main_window_loop_takes(isolated_preferences, tmp_path):
    """Une seule vraie MainWindow (clients ALSA) : Overdub en boucle (passages
    posés pendant la prise), puis Remplacer (piste muette dès le 1er
    passage, dernier passage gardé), Ctrl+Z."""
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)
    from ui.main_window import MainWindow
    win = None
    try:
        win = MainWindow(no_fluidsynth=True, no_sfizz=True)
        win._router.wait_loaded()
        p, r = win._player, win._router
        assert p._on_audio_anchor_cb is not None and p._on_audio_wrap_cb is not None
        win._audio_recorder_factory = lambda: ar.AudioRecorder(
            stream_factory=lambda **kw: LiveStream(**kw))
        win._project_path = str(tmp_path / "Chanson.gvp")
        win._audio_dir = ""
        r._track_kinds[3] = TRACK_AUDIO
        p._cur_track = 3
        pat = p._pattern
        p.set_bpm(240)
        pat.set_bar_count(1)                          # boucle de 1 s
        pat._looping, pat._loop_start, pat._loop_end = True, None, None
        app = wx.GetApp()

        def press(key, shift=False):
            win._key_manager.handle(_Key(key, shift))
            win._take_end_if_idle()

        def pump(secs):
            end = time.time() + secs
            while time.time() < end:
                app.Yield(True)
                time.sleep(0.01)

        # Overdub : deux passages posés pendant la prise
        press(ord('R'))
        pump(2.5)
        posed = len(pat.audio_clips(3))
        press(ord('R'))
        assert posed >= 2
        assert len(pat.audio_clips(3)) == posed + 1
        assert {e.payload["file"] for _, e in pat.audio_clips(3)} == \
            {"Audios/Chanson_pattern01_piste04_take_001.wav"}
        assert pat._num_bars == 1
        p.stop_all()
        pump(0.2)

        # Remplacer : piste muette dès le 1er passage
        press(ord('R'), shift=True)
        pump(0.5)
        assert pat.audio_clips(3) == []
        alive = [cid for cid, (t, v) in r._clip_voices.items() if t == 3 and r._voice_alive(v)]
        assert alive == []
        pump(1.0)
        press(ord('R'), shift=True)
        files = {e.payload["file"] for _, e in pat.audio_clips(3)}
        assert "Audios/Chanson_pattern01_piste04_take_002.wav" in files

        # Ctrl+Z : la prise d'Overdub revient
        p.stop_all()
        win._undo_action()
        assert {e.payload["file"] for _, e in win._player._pattern.audio_clips(3)} == \
            {"Audios/Chanson_pattern01_piste04_take_001.wav"}
    finally:
        if win is not None:
            win._player.stop_all()
            win._router.wait_loaded()
            win._close_midi_devices()
            win._audio_driver.close()
            win.Destroy()
