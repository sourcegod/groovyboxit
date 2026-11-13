#python3
"""
    File: tests/test_track_midi_ports.py
    Entrée et sortie MIDI dans les propriétés de piste (Phase 8 étape 12d1,
    docs/DESIGN.md § Phase 8 étape 12a T7, T9) : listes du dialogue (place
    avant Canal, libellés, « Toutes les entrées » / « Interne (son du
    slot) », port absent gardé, choix lus, on_ports_change, sans ports) ;
    _track_properties_dialog (ports passés, effet immédiat, notes coupées,
    mixage envoyé, avertissement, Ok garde, Annuler remet, port seul =
    modification) ; filtre du jeu en direct (MidiManager.port_filter, Note
    Off toujours passés, _midi_port_accepted : Toutes, même port, adresse
    ALSA changée, autre port).
    Date: Fri, 13/11/2026
    Author: Coolbrother
"""
import sys
import os
import json
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import wx

from app_config import AppConfig
from rack import Rack, InstrumentType
from ui.dialogs_properties import TrackPropertiesDialog
from ui.mw_devices import DevicesMixin
from midi.midi_manager import MidiManager
import midi.midi_manager as mm_module
from test_rack_mode_ui import _RackWin, _env   # noqa: F401  (_env : App, Timer et SynthEngine factices)

MPK = "MPK mini Plus:MPK mini Plus MIDI 1 20:0"
OUT = "Synth USB 24:0"

_APP = None


@pytest.fixture(autouse=True)
def wx_app_alive():
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)
    yield


# ---------------------------------------------------------------------------
# Listes du dialogue
# ---------------------------------------------------------------------------

def _rack():
    rack = Rack()
    rack.set_slot(1, InstrumentType.SYNTH, "Piano", {"patch": "p"})
    return rack


@pytest.fixture
def dialog():
    made = []

    def build(midi_ports=None, on_ports_change=None):
        frame = wx.Frame(None)
        dlg = TrackPropertiesDialog(frame, 0, _rack(), 1, 100, 0, False, False, channel=2,
                                    midi_ports=midi_ports, on_ports_change=on_ports_change)
        made.append((frame, dlg))
        return dlg
    yield build
    for frame, dlg in made:
        dlg.Destroy()
        frame.Destroy()


PORTS = dict(inputs=[MPK, "Through 14:0"], outputs=[OUT], midi_in="", midi_out="")


def _strings(lst):
    return [lst.GetString(i) for i in range(lst.GetCount())]


def test_lists_between_slot_and_channel(dialog):
    dlg = dialog(PORTS)
    kids = list(dlg.GetChildren())
    order = [(type(c).__name__, c.GetLabel() if isinstance(c, wx.StaticText) else "")
             for c in kids if isinstance(c, (wx.StaticText, wx.ListBox))]
    i = order.index(("StaticText", "Slot :"))
    assert order[i:i + 8] == [
        ("StaticText", "Slot :"), ("ListBox", ""),
        ("StaticText", "Entrée MIDI :"), ("ListBox", ""),
        ("StaticText", "Sortie MIDI :"), ("ListBox", ""),
        ("StaticText", "Canal :"), ("ListBox", "")]


def test_list_contents_and_defaults(dialog):
    dlg = dialog(PORTS)
    assert _strings(dlg._midi_in) == ["Toutes les entrées", MPK, "Through 14:0"]
    assert _strings(dlg._midi_out) == ["Interne (son du slot)", OUT]
    assert dlg.get_midi_in() == "" and dlg.get_midi_out() == ""


def test_current_ports_selected(dialog):
    dlg = dialog(dict(PORTS, midi_in="Through 14:0", midi_out=OUT))
    assert dlg._midi_in.GetSelection() == 2 and dlg._midi_out.GetSelection() == 1
    assert dlg.get_midi_in() == "Through 14:0" and dlg.get_midi_out() == OUT


def test_absent_port_kept(dialog):
    dlg = dialog(dict(PORTS, midi_out="Ancien 9:0"))
    assert _strings(dlg._midi_out)[-1] == "Ancien 9:0 — absent"
    assert dlg.get_midi_out() == "Ancien 9:0"


def test_choice_calls_on_ports_change(dialog):
    seen = []
    dlg = dialog(PORTS, on_ports_change=lambda i, o: seen.append((i, o)))
    dlg._midi_out.SetSelection(1)
    evt = wx.CommandEvent(wx.wxEVT_LISTBOX, dlg._midi_out.GetId())
    dlg._midi_out.GetEventHandler().ProcessEvent(evt)
    dlg._midi_in.SetSelection(1)
    dlg._midi_in.GetEventHandler().ProcessEvent(
        wx.CommandEvent(wx.wxEVT_LISTBOX, dlg._midi_in.GetId()))
    assert seen == [("", OUT), (MPK, OUT)]


def test_without_ports_no_lists(dialog):
    dlg = dialog(None)
    assert dlg.get_midi_in() is None and dlg.get_midi_out() is None
    labels = [c.GetLabel() for c in dlg.GetChildren() if isinstance(c, wx.StaticText)]
    assert "Entrée MIDI :" not in labels and "Sortie MIDI :" not in labels


def test_port_choices_helper():
    values, labels = TrackPropertiesDialog._port_choices(["A", "", "B"], "C", "Tout")
    assert values == ["", "A", "B", "C"] and labels == ["Tout", "A", "B", "C — absent"]


# ---------------------------------------------------------------------------
# _track_properties_dialog : effet immédiat, Ok, Annuler
# ---------------------------------------------------------------------------

def _cfg(tmp_path, prefs):
    base = tmp_path / "app"
    os.makedirs(base / "data", exist_ok=True)
    path = tmp_path / "p.json"
    path.write_text(json.dumps(prefs), encoding="utf-8")
    return AppConfig(str(base), prefs_path=str(path))


class _PortsWin(_RackWin):
    def __init__(self, cfg):
        super().__init__(rack_mode=False)
        self._cfg = cfg
        self.warned = 0
        self.port = SimpleNamespace(sent=[])
        self.port.send_message = lambda m: self.port.sent.append(list(m))
        self._router.midi_out_lookup = lambda name: self.port if name == OUT else None

    def _warn_track_midi_outs(self):
        self.warned += 1
        return []


def _ports_dlg(result, midi_in=None, midi_out=None, live=True):
    """Dialogue factice : valeurs d'origine pour tout, sauf les ports ;
    live : choix appliqué en direct (on_ports_change) avant Ok / Annuler."""
    class FakeDlg:
        def __init__(self, parent, tidx, rack, slot, vol, pan, mute, solo, **kw):
            FakeDlg.kw = kw
            ch = kw["channel"]
            info = kw["bank_info"](slot, ch)
            self.v = [slot, vol, pan, mute, solo, ch,
                      info["program"] if info else kw["slot_program"](slot)[1],
                      *kw["slot_gm_tuning"](slot),
                      info["msb"] if info else None, info["lsb"] if info else None]
            mp = kw["midi_ports"]
            self.ports = (mp["midi_in"] if midi_in is None else midi_in,
                          mp["midi_out"] if midi_out is None else midi_out)
            if live:
                kw["on_ports_change"](*self.ports)

        def ShowModal(self):     return result
        def get_slot_idx(self):  return self.v[0]
        def get_volume(self):    return self.v[1]
        def get_pan(self):       return self.v[2]
        def get_mute(self):      return self.v[3]
        def get_solo(self):      return self.v[4]
        def get_channel(self):   return self.v[5]
        def get_program(self):   return self.v[6]
        def get_transpose(self): return self.v[7]
        def get_gain_db(self):   return self.v[8]
        def get_msb(self):       return self.v[9]
        def get_lsb(self):       return self.v[10]
        def get_midi_in(self):   return self.ports[0]
        def get_midi_out(self):  return self.ports[1]
        def Destroy(self):       pass
    return FakeDlg


def _run(win, fake):
    with patch("ui.mw_tracks.TrackPropertiesDialog", fake):
        win._track_properties_dialog()


@pytest.fixture
def win(tmp_path):
    return _PortsWin(_cfg(tmp_path, {"midi_inputs": [MPK],
                                     "midi_outputs": ["Synthé FluidSynth", OUT]}))


def test_ports_passed_to_the_dialog(win):
    win._router._track_midi_outs[0] = OUT
    fake = _ports_dlg(wx.ID_CANCEL, live=False)
    _run(win, fake)
    assert fake.kw["midi_ports"] == dict(inputs=[MPK], outputs=[OUT],   # synthé interne retiré
                                         midi_in="", midi_out=OUT)


def test_ok_keeps_the_ports(win):
    _run(win, _ports_dlg(wx.ID_OK, midi_in=MPK, midi_out=OUT))
    r = win._router
    assert r._track_midi_ins[0] == MPK and r._track_midi_outs[0] == OUT
    assert win.statuses[-1] == "Piste 1: propriétés mises à jour"
    assert win.undos == ["Propriétés piste 1"]                 # port seul = modification


def test_cancel_restores_the_ports(win):
    _run(win, _ports_dlg(wx.ID_CANCEL, midi_in=MPK, midi_out=OUT))
    r = win._router
    assert r._track_midi_ins[0] == "" and r._track_midi_outs[0] == ""
    assert win.undos == ["Propriétés piste 1", "pop"]


def test_unchanged_ports_pop_the_undo(win):
    _run(win, _ports_dlg(wx.ID_OK))
    assert win.undos == ["Propriétés piste 1", "pop"]
    assert win.statuses[-1] == "Piste 1: propriétés inchangées"


def test_live_output_change_cuts_notes_and_sends_mix(win, monkeypatch):
    cut = []
    monkeypatch.setattr(win._router, "cut_track_notes", lambda t: cut.append(t))
    _run(win, _ports_dlg(wx.ID_OK, midi_out=OUT))
    assert cut and cut[0] == 0
    assert [m[1] for m in win.port.sent if m[0] & 0xF0 == 0xB0][:2] == [7, 10]   # CC7, CC10
    assert win.warned >= 1


def test_absent_output_falls_back_and_warns(win):
    _run(win, _ports_dlg(wx.ID_OK, midi_out="Absent 9:0"))
    assert win._router._track_midi_outs[0] == "Absent 9:0"
    assert win._router._ext_port(0) is None and win.port.sent == []
    assert win.warned >= 1


def test_without_config_no_lists(win):
    win._cfg = None
    seen = {}

    class Dlg(_ports_dlg(wx.ID_CANCEL, live=False)):
        def __init__(self, *a, **kw):
            seen.update(kw)
            kw["midi_ports"] = {"midi_in": "", "midi_out": ""}
            super().__init__(*a, **kw)
    _run(win, Dlg)
    assert seen["midi_ports"] is None


# ---------------------------------------------------------------------------
# Filtre du jeu en direct (T9)
# ---------------------------------------------------------------------------

def _mgr(accept):
    notes = []
    mgr = MidiManager(on_note_on=lambda n, v, c: notes.append(("on", n)),
                      on_note_off=lambda n, c: notes.append(("off", n)),
                      on_cc=lambda cc, v, c: notes.append(("cc", cc)))
    mgr.port_filter = accept
    return mgr, notes


def test_filter_refuses_other_ports():
    mgr, notes = _mgr(lambda port: port == MPK)
    mgr._callback(([0x90, 60, 100], 0.0), MPK)
    mgr._callback(([0x90, 62, 100], 0.0), "Through 14:0")
    mgr._callback(([0xB0, 1, 64], 0.0), "Through 14:0")
    assert notes == [("on", 60)]


def test_note_off_always_passes():
    mgr, notes = _mgr(lambda port: False)
    mgr._callback(([0x80, 60, 0], 0.0), "Through 14:0")
    mgr._callback(([0x90, 61, 0], 0.0), "Through 14:0")        # Note On vélocité 0
    assert notes == [("off", 60), ("off", 61)]


def test_no_filter_or_unknown_port():
    mgr, notes = _mgr(None)
    mgr._callback(([0x90, 60, 100], 0.0), "X")
    mgr.port_filter = lambda port: False
    mgr._callback(([0x90, 61, 100], 0.0), None)                 # port inconnu : passe
    assert notes == [("on", 60), ("on", 61)]


def test_ports_reach_the_filter(monkeypatch):
    from test_midi_device import FakeRtmidi
    import devices.midi_device as md
    fake = FakeRtmidi()
    monkeypatch.setattr(md, "rtmidi", fake)
    monkeypatch.setattr(mm_module, "rtmidi", fake)
    monkeypatch.setattr(mm_module, "_RTMIDI_AVAILABLE", True)
    seen = []
    mgr, notes = _mgr(lambda port: seen.append(port) or True)
    mgr.open_names(["Through 14:0", "MPK mini Plus:MPK mini Plus MIDI 1 20:0"])
    for m in fake.opened_ins():
        m.receive([0x90, 64, 80])
    assert seen == ["Through 14:0", "MPK mini Plus:MPK mini Plus MIDI 1 20:0"]
    mgr.close()


@pytest.mark.parametrize("track_in, port, ok", [
    ("", "Through 14:0", True),
    (MPK, MPK, True),
    (MPK, "MPK mini Plus:MPK mini Plus MIDI 1 24:0", True),     # adresse ALSA changée
    (MPK, "Through 14:0", False),
])
def test_midi_port_accepted(track_in, port, ok):
    ins = [""] * 16
    ins[3] = track_in
    win = SimpleNamespace(_router=SimpleNamespace(_track_midi_ins=ins),
                          _player=SimpleNamespace(_cur_track=3))
    assert DevicesMixin._midi_port_accepted(win, port) is ok


def test_midi_port_accepted_follows_the_current_track():
    ins = [""] * 16
    ins[0] = MPK
    win = SimpleNamespace(_router=SimpleNamespace(_track_midi_ins=ins),
                          _player=SimpleNamespace(_cur_track=0))
    assert not DevicesMixin._midi_port_accepted(win, "Through 14:0")
    win._player._cur_track = 1
    assert DevicesMixin._midi_port_accepted(win, "Through 14:0")


def test_midi_port_accepted_without_router():
    assert DevicesMixin._midi_port_accepted(SimpleNamespace(), "X") is True
