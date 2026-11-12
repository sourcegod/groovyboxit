#python3
"""
    File: tests/test_prefs_hardware.py
    Onglet Matériel des Préférences (Phase 8 étape 11f1, docs/DESIGN.md
    § Phase 8 étape 11a H2-H17 et essais de 11f1) : HardwarePage sur un
    matériel factice (ordre des contrôles, libellés, « (Aucun) »,
    périphérique absent gardé, pilote, sortie principale, Tester, Détecter,
    résultat sans déplacer le focus, Valeurs par défaut, réglages changés) ;
    mw_devices.HardwareAccess (listes, greffons ALSA masqués, Synthé
    FluidSynth, Détecter audio / MIDI, La 440 Hz, écoute de 3 s avec
    diagnostic et réécoute) ; audio_device (greffons, diagnostic, RMS,
    stéréo, nom d'un indice) ; midi_device (clients rtmidi retirés) ;
    ports MIDI rouverts depuis les Préférences.
    Date: Thu, 12/11/2026
    Author: Coolbrother
"""
import sys
import os
import json
import math
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest
import wx

from app_config import AppConfig
from devices import audio_device as ad
from devices import midi_device as md
from ui.dialogs_preferences import PreferencesDialog
from ui.prefs_hardware import HardwarePage, _CheckList, ABSENT_SUFFIX, MAIN_DEFAULT_LABEL
import ui.mw_devices as mw_devices
from ui.mw_devices import DevicesMixin, HardwareAccess
from ui.mw_project import ProjectMixin
from audio.sound_device_driver import SdSound

_APP = None


@pytest.fixture(autouse=True)
def wx_app_alive():
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)
    yield


# ---------------------------------------------------------------------------
# Matériel factice
# ---------------------------------------------------------------------------

class FakeHardware:
    def __init__(self):
        self.apis = ["ALSA", "OSS"]
        self.default_api = "ALSA"
        self.audio = {("ALSA", "input"): ["Carte: Analog (hw:0,0)", "pipewire"],
                      ("ALSA", "output"): ["pipewire", "pulse", "default"],
                      ("OSS", "input"): ["/dev/dsp"], ("OSS", "output"): []}
        self.m_in = ["Through 14:0", "MPK 20:0"]
        self.m_out = ["Synthé FluidSynth", "Through 14:0"]
        self.calls = []
        self.pending = []

    def hostapis(self):
        return list(self.apis)
    def default_hostapi(self):
        return self.default_api
    def audio_devices(self, api, kind):
        return list(self.audio.get((api, kind), []))
    def midi_inputs(self):
        return list(self.m_in)
    def midi_outputs(self):
        return list(self.m_out)
    def detect_audio(self):
        self.calls.append("detect_audio")
        return "audio relu"
    def detect_midi(self):
        self.calls.append("detect_midi")
        return "MIDI relu"
    def test_audio_output(self, api, name):
        self.calls.append(("out", api, name))
        return f"La 440 sur {name}"
    def test_audio_input(self, api, name, done):
        self.calls.append(("in", api, name))
        self.pending.append(done)
    def test_midi_output(self, name):
        self.calls.append(("mout", name))
        return f"A4 sur {name}"
    def test_midi_input(self, name, done):
        self.calls.append(("min", name))
        self.pending.append(done)


def _cfg(tmp_path, prefs=None):
    base = tmp_path / "app"
    os.makedirs(base / "data", exist_ok=True)
    path = tmp_path / "cfg" / "preferences.json"
    if prefs is not None:
        os.makedirs(path.parent, exist_ok=True)
        path.write_text(json.dumps(prefs), encoding="utf-8")
    return AppConfig(str(base), prefs_path=str(path))


@pytest.fixture
def dialog(tmp_path):
    made = []

    def build(prefs=None, hw=None):
        hw = hw or FakeHardware()
        applied = []
        dlg = PreferencesDialog(None, _cfg(tmp_path, prefs), on_apply=applied.append,
                                page=1, hardware=hw)
        made.append(dlg)
        return dlg, dlg._hw_page, hw, applied
    yield build
    for dlg in made:
        dlg.Destroy()


def _rows(checklist):
    return [checklist.ctrl.GetString(i) for i in range(checklist.ctrl.GetCount())]


def _check(checklist, row, on=True):
    """Coche une ligne comme l'utilisateur (événement de la liste)."""
    checklist.ctrl.Check(row, on)
    evt = wx.CommandEvent(wx.wxEVT_CHECKLISTBOX, checklist.ctrl.GetId())
    evt.SetInt(row)
    evt.SetEventObject(checklist.ctrl)
    checklist.ctrl.GetEventHandler().ProcessEvent(evt)


# ---------------------------------------------------------------------------
# Construction et ordre (H11, H13)
# ---------------------------------------------------------------------------

def test_without_hardware_a_sentence(tmp_path):
    dlg = PreferencesDialog(None, _cfg(tmp_path))
    try:
        children = dlg._pages["Matériel"].GetChildren()
        assert len(children) == 1 and isinstance(children[0], wx.StaticText)
        assert "Matériel" not in dlg._tab_keys and dlg._hw_page is None
    finally:
        dlg.Destroy()


def test_controls_order(dialog):
    dlg, page, hw, _ = dialog()
    kinds = [(type(c).__name__, c.GetLabel()) for c in dlg._pages["Matériel"].GetChildren()]
    assert kinds == [
        ("StaticText", "Pilote audio :"), ("Choice", ""),
        ("StaticText", "Entrées audio :"), ("CheckListBox", ""),
        ("Button", "Tester l'entrée audio"),
        ("StaticText", "Sorties audio :"), ("CheckListBox", ""),
        ("Button", "Tester la sortie audio"),
        ("StaticText", "Sortie principale :"), ("Choice", ""),
        ("Button", "Détecter les périphériques audio"),
        ("StaticText", "Entrées MIDI :"), ("CheckListBox", ""),
        ("Button", "Tester l'entrée MIDI"),
        ("StaticText", "Sorties MIDI :"), ("CheckListBox", ""),
        ("Button", "Tester la sortie MIDI"),
        ("Button", "Détecter les périphériques MIDI"),
        ("StaticText", "Résultat du test :"), ("TextCtrl", ""),
        ("Button", "Valeurs par défaut"),
    ]


def test_each_field_follows_its_label(dialog):
    dlg, *_ = dialog()
    children = list(dlg._pages["Matériel"].GetChildren())
    for i, c in enumerate(children):
        if isinstance(c, (wx.Choice, wx.CheckListBox, wx.TextCtrl)):
            assert isinstance(children[i - 1], wx.StaticText)


def test_result_is_read_only(dialog):
    _, page, *_ = dialog()
    assert not page.result.IsEditable()


# ---------------------------------------------------------------------------
# « (Aucun) » et cases
# ---------------------------------------------------------------------------

def test_none_first_in_every_list(dialog):
    _, page, *_ = dialog()
    for checklist in (page.audio_in, page.audio_out, page.midi_in, page.midi_out):
        assert _rows(checklist)[0] == "(Aucun)"
        assert checklist.ctrl.GetSelection() == 0           # curseur sur (Aucun)
        assert checklist.selected() is None


def test_none_checked_when_nothing_else(dialog):
    _, page, *_ = dialog({"midi_inputs": ["MPK 20:0"]})
    assert page.audio_in.ctrl.IsChecked(0)
    assert not page.midi_in.ctrl.IsChecked(0)
    _check(page.audio_in, 2)
    assert not page.audio_in.ctrl.IsChecked(0)
    _check(page.audio_in, 2, on=False)
    assert page.audio_in.ctrl.IsChecked(0)


def test_checking_none_clears_everything(dialog):
    _, page, *_ = dialog({"midi_inputs": ["MPK 20:0", "Through 14:0"]})
    _check(page.midi_in, 0)
    assert page.midi_in.checked() == [] and page.midi_in.ctrl.IsChecked(0)


def test_none_cannot_be_unchecked_alone(dialog):
    _, page, *_ = dialog()
    _check(page.audio_out, 0, on=False)
    assert page.audio_out.ctrl.IsChecked(0)


def test_absent_device_kept_and_checked(dialog):
    _, page, *_ = dialog({"midi_inputs": ["Clavier débranché 24:0"]})
    assert _rows(page.midi_in)[-1] == "Clavier débranché 24:0" + ABSENT_SUFFIX
    assert page.midi_in.checked() == ["Clavier débranché 24:0"]


def test_selection_kept_by_name_on_refill(dialog):
    _, page, hw, _ = dialog()
    page.audio_out.ctrl.SetSelection(2)                     # « pulse »
    hw.audio[("ALSA", "output")].insert(0, "Carte USB (hw:1,0)")
    page.detect_audio()
    assert page.audio_out.selected() == "pulse"


# ---------------------------------------------------------------------------
# Valeurs, pilote, sortie principale (H1, H3, H12, H16)
# ---------------------------------------------------------------------------

def test_values_from_preferences(dialog):
    dlg, page, *_ = dialog({"audio_hostapi": "ALSA", "audio_inputs": ["pipewire"],
                            "audio_outputs": ["pulse", "default"],
                            "audio_main_output": "default",
                            "midi_inputs": ["MPK 20:0"], "midi_outputs": ["Through 14:0"]})
    assert page.values() == {"audio_hostapi": "ALSA", "audio_inputs": ["pipewire"],
                             "audio_outputs": ["pulse", "default"],
                             "audio_main_output": "default",
                             "midi_inputs": ["MPK 20:0"], "midi_outputs": ["Through 14:0"]}
    assert dlg.changes() == {}


def test_default_values_shown(dialog):
    dlg, page, *_ = dialog()
    assert page.values() == {"audio_hostapi": "ALSA", "audio_inputs": [], "audio_outputs": [],
                             "audio_main_output": "", "midi_inputs": [],
                             "midi_outputs": ["Synthé FluidSynth"]}
    assert dlg.changes() == {}


def test_synth_not_proposed_without_library(dialog):
    hw = FakeHardware()
    hw.m_out = ["Through 14:0"]
    _, page, *_ = dialog(hw=hw)
    assert page.values()["midi_outputs"] == []
    assert "Synthé FluidSynth" not in _rows(page.midi_out)


def test_unknown_saved_hostapi_shows_default(dialog):
    _, page, *_ = dialog({"audio_hostapi": "JACK"})
    assert page.hostapi.GetStringSelection() == "ALSA"


def test_changing_hostapi_refills_and_keeps_checks(dialog):
    dlg, page, hw, _ = dialog({"audio_inputs": ["pipewire"]})
    hw.audio[("OSS", "input")] = ["/dev/dsp", "pipewire"]
    page.hostapi.SetStringSelection("OSS")
    page._on_hostapi()
    assert _rows(page.audio_in)[1:] == ["/dev/dsp", "pipewire"]
    assert page.audio_in.checked() == ["pipewire"]
    assert dlg.changes() == {"audio_hostapi": "OSS"}


def test_main_output_follows_checked_outputs(dialog):
    _, page, *_ = dialog()
    assert [page.main_output.GetString(i) for i in range(page.main_output.GetCount())] == \
        [MAIN_DEFAULT_LABEL]
    _check(page.audio_out, 1)                                # pipewire
    _check(page.audio_out, 3)                                # default
    # sorties cochées seulement, comme AppConfig.audio_main_output (H16)
    assert [page.main_output.GetString(i) for i in range(page.main_output.GetCount())] == \
        ["pipewire", "default"]
    assert page.values()["audio_main_output"] == "pipewire"  # première cochée
    page.main_output.SetSelection(1)
    assert page.values()["audio_main_output"] == "default"
    _check(page.audio_out, 3, on=False)                      # principale décochée
    assert page.values()["audio_main_output"] == "pipewire"
    _check(page.audio_out, 0)                                # (Aucun) : tout décoché
    assert [page.main_output.GetString(i) for i in range(page.main_output.GetCount())] == \
        [MAIN_DEFAULT_LABEL]
    assert page.values()["audio_main_output"] == ""


def test_changes_and_none_for_defaults(dialog):
    dlg, page, hw, applied = dialog({"midi_outputs": ["Through 14:0"]})
    _check(page.midi_in, 2)
    _check(page.midi_out, 1)                                 # Synthé FluidSynth
    _check(page.midi_out, 2, on=False)                       # Through décoché
    assert dlg.changes() == {"midi_inputs": ["MPK 20:0"], "midi_outputs": ["Synthé FluidSynth"]}
    dlg._apply()
    assert applied == [{"midi_inputs": ["MPK 20:0"], "midi_outputs": None}]   # défaut retiré


def test_hardware_default_values_button(dialog):
    dlg, page, *_ = dialog({"audio_outputs": ["pulse"], "midi_inputs": ["MPK 20:0"],
                            "midi_outputs": []})
    dlg.restore_defaults("Matériel")
    assert page.values() == {"audio_hostapi": "ALSA", "audio_inputs": [], "audio_outputs": [],
                             "audio_main_output": "", "midi_inputs": [],
                             "midi_outputs": ["Synthé FluidSynth"]}
    assert dlg._default_btns["Matériel"].GetLabel() == "Valeurs par défaut"


# ---------------------------------------------------------------------------
# Tester, Détecter, résultat (H5, H9, H14, H17)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method, what", [
    ("test_audio_input", "une entrée audio"), ("test_audio_output", "une sortie audio"),
    ("test_midi_input", "une entrée MIDI"), ("test_midi_output", "une sortie MIDI")])
def test_nothing_selected(dialog, method, what):
    _, page, hw, _ = dialog()
    getattr(page, method)()
    assert page.result.GetValue() == f"Choisissez d'abord {what} dans la liste."
    assert hw.calls == []


def test_test_audio_output(dialog):
    _, page, hw, _ = dialog()
    page.audio_out.ctrl.SetSelection(2)
    page.test_audio_output()
    assert hw.calls == [("out", "ALSA", "pulse")]
    assert page.result.GetValue() == "La 440 sur pulse"


def test_test_unchecked_line(dialog):
    # on peut tester une ligne avant de la cocher
    _, page, hw, _ = dialog()
    page.midi_out.ctrl.SetSelection(2)
    page.test_midi_output()
    assert hw.calls == [("mout", "Through 14:0")] and page.midi_out.checked() == ["Synthé FluidSynth"]


def test_test_audio_input_async(dialog):
    _, page, hw, _ = dialog()
    page.audio_in.ctrl.SetSelection(2)
    page.test_audio_input()
    assert page.result.GetValue() == "Entrée audio pipewire : parlez ou jouez pendant 3 secondes…"
    hw.pending.pop()("Entrée audio pipewire : signal présent")
    assert page.result.GetValue() == "Entrée audio pipewire : signal présent"


def test_test_midi_input_async(dialog):
    _, page, hw, _ = dialog()
    page.midi_in.ctrl.SetSelection(2)
    page.test_midi_input()
    assert page.result.GetValue() == "Entrée MIDI MPK 20:0 : jouez une note (5 secondes)…"
    hw.pending.pop()("note A4")
    assert page.result.GetValue() == "note A4"


def test_result_does_not_take_the_focus(dialog, monkeypatch):
    _, page, *_ = dialog()
    moved = []
    monkeypatch.setattr(page.result, "SetFocus", lambda: moved.append(1))
    page.audio_out.ctrl.SetSelection(1)
    page.test_audio_output()
    page.detect_midi()
    assert moved == []


def test_detect_buttons(dialog):
    _, page, hw, _ = dialog()
    hw.m_in.append("Nouveau 28:0")
    page.detect_midi()
    assert _rows(page.midi_in)[-1] == "Nouveau 28:0"
    assert page.result.GetValue() == "MIDI relu"
    page.detect_audio()
    assert hw.calls == ["detect_midi", "detect_audio"] and page.result.GetValue() == "audio relu"


def test_say_after_close(dialog):
    _, page, *_ = dialog()
    page.result = None                          # champ détruit (dialogue fermé)
    page.say("trop tard")                       # sans erreur


# ---------------------------------------------------------------------------
# devices : greffons ALSA, diagnostic, clients rtmidi
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, api, plugin", [
    ("lavrate", "ALSA", True), ("speex", "ALSA", True), ("upmix", "ALSA", True),
    ("sysdefault", "ALSA", True), ("HDA Intel PCH: ALC257 Analog (hw:0,0)", "ALSA", False),
    ("default", "ALSA", False), ("pipewire", "ALSA", False), ("pulse", "ALSA", False),
    ("/dev/dsp", "OSS", False)])
def test_is_alsa_plugin(name, api, plugin):
    assert ad.is_alsa_plugin(name, api) is plugin


def test_devices_hide_plugins(monkeypatch):
    monkeypatch.setattr(ad, "_devices", lambda api, kind: list(enumerate(
        ["Carte (hw:0,0)", "lavrate", "pipewire", "speex", "default"])))
    assert ad.devices("ALSA", "input") == ["Carte (hw:0,0)", "lavrate", "pipewire", "speex", "default"]
    assert ad.devices("ALSA", "input", hide_plugins=True) == ["Carte (hw:0,0)", "pipewire", "default"]


def test_analyse_silence():
    verdict, rms, peak = ad.analyse_input(np.zeros((1000, 2), np.float32))
    assert verdict == ad.SILENT and rms == float("-inf")
    assert ad.describe_input(verdict, rms, peak) == "silence (rien ne rentre)"


def test_analyse_stuck():
    data = -np.ones((1000, 1), np.float32)
    data[:100] = 0.1
    verdict, rms, peak = ad.analyse_input(data)
    assert verdict == ad.STUCK
    assert ad.describe_input(verdict, rms, peak) == \
        "signal bloqué à pleine échelle : entrée saturée ou inutilisable"


def test_analyse_present_with_noise_peak():
    rng = np.random.default_rng(0)
    data = (0.1 * rng.standard_normal((44100, 2))).astype(np.float32)
    data[500, 0] = 0.98                          # un pic de souffle : crête près de 0 dB
    verdict, rms, peak = ad.analyse_input(data)
    assert verdict == ad.PRESENT
    assert rms == pytest.approx(-20.0, abs=0.5) and peak > -1.0
    assert ad.describe_input(verdict, rms, peak) == \
        f"signal présent — niveau moyen {ad.format_db(rms)}, crête {ad.format_db(peak)}"


def test_analyse_very_quiet_is_silence():
    data = np.full((1000, 1), 1e-5, np.float32)  # −100 dB
    assert ad.analyse_input(data)[0] == ad.SILENT


def test_rms_db():
    assert ad.rms_db(np.ones((10, 2))) == 0.0
    assert ad.rms_db(np.full((10, 1), 0.1)) == pytest.approx(-20.0)
    assert ad.rms_db(np.zeros((0, 2))) == float("-inf")


@pytest.mark.parametrize("shape", [(100,), (100, 1), (100, 2), (100, 4)])
def test_to_stereo(shape):
    data = np.arange(np.prod(shape), dtype=np.float64).reshape(shape)
    out = ad.to_stereo(data)
    assert out.shape == (100, 2) and out.dtype == np.float32 and out.flags["C_CONTIGUOUS"]


def test_record_input_default_three_seconds(monkeypatch):
    seen = {}
    fake = SimpleNamespace(PortAudioError=RuntimeError,
                           query_devices=lambda d: {"max_input_channels": 1},
                           rec=lambda frames, **kw: seen.update(frames=frames, **kw) or
                           np.zeros((frames, 1), np.float32))
    monkeypatch.setattr(ad, "sd", fake)
    data = ad.record_input(3)
    assert seen["frames"] == 3 * 44100 and seen["channels"] == 1 and data.shape == (132300, 1)


def test_device_name(monkeypatch):
    fake = SimpleNamespace(PortAudioError=RuntimeError,
                           query_devices=lambda i: {"name": f"dev{i}"} if i < 3 else
                           (_ for _ in ()).throw(ValueError("no")))
    monkeypatch.setattr(ad, "sd", fake)
    assert ad.device_name(2) == "dev2"
    assert ad.device_name(None) == "" and ad.device_name(9) == ""


@pytest.mark.parametrize("name, own", [
    ("RtMidiIn Client:RtMidi input 133:0", True), ("RtMidiOut Client:RtMidi output 140:0", True),
    ("devices:devices 150:0", True), ("MPK mini Plus:MPK mini Plus MIDI 1 20:0", False),
    ("Midi Through:Midi Through Port-0 14:0", False)])
def test_is_own_port(name, own):
    assert md.is_own_port(name) is own


def test_ports_without_rtmidi_clients(monkeypatch):
    made = []

    class Probe:
        def __init__(self, name=None):
            made.append(name)
        def get_ports(self):
            return ["Through 14:0", "RtMidiIn Client:RtMidi input 133:0", "devices:x 150:0"]
        def delete(self):
            pass
    monkeypatch.setattr(md, "rtmidi", SimpleNamespace(MidiIn=Probe, MidiOut=Probe))
    assert md.input_ports() == ["Through 14:0"]
    assert md.output_ports() == ["Through 14:0"]
    assert made == [md.CLIENT_NAME, md.CLIENT_NAME]          # nos clients sont nommés


# ---------------------------------------------------------------------------
# HardwareAccess
# ---------------------------------------------------------------------------

class _Driver:
    samplerate = 44100

    def __init__(self, device=None):
        self.device = device
        self.played = []
        self.events = []
    def play(self, sound, vol=1.0, pan=0):
        self.played.append(sound)
    def stop_stream(self):
        self.events.append("stop")
    def start_stream(self, device=None):
        self.events.append(("start", device))
        self.device = device


def _access(tmp_path, driver=None, prefs=None):
    win = SimpleNamespace(_cfg=_cfg(tmp_path, prefs or {}), _audio_driver=driver)
    win._test_midi_output = lambda name: f"A4 {name}"
    win._listen_midi_input = lambda name, done: done(f"écoute {name}")
    return HardwareAccess(win)


def test_access_lists(tmp_path, monkeypatch):
    monkeypatch.setattr(ad, "devices", lambda api, kind, hide_plugins=False:
                        ["Carte (hw:0,0)"] if hide_plugins else ["Carte (hw:0,0)", "lavrate"])
    monkeypatch.setattr(md, "input_ports", lambda: ["MPK 20:0"])
    monkeypatch.setattr(md, "output_ports", lambda: ["Through 14:0"])
    import audio.engines.fluidsynth_engine as fe
    monkeypatch.setattr(fe, "fluidsynth_available", lambda: True)
    hw = _access(tmp_path)
    assert hw.audio_devices("ALSA", "input") == ["Carte (hw:0,0)"]     # greffons masqués
    assert hw.midi_inputs() == ["MPK 20:0"]
    assert hw.midi_outputs() == ["Synthé FluidSynth", "Through 14:0"]
    monkeypatch.setattr(fe, "fluidsynth_available", lambda: False)
    assert hw.midi_outputs() == ["Through 14:0"]


def test_detect_audio_reopens_same_output(tmp_path, monkeypatch):
    names = {4: "pipewire"}
    monkeypatch.setattr(ad, "device_name", lambda i: names.get(i, ""))
    monkeypatch.setattr(ad, "rescan", lambda: driver.events.append("rescan"))
    monkeypatch.setattr(ad, "default_hostapi", lambda: "ALSA")
    monkeypatch.setattr(ad, "find_device", lambda name, api, kind: 7 if name == "pipewire" else None)
    monkeypatch.setattr(ad, "hostapis", lambda: ["ALSA"])
    monkeypatch.setattr(ad, "devices", lambda api, kind, hide_plugins=False: ["a", "b"])
    driver = _Driver(device=4)
    msg = _access(tmp_path, driver).detect_audio()
    assert driver.events == ["stop", "rescan", ("start", 7)]  # nouvel indice, même nom
    assert msg == "Périphériques audio relus : 4 entrées et sorties"


def test_detect_audio_default_output(tmp_path, monkeypatch):
    monkeypatch.setattr(ad, "rescan", lambda: None)
    monkeypatch.setattr(ad, "hostapis", lambda: [])
    driver = _Driver(device=None)
    _access(tmp_path, driver).detect_audio()
    assert driver.events == ["stop", ("start", None)]


def test_detect_midi(tmp_path, monkeypatch):
    monkeypatch.setattr(md, "input_ports", lambda: ["a", "b"])
    monkeypatch.setattr(md, "output_ports", lambda: ["c"])
    assert _access(tmp_path).detect_midi() == "Périphériques MIDI relus : 2 entrées, 1 sorties"


def test_tone_through_the_app_driver(tmp_path, monkeypatch):
    monkeypatch.setattr(ad, "find_device", lambda n, a, k: 4)
    monkeypatch.setattr(ad, "play_tone", lambda idx: pytest.fail("ouverture en double"))
    driver = _Driver(device=4)
    msg = _access(tmp_path, driver).test_audio_output("ALSA", "pipewire")
    assert msg == "Sortie audio pipewire : La 440 Hz joué pendant une seconde"
    (snd,) = driver.played
    assert isinstance(snd, SdSound) and snd.data.shape == (44100, 2)


def test_tone_on_another_output(tmp_path, monkeypatch):
    played = []
    monkeypatch.setattr(ad, "find_device", lambda n, a, k: 5)
    monkeypatch.setattr(ad, "play_tone", played.append)
    driver = _Driver(device=4)
    _access(tmp_path, driver).test_audio_output("ALSA", "pulse")
    assert played == [5] and driver.played == []


def test_tone_missing_or_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(ad, "find_device", lambda n, a, k: None)
    assert _access(tmp_path).test_audio_output("ALSA", "x") == "Sortie audio x : introuvable"

    def refuse(idx):
        raise ad.AudioDeviceError("occupé")
    monkeypatch.setattr(ad, "find_device", lambda n, a, k: 5)
    monkeypatch.setattr(ad, "play_tone", refuse)
    assert _access(tmp_path).test_audio_output("ALSA", "x") == "Sortie audio x : refusée (occupé)"


@pytest.fixture
def sync_call_after(monkeypatch):
    monkeypatch.setattr(mw_devices.wx, "CallAfter", lambda fn, *a: fn(*a))


def _listen(tmp_path, monkeypatch, data, driver):
    monkeypatch.setattr(ad, "find_device", lambda n, a, k: 2)
    monkeypatch.setattr(ad, "record_input", lambda idx, samplerate=44100: data)
    said = []
    _access(tmp_path, driver).test_audio_input("ALSA", "pipewire", said.append).join(2)
    return said


def test_input_present_replayed(tmp_path, monkeypatch, sync_call_after):
    data = np.full((44100, 1), 0.1, np.float32)
    driver = _Driver()
    said = _listen(tmp_path, monkeypatch, data, driver)
    assert said == ["Entrée audio pipewire : signal présent — niveau moyen −20 dB, crête −20 dB"
                    " ; réécoute des 3 secondes captées"]
    (snd,) = driver.played
    assert snd.data.shape == (44100, 2)                       # mono rejoué en stéréo


def test_input_stuck_not_replayed(tmp_path, monkeypatch, sync_call_after):
    driver = _Driver()
    said = _listen(tmp_path, monkeypatch, -np.ones((1000, 2), np.float32), driver)
    assert "bloqué" in said[0] and driver.played == []


def test_input_silent_not_replayed(tmp_path, monkeypatch, sync_call_after):
    driver = _Driver()
    said = _listen(tmp_path, monkeypatch, np.zeros((1000, 2), np.float32), driver)
    assert said == ["Entrée audio pipewire : silence (rien ne rentre)"] and driver.played == []


def test_input_missing_or_refused(tmp_path, monkeypatch, sync_call_after):
    monkeypatch.setattr(ad, "find_device", lambda n, a, k: None)
    said = []
    _access(tmp_path).test_audio_input("ALSA", "x", said.append).join(2)
    assert said == ["Entrée audio x : introuvable"]

    def refuse(idx, samplerate=44100):
        raise ad.AudioDeviceError("occupé")
    monkeypatch.setattr(ad, "find_device", lambda n, a, k: 2)
    monkeypatch.setattr(ad, "record_input", refuse)
    _access(tmp_path).test_audio_input("ALSA", "x", said.append).join(2)
    assert said[-1] == "Entrée audio x : refusée (occupé)"


def test_midi_tests_delegate(tmp_path):
    hw = _access(tmp_path)
    said = []
    assert hw.test_midi_output("Through") == "A4 Through"
    hw.test_midi_input("MPK", said.append)
    assert said == ["écoute MPK"]


# ---------------------------------------------------------------------------
# Ports MIDI rouverts depuis les Préférences
# ---------------------------------------------------------------------------

def test_apply_midi_devices(tmp_path):
    calls = []
    win = SimpleNamespace(
        _close_midi_devices=lambda: calls.append("close"),
        _open_midi_devices=lambda: (calls.append("open") or (["MPK"], ["Entrée MIDI introuvable : X."])),
        _show_device_notes=lambda notes: calls.append(("box", notes)))
    assert DevicesMixin._apply_midi_devices(win) == ["Entrée MIDI introuvable : X."]
    assert calls == ["close", "open", ("box", ["Entrée MIDI introuvable : X."])]


def test_apply_preferences_reopens_midi(tmp_path):
    win = SimpleNamespace(_cfg=_cfg(tmp_path), PREFS_AUDIO_OUT_KEYS=ProjectMixin.PREFS_AUDIO_OUT_KEYS,
                          PREFS_MIDI_KEYS=ProjectMixin.PREFS_MIDI_KEYS)
    win._apply_preferences_now = lambda changes: []
    reopened = []
    win._apply_midi_devices = lambda: reopened.append(1) or []
    said = []
    ProjectMixin._apply_preferences(win, {"midi_inputs": ["MPK"]}, said.append)
    assert reopened == [1] and said == ["Préférences enregistrées (1 réglage) ; MIDI rouvert"]
    win._apply_midi_devices = lambda: ["Sortie MIDI introuvable : Y."]
    ProjectMixin._apply_preferences(win, {"midi_outputs": ["Y"]}, said.append)
    assert said[-1].endswith("MIDI rouvert — Sortie MIDI introuvable : Y.")
    ProjectMixin._apply_preferences(win, {"autoplay": False}, said.append)
    assert said[-1] == "Préférences enregistrées (1 réglage)"


def test_open_preferences_passes_the_hardware(tmp_path, monkeypatch):
    import ui.dialogs_preferences as dp
    seen = {}

    class Dlg:
        def __init__(self, parent, cfg, on_apply=None, page=0, hardware=None):
            seen.update(page=page, hardware=hardware)
        def ShowModal(self):
            return wx.ID_OK
        def Destroy(self):
            pass
    monkeypatch.setattr(dp, "PreferencesDialog", Dlg)
    hw = object()
    win = SimpleNamespace(_cfg=_cfg(tmp_path), _show_status=lambda m: None,
                          _hardware=lambda: hw)
    ProjectMixin._open_preferences(win, page=1)
    assert seen == {"page": 1, "hardware": hw}
