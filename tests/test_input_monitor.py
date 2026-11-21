#python3
"""
    File: tests/test_input_monitor.py
    Monitoring de l'entrée audio (Phase 8 étape 20e1, docs/DESIGN.md
    § Phase 8 étape 20a M1-M9, avancement 20d1) :
    - InputMonitor sur un flux factice : ouverture (bloc, latence basse,
      canaux bornés), refus, fermeture, anomalies ; tampon (mono → deux
      côtés, retard plafonné, bloc trop grand, tour du tampon) ; rendu
      (amorce, vide, ajout au mix) ; gain (volume, pan, rampe de 10 ms) ;
    - AudioRecorder.on_block ;
    - AudioMonitorMixin sur une fenêtre factice avec les vrais
      AudioRecMixin et RecordOptionsMixin : règle (case, piste audio,
      pilote), entrée de la piste, flux rouvert seulement au changement,
      gain de piste (pan global, Mute), entrée refusée (un seul bip),
      relais de la prise, F8 (Undo, annonces), options du projet,
      fréquence changée, Détecter, fermeture ; F8 par KeyManager ;
    - latences affichées par Tester (audio_device.device_latency,
      format_ms, textes d'entrée et de sortie, messages complets).
    Sans marque, sauf : un essai sur la vraie entrée (audio) ; la minuterie
    sur une vraie fenêtre détruite, et la case du vrai dialogue affiché (gui).
    Date: Sat, 21/11/2026
    Author: Coolbrother
"""
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pytest
import wx

import record_modes as rm
from audio import audio_recorder as ar
from audio.input_monitor import InputMonitor
from audio.sound_device_driver import pan_gains, Mixer
from devices import audio_device as ad
import ui.mw_audio_monitor as mam
import ui.mw_audio_rec as mar
import ui.mw_devices as mw_devices
from ui.mw_audio_monitor import AudioMonitorMixin
from ui.mw_audio_rec import AudioRecMixin
from ui.mw_record_options import RecordOptionsMixin
from ui.mw_devices import HardwareAccess
from pattern import TRACK_AUDIO, TRACK_MIDI

SR = 44100
RAMP = int(SR * Mixer.GAIN_RAMP_MS / 1000)


# ---------------------------------------------------------------------------
# Flux factice
# ---------------------------------------------------------------------------

class FakeStream:
    instances = []
    refuse = None                   # exception levée par start()

    def __init__(self, **kw):
        self.kw = kw
        self.callback = kw["callback"]
        self.calls = []
        self.fail_stop = False
        FakeStream.instances.append(self)

    def start(self):
        self.calls.append("start")
        if FakeStream.refuse is not None:
            raise FakeStream.refuse

    def stop(self):
        self.calls.append("stop")
        if self.fail_stop:
            raise RuntimeError("carte débranchée")

    def close(self):
        self.calls.append("close")


@pytest.fixture(autouse=True)
def fresh_streams():
    FakeStream.instances = []
    FakeStream.refuse = None
    yield


def _mon():
    return InputMonitor(SR, stream_factory=lambda **kw: FakeStream(**kw))


def _render(mon, frames=512):
    mix = np.zeros((frames, 2), np.float32)
    mon.render(mix)
    return mix


def _full_gain(mon):
    """Gain 1 tout de suite (rampe consommée)."""
    mon.set_gain(1.0, 0)
    mon._gain.vol_l = mon._gain.vol_r = 1.0
    mon._gain.ramp = 0


# ---------------------------------------------------------------------------
# InputMonitor : flux propre
# ---------------------------------------------------------------------------

def test_start_opens_a_low_latency_small_block_stream():
    mon = _mon()
    mon.start(device=3, channels=2)
    (s,) = FakeStream.instances
    assert s.kw["device"] == 3 and s.kw["samplerate"] == SR and s.kw["channels"] == 2
    assert s.kw["blocksize"] == InputMonitor.BLOCKSIZE == 256
    assert s.kw["latency"] == "low" and s.kw["dtype"] == "float32"
    assert s.calls == ["start"] and mon.active


@pytest.mark.parametrize("channels, opened", [(0, 1), (1, 1), (2, 2), (8, 2)])
def test_channels_bounded(channels, opened):
    mon = _mon()
    mon.start(None, channels)
    assert FakeStream.instances[0].kw["channels"] == opened


def test_stop_closes_the_stream():
    mon = _mon()
    mon.start(None, 1)
    mon.stop()
    assert FakeStream.instances[0].calls == ["start", "stop", "close"] and not mon.active
    mon.stop()                                           # deux fois : rien


def test_stop_error_noted():
    mon = _mon()
    mon.start(None, 1)
    FakeStream.instances[0].fail_stop = True
    mon.stop()
    assert mon.errors == ["carte débranchée"] and not mon.active


def test_start_again_closes_the_previous_stream_and_clears():
    mon = _mon()
    mon.start(1, 1)
    mon.feed(np.ones((300, 1), np.float32))
    mon.start(2, 1)
    first, second = FakeStream.instances
    assert first.calls == ["start", "stop", "close"] and second.calls == ["start"]
    assert mon.pending() == 0


def test_refused_start_leaves_nothing_open():
    FakeStream.refuse = RuntimeError("occupé")
    mon = _mon()
    with pytest.raises(RuntimeError):
        mon.start(5, 1)
    assert not mon.active and FakeStream.instances[0].calls == ["start", "close"]


def test_callback_feeds_and_notes_anomalies():
    mon = _mon()
    mon.start(None, 1)
    FakeStream.instances[0].callback(np.ones((256, 1), np.float32), 256, None, "input overflow")
    assert mon.pending() == 256 and mon.errors == ["input overflow"]


def test_default_stream_is_sounddevice(monkeypatch):
    import sounddevice as sd
    made = []
    monkeypatch.setattr(sd, "InputStream", lambda **kw: made.append(kw) or FakeStream(**kw))
    InputMonitor(SR).start(None, 1)
    assert made and made[0]["blocksize"] == 256


# ---------------------------------------------------------------------------
# InputMonitor : tampon et rendu
# ---------------------------------------------------------------------------

def test_silence_until_primed_nothing_consumed():
    mon = _mon()
    _full_gain(mon)
    mon.feed(np.full((InputMonitor.PRIME - 1, 1), 0.5, np.float32))
    assert not _render(mon).any() and mon.pending() == InputMonitor.PRIME - 1
    mon.feed(np.full((1, 1), 0.5, np.float32))
    mix = _render(mon)
    assert np.allclose(mix[:InputMonitor.PRIME], 0.5) and not mix[InputMonitor.PRIME:].any()


def test_empty_again_waits_for_prime():
    mon = _mon()
    _full_gain(mon)
    mon.feed(np.full((300, 1), 0.5, np.float32))
    _render(mon)                                       # 300 joués, tampon vide
    mon.feed(np.full((100, 1), 0.5, np.float32))
    assert not _render(mon).any() and mon.pending() == 100


def test_mono_to_both_sides_stereo_kept():
    mon = _mon()
    _full_gain(mon)
    mon.feed(np.full(512, 0.25, np.float32))           # 1D : mono
    mix = _render(mon)
    assert np.allclose(mix, 0.25)
    block = np.column_stack([np.full(512, 0.1), np.full(512, -0.2), np.full(512, 9.0)])
    mon.feed(block.astype(np.float32))                 # 3 canaux : les deux premiers
    mix = _render(mon)
    assert np.allclose(mix[:, 0], 0.1) and np.allclose(mix[:, 1], -0.2)


def test_render_adds_to_the_mix():
    mon = _mon()
    _full_gain(mon)
    mon.feed(np.full((512, 1), 0.25, np.float32))
    mix = np.full((512, 2), 0.5, np.float32)
    mon.render(mix)
    assert np.allclose(mix, 0.75)


def test_lag_capped_oldest_dropped():
    mon = _mon()
    _full_gain(mon)
    data = np.arange(4000, dtype=np.float32)[:, None] / 4000
    mon.feed(data)
    assert mon.pending() == InputMonitor.MAX_LAG and mon.dropped == 4000 - InputMonitor.MAX_LAG
    mix = _render(mon, 512)
    assert np.allclose(mix[:, 0], data[4000 - InputMonitor.MAX_LAG:][:512, 0])  # les plus récents


def test_block_larger_than_the_buffer():
    mon = _mon()
    mon.feed(np.zeros((InputMonitor.CAPACITY + 10, 1), np.float32))
    assert mon.pending() == InputMonitor.MAX_LAG
    assert mon.dropped == InputMonitor.CAPACITY + 10 - InputMonitor.MAX_LAG


def test_ring_wraps_without_loss():
    """Plusieurs tours du tampon : ce qui sort est ce qui est entré."""
    mon = _mon()
    _full_gain(mon)
    out, src = [], []
    k = 0
    for _ in range(200):
        block = (np.arange(k, k + 300, dtype=np.float32) % 1000 / 1000)[:, None]
        k += 300
        src.append(block[:, 0])
        mon.feed(block)
        out.append(_render(mon, 300)[:, 0])
    src, out = np.concatenate(src), np.concatenate(out)
    assert 200 * 300 > InputMonitor.CAPACITY and mon.dropped == 0
    assert np.allclose(out, src)                       # 300 ≥ PRIME : rien n'attend


def test_clear():
    mon = _mon()
    mon.feed(np.ones((500, 1), np.float32))
    mon.clear()
    assert mon.pending() == 0


# ---------------------------------------------------------------------------
# InputMonitor : gain
# ---------------------------------------------------------------------------

def test_gain_starts_at_zero_and_ramps_in_10_ms():
    mon = _mon()
    mon.feed(np.ones((1024, 1), np.float32))
    mon.set_gain(1.0, 0)
    mix = _render(mon, 1024)
    assert mix[0, 0] < 0.01 and 0.4 < mix[RAMP // 2, 0] < 0.6
    assert np.allclose(mix[RAMP:, 0], 1.0)


@pytest.mark.parametrize("vol, pan", [(0.5, 0), (1.0, -100), (0.8, 50), (0.0, 0)])
def test_gain_follows_the_pan_law(vol, pan):
    mon = _mon()
    mon.set_gain(vol, pan)
    assert mon.target_gain() == pan_gains(vol, pan)
    mon.feed(np.ones((1024, 1), np.float32))          # sous MAX_LAG
    mix = _render(mon, 1024)
    gl, gr = pan_gains(vol, pan)
    assert np.allclose(mix[-100:, 0], gl) and np.allclose(mix[-100:, 1], gr)


def test_same_gain_does_not_restart_the_ramp():
    mon = _mon()
    mon.set_gain(0.5, 0)
    mon.feed(np.ones((1024, 1), np.float32))
    _render(mon, 1024)
    mon.set_gain(0.5, 0)
    assert mon._gain.ramp == 0


def test_ramp_advances_while_priming():
    """Pendant l'amorce, la rampe avance : le gain est atteint au retour."""
    mon = _mon()
    mon.set_gain(1.0, 0)
    _render(mon, 512)                                  # rien en attente
    mon.feed(np.ones((512, 1), np.float32))
    assert np.allclose(_render(mon, 512), 1.0)


def test_negative_volume_is_silence():
    mon = _mon()
    mon.set_gain(-1.0, 0)
    assert mon.target_gain() == (0.0, 0.0)


# ---------------------------------------------------------------------------
# AudioRecorder.on_block
# ---------------------------------------------------------------------------

class RecStream(FakeStream):
    def __init__(self, blocks=(), **kw):
        super().__init__(**kw)
        self.blocks = blocks
        self.latency = 0.0

    def start(self):
        for b in self.blocks:
            self.callback(b, len(b), SimpleNamespace(currentTime=1.0, inputBufferAdcTime=0.99),
                          None)


def test_recorder_passes_each_block_to_on_block(tmp_path):
    blocks = [np.full((256, 1), 0.1, np.float32), np.full((128, 1), 0.2, np.float32)]
    rec = ar.AudioRecorder(stream_factory=lambda **kw: RecStream(blocks, **kw),
                           clock=lambda: 5.0)
    got = []
    rec.on_block = got.append
    rec.start(str(tmp_path / "t.wav"), None, SR, 1)
    rec.stop()
    assert [len(b) for b in got] == [256, 128] and np.allclose(got[1], 0.2)


def test_recorder_without_on_block(tmp_path):
    rec = ar.AudioRecorder(stream_factory=lambda **kw: RecStream([np.ones((10, 1), np.float32)],
                                                                 **kw), clock=lambda: 5.0)
    assert rec.on_block is None
    rec.start(str(tmp_path / "t.wav"), None, SR, 1)
    assert rec.stop().frames == 10


# ---------------------------------------------------------------------------
# AudioMonitorMixin sur une fenêtre factice
# ---------------------------------------------------------------------------

class FakeDriver:
    def __init__(self, samplerate=SR):
        self.samplerate = samplerate
        self.sources = []
        self.output_latency = 0.02

    def add_render_source(self, fn):
        if fn not in self.sources:
            self.sources.append(fn)

    def remove_render_source(self, fn):
        self.sources = [f for f in self.sources if f != fn]


class FakeRouter:
    def __init__(self):
        self._track_kinds = [TRACK_MIDI] * 16
        self._track_audio_ins = [""] * 16
        self._track_volumes = [100] * 16
        self._track_pans = [0] * 16
        self.master_pan = 0
        self.muted = set()

    def _track_is_audible(self, t):
        return t not in self.muted


class FakeRecorder:
    def __init__(self):
        self.on_block = None


class _TestMonitor(InputMonitor):
    def __init__(self, samplerate):
        super().__init__(samplerate, stream_factory=lambda **kw: FakeStream(**kw))


class Win(AudioMonitorMixin, AudioRecMixin, RecordOptionsMixin):
    _input_monitor_factory = _TestMonitor

    def __init__(self):
        self._audio_driver = FakeDriver()
        self._router = FakeRouter()
        self._player = SimpleNamespace(_cur_track=0, count_in_bars=1, click_in_recording=True,
                                       click_in_playback=False, count_in_play_bars=0)
        self._cfg = SimpleNamespace(audio_inputs=["Micro", "Ligne"], audio_hostapi="ALSA")
        self._record_options = dict(rm.DEFAULTS)
        self._audio_rec = None
        self.statuses, self.undos, self.beeps = [], [], 0
        self._init_audio_monitor(timer=False)

    def _show_status(self, msg):  self.statuses.append(msg)
    def _add_undo(self, title):   self.undos.append(title)
    def _update_title(self):      pass
    def _alert_beep(self):        self.beeps += 1


DEVICES = {"Micro": 3, "Ligne": 4}


@pytest.fixture
def win(monkeypatch):
    monkeypatch.setattr(mar.audio_devices, "find_device",
                        lambda name, api, kind: DEVICES.get(name))
    monkeypatch.setattr(mar.audio_devices, "default_device", lambda api, kind: "Défaut")
    monkeypatch.setattr(mar.audio_devices, "default_hostapi", lambda: "ALSA")
    monkeypatch.setattr(mam.audio_devices, "input_channels", lambda idx: 2 if idx == 4 else 1)
    w = Win()
    w._router._track_kinds[0] = TRACK_AUDIO
    return w


def _on(w):
    w._apply_record_options(dict(w._record_options, monitor=True))


def test_off_by_default_nothing_open(win):
    win._update_monitor()
    assert win._monitor is None and FakeStream.instances == [] and win._audio_driver.sources == []


def test_on_audio_track_opens_the_track_input(win):
    _on(win)
    (s,) = FakeStream.instances
    assert s.kw["device"] == 3 and s.kw["channels"] == 1             # première cochée : Micro
    assert win._audio_driver.sources == [win._monitor.render]
    assert win.monitor_heard_track() == 0


def test_track_input_used(win):
    win._router._track_audio_ins[0] = "Ligne"
    _on(win)
    assert FakeStream.instances[0].kw["device"] == 4 and FakeStream.instances[0].kw["channels"] == 2


def test_midi_track_hears_nothing(win):
    _on(win)
    win._player._cur_track = 1
    win._update_monitor()
    assert win._monitor is None and win._audio_driver.sources == []
    assert FakeStream.instances[0].calls == ["start", "stop", "close"]
    assert win.monitor_heard_track() is None


def test_without_driver_nothing(win):
    win._audio_driver = None
    _on(win)
    assert FakeStream.instances == []


def test_stream_reopened_only_on_change(win):
    win._router._track_kinds[1] = TRACK_AUDIO
    win._router._track_audio_ins[1] = "Ligne"
    _on(win)
    for _ in range(5):
        win._update_monitor()                         # minuterie : rien ne change
    assert len(FakeStream.instances) == 1
    win._player._cur_track = 1
    win._update_monitor()
    assert len(FakeStream.instances) == 2 and FakeStream.instances[1].kw["device"] == 4
    assert win.monitor_heard_track() == 1
    win._router._track_audio_ins[1] = "Micro"          # entrée changée (Alt+Entrée)
    win._update_monitor()
    assert len(FakeStream.instances) == 3 and FakeStream.instances[2].kw["device"] == 3


def test_gain_follows_volume_pan_master_and_mute(win):
    _on(win)
    r = win._router
    r._track_volumes[0], r._track_pans[0], r.master_pan = 50, 30, 20
    win._update_monitor()
    assert win._monitor.target_gain() == pan_gains(0.5, 50)
    r._track_pans[0] = 90
    win._update_monitor()
    assert win._monitor.target_gain() == pan_gains(0.5, 100)          # borné
    r.muted.add(0)
    win._update_monitor()
    assert win._monitor.target_gain() == (0.0, 0.0)
    assert len(FakeStream.instances) == 1                             # flux gardé


def test_refused_input_beeps_once_until_a_change(win):
    FakeStream.refuse = RuntimeError("occupé")
    _on(win)
    win._update_monitor()
    win._update_monitor()
    assert win.beeps == 1 and win.statuses == ["Monitoring de l'entrée : Micro refusée (occupé)"]
    assert not win._monitor.active
    FakeStream.refuse = None
    win._router._track_audio_ins[0] = "Ligne"          # autre entrée : redemandée
    win._update_monitor()
    assert win._monitor.active and win.beeps == 1


def test_missing_input_falls_back_with_a_note(win):
    win._router._track_audio_ins[0] = "Absente"
    win._apply_record_options(dict(rm.DEFAULTS, monitor=True))
    assert FakeStream.instances[0].kw["device"] is None
    assert win._last_monitor_note == "entrée « Absente » introuvable, Défaut à la place"


def test_take_relays_the_recorder(win):
    _on(win)
    rec = FakeRecorder()
    win._monitor_release()                            # avant d'ouvrir l'entrée
    assert not win._monitor.active
    win._audio_rec = {"track": 0, "recorder": rec}
    win._update_monitor()
    assert rec.on_block == win._monitor.feed and win.monitor_heard_track() == 0
    assert len(FakeStream.instances) == 1                             # pas de second flux
    rec.on_block(np.ones((300, 1), np.float32))
    assert win._monitor.pending() == 300
    win._audio_rec = None                             # fin de prise : flux propre rouvert
    win._update_monitor()
    assert win._monitor.active and len(FakeStream.instances) == 2


def test_take_on_another_track_keeps_own_stream(win):
    _on(win)
    rec = FakeRecorder()
    win._audio_rec = {"track": 5, "recorder": rec}
    win._update_monitor()
    assert rec.on_block is None and win._monitor.active


def test_close_detaches_the_recorder(win):
    _on(win)
    rec = FakeRecorder()
    win._audio_rec = {"track": 0, "recorder": rec}
    win._update_monitor()
    win._apply_record_options(dict(win._record_options, monitor=False))
    assert rec.on_block is None and win._monitor is None


def test_samplerate_change_makes_a_new_monitor(win):
    _on(win)
    old = win._monitor
    win._audio_driver.samplerate = 48000
    win._update_monitor()
    assert win._monitor is not old and win._monitor.samplerate == 48000
    assert win._audio_driver.sources == [win._monitor.render]


def test_project_options_drive_the_monitor(win):
    """Ctrl+N, ancien projet (None), Ctrl+O, Ctrl+Z : par _apply_record_options."""
    win._apply_record_options({"monitor": True})
    assert win._monitor is not None and win._monitor.active
    win._apply_record_options(None)
    assert win._monitor is None


def test_stop_all(win):
    _on(win)
    win._monitor_stop_all()
    assert win._monitor is None and win._audio_driver.sources == []


# -- F8 -------------------------------------------------------------------

def test_f8_toggles_with_undo_and_announces(win):
    assert win._toggle_monitor() is True
    assert win.undos == ["Monitoring de l'entrée activé"]
    assert win.statuses[-1] == "Monitoring de l'entrée activé (piste 1 — Micro)"
    assert win._record_options["monitor"] and win._monitor.active
    assert win._toggle_monitor() is False
    assert win.undos[-1] == "Monitoring de l'entrée désactivé"
    assert win.statuses[-1] == "Monitoring de l'entrée désactivé" and win._monitor is None


def test_f8_on_a_midi_track(win):
    win._player._cur_track = 2
    win._toggle_monitor()
    assert win.statuses[-1] == "Monitoring de l'entrée activé (piste courante non audio)"
    assert win._monitor is None


def test_f8_refused_input(win):
    FakeStream.refuse = RuntimeError("occupé")
    win._toggle_monitor()
    assert win.statuses[-1] == "Monitoring de l'entrée activé (piste 1 — Micro) — entrée refusée"
    assert win.beeps == 1


def test_f8_input_replaced(win):
    win._router._track_audio_ins[0] = "Absente"
    win._toggle_monitor()
    assert win.statuses[-1] == ("Monitoring de l'entrée activé (piste 1 — Défaut) ; "
                                "entrée « Absente » introuvable, Défaut à la place")


def test_f8_custom_status(win):
    said = []
    win._toggle_monitor(status=said.append)
    assert said == ["Monitoring de l'entrée activé (piste 1 — Micro)"]


def test_f8_through_key_manager():
    from test_key_manager import make_km, FakeEvent
    app, fake, km = make_km()
    toggled = []
    fake._toggle_monitor = lambda: toggled.append(1)
    km.handle(FakeEvent(key=wx.WXK_F8))
    assert toggled == [1]
    for mods in ({"ctrl": True}, {"shift": True}, {"alt": True}):
        km.handle(FakeEvent(key=wx.WXK_F8, **mods))
    assert toggled == [1]                               # modificateurs : rien


# -- Détecter, prise ----------------------------------------------------------

def test_detect_audio_closes_the_monitor(win, monkeypatch):
    """Détecter relit PortAudio (réinitialisé) : le flux d'entrée se ferme
    avant ; la minuterie le rouvrira."""
    monkeypatch.setattr(ad, "rescan", lambda: order.append("relecture"))
    monkeypatch.setattr(ad, "hostapis", lambda: [])
    order = []
    _on(win)
    real_close = win._monitor_close
    win._monitor_close = lambda: (order.append("monitor fermé"), real_close())
    win._audio_driver = None                          # pas de flux de sortie à relancer
    HardwareAccess(win).detect_audio()
    assert order == ["monitor fermé", "relecture"] and win._monitor is None


def test_take_prepare_releases_then_relays(win, monkeypatch, tmp_path):
    """_audio_rec_prepare : flux propre fermé avant l'enregistreur, puis relais."""
    _on(win)
    order = []
    mon = win._monitor
    real_stop = mon.stop
    mon.stop = lambda: (order.append("monitor fermé"), real_stop())

    class Rec(FakeRecorder):
        samplerate = SR
        def start(self, *a):
            order.append("enregistreur ouvert")

    win._audio_recorder_factory = Rec
    win._project_needs_name = lambda: False
    win._project_path = str(tmp_path / "P.gvp")
    win._cur_pattern_idx = 0
    win._audio_dir = ""
    win._player.arm_audio_take = lambda: order.append("armé")
    monkeypatch.setattr(mar.audio_devices, "input_channels", lambda idx: 1)
    assert win._audio_rec_prepare()
    assert order[:2] == ["monitor fermé", "enregistreur ouvert"]
    assert win._audio_rec["recorder"].on_block == mon.feed


# ---------------------------------------------------------------------------
# Latences affichées par Tester
# ---------------------------------------------------------------------------

def test_device_latency(monkeypatch):
    import sounddevice as sd
    asked = []

    def query(index=None, kind=None):
        asked.append((index, kind))
        return {"default_low_input_latency": 0.0058, "default_high_input_latency": 0.0348,
                "default_low_output_latency": 0.0087, "default_high_output_latency": 0.0348}
    monkeypatch.setattr(sd, "query_devices", query)
    assert ad.device_latency(2, ad.INPUT) == (0.0058, 0.0348)
    assert ad.device_latency(None, ad.OUTPUT) == (0.0087, 0.0348)
    assert asked == [(2, "input"), (None, "output")]


def test_device_latency_unknown(monkeypatch):
    import sounddevice as sd

    def refuse(index=None, kind=None):
        raise ValueError("pas d'entrée")
    monkeypatch.setattr(sd, "query_devices", refuse)
    assert ad.device_latency(7, ad.INPUT) is None


@pytest.mark.parametrize("secs, text", [(0.0058, "5,8 ms"), (0.02322, "23,2 ms"), (0, "0,0 ms")])
def test_format_ms(secs, text):
    assert ad.format_ms(secs) == text


def test_input_latency_text(monkeypatch):
    monkeypatch.setattr(ad, "device_latency", lambda idx, kind: (0.0058, 0.0348))
    drv = SimpleNamespace(output_latency=0.0232)
    expected_mon = 0.0058 + 0.0232 + InputMonitor.PRIME / SR
    assert HardwareAccess._input_latency_text(2, drv, SR) == (
        " ; latence d'entrée : 5,8 ms (basse) à 34,8 ms (haute) ; monitoring ≈ "
        + ad.format_ms(expected_mon))
    monkeypatch.setattr(ad, "device_latency", lambda idx, kind: None)
    assert HardwareAccess._input_latency_text(2, drv, SR) == ""


def test_output_latency_text(monkeypatch):
    monkeypatch.setattr(ad, "device_latency", lambda idx, kind: (0.0087, 0.0348))
    app_out = SimpleNamespace(device=4, output_latency=0.0232)
    assert HardwareAccess._output_latency_text(4, app_out) == " ; latence de sortie : 23,2 ms"
    assert HardwareAccess._output_latency_text(5, app_out) == " ; latence de sortie : 8,7 ms"
    assert HardwareAccess._output_latency_text(5, None) == " ; latence de sortie : 8,7 ms"
    monkeypatch.setattr(ad, "device_latency", lambda idx, kind: None)
    assert HardwareAccess._output_latency_text(5, None) == ""


def _access(driver):
    return HardwareAccess(SimpleNamespace(_cfg=SimpleNamespace(audio_hostapi="ALSA"),
                                          _audio_driver=driver))


def test_input_test_message_with_latency(monkeypatch):
    monkeypatch.setattr(mw_devices.wx, "CallAfter", lambda fn, *a: fn(*a))
    monkeypatch.setattr(ad, "find_device", lambda n, a, k: 2)
    monkeypatch.setattr(ad, "record_input", lambda idx, samplerate=SR: np.zeros((100, 1), np.float32))
    monkeypatch.setattr(ad, "device_latency", lambda idx, kind: (0.0058, 0.0348))
    said = []
    drv = SimpleNamespace(samplerate=SR, output_latency=0.0, device=None, play=lambda s: None)
    _access(drv).test_audio_input("ALSA", "Micro", said.append).join(2)
    assert said == ["Entrée audio Micro : silence (rien ne rentre) ; latence d'entrée : 5,8 ms "
                    "(basse) à 34,8 ms (haute) ; monitoring ≈ "
                    + ad.format_ms(0.0058 + InputMonitor.PRIME / SR)]


def test_output_test_message_with_latency(monkeypatch):
    monkeypatch.setattr(ad, "find_device", lambda n, a, k: 4)
    played = []
    drv = SimpleNamespace(samplerate=SR, output_latency=0.0232, device=4, play=played.append)
    msg = _access(drv).test_audio_output("ALSA", "pipewire")
    assert msg == ("Sortie audio pipewire : La 440 Hz joué pendant une seconde ; "
                   "latence de sortie : 23,2 ms") and len(played) == 1


# ---------------------------------------------------------------------------
# Vraie carte, vraies fenêtres
# ---------------------------------------------------------------------------

@pytest.mark.audio
def test_real_input_stream():
    """Entrée par défaut ouverte pour de vrai : des blocs arrivent, le retard
    reste plafonné sans rendu, fermeture propre."""
    mon = InputMonitor(SR)
    try:
        mon.start(None, 1)
    except Exception as e:                            # machine sans entrée
        pytest.skip(f"pas d'entrée audio : {e}")
    try:
        time.sleep(0.3)
        assert mon.active and 0 < mon.pending() <= InputMonitor.MAX_LAG
        mix = np.zeros((512, 2), np.float32)
        mon.render(mix)
    finally:
        mon.stop()
    assert not mon.active


class _TimerFrame(AudioMonitorMixin, wx.Frame):
    def __init__(self):
        wx.Frame.__init__(self, None)
        self._audio_driver = None
        self.ticks = 0
        self._init_audio_monitor(timer=True)

    def _update_monitor(self):
        self.ticks += 1
        return ""


@pytest.mark.gui                  # boucle d'événements, fenêtre détruite
def test_timer_has_no_owner_and_stops_with_the_window():
    frame = _TimerFrame()
    timer = frame._monitor_timer
    assert timer.IsRunning() and timer.GetOwner() is timer   # pas la fenêtre
    t0 = time.time()
    while frame.ticks == 0 and time.time() - t0 < 2:
        wx.SafeYield()
        time.sleep(0.02)
    assert frame.ticks > 0                            # la minuterie appelle _update_monitor
    frame.Destroy()
    t0 = time.time()
    while time.time() - t0 < 0.4:                     # tops en file après Destroy : sans plantage
        wx.SafeYield()
        time.sleep(0.02)
    assert not timer.IsRunning()


@pytest.mark.gui                  # dialogue affiché
def test_monitor_box_in_the_shown_dialog():
    from ui.dialogs import RecordOptionsDialog
    frame = wx.Frame(None)
    dlg = RecordOptionsDialog(frame, dict(rm.DEFAULTS, monitor=True))
    try:
        dlg.Show()
        wx.SafeYield()
        assert dlg._monitor.IsShownOnScreen() and dlg._monitor.GetValue()
        assert dlg._monitor.AcceptsFocusFromKeyboard()          # atteinte par Tab
        assert dlg._monitor.GetPrevSibling() is dlg._count_lb   # juste après le décompte
        dlg._monitor.SetValue(False)
        assert dlg.get_options()["monitor"] is False
    finally:
        dlg.Destroy()
        frame.Destroy()
