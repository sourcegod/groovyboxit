#python3
"""
    File: tests/test_midi_device.py
    Périphériques MIDI (Phase 8 étape 11d1, docs/DESIGN.md § Phase 8 étape
    11a H6, H8, H9, H12, H14, H15 et essais) : devices.midi_device sur un
    rtmidi factice (ports par nom, adresse ALSA changée, plusieurs entrées
    ensemble, sorties, A4 d'une seconde, prochaine note, sans rtmidi) ;
    python3 -m devices --note / --listen ; MidiManager.open_names ; clés
    midi_inputs / midi_outputs ; DevicesMixin (ouverture au démarrage,
    Shift+F12, Ctrl+Shift+F12, boîte bloquante, tests de sortie et
    d'entrée) ; raccourcis F12 dans les trois fenêtres, Alt+M retiré ; vraie
    fenêtre principale avec une entrée introuvable.
    Date: Wed, 11/11/2026
    Author: Coolbrother
"""
import sys
import os
import json
import threading
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import wx

from app_config import AppConfig
from devices import midi_device as md
from devices import __main__ as devices_cli
import midi.midi_manager as mm_module
from midi.midi_manager import MidiManager
from ui.mw_devices import DevicesMixin
import ui.mw_devices as mw_devices
import ui.main_window as main_window
from ui.main_window import MainWindow
from ui.song_window import SongWindow
import ui.midi_editor_window as mew
from ui.key_manager import KeyManager
from test_key_manager import FakeWindow, FakeEvent


_APP = None


@pytest.fixture(autouse=True)
def wx_app_alive():
    """Un fichier de tests précédent peut détruire la wx.App de la session
    (make_km / teardown) : la recréer et la garder dans le module."""
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)
    yield


# ---------------------------------------------------------------------------
# rtmidi factice
# ---------------------------------------------------------------------------

class FakeRtmidi:
    def __init__(self, ins=("Through 14:0", "MPK mini Plus:MPK mini Plus MIDI 1 20:0"),
                 outs=("Through 14:0", "Synth USB 24:0")):
        self.ins, self.outs = list(ins), list(outs)
        self.refuse = set()
        self.midi_ins, self.midi_outs = [], []
        rt = self

        class MidiIn:
            def __init__(self):
                self.port = None
                self.callback = None
                self.ignored = None
                self.cancelled = self.closed = False
                rt.midi_ins.append(self)
            def get_ports(self):
                return list(rt.ins)
            def open_port(self, idx):
                if rt.ins[idx] in rt.refuse:
                    raise RuntimeError("port occupé")
                self.port = rt.ins[idx]
            def ignore_types(self, **kw):
                self.ignored = kw
            def set_callback(self, fn, data=None):
                self.callback = (fn, data)
            def cancel_callback(self):
                self.cancelled = True
            def close_port(self):
                self.closed = True
            def receive(self, message):
                fn, data = self.callback
                fn((message, 0.0), data)

        class MidiOut:
            def __init__(self):
                self.port = None
                self.sent = []
                self.closed = False
                rt.midi_outs.append(self)
            def get_ports(self):
                return list(rt.outs)
            def open_port(self, idx):
                if rt.outs[idx] in rt.refuse:
                    raise RuntimeError("port occupé")
                self.port = rt.outs[idx]
            def send_message(self, msg):
                self.sent.append(list(msg))
            def close_port(self):
                self.closed = True

        self.MidiIn, self.MidiOut = MidiIn, MidiOut

    def opened_ins(self):
        return [m for m in self.midi_ins if m.port is not None]


@pytest.fixture
def rt(monkeypatch):
    fake = FakeRtmidi()
    monkeypatch.setattr(md, "rtmidi", fake)
    monkeypatch.setattr(mm_module, "rtmidi", fake)
    monkeypatch.setattr(mm_module, "_RTMIDI_AVAILABLE", True)
    return fake


MPK = "MPK mini Plus:MPK mini Plus MIDI 1 20:0"


# ---------------------------------------------------------------------------
# Noms et ports
# ---------------------------------------------------------------------------

def test_package_has_midi_device():
    assert "midi_device.py" in os.listdir(os.path.join(os.path.dirname(__file__),
                                                       "..", "src", "devices"))


@pytest.mark.parametrize("note, name", [(60, "C4"), (69, "A4"), (0, "C-1"), (127, "G9"),
                                        (61, "C#4")])
def test_note_name(note, name):
    assert md.note_name(note) == name


def test_ports(rt):
    assert md.input_ports() == ["Through 14:0", MPK]
    assert md.output_ports() == ["Through 14:0", "Synth USB 24:0"]


def test_without_rtmidi(monkeypatch):
    monkeypatch.setattr(md, "rtmidi", None)
    assert not md.available()
    assert md.input_ports() == [] and md.output_ports() == []
    assert md.MidiInputs(lambda m, n: None).open_names(["X"]) == ([], ["X"])
    with pytest.raises(md.MidiDeviceError):
        md.open_output("X")


@pytest.mark.parametrize("name, base", [
    (MPK, "MPK mini Plus:MPK mini Plus MIDI 1"),
    ("Through 14:0", "Through"),
    ("Sans adresse", "Sans adresse"),
    ("Nom 12:3 au milieu", "Nom 12:3 au milieu"),
])
def test_base_name(name, base):
    assert md.base_name(name) == base


def test_find_port_address_changed():
    ports = ["Through 14:0", "MPK mini Plus:MPK mini Plus MIDI 1 24:0"]
    assert md.find_port(ports, MPK) == "MPK mini Plus:MPK mini Plus MIDI 1 24:0"
    assert md.find_port(ports, "Autre 20:0") is None


def test_find_port_prefers_exact_name():
    ports = ["Synth 20:0", "Synth 21:0"]
    assert md.find_port(ports, "Synth 21:0") == "Synth 21:0"
    assert md.find_port(ports, "Synth 99:0") == "Synth 20:0"


# ---------------------------------------------------------------------------
# MidiInputs : plusieurs entrées ensemble
# ---------------------------------------------------------------------------

def test_open_several_inputs(rt):
    got = []
    ins = md.MidiInputs(lambda m, n: got.append((m, n)))
    assert ins.open_names([MPK, "Through 14:0", "Absent"]) == ([MPK, "Through 14:0"], ["Absent"])
    assert ins.names == [MPK, "Through 14:0"] and ins.is_open()
    a, b = rt.opened_ins()
    assert (a.port, b.port) == (MPK, "Through 14:0")
    assert a.ignored == {"sysex": True, "timing": True, "active_sense": True}
    a.receive([0x90, 60, 100])
    b.receive([0x80, 62, 0])
    assert got == [([0x90, 60, 100], MPK), ([0x80, 62, 0], "Through 14:0")]


def test_empty_message_ignored(rt):
    got = []
    ins = md.MidiInputs(lambda m, n: got.append(m))
    ins.open_names([MPK])
    rt.opened_ins()[0].receive([])
    assert got == []


def test_already_open_kept(rt):
    ins = md.MidiInputs(lambda m, n: None)
    ins.open_names([MPK])
    assert ins.open_names([MPK]) == ([MPK], [])
    assert len(rt.opened_ins()) == 1


def test_input_found_after_address_change(rt):
    rt.ins = ["MPK mini Plus:MPK mini Plus MIDI 1 24:0"]
    ins = md.MidiInputs(lambda m, n: None)
    assert ins.open_names([MPK]) == ([MPK], [])          # nom enregistré gardé
    assert rt.opened_ins()[0].port == "MPK mini Plus:MPK mini Plus MIDI 1 24:0"


def test_refused_input_counts_as_missing(rt):
    rt.refuse.add(MPK)
    ins = md.MidiInputs(lambda m, n: None)
    assert ins.open_names([MPK]) == ([], [MPK])
    assert not ins.is_open()


def test_close_and_close_all(rt):
    ins = md.MidiInputs(lambda m, n: None)
    ins.open_names([MPK, "Through 14:0"])
    a, b = rt.opened_ins()
    ins.close(MPK)
    assert a.cancelled and a.closed and ins.names == ["Through 14:0"]
    ins.close("pas ouvert")
    ins.close_all()
    assert b.closed and not ins.is_open()


# ---------------------------------------------------------------------------
# Sorties, A4, prochaine note
# ---------------------------------------------------------------------------

def test_open_output(rt):
    out = md.open_output("Synth USB 24:0")
    assert out.port == "Synth USB 24:0"
    assert md.open_output("Synth USB 30:0").port == "Synth USB 24:0"


def test_open_output_missing_or_refused(rt):
    with pytest.raises(md.MidiDeviceError, match="introuvable"):
        md.open_output("Absent")
    rt.refuse.add("Synth USB 24:0")
    with pytest.raises(md.MidiDeviceError, match="occupé"):
        md.open_output("Synth USB 24:0")


def test_send_test_note():
    out = SimpleNamespace(sent=[])
    out.send_message = lambda m: out.sent.append(list(m))
    timer = md.send_test_note(out, seconds=0.01)
    assert out.sent == [[0x90, 69, 100]]
    timer.join(1)
    assert out.sent == [[0x90, 69, 100], [0x80, 69, 0]]


def test_send_test_note_defaults_and_channel():
    assert (md.TEST_NOTE, md.TEST_SECONDS) == (69, 1.0)
    out = SimpleNamespace(sent=[])
    out.send_message = lambda m: out.sent.append(list(m))
    md.send_test_note(out, channel=9, seconds=0.01).join(1)
    assert out.sent == [[0x99, 69, 100], [0x89, 69, 0]]


@pytest.mark.parametrize("msg, yes", [([0x90, 60, 1], True), ([0x9F, 60, 127], True),
                                      ([0x90, 60, 0], False), ([0x80, 60, 64], False),
                                      ([0xB0, 1, 64], False), ([0x90, 60], False)])
def test_is_note_on(msg, yes):
    assert md.is_note_on(msg) is yes


def test_wait_note_receives_the_next_note(rt):
    def play():
        for _ in range(100):
            ins = rt.opened_ins()
            if ins and ins[-1].callback:
                ins[-1].receive([0xB0, 1, 10])          # CC ignoré
                ins[-1].receive([0x93, 69, 90])
                return
            time.sleep(0.01)
    threading.Thread(target=play).start()
    assert md.wait_note(MPK, timeout=2) == (69, 90, 3)
    assert rt.opened_ins()[-1].closed                   # accès refermé


def test_wait_note_timeout(rt):
    assert md.wait_note(MPK, timeout=0.05) is None


def test_wait_note_missing_port(rt):
    with pytest.raises(md.MidiDeviceError, match="introuvable"):
        md.wait_note("Absent", timeout=0.05)


# ---------------------------------------------------------------------------
# python3 -m devices
# ---------------------------------------------------------------------------

def test_cli_lists_midi_ports(rt, capsys, monkeypatch):
    from devices import audio_device
    fake_sd = SimpleNamespace(query_hostapis=lambda i=None: () if i is None else {},
                              query_devices=lambda d=None: [],
                              default=SimpleNamespace(device=[None, None]),
                              PortAudioError=Exception)
    monkeypatch.setattr(audio_device, "sd", fake_sd)
    assert devices_cli.main([]) == 0
    out = capsys.readouterr().out
    assert "== MIDI ==" in out and f"  - {MPK}" in out and "Sorties (2) :" in out


def test_cli_note(rt, capsys):
    assert devices_cli.main(["--note", "Synth USB 24:0"]) == 0
    out = rt.midi_outs[-1]
    assert out.sent == [[0x90, 69, 100], [0x80, 69, 0]] and out.closed
    assert "Note A4 envoyée" in capsys.readouterr().out


def test_cli_note_missing(rt, capsys):
    assert devices_cli.main(["--note", "Absent"]) == 1
    assert "MIDI : port de sortie introuvable" in capsys.readouterr().out


def test_cli_listen(rt, capsys, monkeypatch):
    monkeypatch.setattr(md, "wait_note", lambda name, timeout=5: (60, 80, 0))
    assert devices_cli.main(["--listen", MPK]) == 0
    assert "Note C4, vélocité 80, canal 1" in capsys.readouterr().out
    monkeypatch.setattr(md, "wait_note", lambda name, timeout=5: None)
    devices_cli.main(["--listen", MPK])
    assert "Aucune note reçue" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# MidiManager sur plusieurs ports
# ---------------------------------------------------------------------------

def test_manager_open_names(rt):
    notes, status = [], []
    mgr = MidiManager(on_note_on=lambda n, v, c: notes.append((n, v, c)),
                      on_status=status.append)
    assert mgr.open_names([MPK, "Through 14:0", "X"]) == ([MPK, "Through 14:0"], ["X"])
    assert mgr.port_names == [MPK, "Through 14:0"]
    assert mgr.port_name == f"{MPK}, Through 14:0"
    assert status == [f"MIDI connecté : {MPK}, Through 14:0"]
    for m in rt.opened_ins():
        m.receive([0x90, 64, 70])
    assert notes == [(64, 70, 0), (64, 70, 0)]          # les deux ports, même décodage
    mgr.close()
    assert not mgr.is_open() and status[-1] == "MIDI déconnecté"


def test_manager_open_names_silent(rt):
    status = []
    mgr = MidiManager(on_status=status.append)
    mgr.open_names([MPK], notify=False)
    assert status == []


def test_manager_without_rtmidi(rt, monkeypatch):
    monkeypatch.setattr(mm_module, "_RTMIDI_AVAILABLE", False)
    assert MidiManager().open_names([MPK]) == ([], [MPK])


def test_manager_open_by_index_closes_others(rt):
    mgr = MidiManager()
    mgr.open_names([MPK, "Through 14:0"])
    assert mgr.open(0) is True
    assert mgr.port_names == ["Through 14:0"]


def test_manager_open_refused(rt):
    rt.refuse.add("Through 14:0")
    status = []
    mgr = MidiManager(on_status=status.append)
    assert mgr.open(0) is False and "refusé" in status[-1]


# ---------------------------------------------------------------------------
# Clés
# ---------------------------------------------------------------------------

def _cfg(tmp_path, prefs=None):
    base = tmp_path / "app"
    os.makedirs(base / "data", exist_ok=True)
    path = tmp_path / "cfg" / "preferences.json"
    if prefs is not None:
        os.makedirs(path.parent, exist_ok=True)
        path.write_text(json.dumps(prefs), encoding="utf-8")
    return AppConfig(str(base), prefs_path=str(path))


def test_midi_keys(tmp_path):
    cfg = _cfg(tmp_path)
    assert cfg.midi_inputs == []
    assert cfg.midi_outputs == ["Synthé FluidSynth"] == [AppConfig.MIDI_SYNTH_OUTPUT]
    cfg = _cfg(tmp_path, {"midi_inputs": [MPK, MPK, ""], "midi_outputs": []})
    assert cfg.midi_inputs == [MPK]
    assert cfg.midi_outputs == []                        # tout décoché : rien


# ---------------------------------------------------------------------------
# DevicesMixin
# ---------------------------------------------------------------------------

class _Midi:
    def __init__(self, present=(MPK,)):
        self.present = set(present)
        self.open = []
        self.connect_calls = 0
    def open_names(self, names, notify=True):
        opened = [n for n in names if n in self.present]
        self.open = opened
        return list(opened), [n for n in names if n not in self.present]
    def is_open(self):
        return bool(self.open)
    def close(self):
        self.open = []


def _win(tmp_path, prefs, present=(MPK,)):
    win = SimpleNamespace(_cfg=_cfg(tmp_path, prefs), _midi=_Midi(present), _midi_outs={},
                          statuses=[], boxes=[], SYNTH_OUTPUT=DevicesMixin.SYNTH_OUTPUT)
    win._show_status = win.statuses.append
    win._show_device_notes = lambda notes=None: win.boxes.append(list(notes))
    win._midi_handler = SimpleNamespace(connect=lambda: win.statuses.append("liste"))
    for name in ("_open_midi_devices", "_close_midi_devices"):
        setattr(win, name, getattr(DevicesMixin, name).__get__(win))
    return win


def test_open_devices_at_startup(tmp_path, rt):
    win = _win(tmp_path, {"midi_inputs": [MPK, "Absent"],
                          "midi_outputs": ["Synthé FluidSynth", "Synth USB 24:0", "Partie"]})
    opened, notes = DevicesMixin._open_midi_devices(win)
    assert opened == [MPK, "Synth USB 24:0"]
    assert notes == ["Entrée MIDI introuvable : Absent.", "Sortie MIDI introuvable : Partie."]
    assert list(win._midi_outs) == ["Synth USB 24:0"]   # le synthé interne n'est pas un port


def test_open_devices_keeps_open_outputs(tmp_path, rt):
    win = _win(tmp_path, {"midi_outputs": ["Synth USB 24:0"]})
    DevicesMixin._open_midi_devices(win)
    first = win._midi_outs["Synth USB 24:0"]
    opened, _ = DevicesMixin._open_midi_devices(win)
    assert win._midi_outs["Synth USB 24:0"] is first and opened == ["Synth USB 24:0"]


def test_close_devices(tmp_path, rt):
    win = _win(tmp_path, {"midi_inputs": [MPK], "midi_outputs": ["Synth USB 24:0"]})
    DevicesMixin._open_midi_devices(win)
    out = win._midi_outs["Synth USB 24:0"]
    DevicesMixin._close_midi_devices(win)
    assert out.closed and win._midi_outs == {} and not win._midi.is_open()


def test_shift_f12_disconnects_then_connects(tmp_path, rt):
    win = _win(tmp_path, {"midi_inputs": [MPK]})
    DevicesMixin._toggle_midi_inputs(win)
    assert win._midi.open == [MPK]
    DevicesMixin._toggle_midi_inputs(win)
    assert win._midi.open == []
    assert win.boxes == []


def test_shift_f12_missing_shows_the_box(tmp_path, rt):
    win = _win(tmp_path, {"midi_inputs": [MPK]}, present=())
    DevicesMixin._toggle_midi_inputs(win)
    assert win.statuses == [f"MIDI : introuvable : {MPK}"]
    assert win.boxes == [[f"Entrée MIDI introuvable : {MPK}."]]


def test_shift_f12_without_checked_input_points_to_preferences(tmp_path, rt):
    # liste « MIDI: » retirée (11f1) : on renvoie à l'onglet Matériel
    win = _win(tmp_path, {})
    DevicesMixin._toggle_midi_inputs(win)
    assert win.statuses == ["MIDI : aucune entrée cochée — Alt+Shift+P, onglet Matériel"]
    assert not win._midi.is_open() and win.boxes == []


def test_ctrl_shift_f12_reconnects(tmp_path, rt):
    win = _win(tmp_path, {"midi_inputs": [MPK], "midi_outputs": ["Synth USB 24:0"]})
    DevicesMixin._open_midi_devices(win)
    old = win._midi_outs["Synth USB 24:0"]
    msg = DevicesMixin._reconnect_midi(win)
    assert msg == f"MIDI reconnecté : {MPK}, Synth USB 24:0"
    assert old.closed and win._midi_outs["Synth USB 24:0"] is not old
    assert win.boxes == []


def test_ctrl_shift_f12_missing_shows_the_box(tmp_path, rt):
    win = _win(tmp_path, {"midi_inputs": [MPK]}, present=())
    msg = DevicesMixin._reconnect_midi(win)
    assert msg == f"MIDI reconnecté : aucun port — Entrée MIDI introuvable : {MPK}."
    assert win.boxes == [[f"Entrée MIDI introuvable : {MPK}."]]


def test_ctrl_shift_f12_nothing_checked(tmp_path, rt):
    win = _win(tmp_path, {"midi_outputs": []})
    assert DevicesMixin._reconnect_midi(win) == \
        "MIDI : aucun périphérique coché dans les Préférences"


def test_test_output_opened_port(tmp_path, rt, monkeypatch):
    monkeypatch.setattr(md, "TEST_SECONDS", 0.01)
    win = _win(tmp_path, {"midi_outputs": ["Synth USB 24:0"]})
    DevicesMixin._open_midi_devices(win)
    msg = DevicesMixin._test_midi_output(win, "Synth USB 24:0")
    assert msg == "Sortie MIDI Synth USB 24:0 : note A4 envoyée pendant une seconde"
    assert win._midi_outs["Synth USB 24:0"].sent[0] == [0x90, 69, 100]


def test_test_output_temporary_port(tmp_path, rt, monkeypatch):
    monkeypatch.setattr(md, "TEST_SECONDS", 0.01)
    win = _win(tmp_path, {})
    DevicesMixin._test_midi_output(win, "Through 14:0")
    out = rt.midi_outs[-1]
    assert out.port == "Through 14:0" and out.sent[0] == [0x90, 69, 100]
    time.sleep(0.5)
    assert out.closed                                   # refermé après la note


def test_test_output_missing(tmp_path, rt):
    msg = DevicesMixin._test_midi_output(_win(tmp_path, {}), "Absent")
    assert msg == "Sortie MIDI Absent : port de sortie introuvable : Absent"


def test_test_output_synth_delegates(tmp_path, rt):
    win = _win(tmp_path, {})
    win._test_synth_output = lambda label: f"synthé {label}"
    assert DevicesMixin._test_midi_output(win, "Synthé FluidSynth") == "synthé A4"


class _FakeEngine:
    made = []
    fail_load = False

    def __init__(self, samplerate=44100, gain=0.4):
        self.events = []
        self.closed = False
        _FakeEngine.made.append(self)
    def load(self, slot, path):
        return not _FakeEngine.fail_load
    def select(self, ch, slot, bank, prog):
        return True
    def note_on(self, ch, note, vel):
        self.events.append(("on", note, vel))
    def note_off(self, ch, note):
        self.events.append(("off", note))
    def render(self, out):
        pass
    def close(self):
        self.closed = True


class _Driver:
    samplerate = 44100

    def __init__(self):
        self.sources = []
    def add_render_source(self, fn):
        self.sources.append(fn)
    def remove_render_source(self, fn):
        self.sources.remove(fn)


def test_test_synth_output(tmp_path, monkeypatch):
    import audio.engines.fluidsynth_engine as fe
    _FakeEngine.made, _FakeEngine.fail_load = [], False
    monkeypatch.setattr(fe, "FluidSynthEngine", _FakeEngine)
    monkeypatch.setattr(md, "TEST_SECONDS", 0.01)
    win = _win(tmp_path, {})
    win._audio_driver, win._gm_soundfont, win.TEST_SYNTH_SECONDS = _Driver(), "/sf2/GM.sf2", 0.05
    assert DevicesMixin._test_synth_output(win, "A4") == \
        "Synthé FluidSynth : note A4 jouée pendant une seconde"
    eng = _FakeEngine.made[0]
    assert win._audio_driver.sources == [eng.render]
    time.sleep(0.3)
    assert eng.events == [("on", 69, 100), ("off", 69)]
    assert win._audio_driver.sources == [] and eng.closed


def test_test_synth_output_soundfont_missing(tmp_path, monkeypatch):
    import audio.engines.fluidsynth_engine as fe
    _FakeEngine.made, _FakeEngine.fail_load = [], True
    monkeypatch.setattr(fe, "FluidSynthEngine", _FakeEngine)
    win = _win(tmp_path, {})
    win._audio_driver, win._gm_soundfont = _Driver(), "/nulle/part.sf2"
    msg = DevicesMixin._test_synth_output(win, "A4")
    assert msg == "Synthé FluidSynth : soundfont introuvable — /nulle/part.sf2"
    assert _FakeEngine.made[0].closed and win._audio_driver.sources == []


def test_test_synth_output_without_library(tmp_path, monkeypatch):
    import audio.engines.fluidsynth_engine as fe

    def unavailable(**kw):
        raise fe.FluidSynthUnavailable("absente")
    monkeypatch.setattr(fe, "FluidSynthEngine", unavailable)
    win = _win(tmp_path, {})
    win._audio_driver, win._gm_soundfont = _Driver(), "/sf2/GM.sf2"
    assert DevicesMixin._test_synth_output(win, "A4") == \
        "Synthé FluidSynth : bibliothèque FluidSynth absente"


@pytest.mark.parametrize("got, expected", [
    ((69, 90, 0), f"Entrée MIDI {MPK} : note A4, vélocité 90, canal 1"),
    (None, f"Entrée MIDI {MPK} : aucune note reçue en 5 secondes"),
])
def test_listen_input(tmp_path, monkeypatch, got, expected):
    monkeypatch.setattr(md, "wait_note", lambda name, timeout: got)
    monkeypatch.setattr(mw_devices.wx, "CallAfter", lambda fn, *a: fn(*a))
    said = []
    DevicesMixin._listen_midi_input(_win(tmp_path, {}), MPK, said.append).join(2)
    assert said == [expected]


def test_listen_input_missing(tmp_path, monkeypatch):
    def missing(name, timeout):
        raise md.MidiDeviceError("port d'entrée introuvable : X")
    monkeypatch.setattr(md, "wait_note", missing)
    monkeypatch.setattr(mw_devices.wx, "CallAfter", lambda fn, *a: fn(*a))
    said = []
    DevicesMixin._listen_midi_input(_win(tmp_path, {}), "X", said.append).join(2)
    assert said == ["Entrée MIDI X : port d'entrée introuvable : X"]


# ---------------------------------------------------------------------------
# Boîte bloquante devant la fenêtre active
# ---------------------------------------------------------------------------

def test_device_box_on_the_active_window(monkeypatch):
    seen = {}

    class Dialog:
        def __init__(self, parent, message, caption, style):
            seen.update(parent=parent, message=message, caption=caption)
        def ShowModal(self):
            return wx.ID_OK
        def Destroy(self):
            pass
    monkeypatch.setattr(main_window.wx, "MessageDialog", Dialog)
    frame = wx.Frame(None)
    child = wx.Panel(frame)
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: child))
    win = SimpleNamespace(_device_notes=["démarrage"], _alert_beep=lambda: None)
    try:
        MainWindow._show_device_notes(win, ["Entrée MIDI introuvable : X."])
        assert seen == {"parent": frame, "message": "Entrée MIDI introuvable : X.",
                        "caption": "Périphérique introuvable"}
        monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: None))
        MainWindow._show_device_notes(win)
        assert seen["parent"] is win and seen["message"] == "démarrage"
    finally:
        frame.Destroy()


# ---------------------------------------------------------------------------
# Raccourcis F12 (fenêtre principale, éditeur MIDI, fenêtre Songs)
# ---------------------------------------------------------------------------

def _key_win():
    win = FakeWindow()          # wx.App de la session (make_km la détruirait)
    calls = []
    win._toggle_midi_inputs = lambda: calls.append("toggle")
    win._reconnect_midi = lambda: calls.append("reconnect")
    win._midi_handler.toggle = lambda: calls.append("ancien Alt+M")
    return win, KeyManager(win), calls


def test_f12_shortcuts_main_window():
    win, km, calls = _key_win()
    km.handle(FakeEvent(key=wx.WXK_F12, shift=True))
    km.handle(FakeEvent(key=wx.WXK_F12, ctrl=True, shift=True))
    assert calls == ["toggle", "reconnect"]


def test_alt_m_no_longer_toggles():
    win, km, calls = _key_win()
    km.handle(FakeEvent(key=ord('M'), alt=True))
    assert calls == []


def test_alt_shift_f12_not_taken():
    win, km, calls = _key_win()
    km.handle(FakeEvent(key=wx.WXK_F12, alt=True, shift=True))
    assert calls == []


def _transport_parent(calls):
    win = FakeWindow()
    win._toggle_midi_inputs = lambda: calls.append("toggle")
    win._reconnect_midi = lambda: calls.append("reconnect")
    return SimpleNamespace(_key_manager=KeyManager(win))


def test_f12_shortcuts_song_window():
    calls = []
    stub = SimpleNamespace(_parent=_transport_parent(calls), _cur_song_idx=0,
                           _set_status=lambda m: None)
    SongWindow._on_key(stub, FakeEvent(key=wx.WXK_F12, shift=True))
    SongWindow._on_key(stub, FakeEvent(key=wx.WXK_F12, ctrl=True, shift=True))
    assert calls == ["toggle", "reconnect"]


def test_f12_shortcuts_midi_editor(monkeypatch):
    calls = []
    parent = _transport_parent(calls)
    ed = SimpleNamespace(_parent=parent, _set_status=lambda m: None,
                         _view_mode=0, MODE_NOTES=0, MODE_ALL=1)
    for evt in (FakeEvent(key=wx.WXK_F12, shift=True),
                FakeEvent(key=wx.WXK_F12, ctrl=True, shift=True)):
        try:
            mew.MidiEditorWindow._on_key(ed, evt)
        except AttributeError:
            pass                    # stub minimal : seule la délégation compte
    assert calls == ["toggle", "reconnect"]


# ---------------------------------------------------------------------------
# Vraie fenêtre principale : entrée MIDI introuvable au démarrage
# ---------------------------------------------------------------------------

def test_real_main_window_missing_midi_input(isolated_preferences, monkeypatch):
    """Une seule vraie MainWindow (clients ALSA), vrai rtmidi."""
    path = str(isolated_preferences)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"midi_inputs": ["Contrôleur absent 99:0"], "midi_outputs": []}, f)
    shown = []
    monkeypatch.setattr(wx.MessageDialog, "ShowModal",
                        lambda self: shown.append((self.GetTitle(), self.GetMessage())) or wx.ID_OK)
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    win = None
    try:
        win = MainWindow(no_fluidsynth=True, no_sfizz=True)
        assert shown == [("Périphérique introuvable",
                          "Entrée MIDI introuvable : Contrôleur absent 99:0.")]
        assert not win._midi.is_open() and win._midi_outs == {}
    finally:
        if win is not None:
            win._router.wait_loaded()     # fils de chargement finis avant Destroy
            win._close_midi_devices()
            win._audio_driver.close()
            win.Destroy()
        os.remove(path)
