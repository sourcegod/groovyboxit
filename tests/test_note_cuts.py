"""
    File: tests/test_note_cuts.py
    Notes coupées avant un changement de son (Phase 8 étape 6c1, tests de
    6b1 ; docs/DESIGN.md § Phase 8 étape 6a, N1-N3, N7-N9) : toutes les
    notes avant un Mute / Solo, celles de la piste avant un changement de
    slot, de canal ou de programme fait par l'utilisateur, rien au Program
    Change rejoué ; notes seules (Pitch Bend et modulation gardés).
    Date: Tue, 03/11/2026
    Author: Coolbrother
"""

import os
import sys
import threading
import types
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import wx

import track_router as tr_mod
import ui.midi_handler_window as mh
from engines.bank_engine import BankEngine
from engines.fluidsynth_engine import FluidSynthEngine
from pattern import Pattern, with_bank_header
from rack import Rack, InstrumentType
from track_router import TrackRouter
from test_bank_slot import FakeBankEngine, FakeTimer


SF = "/fake/FluidR3_GM.sf2"
SYNTH, SYNTH2, BANK, KIT = 1, 2, 5, 9


class _Synth:
    """Moteur synthé factice : chargé, coupures notées."""
    def __init__(self, *a, **kw):
        self.cuts, self.sustain, self.patch = 0, True, None
        self.plays, self.stops = [], []
        self.pitch_bend, self.pitch_bend_semitones = 0, 0.0
    def load_patch(self, name):     self.patch = name
    def is_loaded(self):            return True
    def has_full_range(self):       return True
    def precompute(self, notes):    pass
    def stop_all_voices(self):      self.cuts += 1
    def play(self, note, *a):       self.plays.append(note)
    def stop(self, note):           self.stops.append(note)


class _Snd:
    def __init__(self):
        self.stops = 0
    def stop_all(self):              self.stops += 1
    def play_sound(self, *a):        pass
    def play_note(self, *a):         pass


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    if wx.GetApp() is None:
        globals()["_APP"] = wx.App(False)
    FakeTimer.created = []
    monkeypatch.setattr(tr_mod, "threading",
                        types.SimpleNamespace(Timer=FakeTimer, Thread=threading.Thread))
    monkeypatch.setattr(tr_mod, "SynthEngine", _Synth)


def _router(rack_mode=False):
    rack = Rack()
    rack.set_slot(SYNTH,  InstrumentType.SYNTH, "Piano", {"patch": "p"})
    rack.set_slot(SYNTH2, InstrumentType.SYNTH, "Orgue", {"patch": "o"})
    rack.set_slot(BANK,   InstrumentType.BANK,  "FluidR3", {"bank_slot": 0})
    rack.set_slot(KIT,    InstrumentType.KIT,   "808", {})
    rack.set_bank_file(0, SF)
    r = TrackRouter(rack, "/fake", _Snd(), lambda m: None,
                    bank_engine=FakeBankEngine(), schedule=lambda *a: None)
    r.sync_bank_files()
    r.rack_mode = rack_mode
    for idx in (SYNTH, SYNTH2):
        r._ensure_slot_synth(idx)
    r.wait_loaded()
    r.bank_engine.calls.clear()
    return r


def _cc(eng, num):
    return [c for c in eng.calls if c[0] == "cc" and c[2] == num]


# ---------------------------------------------------------------------------
# Moteur de banque : un canal seul (N9)
# ---------------------------------------------------------------------------

def test_bank_engine_channel_sounds_off_default_is_cc120_on_channel():
    eng = FakeBankEngine()
    eng.channel_sounds_off(4)
    assert eng.calls == [("cc", 4, 120, 0)]


def test_fluidsynth_channel_sounds_off_uses_channel():
    eng = FluidSynthEngine.__new__(FluidSynthEngine)
    eng._lib, eng._synth = MagicMock(), "synth"
    eng.channel_sounds_off(3)
    eng._lib.fluid_synth_all_sounds_off.assert_called_once_with("synth", 3)


# ---------------------------------------------------------------------------
# cut_all_notes (N1, N7, N8)
# ---------------------------------------------------------------------------

def test_cut_all_notes_cuts_every_engine_and_bank_channel():
    r = _router()
    r.load_slot_preview(SYNTH)                  # préécoute = moteur du slot (partagé)
    r._kit_synth = _Synth()
    r.cut_all_notes()
    assert r._slot_synths[SYNTH].cuts == 1      # une fois, même partagé
    assert r._slot_synths[SYNTH2].cuts == 1
    assert r._kit_synth.cuts == 1
    assert not r._slot_synths[SYNTH].sustain    # pédale relâchée
    assert r._snd.stops == 1
    eng = r.bank_engine
    assert eng.of("all_sounds_off") == [("all_sounds_off",)]
    assert sorted(c[1] for c in _cc(eng, 64)) == list(range(16))


def test_cut_all_notes_keeps_pitch_bend_and_modulation():
    r = _router()
    r.cut_all_notes()
    eng = r.bank_engine
    assert eng.of("bend") == [] and _cc(eng, 1) == [] and _cc(eng, 121) == []
    assert eng.of("reset_controllers") == []


def test_cut_all_notes_without_bank_engine():
    r = _router()
    r.bank_engine = None
    r.cut_all_notes()                            # pas d'erreur
    assert r._snd.stops == 1


# ---------------------------------------------------------------------------
# cut_track_notes (N2, N9)
# ---------------------------------------------------------------------------

def test_cut_track_notes_bank_track_cuts_its_current_channel_only():
    r = _router()
    r._track_slots[0] = BANK
    r._track_channels[0] = r._track_cur_channels[0] = 2
    r.program_change(0, 33, 6)                  # la piste passe au canal 7
    r.bank_engine.calls.clear()
    r.cut_track_notes(0)
    assert _cc(r.bank_engine, 120) == [("cc", 6, 120, 0)]
    assert _cc(r.bank_engine, 64) == [("cc", 6, 64, 0)]
    assert r._slot_synths[SYNTH].cuts == 0


def test_cut_track_notes_bank_preview_same_channel_once():
    r = _router()
    r._track_slots[0] = BANK
    r._track_channels[0] = r._track_cur_channels[0] = 2
    r.load_slot_preview(BANK)                   # jeu direct sur la banque
    r.cut_track_notes(0)
    assert _cc(r.bank_engine, 120) == [("cc", 2, 120, 0)]


def test_held_controller_note_cut_before_channel_change():
    """La cause des notes sans fin : la note tenue sur le canal 3 est coupée
    sur ce canal avant que la piste ne passe au canal 7."""
    r = _router()
    r._track_slots[0] = BANK
    r._track_channels[0] = r._track_cur_channels[0] = 2
    r.load_slot_preview(BANK)
    r.synth.play(60, 1.0, 0, 0)                 # tenue (durée 0)
    r.cut_track_notes(0)
    r.program_change(0, 33, 6)
    calls = r.bank_engine.calls
    on   = calls.index(("note_on", 2, 60, 127))
    cut  = calls.index(("cc", 2, 120, 0))
    assert on < cut


def test_cut_track_notes_synth_track_cuts_its_engine_and_preview():
    r = _router()
    r._track_slots[0] = SYNTH
    r.load_slot_preview(SYNTH2)                 # le clavier joue un autre synthé
    r.cut_track_notes(0)
    assert r._slot_synths[SYNTH].cuts == 1
    assert r._slot_synths[SYNTH2].cuts == 1     # préécoute
    assert r.bank_engine.calls == []


def test_cut_track_notes_synth_track_leaves_other_engines():
    r = _router()
    r._track_slots[0] = SYNTH
    r.load_slot_preview(SYNTH)
    r.cut_track_notes(0)
    assert r._slot_synths[SYNTH].cuts == 1 and r._slot_synths[SYNTH2].cuts == 0
    assert r._snd.stops == 0


def test_cut_track_notes_kit_track_cuts_only_preview():
    r = _router()
    r._track_slots[0] = KIT
    r.cut_track_notes(0)                         # sans préécoute
    assert r._snd.stops == 0 and r.bank_engine.calls == []
    assert all(e.cuts == 0 for e in r._slot_synths.values())


def test_cut_track_notes_rack_mode_uses_slot_of_channel():
    r = _router(rack_mode=True)
    r._track_slots[0] = KIT
    r._track_channels[0] = r._track_cur_channels[0] = SYNTH2   # canal 3 → slot 3
    r.cut_track_notes(0)
    assert r._slot_synths[SYNTH2].cuts == 1 and r._slot_synths[SYNTH].cuts == 0


def test_program_change_replayed_by_pattern_cuts_nothing():
    r = _router()
    r._track_slots[0] = BANK
    r._track_channels[0] = r._track_cur_channels[0] = 2
    r.on_program_change_tape(0, 40, 6)
    assert _cc(r.bank_engine, 120) == [] and r.bank_engine.of("all_sounds_off") == []


# ---------------------------------------------------------------------------
# Gestes : Mute / Solo de la fenêtre principale (N1)
# ---------------------------------------------------------------------------

from test_mix_undo import _MixWindow, _char


def _mix_window():
    win = _MixWindow()
    seen = []
    win._router.cut_all_notes = lambda: seen.append(
        (list(win._router._track_mutes), list(win._router._track_solos)))
    return win, seen


@pytest.mark.parametrize("letter, shift", [("X", False), ("S", False), ("X", True), ("S", True)])
def test_track_mute_solo_keys_cut_all_notes_before_change(letter, shift):
    win, seen = _mix_window()
    win._player._cur_track = 2
    if shift:                                    # quelque chose à défaire
        win._router._track_mutes[4] = win._router._track_solos[4] = True
    _char(win, letter, shift=shift, on_track_list=True)
    assert len(seen) == 1
    before = seen[0][0 if letter == "X" else 1]
    assert before[2] is False and (not shift or before[4] is True)   # coupé avant


def test_pad_mute_does_not_cut_notes():
    win, seen = _mix_window()
    _char(win, "X", on_track_list=False)
    assert seen == []


# ---------------------------------------------------------------------------
# Gestes : propriétés de piste, Ctrl+T, Program Change du contrôleur (N1, N2)
# ---------------------------------------------------------------------------

from test_rack_mode_ui import _RackWin, _scripted_track_dlg, _channels


def _recording_window(rack_mode=False):
    win = _RackWin(rack_mode=rack_mode)
    log = []
    r = win._router
    real_track = r.cut_track_notes
    r.cut_all_notes = lambda: log.append(("all", list(r._track_mutes)))
    r.cut_track_notes = lambda t: (log.append(("track", t, r.get_track_channel(t),
                                               r._track_slots[t])), real_track(t))
    return win, log


def _track_props(win, fake):
    with patch("ui.mw_tracks.TrackPropertiesDialog", fake):
        win._track_properties_dialog()


def _scripted(result, change):
    """Dialogue factice : change(values) modifie les valeurs, transmises
    une fois par on_change, puis Ok ou Annuler."""
    base = _scripted_track_dlg(result)

    class FakeDlg(base):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            change(self.v)
            kw["on_change"](*self.v)
    return FakeDlg


def test_track_properties_channel_change_cuts_track_notes_before():
    win, log = _recording_window()
    _channels(win, [3])
    _track_props(win, _scripted(wx.ID_OK, lambda v: v.__setitem__(5, 7)))
    assert log[0] == ("track", 0, 3, BANK)       # avant : canal 4
    assert win._router.get_track_channel(0) == 7
    assert not any(e[0] == "all" for e in log)


def test_track_properties_slot_change_cuts_track_notes():
    win, log = _recording_window()
    _track_props(win, _scripted(wx.ID_OK, lambda v: v.__setitem__(0, SYNTH)))
    assert log[0][:2] == ("track", 0) and log[0][3] == BANK


def test_track_properties_volume_change_cuts_nothing():
    win, log = _recording_window()
    _track_props(win, _scripted(wx.ID_OK, lambda v: v.__setitem__(1, 40)))
    assert log == []


def test_track_properties_mute_change_cuts_all_notes_before():
    win, log = _recording_window()
    _track_props(win, _scripted(wx.ID_OK, lambda v: v.__setitem__(3, True)))
    assert log[0] == ("all", [False] * 16)
    assert win._router._track_mutes[0] is True


def test_track_properties_cancel_after_change_cuts_again():
    win, log = _recording_window()
    _channels(win, [3])
    _track_props(win, _scripted(wx.ID_CANCEL, lambda v: v.__setitem__(5, 7)))
    tracks = [e for e in log if e[0] == "track"]
    assert [e[2] for e in tracks] == [3, 7]      # puis retour au canal 4
    assert win._router.get_track_channel(0) == 3


def test_ctrl_t_cuts_track_notes_before_assigning():
    win, log = _recording_window()
    win._cur_slot = SYNTH
    win._assign_track_slot()
    assert log == [("track", 0, 0, BANK)]
    assert win._router._track_slots[0] == SYNTH


def test_ctrl_t_same_slot_cuts_nothing():
    win, log = _recording_window()
    win._cur_slot = BANK
    win._assign_track_slot()
    assert log == []


def test_ctrl_t_rack_mode_cuts_track_notes_before_channel_change():
    win, log = _recording_window(rack_mode=True)
    _channels(win, [0])
    win._cur_slot = SYNTH
    win._assign_track_slot()
    assert log == [("track", 0, 0, BANK)]
    assert win._router.get_track_channel(0) == SYNTH


def test_controller_program_change_cuts_track_notes():
    win, log = _recording_window()
    _channels(win, [3])
    win._input_mode = "pads"
    mh.MidiHandler(win).on_program_change(33, 0)
    assert log == [("track", 0, 3, BANK)]


# ---------------------------------------------------------------------------
# Le relâchement va là où la note a été jouée (Phase 8 étape 6c2, tests de
# 6b2 : essai de l'utilisateur, note tenue pendant la navigation des pistes)
# ---------------------------------------------------------------------------

def test_bank_preview_stops_held_note_on_its_own_channel():
    r = _router()
    r._track_slots[:2] = [BANK, BANK]
    r._track_channels[:2] = r._track_cur_channels[:2] = [3, 5]
    cur = [0]
    r._cur_track_cb = lambda: cur[0]
    r.load_slot_preview(BANK)
    r.synth.play(64, 1.0, 0, 0)                  # tenue, canal 4
    cur[0] = 1                                   # piste suivante, canal 6
    r.synth.stop(64)
    assert r.bank_engine.of("note_off") == [("note_off", 3, 64)]


def test_bank_preview_unheld_note_stops_on_current_channel():
    r = _router()
    r._track_slots[0] = BANK
    r._track_channels[0] = r._track_cur_channels[0] = 3
    r._cur_track_cb = lambda: 0
    r.load_slot_preview(BANK)
    r.synth.play(64, 1.0, 0, 300)                # durée : pas retenue
    assert r.synth._held == {}
    r.synth.stop(64)
    assert r.bank_engine.of("note_off")[-1] == ("note_off", 3, 64)


def _live_window(rack_mode=False):
    win = _RackWin(rack_mode=rack_mode)
    win._router._cur_track_cb = lambda: win._player._cur_track
    win._input_mode = "keyboard"
    win._kb_root_midi = win._kb_play_root = 60
    win._note_repeat, win._vel_level, win._cur_row = False, 0, 0
    win._player.erasing = False
    win.ROWS = win.COLS = 16
    win._shift_pad = 0
    return win, mh.MidiHandler(win)


def test_held_note_released_on_previous_track_channel_after_navigation():
    """Le cas de l'essai : la note jouée sur la piste 1 (canal 4) est
    arrêtée sur le canal 4, même si la piste 2 (canal 6) est devenue
    courante entre l'appui et le relâchement."""
    win, h = _live_window()
    r = win._router
    _channels(win, [3, 5])
    win._go_to_track(0)
    h.on_note_on(64, 100, 0)
    win._go_to_track(1)
    h.on_note_off(64, 0)
    notes = [c for c in r.bank_engine.calls if c[0] in ("note_on", "note_off")]
    assert notes == [("note_on", 3, 64, 127), ("note_off", 3, 64)]
    assert h._live_held == {}


def test_held_note_released_on_previous_synth_after_navigation():
    win, h = _live_window()
    r = win._router
    win._rack.set_slot(SYNTH2, InstrumentType.SYNTH, "Orgue", {"patch": "o"})
    r.assign_slot(0, SYNTH)                      # chaque synthé a son moteur
    r.assign_slot(1, SYNTH2)
    r.wait_loaded()
    win._go_to_track(0)
    first = r.synth
    h.on_note_on(64, 100, 0)
    win._go_to_track(1)                          # préécoute : l'autre synthé
    second = r.synth
    h.on_note_off(64, 0)
    assert first is not second
    assert first.plays == [64] and first.stops == [64]
    assert second.stops == []


def test_held_note_off_recorded_with_played_note():
    win, h = _live_window()
    r = win._router
    r._track_slots[:2] = [SYNTH, SYNTH2]
    win._go_to_track(0)
    win._player.recording = True
    played = []
    win._player.record_patch_note = lambda note, vel, **kw: None
    win._player.record_patch_note_off = lambda note: played.append(note)
    h.on_note_on(64, 100, 0)
    win._kb_root_midi = 72                       # transposition changée entre-temps
    h.on_note_off(64, 0)
    assert played == [64]                        # la note jouée, pas 76


def test_held_pad_note_released_with_its_drum_note():
    """Mode pads : au canal 10 d'une banque, le pad joue 36 + pad ; après
    passage sur une piste en gamme, l'arrêt vise toujours cette note."""
    win, h = _live_window()
    win._input_mode = "pads"
    r = win._router
    _channels(win, [Pattern.KIT_CHANNEL, 3])
    r.update_kb_notes("major", 48)
    win._go_to_track(0)
    h.on_note_on(36, 100, 0)                     # pad 1 → note 36 sur le canal 10
    win._go_to_track(1)
    h.on_note_off(36, 0)
    offs = r.bank_engine.of("note_off")
    assert offs and offs[-1][1] == Pattern.KIT_CHANNEL
