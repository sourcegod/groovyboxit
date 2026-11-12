#python3
"""
    File: tests/test_audio_device.py
    Périphériques audio (Phase 8 étape 11b1, docs/DESIGN.md § Phase 8 étape
    11a H1-H5, H12-H16 et avenants) : paquet autonome devices
    (devices.audio_device sur un PortAudio factice : pilotes, périphériques
    par nom, défauts, sortie absente, relecture, La 440 Hz, crête d'une
    entrée ; python3 -m devices ; aucun import de l'appli) ;
    SoundDeviceDriver.set_device / start_stream / stop_stream ; clés
    audio_hostapi, audio_inputs, audio_outputs, audio_main_output ;
    démarrage (_open_audio_driver), boîte « Périphérique introuvable » et
    bip d'alerte ; sortie changée depuis les Préférences
    (_apply_audio_output) ; vraie fenêtre principale.
    Date: Wed, 11/11/2026
    Author: Coolbrother
"""
import sys
import os
import ast
import json
import math
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest
import wx

from app_config import AppConfig
import devices
from devices import audio_device as ad
from devices import __main__ as devices_cli
import audio.sound_device_driver as sdd
from audio.sound_device_driver import SoundDeviceDriver, Mixer, SdSound
import ui.main_window as main_window
from ui.main_window import MainWindow
from ui.mw_project import ProjectMixin


# ---------------------------------------------------------------------------
# PortAudio factice
# ---------------------------------------------------------------------------

class _PortAudioError(Exception):
    pass


HOSTAPIS = [
    {"name": "ALSA", "default_output_device": 2, "default_input_device": 0},
    {"name": "OSS", "default_output_device": -1, "default_input_device": 3},
]
DEVICES = [
    {"name": "Carte A: Analog (hw:1,0)", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0},
    {"name": "pipewire", "hostapi": 0, "max_input_channels": 64, "max_output_channels": 64},
    {"name": "default", "hostapi": 0, "max_input_channels": 64, "max_output_channels": 64},
    {"name": "/dev/dsp", "hostapi": 1, "max_input_channels": 16, "max_output_channels": 0},
    {"name": "Carte B: HDMI 0 (hw:2,3)", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 8},
]


class FakeSd:
    PortAudioError = _PortAudioError

    def __init__(self, hostapis=HOSTAPIS, devs=DEVICES, default=(0, 2)):
        self.hostapis = [dict(h) for h in hostapis]
        self.devs = [dict(d) for d in devs]
        self.default = SimpleNamespace(device=list(default))
        self.calls = []
        self.recorded = None
        self.refuse = set()

    def query_hostapis(self, index=None):
        return tuple(self.hostapis) if index is None else self.hostapis[index]

    def query_devices(self, device=None):
        if device is None:
            return list(self.devs)
        if not 0 <= device < len(self.devs):
            raise ValueError(f"No device {device}")
        return self.devs[device]

    def play(self, data, samplerate=None, device=None):
        if device in self.refuse:
            raise _PortAudioError("Device unavailable")
        self.calls.append(("play", data, samplerate, device))

    def rec(self, frames, samplerate=None, channels=1, dtype="float32", device=None,
            blocking=False):
        if device in self.refuse:
            raise _PortAudioError("Device unavailable")
        self.calls.append(("rec", frames, samplerate, channels, device, blocking))
        if self.recorded is not None:
            return self.recorded
        return np.zeros((frames, channels), np.float32)

    def _terminate(self):
        self.calls.append(("terminate",))

    def _initialize(self):
        self.calls.append(("initialize",))


@pytest.fixture
def fake_sd(monkeypatch):
    sd = FakeSd()
    monkeypatch.setattr(ad, "sd", sd)
    return sd


# ---------------------------------------------------------------------------
# Paquet autonome
# ---------------------------------------------------------------------------

DEVICES_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "devices")
APP_MODULES = {"app_config", "audio", "ui", "player", "midi", "pattern", "rack", "song",
               "track_router", "project_manager", "voice_manager"}


@pytest.mark.parametrize("name", sorted(f for f in os.listdir(DEVICES_DIR) if f.endswith(".py")))
def test_package_imports_nothing_from_the_app(name):
    with open(os.path.join(DEVICES_DIR, name), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots = {(node.module or "").split(".")[0]}
        else:
            continue
        assert not roots & APP_MODULES, f"{name} importe {roots & APP_MODULES}"


def test_package_file_names():
    files = set(os.listdir(DEVICES_DIR))
    assert "audio_device.py" in files and "audio.py" not in files


def test_package_docstring():
    assert "AUTONOME" in devices.__doc__


# ---------------------------------------------------------------------------
# Pilotes et périphériques par nom
# ---------------------------------------------------------------------------

def test_hostapis(fake_sd):
    assert ad.hostapis() == ["ALSA", "OSS"]


def test_default_hostapi_from_default_output(fake_sd):
    assert ad.default_hostapi() == "ALSA"
    fake_sd.default.device = [3, 3]
    assert ad.default_hostapi() == "OSS"


@pytest.mark.parametrize("default", [(0, -1), (0, None), (0, 99)])
def test_default_hostapi_falls_back_to_first(fake_sd, default):
    fake_sd.default.device = list(default)
    assert ad.default_hostapi() == "ALSA"


def test_default_hostapi_without_hostapi(fake_sd):
    fake_sd.hostapis = []
    fake_sd.default.device = [None, None]
    assert ad.default_hostapi() == ""


def test_devices_by_direction(fake_sd):
    assert ad.devices("ALSA", "output") == ["pipewire", "default", "Carte B: HDMI 0 (hw:2,3)"]
    assert ad.devices("ALSA", "input") == ["Carte A: Analog (hw:1,0)", "pipewire", "default"]
    assert ad.devices("OSS", "input") == ["/dev/dsp"]
    assert ad.devices("OSS", "output") == []


def test_devices_of_unknown_hostapi(fake_sd):
    assert ad.devices("JACK", "output") == []


def test_default_device(fake_sd):
    assert ad.default_device("ALSA", "output") == "default"
    assert ad.default_device("ALSA", "input") == "Carte A: Analog (hw:1,0)"
    assert ad.default_device("OSS", "output") == ""
    assert ad.default_device("JACK", "output") == ""


def test_find_device_by_name_and_direction(fake_sd):
    assert ad.find_device("pipewire", "ALSA", "output") == 1
    assert ad.find_device("Carte B: HDMI 0 (hw:2,3)", "ALSA", "output") == 4
    assert ad.find_device("Carte B: HDMI 0 (hw:2,3)", "ALSA", "input") is None
    assert ad.find_device("/dev/dsp", "ALSA", "input") is None      # autre pilote
    assert ad.find_device("absente", "ALSA", "output") is None


def test_name_survives_renumbering(fake_sd):
    # une carte branchée avant : les numéros changent, le nom retrouve la sortie
    fake_sd.devs.insert(0, {"name": "Clé USB", "hostapi": 0, "max_input_channels": 1,
                            "max_output_channels": 2})
    assert ad.find_device("pipewire", "ALSA", "output") == 2


def test_resolve_output(fake_sd):
    assert ad.resolve_output("", "ALSA") == (None, "")
    assert ad.resolve_output("pipewire", "ALSA") == (1, "")
    idx, note = ad.resolve_output("Carte inexistante", "ALSA")
    assert idx is None
    assert note == "Sortie audio introuvable : Carte inexistante. Sortie par défaut utilisée."


def test_rescan_reinitialises_portaudio(fake_sd):
    ad.rescan()
    assert fake_sd.calls == [("terminate",), ("initialize",)]


# ---------------------------------------------------------------------------
# Tester : La 440 Hz, crête d'une entrée
# ---------------------------------------------------------------------------

def test_tone_is_a_440_hz_second():
    data = ad.tone(44100)
    assert data.shape == (44100, 2) and data.dtype == np.float32
    assert np.array_equal(data[:, 0], data[:, 1])
    spectrum = np.abs(np.fft.rfft(data[:, 0]))
    assert np.argmax(spectrum) == 440                      # 1 Hz par case sur 1 s


def test_tone_level_and_fades():
    data = ad.tone(44100)
    assert np.max(np.abs(data)) == pytest.approx(0.3, abs=1e-3)
    assert data[0, 0] == 0.0 and abs(data[-1, 0]) < 1e-3   # sans clic
    fade = int(44100 * 0.01)                               # fondu linéaire de 10 ms
    assert np.max(np.abs(data[:100])) <= 0.3 * 100 / fade + 1e-3
    assert np.max(np.abs(data[fade:fade + 200])) > 0.29


def test_tone_other_settings():
    data = ad.tone(48000, freq=880.0, seconds=0.15, level=0.5)
    assert data.shape == (7200, 2)
    assert np.max(np.abs(data)) <= 0.5


def test_play_tone(fake_sd):
    ad.play_tone(4, samplerate=48000)
    kind, data, sr, device = fake_sd.calls[0]
    assert (kind, sr, device) == ("play", 48000, 4) and data.shape == (48000, 2)


def test_play_tone_refused(fake_sd):
    fake_sd.refuse.add(4)
    with pytest.raises(ad.AudioDeviceError, match="unavailable"):
        ad.play_tone(4)


def test_input_peak_db(fake_sd):
    rec = np.zeros((3 * 44100, 2), np.float32)
    rec[100, 1] = -0.125
    fake_sd.recorded = rec
    assert ad.input_peak_db(0) == pytest.approx(20 * math.log10(0.125))
    kind, frames, sr, channels, device, blocking = fake_sd.calls[0]
    # écoute de 3 secondes (essai de 11f1)
    assert (frames, sr, channels, device, blocking) == (3 * 44100, 44100, 2, 0, True)


def test_input_peak_db_mono_device_and_default(fake_sd):
    fake_sd.devs[0]["max_input_channels"] = 1
    ad.input_peak_db(0, seconds=0.5)
    assert fake_sd.calls[-1][1:4] == (22050, 44100, 1)
    ad.input_peak_db(None)
    assert fake_sd.calls[-1][3:5] == (1, None)


def test_input_peak_db_refused(fake_sd):
    fake_sd.refuse.add(0)
    with pytest.raises(ad.AudioDeviceError):
        ad.input_peak_db(0)


def test_peak_db_and_format():
    assert ad.peak_db(np.zeros((10, 2))) == float("-inf")
    assert ad.peak_db(np.ones((10, 2))) == 0.0
    assert ad.format_db(float("-inf")) == "silence"
    assert ad.format_db(-18.4) == "−18 dB"
    assert ad.format_db(0.0) == "0 dB"


# ---------------------------------------------------------------------------
# python3 -m devices
# ---------------------------------------------------------------------------

def test_cli_lists_everything(fake_sd, capsys):
    assert devices_cli.main([]) == 0
    out = capsys.readouterr().out
    assert "Pilotes : ALSA, OSS (défaut : ALSA)" in out
    assert "== ALSA ==" in out and "== OSS ==" in out
    assert "  - default  [défaut]" in out
    assert "Sorties (3) :" in out and "  - Carte B: HDMI 0 (hw:2,3)" in out


def test_cli_tone(fake_sd, capsys, monkeypatch):
    monkeypatch.setattr(devices_cli.time, "sleep", lambda s: None)
    assert devices_cli.main(["--tone", "pipewire"]) == 0
    assert fake_sd.calls[0][0] == "play" and fake_sd.calls[0][3] == 1
    assert "La 440 Hz joué sur « pipewire »" in capsys.readouterr().out


def test_cli_input(fake_sd, capsys):
    assert devices_cli.main(["--input", "Carte A: Analog (hw:1,0)"]) == 0
    assert "crête silence" in capsys.readouterr().out


def test_cli_unknown_device(fake_sd, capsys):
    assert devices_cli.main(["--tone", "nulle"]) == 1
    assert "introuvable dans ALSA" in capsys.readouterr().out


def test_cli_refused(fake_sd, capsys, monkeypatch):
    fake_sd.refuse.add(1)
    assert devices_cli.main(["--tone", "pipewire"]) == 1
    assert "Refusé par PortAudio" in capsys.readouterr().out


def test_cli_other_hostapi(fake_sd, capsys):
    assert devices_cli.main(["--pilote", "OSS", "--input", "/dev/dsp"]) == 0


# ---------------------------------------------------------------------------
# SoundDeviceDriver : périphérique et flux (H2, H5)
# ---------------------------------------------------------------------------

class FakeStream:
    opened = []

    def __init__(self, samplerate, blocksize, channels, dtype, callback, device=None):
        if device == 99:
            raise _PortAudioError("Device unavailable")
        self.device = device
        self.active = False
        self.closed = False
        FakeStream.opened.append(self)

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        self.closed = True


@pytest.fixture
def fake_stream(monkeypatch):
    FakeStream.opened = []
    monkeypatch.setattr(sdd.sd, "OutputStream", FakeStream)
    monkeypatch.setattr(sdd.sd, "PortAudioError", _PortAudioError)
    return FakeStream


def test_driver_opens_on_given_device(fake_stream):
    drv = SoundDeviceDriver(device=4)
    assert drv.device == 4
    assert fake_stream.opened[0].device == 4 and fake_stream.opened[0].active


def test_driver_default_device(fake_stream):
    assert SoundDeviceDriver().device is None
    assert fake_stream.opened[0].device is None


def test_set_device_reopens(fake_stream):
    drv = SoundDeviceDriver()
    first = fake_stream.opened[0]
    drv.set_device(1)
    assert first.closed and not first.active
    assert drv.device == 1 and drv._stream.device == 1 and drv._stream.active


def test_set_device_refused_keeps_previous(fake_stream):
    drv = SoundDeviceDriver(device=1)
    with pytest.raises(_PortAudioError):
        drv.set_device(99)
    assert drv.device == 1 and drv._stream.device == 1 and drv._stream.active
    assert len(fake_stream.opened) == 2          # le précédent rouvert


def test_voices_and_sources_survive_a_device_change(fake_stream):
    drv = SoundDeviceDriver()
    snd = SdSound(np.zeros((1000, 2), np.float32), 44100)
    drv.play(snd)
    source = lambda out: None
    drv.add_render_source(source)
    voices = list(drv._voices)
    drv.set_device(1)
    assert list(drv._voices) == voices and len(voices) == 1
    assert source in drv._render_sources


def test_stop_and_start_stream(fake_stream):
    drv = SoundDeviceDriver(device=2)
    drv.stop_stream()
    assert drv._stream is None and fake_stream.opened[0].closed
    drv.stop_stream()                              # deux fois : sans effet
    drv.start_stream()
    assert drv._stream.device == 2 and drv._stream.active
    drv.start_stream()                             # déjà ouvert : sans effet
    assert len(fake_stream.opened) == 2
    drv.stop_stream()
    drv.start_stream(4)                            # relu après rescan : nouvel indice
    assert drv.device == 4 and drv._stream.device == 4


def test_close_stops_the_stream(fake_stream):
    drv = SoundDeviceDriver()
    drv.close()
    assert drv._stream is None and fake_stream.opened[0].closed


# ---------------------------------------------------------------------------
# Clés de configuration (H1, H12, H16)
# ---------------------------------------------------------------------------

def _cfg(tmp_path, prefs=None):
    base = tmp_path / "app"
    os.makedirs(base / "data", exist_ok=True)
    path = tmp_path / "cfg" / "preferences.json"
    if prefs is not None:
        os.makedirs(path.parent, exist_ok=True)
        path.write_text(json.dumps(prefs), encoding="utf-8")
    return AppConfig(str(base), prefs_path=str(path))


def test_audio_keys_defaults(tmp_path):
    cfg = _cfg(tmp_path)
    assert cfg.audio_hostapi == ""
    assert cfg.audio_inputs == [] and cfg.audio_outputs == []
    assert cfg.audio_main_output == ""


def test_audio_lists_cleaned(tmp_path):
    cfg = _cfg(tmp_path, {"audio_outputs": [" pipewire ", "", 3, "pipewire", "Carte B"],
                          "audio_inputs": "pas une liste"})
    assert cfg.audio_outputs == ["pipewire", "Carte B"]
    assert cfg.audio_inputs == []


def test_main_output_when_checked(tmp_path):
    cfg = _cfg(tmp_path, {"audio_outputs": ["pipewire", "Carte B"],
                          "audio_main_output": "Carte B"})
    assert cfg.audio_main_output == "Carte B"


def test_main_output_unchecked_takes_first_checked(tmp_path):
    cfg = _cfg(tmp_path, {"audio_outputs": ["pipewire", "Carte B"],
                          "audio_main_output": "Carte C"})
    assert cfg.audio_main_output == "pipewire"
    assert _cfg(tmp_path, {"audio_outputs": ["Carte B"]}).audio_main_output == "Carte B"


def test_main_output_without_checked_outputs(tmp_path):
    assert _cfg(tmp_path, {"audio_main_output": "pipewire"}).audio_main_output == "pipewire"


def test_audio_hostapi(tmp_path):
    assert _cfg(tmp_path, {"audio_hostapi": " OSS "}).audio_hostapi == "OSS"


# ---------------------------------------------------------------------------
# Démarrage : _open_audio_driver, boîte et bip
# ---------------------------------------------------------------------------

class _RecordingDriver(Mixer):
    made = []
    refuse = set()

    def __init__(self, samplerate=Mixer.SAMPLERATE, blocksize=Mixer.BLOCKSIZE,
                 limiter=True, device=None):
        if device in _RecordingDriver.refuse:
            raise _PortAudioError("Device busy")
        super().__init__(samplerate)
        self.device = device
        self.limiter_arg = limiter
        _RecordingDriver.made.append(self)


@pytest.fixture
def startup(monkeypatch, fake_sd):
    _RecordingDriver.made = []
    _RecordingDriver.refuse = set()
    monkeypatch.setattr(main_window, "SoundDeviceDriver", _RecordingDriver)
    return SimpleNamespace(_device_notes=[])


def test_startup_on_main_output(tmp_path, startup):
    cfg = _cfg(tmp_path, {"audio_main_output": "Carte B: HDMI 0 (hw:2,3)"})
    drv = MainWindow._open_audio_driver(startup, cfg)
    assert drv.device == 4 and startup._device_notes == []


def test_startup_without_setting(tmp_path, startup):
    drv = MainWindow._open_audio_driver(startup, _cfg(tmp_path))
    assert drv.device is None and startup._device_notes == []


def test_startup_main_output_missing(tmp_path, startup):
    cfg = _cfg(tmp_path, {"audio_main_output": "Carte inexistante"})
    drv = MainWindow._open_audio_driver(startup, cfg)
    assert drv.device is None
    assert startup._device_notes == [
        "Sortie audio introuvable : Carte inexistante. Sortie par défaut utilisée."]


def test_startup_main_output_refused(tmp_path, startup):
    _RecordingDriver.refuse = {1}
    cfg = _cfg(tmp_path, {"audio_main_output": "pipewire"})
    drv = MainWindow._open_audio_driver(startup, cfg)
    assert drv.device is None
    assert startup._device_notes[0].startswith("Sortie audio refusée : pipewire (Device busy).")
    assert startup._device_notes[0].endswith("Sortie par défaut utilisée.")


def test_startup_default_refused_raises(tmp_path, startup):
    _RecordingDriver.refuse = {None}
    with pytest.raises(_PortAudioError):
        MainWindow._open_audio_driver(startup, _cfg(tmp_path))


def test_startup_uses_saved_hostapi(tmp_path, startup):
    cfg = _cfg(tmp_path, {"audio_hostapi": "OSS", "audio_main_output": "pipewire"})
    drv = MainWindow._open_audio_driver(startup, cfg)
    assert drv.device is None                     # pipewire n'est pas une sortie OSS
    assert "introuvable : pipewire" in startup._device_notes[0]


def test_startup_passes_limiter(tmp_path, startup):
    cfg = _cfg(tmp_path, {"live_limiter": False})
    assert MainWindow._open_audio_driver(startup, cfg).limiter_arg is False


class _Dialog:
    shown = []

    def __init__(self, parent, message, caption, style):
        self.message, self.caption, self.style = message, caption, style
        self.destroyed = False
        _Dialog.shown.append(self)

    def ShowModal(self):
        return wx.ID_OK

    def Destroy(self):
        self.destroyed = True


class _PlayDriver:
    samplerate = 44100

    def __init__(self, fail=False):
        self.played = []
        self.fail = fail

    def play(self, sound, vol=1.0, pan=0):
        if self.fail:
            raise RuntimeError("pas de son")
        self.played.append(sound)


@pytest.fixture
def notes_win(monkeypatch):
    _Dialog.shown = []
    monkeypatch.setattr(main_window.wx, "MessageDialog", _Dialog)
    win = SimpleNamespace(_device_notes=[], _audio_driver=_PlayDriver(),
                          ALERT_FREQS=MainWindow.ALERT_FREQS)
    win._alert_beep = lambda: MainWindow._alert_beep(win)
    return win


def test_device_box_one_device(notes_win):
    notes_win._device_notes = ["Sortie audio introuvable : Carte X. Sortie par défaut utilisée."]
    MainWindow._show_device_notes(notes_win)
    dlg = _Dialog.shown[0]
    assert dlg.caption == "Périphérique introuvable"
    assert dlg.message.startswith("Sortie audio introuvable : Carte X.")
    assert dlg.style & wx.OK and dlg.style & wx.ICON_WARNING
    assert dlg.destroyed


def test_device_box_several_devices(notes_win):
    notes_win._device_notes = ["Sortie A introuvable.", "Entrée B introuvable."]
    MainWindow._show_device_notes(notes_win)
    dlg = _Dialog.shown[0]
    assert dlg.caption == "2 périphériques introuvables"
    assert dlg.message == "Sortie A introuvable.\nEntrée B introuvable."


def test_device_box_beeps(notes_win):
    notes_win._device_notes = ["x"]
    MainWindow._show_device_notes(notes_win)
    (beep,) = notes_win._audio_driver.played
    assert isinstance(beep, SdSound) and beep.samplerate == 44100
    assert beep.data.shape == (int(44100 * 0.15) * 2, 2)       # deux bips de 0,15 s
    half = len(beep.data) // 2
    first = np.argmax(np.abs(np.fft.rfft(beep.data[:half, 0])))
    second = np.argmax(np.abs(np.fft.rfft(beep.data[half:, 0])))
    assert first > second                                      # descendants : 880 puis 660


def test_beep_falls_back_to_bell(notes_win, monkeypatch):
    rang = []
    monkeypatch.setattr(main_window.wx, "Bell", lambda: rang.append(1))
    notes_win._audio_driver = _PlayDriver(fail=True)
    MainWindow._alert_beep(notes_win)
    assert rang == [1]


def test_beep_without_driver(notes_win):
    notes_win._audio_driver = None
    MainWindow._alert_beep(notes_win)              # rien, sans erreur


# ---------------------------------------------------------------------------
# Sortie changée depuis les Préférences : _apply_audio_output (H2)
# ---------------------------------------------------------------------------

class _SwitchDriver:
    def __init__(self, device=None, refuse=()):
        self.device = device
        self.refuse = set(refuse)
        self.switched = []

    def set_device(self, device):
        if device in self.refuse:
            raise _PortAudioError("Device busy")
        self.switched.append(device)
        self.device = device


def _out_win(tmp_path, prefs, driver):
    return SimpleNamespace(_cfg=_cfg(tmp_path, prefs), _audio_driver=driver)


def test_apply_output_switches(tmp_path, fake_sd):
    win = _out_win(tmp_path, {"audio_main_output": "pipewire"}, _SwitchDriver())
    assert ProjectMixin._apply_audio_output(win) == "sortie audio : pipewire"
    assert win._audio_driver.switched == [1]


def test_apply_output_back_to_default(tmp_path, fake_sd):
    win = _out_win(tmp_path, {}, _SwitchDriver(device=1))
    assert ProjectMixin._apply_audio_output(win) == "sortie audio : défaut"
    assert win._audio_driver.switched == [None]


def test_apply_output_unchanged_does_nothing(tmp_path, fake_sd):
    win = _out_win(tmp_path, {"audio_main_output": "pipewire"}, _SwitchDriver(device=1))
    assert ProjectMixin._apply_audio_output(win) == ""
    assert win._audio_driver.switched == []


def test_apply_output_missing(tmp_path, fake_sd):
    win = _out_win(tmp_path, {"audio_main_output": "Carte X"}, _SwitchDriver(device=1))
    note = ProjectMixin._apply_audio_output(win)
    assert note == "Sortie audio introuvable : Carte X. Sortie par défaut utilisée."
    assert win._audio_driver.switched == [None]


def test_apply_output_refused_keeps_previous(tmp_path, fake_sd):
    win = _out_win(tmp_path, {"audio_main_output": "pipewire"},
                   _SwitchDriver(device=None, refuse={1}))
    note = ProjectMixin._apply_audio_output(win)
    assert note == "sortie audio refusée (Device busy) : sortie précédente gardée"
    assert win._audio_driver.device is None


def test_apply_output_without_driver(tmp_path, fake_sd):
    win = _out_win(tmp_path, {"audio_main_output": "pipewire"}, None)
    assert ProjectMixin._apply_audio_output(win) == ""
    win._audio_driver = object()                    # pilote sans set_device (Mixer, pygame)
    assert ProjectMixin._apply_audio_output(win) == ""


def _prefs_win(tmp_path, driver):
    win = _out_win(tmp_path, {}, driver)
    win.PREFS_AUDIO_OUT_KEYS = ProjectMixin.PREFS_AUDIO_OUT_KEYS
    win.PREFS_MIDI_KEYS = ProjectMixin.PREFS_MIDI_KEYS
    win._apply_preferences_now = lambda changes: []
    win._apply_audio_output = lambda: ProjectMixin._apply_audio_output(win)
    return win


def test_apply_preferences_announces_the_output(tmp_path, fake_sd):
    win = _prefs_win(tmp_path, _SwitchDriver())
    said = []
    ProjectMixin._apply_preferences(win, {"audio_outputs": ["pipewire"]}, said.append)
    assert said == ["Préférences enregistrées (1 réglage) ; sortie audio : pipewire"]
    assert win._audio_driver.device == 1


@pytest.mark.parametrize("key", ["audio_hostapi", "audio_outputs", "audio_main_output"])
def test_output_keys_trigger_the_switch(key):
    assert key in ProjectMixin.PREFS_AUDIO_OUT_KEYS


def test_other_keys_do_not_touch_the_output(tmp_path, fake_sd):
    win = _prefs_win(tmp_path, _SwitchDriver(device=7))
    said = []
    ProjectMixin._apply_preferences(win, {"audio_inputs": ["pipewire"]}, said.append)
    assert win._audio_driver.switched == []
    assert said == ["Préférences enregistrées (1 réglage)"]


# ---------------------------------------------------------------------------
# Vraie fenêtre principale : sortie absente au démarrage
# ---------------------------------------------------------------------------

def test_real_main_window_missing_output(isolated_preferences, monkeypatch):
    """Une seule vraie MainWindow (clients ALSA, cf. test_auto_input_mode)."""
    path = str(isolated_preferences)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"audio_main_output": "Carte inexistante"}, f)
    shown = []
    monkeypatch.setattr(wx.MessageDialog, "ShowModal",
                        lambda self: shown.append((self.GetTitle(), self.GetMessage())) or wx.ID_OK)
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    win = None
    try:
        win = MainWindow(no_fluidsynth=True, no_sfizz=True)
        assert shown == [("Périphérique introuvable",
                          "Sortie audio introuvable : Carte inexistante. "
                          "Sortie par défaut utilisée.")]
        assert win._audio_driver.device is None
        assert "Carte inexistante" in win._status_ctrl.GetString(0)
    finally:
        if win is not None:
            win._router.wait_loaded()     # fils de chargement finis avant Destroy
            win._midi.close()
            win._audio_driver.close()
            win.Destroy()
        os.remove(path)
