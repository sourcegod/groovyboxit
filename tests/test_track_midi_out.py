#python3
"""
    File: tests/test_track_midi_out.py
    Sortie MIDI externe des pistes (Phase 8 étape 12b1, docs/DESIGN.md
    § Phase 8 étape 12a T1, T8, T10) : TrackMidiOutMixin sur un vrai
    TrackRouter et un port factice (notes de grille traduites selon le slot,
    KIT / PATCH, CC, Pitch Bend, Program Change, CC7 / CC10, poursuite,
    All Notes Off au Stop / Mute / Panic, son interne tu ; port absent ou
    « Interne » → son interne) ; entrée / sortie par piste dans Pattern
    (.gvp, anciens projets, redimensionnement, copie vers le routeur) ;
    avertissement de port absent (une fois par port, boîte ou démarrage) ;
    rendu WAV toujours interne ; vraie fenêtre principale.
    Date: Fri, 13/11/2026
    Author: Coolbrother
"""
import sys
import os
import json
import types
import threading
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import wx

import track_router as tr_mod
from track_router import TrackRouter
from rack import Rack, InstrumentType
from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_PGM, ETYPE_CC
from song import Song
from midi.track_midi_out import (NOTE_ON, NOTE_OFF, CC, PGM, BEND,
                                 CC_ALL_NOTES_OFF, CC_ALL_SOUND_OFF, CC_RESET)
from midi.midi_export import volume_to_cc7, pan_to_cc10
from ui.mw_devices import DevicesMixin
from test_bank_slot import FakeBankEngine, FakeSoundManager, FakeTimer, FakeSynthEngine

KIT, PIANO, BANK, EMPTY = 0, 1, 2, 5
PORT = "Synth USB 24:0"


class FakePort:
    def __init__(self):
        self.sent = []
    def send_message(self, msg):
        self.sent.append(list(msg))
    def of(self, status):
        return [m for m in self.sent if m[0] & 0xF0 == status]


class BrokenPort:
    def send_message(self, msg):
        raise RuntimeError("débranché")


@pytest.fixture(autouse=True)
def _fake_timer_and_synth(monkeypatch):
    FakeTimer.created = []
    monkeypatch.setattr(tr_mod, "threading",
                        types.SimpleNamespace(Timer=FakeTimer, Thread=threading.Thread))
    monkeypatch.setattr(tr_mod, "SynthEngine", FakeSynthEngine)


class _Snd(FakeSoundManager):
    def __init__(self):
        super().__init__()
        self.pad_notes = [35 + i for i in range(16)]
        self.gm_note_map = {35: 36, 38: 40}               # note de kit → note GM

    def render_copy(self, driver):                         # rendu WAV (render_copy)
        return _Snd()


@pytest.fixture
def env():
    rack = Rack()
    rack.set_slot(KIT, InstrumentType.KIT, "TR-707", {})
    rack.set_slot(PIANO, InstrumentType.SYNTH, "Piano", {"patch": "p"})
    rack.set_slot(BANK, InstrumentType.BANK, "FluidR3", {"bank_slot": 0})
    rack.bank_files = ["/fake/gm.sf2", None, None, None]
    bank = FakeBankEngine()
    bank.paths[0] = "/fake/gm.sf2"
    snd = _Snd()
    scheduled = []
    router = TrackRouter(rack, "/fake", snd, lambda m: None, bank_engine=bank,
                         schedule=lambda ms, fn, *a: scheduled.append((ms, fn, a)))
    router.set_playback_kb("major", 48)
    port = FakePort()
    ports = {PORT: port}
    router.midi_out_lookup = lambda name: ports.get(name)
    return SimpleNamespace(router=router, port=port, ports=ports, bank=bank, snd=snd,
                           scheduled=scheduled, rack=rack)


def _external(env, track=1, slot=KIT, channel=9):
    r = env.router
    r._track_slots[track] = slot
    r._track_channels[track] = channel
    r._track_cur_channels[track] = channel
    r._track_midi_outs[track] = PORT


def _fire(env):
    for ms, fn, args in env.scheduled:
        fn(*args)
    env.scheduled.clear()


# ---------------------------------------------------------------------------
# Port de la piste
# ---------------------------------------------------------------------------

def test_defaults_internal(env):
    r = env.router
    assert r._track_midi_outs == [""] * r.NUM_TRACKS
    assert r._track_midi_ins == [""] * r.NUM_TRACKS
    assert r.track_midi_out(1) == "" and r._ext_port(1) is None
    assert r.track_midi_out(99) == ""


def test_ext_port_open_absent_or_no_lookup(env):
    _external(env)
    assert env.router._ext_port(1) == (PORT, env.port)
    env.router._track_midi_outs[1] = "Absent 9:0"
    assert env.router._ext_port(1) is None
    env.router._track_midi_outs[1] = PORT
    env.router.midi_out_lookup = None                     # rendu WAV, tests
    assert env.router._ext_port(1) is None and env.router.missing_midi_outs() == []


def test_missing_midi_outs(env):
    r = env.router
    r._track_midi_outs[2] = PORT
    r._track_midi_outs[4] = "Absent 9:0"
    r._track_midi_outs[6] = "Absent 9:0"
    assert r.missing_midi_outs() == [(4, "Absent 9:0"), (6, "Absent 9:0")]


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def test_kit_grid_note_goes_out_as_gm_note(env):
    _external(env, slot=KIT, channel=9)
    env.router.on_play(1, 0, 0.8, 0, 120)
    assert env.port.sent == [[NOTE_ON | 9, 36, 102]]      # 35 → note GM 36
    assert env.snd.played == [] and env.snd.played_notes == []   # son interne tu
    assert env.scheduled[0][0] == 120
    _fire(env)
    assert env.port.sent[-1] == [NOTE_OFF | 9, 36, 0]


def test_kit_grid_note_without_gm_mapping(env):
    _external(env, slot=KIT, channel=9)
    env.router.on_play(1, 1, 1.0, 0, 0)                  # 36 : pas dans la table
    assert env.port.sent == [[NOTE_ON | 9, 36, 127]]
    assert env.scheduled[0][0] == 500                    # durée par défaut


def test_synth_grid_note_follows_the_scale(env):
    _external(env, slot=PIANO, channel=2)
    r = env.router
    r.on_play(1, 2, 0.5, 0, 200)
    assert env.port.sent == [[NOTE_ON | 2, r._kb_notes_play[2], 64]]


def test_bank_grid_on_channel_10(env):
    _external(env, slot=BANK, channel=9)
    env.router.on_play(1, 3, 1.0, 0, 200)
    assert env.port.sent == [[NOTE_ON | 9, 36 + 3, 127]]
    assert env.bank.of("note_on") == []


def test_kit_tape_note(env):
    _external(env, slot=KIT, channel=9)
    env.router.on_kit_tape(1, 38, 90, 0)
    assert env.port.sent == [[NOTE_ON | 9, 40, 90]]      # note de kit → GM
    _external(env, track=2, slot=BANK, channel=9)
    env.router.on_kit_tape(2, 38, 90, 0)
    assert env.port.sent[-1] == [NOTE_ON | 9, 38, 90]   # banque : telle quelle


def test_patch_note(env):
    _external(env, slot=PIANO, channel=0)
    env.router.on_patch_tape(1, 60, 100, 300)
    assert env.port.sent == [[NOTE_ON | 0, 60, 100]]
    _fire(env)
    assert env.port.sent[-1] == [NOTE_OFF | 0, 60, 0]


def test_velocity_and_note_bounds(env):
    _external(env, slot=PIANO, channel=0)
    env.router.on_patch_tape(1, 200, 0, 10)
    assert env.port.sent == [[NOTE_ON | 0, 127, 1]]


def test_muted_track_sends_nothing(env):
    _external(env)
    env.router._track_mutes[1] = True
    env.router.on_play(1, 0, 1.0, 0, 100)
    env.router.on_patch_tape(1, 60, 100, 100)
    assert env.port.sent == []


def test_internal_track_untouched(env):
    env.router._track_slots[1] = KIT
    env.router.on_play(1, 0, 1.0, 0, 100)
    assert env.port.sent == [] and env.snd.played


def test_absent_port_falls_back_to_internal_sound(env):
    _external(env)
    env.router._track_midi_outs[1] = "Absent 9:0"
    env.router.on_play(1, 0, 1.0, 0, 100)
    assert env.port.sent == [] and env.snd.played        # T10


def test_broken_port_is_harmless(env):
    _external(env)
    env.ports[PORT] = BrokenPort()
    env.router.on_play(1, 0, 1.0, 0, 100)                # sans exception


# ---------------------------------------------------------------------------
# Contrôleurs, Pitch Bend, Program Change, mixage
# ---------------------------------------------------------------------------

def test_cc_and_mod(env):
    _external(env, slot=PIANO, channel=3)
    r = env.router
    r.on_cc_tape(1, 74, 50)
    r.on_mod_tape(1, 80)
    r.on_cc_tape(1, 64, 127)                             # pédale : vers le port
    assert env.port.sent == [[CC | 3, 74, 50], [CC | 3, 1, 80], [CC | 3, 64, 127]]


def test_bank_select_on_event_channel(env):
    _external(env, slot=PIANO, channel=3)
    env.router.on_cc_tape(1, 0, 8, channel=5)
    assert env.port.sent == [[CC | 5, 0, 8]]


def test_global_ccs_stay_on_the_port(env):
    _external(env, slot=PIANO, channel=3)
    stopped = []
    env.router.stop_all_sounds = lambda: stopped.append(1)
    env.router.on_cc_tape(1, 120, 0)
    assert env.port.sent == [[CC | 3, 120, 0]] and stopped == []


def test_volume_and_pan_ccs_become_track_mix(env):
    _external(env, slot=PIANO, channel=3)
    env.router.on_cc_tape(1, 7, 64)
    vol = env.router._track_volumes[1]
    assert vol == round(64 * 100 / 127)
    assert env.port.sent == [[CC | 3, 7, volume_to_cc7(vol)], [CC | 3, 10, pan_to_cc10(0)]]


def test_set_volume_and_pan_send_mix(env):
    _external(env, slot=BANK, channel=4)
    env.router.set_track_volume(1, 50)
    env.router.set_track_pan(1, -100)
    assert env.port.sent == [[CC | 4, 7, 64], [CC | 4, 10, 64],
                             [CC | 4, 7, 64], [CC | 4, 10, 1]]
    assert env.bank.ccs(channel=4) == []                 # pas de mixage interne


@pytest.mark.parametrize("bend, lsb, msb", [(0, 0, 64), (-8192, 0, 0), (8191, 127, 127),
                                             (4096, 0, 96)])
def test_pitch_bend(env, bend, lsb, msb):
    _external(env, slot=PIANO, channel=1)
    env.router.on_bend_tape(1, bend)
    assert env.port.sent == [[BEND | 1, lsb, msb]]


def test_program_change(env):
    _external(env, slot=BANK, channel=2)
    env.router.on_program_change_tape(1, 48)
    assert env.port.sent == [[PGM | 2, 48]]
    env.router.on_program_change_tape(1, 33, channel=6)  # la piste passe au canal 6
    assert env.port.sent[-1] == [PGM | 6, 33]
    assert env.router._track_cur_channels[1] == 6
    assert env.bank.of("select") == []


def test_chase_sends_bank_program_and_mix(env):
    _external(env, slot=PIANO, channel=2)
    env.router._track_volumes[1] = 80
    env.router._track_pans[1] = 50
    tape = [[] for _ in range(env.router.NUM_TRACKS)]
    tape[1] = [TapeEvent(ETYPE_CC, channel=2, payload={"cc_num": 0, "value": 8}, time=0),
               TapeEvent(ETYPE_PGM, channel=2, payload={"program": 48}, time=0),
               TapeEvent(ETYPE_PGM, channel=2, payload={"program": 60}, time=8)]
    env.router.chase(tape, pos=4)
    assert env.port.sent == [[CC | 2, 0, 8], [CC | 2, 32, 0], [PGM | 2, 48],
                             [CC | 2, 7, volume_to_cc7(80)], [CC | 2, 10, pan_to_cc10(50)]]


def test_chase_without_external_track_sends_nothing(env):
    env.router.chase([[] for _ in range(env.router.NUM_TRACKS)], 0)
    assert env.port.sent == []


# ---------------------------------------------------------------------------
# Coupures
# ---------------------------------------------------------------------------

def test_stop_sends_all_notes_off_on_used_channels(env):
    _external(env, track=1, slot=KIT, channel=9)
    _external(env, track=2, slot=PIANO, channel=0)
    env.router.on_play(1, 0, 1.0, 0, 100)
    env.router.on_patch_tape(2, 60, 100, 100)
    env.port.sent.clear()
    env.router.on_play_stop()
    assert sorted(env.port.sent) == sorted([[CC | 9, CC_ALL_NOTES_OFF, 0],
                                            [CC | 0, CC_ALL_NOTES_OFF, 0]])
    env.port.sent.clear()
    env.router.on_play_stop()                            # plus rien d'utilisé
    assert env.port.sent == []


def test_cut_track_notes_on_its_port(env):
    _external(env, slot=PIANO, channel=5)
    env.router.cut_track_notes(1)
    assert env.port.sent == [[CC | 5, CC_ALL_NOTES_OFF, 0]]


def test_cut_all_notes_before_mute(env):
    _external(env, slot=PIANO, channel=5)
    env.router.on_patch_tape(1, 60, 100, 100)
    env.port.sent.clear()
    env.router.cut_all_notes()
    assert env.port.sent == [[CC | 5, CC_ALL_NOTES_OFF, 0]]


def test_panic(env):
    _external(env, slot=PIANO, channel=5)
    env.router.on_patch_tape(1, 60, 100, 100)
    env.port.sent.clear()
    env.router.panic()
    assert env.port.sent == [[CC | 5, CC_ALL_NOTES_OFF, 0], [CC | 5, CC_ALL_SOUND_OFF, 0],
                             [CC | 5, CC_RESET, 0]]


def test_cut_without_lookup(env):
    env.router.midi_out_lookup = None
    env.router.ext_notes_off()
    env.router.ext_notes_off(1)


# ---------------------------------------------------------------------------
# Données par pattern (T8)
# ---------------------------------------------------------------------------

def test_pattern_defaults_and_serialisation():
    p = Pattern()
    assert p._track_midi_ins == [""] * p._num_tracks
    assert p._track_midi_outs == [""] * p._num_tracks
    p._track_midi_outs[2] = PORT
    p._track_midi_ins[3] = "MPK 20:0"
    d = p.to_dict()
    assert d["track_midi_outs"][2] == PORT and d["track_midi_ins"][3] == "MPK 20:0"
    q = Pattern()
    q.from_dict(json.loads(json.dumps(d)))
    assert q._track_midi_outs == p._track_midi_outs and q._track_midi_ins == p._track_midi_ins


def test_old_project_without_keys():
    p = Pattern()
    d = p.to_dict()
    del d["track_midi_ins"], d["track_midi_outs"]
    q = Pattern()
    q._track_midi_outs[1] = "ancien"
    q.from_dict(d)
    assert q._track_midi_outs == [""] * q._num_tracks
    assert q._track_midi_ins == [""] * q._num_tracks


@pytest.mark.parametrize("value", [None, "pas une liste", [1, None, "Port"], ["A"]])
def test_invalid_keys_cleaned(value):
    p = Pattern()
    d = p.to_dict()
    d["track_midi_outs"] = value
    q = Pattern()
    q.from_dict(d)
    assert len(q._track_midi_outs) == q._num_tracks
    assert all(isinstance(n, str) for n in q._track_midi_outs)
    if value == [1, None, "Port"]:
        assert q._track_midi_outs[:3] == ["", "", "Port"]


def test_resize_pads_the_lists():
    p = Pattern()
    n = p._num_tracks
    p._track_midi_outs[0] = PORT
    p._extend_tracks(n + 4)
    assert len(p._track_midi_outs) == n + 4 and p._track_midi_outs[0] == PORT
    assert p._track_midi_outs[-1] == "" and len(p._track_midi_ins) == n + 4


def test_frozen_pattern_copies_the_lists():
    from song import frozen_pattern
    p = Pattern()
    p._track_midi_outs[3] = PORT
    p._track_midi_ins[3] = "MPK 20:0"
    out = frozen_pattern(p)
    assert out._track_midi_outs[3] == PORT and out._track_midi_ins[3] == "MPK 20:0"
    p._track_midi_outs[3] = ""
    assert out._track_midi_outs[3] == PORT                # copie, pas la même liste


def test_copy_to_router_and_back(tmp_path):
    from ui.mw_patterns import PatternMixin
    p = Pattern()
    p._track_midi_outs[1] = PORT
    p._track_midi_ins[1] = "MPK 20:0"
    router = SimpleNamespace(_track_slots=[0] * 16, _track_mutes=[False] * 16,
                             _track_solos=[False] * 16, _track_volumes=[100] * 16,
                             _track_pans=[0] * 16, _track_channels=[0] * 16,
                             _track_midi_outs=[""] * 16, _track_midi_ins=[""] * 16)
    win = SimpleNamespace(_router=router,
                          _player=SimpleNamespace(_pattern=Pattern(), bpm=120))
    router._track_midi_outs[:] = p._track_midi_outs
    router._track_midi_ins[:] = p._track_midi_ins
    out = Pattern()
    PatternMixin._flush_pattern_to_store(win, out)
    assert out._track_midi_outs[1] == PORT and out._track_midi_ins[1] == "MPK 20:0"


# ---------------------------------------------------------------------------
# Avertissement : port absent → son interne (T10)
# ---------------------------------------------------------------------------

def _warn_win(missing, started=True):
    win = SimpleNamespace(_router=SimpleNamespace(missing_midi_outs=lambda: list(missing)),
                          _started=started, _device_notes=[], statuses=[], boxes=[])
    win._show_status = win.statuses.append
    win._show_device_notes = lambda notes: win.boxes.append(list(notes))
    return win


def test_warning_box_once_per_port():
    win = _warn_win([(2, "A 9:0"), (5, "A 9:0"), (3, "B 8:0")])
    notes = DevicesMixin._warn_track_midi_outs(win)
    assert notes == ["Sortie MIDI introuvable : A 9:0. Pistes 3, 6 : son interne.",
                     "Sortie MIDI introuvable : B 8:0. Piste 4 : son interne."]
    assert win.boxes == [notes] and win.statuses == [" ".join(notes)]
    assert DevicesMixin._warn_track_midi_outs(win) == []    # déjà averti
    assert len(win.boxes) == 1


def test_warning_at_startup_goes_to_the_startup_box():
    win = _warn_win([(0, "A 9:0")], started=False)
    DevicesMixin._warn_track_midi_outs(win)
    assert win._device_notes == ["Sortie MIDI introuvable : A 9:0. Piste 1 : son interne."]
    assert win.boxes == [] and win.statuses == []


def test_no_warning_without_missing_port_or_router():
    win = _warn_win([])
    assert DevicesMixin._warn_track_midi_outs(win) == [] and win.boxes == []
    assert DevicesMixin._warn_track_midi_outs(SimpleNamespace()) == []


def test_new_port_warned_after_an_old_one():
    win = _warn_win([(0, "A 9:0")])
    DevicesMixin._warn_track_midi_outs(win)
    win._router.missing_midi_outs = lambda: [(0, "A 9:0"), (1, "C 7:0")]
    assert DevicesMixin._warn_track_midi_outs(win) == \
        ["Sortie MIDI introuvable : C 7:0. Piste 2 : son interne."]


# ---------------------------------------------------------------------------
# Rendu WAV : toujours le son interne
# ---------------------------------------------------------------------------

def test_render_copy_has_no_port(env):
    _external(env, slot=PIANO, channel=0)
    copy = env.router.render_copy(driver=None, schedule=lambda ms, fn, *a: None)
    assert copy.midi_out_lookup is None
    copy._track_midi_outs[1] = PORT
    assert copy._ext_port(1) is None                     # rendu : son interne


# ---------------------------------------------------------------------------
# Vraie fenêtre principale
# ---------------------------------------------------------------------------

_APP = None


def test_real_main_window_sends_to_an_open_port(isolated_preferences, monkeypatch):
    """Une seule vraie MainWindow (clients ALSA) ; port factice ouvert à la
    place du vrai, pattern chargé avec une sortie absente."""
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)
    from ui.main_window import MainWindow
    import devices.midi_device as md
    path = str(isolated_preferences)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"midi_outputs": [PORT], "midi_inputs": []}, f)
    port = FakePort()
    monkeypatch.setattr(md, "open_output", lambda name: port if name == PORT else
                        (_ for _ in ()).throw(md.MidiDeviceError("introuvable")))
    shown = []
    monkeypatch.setattr(wx.MessageDialog, "ShowModal",
                        lambda self: shown.append(self.GetMessage()) or wx.ID_OK)
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    win = None
    try:
        win = MainWindow(no_fluidsynth=True, no_sfizz=True)
        r = win._router
        assert r.midi_out_lookup(PORT) is port and r.midi_out_lookup("x") is None
        pat = win._pattern_list[win._cur_pattern_idx]
        pat._track_midi_outs[1] = PORT
        pat._track_midi_outs[2] = "Absent 9:0"
        win._apply_pattern_from_store(pat)
        assert r._track_midi_outs[1] == PORT
        assert shown == ["Sortie MIDI introuvable : Absent 9:0. Piste 3 : son interne."]
        r.on_patch_tape(1, 60, 100, 0)
        assert port.sent[-1][1:] == [60, 100]
    finally:
        if win is not None:
            win._router.wait_loaded()
            win._close_midi_devices = lambda: win._midi.close()
            win._midi.close()
            win._audio_driver.close()
            win.Destroy()
        os.remove(path)
