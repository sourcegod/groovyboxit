#python3
"""
    File: tests/test_render_copy.py
    Tests de la Phase 8 étape 1d1 (docs/DESIGN.md § Phase 8 étape 1a, W6,
    W7) : ordonnanceur des fins de note injecté dans TrackRouter ; copies
    pour le rendu hors temps réel (TrackRouter, SoundManager, SynthEngine,
    FluidSynthEngine), indépendantes des moteurs de l'écoute ; événements
    de _tape et jeu partagés par la lecture et le rendu
    (player/tape_events.py).
    Date: Sat, 31/10/2026
    Author: Coolbrother
"""
import sys
import os
import types
import threading
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest
import soundfile as sf

import track_router as tr_mod
from track_router import TrackRouter
from rack import Rack, InstrumentType
from pattern import (TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH,
                     ETYPE_CC, ETYPE_PGM, ETYPE_BEND)
from engines.bank_engine import BankEngine
from engines import fluidsynth_engine as fs_mod
from sound_device_driver import Mixer
from sound_manager import SoundManager
from synth_engine import SynthEngine
from voice_manager import VoiceManager
from player import tape_events as te
from player.dp_playback import PlaybackLoopMixin


# ---------------------------------------------------------------------------
# Faux moteurs et aides
# ---------------------------------------------------------------------------

class FakeBankEngine(BankEngine):
    """Moteur de banque sans son : enregistre les appels."""

    def __init__(self, bank_select="gs"):
        super().__init__(bank_select)
        self.paths = [None] * self.NUM_BANK_SLOTS
        self.calls = []

    def load(self, slot, path):
        self.paths[slot] = path
        self.calls.append(("load", slot, path))
        return True

    def unload(self, slot):
        self.paths[slot] = None

    def loaded_path(self, slot):
        return self.paths[slot]

    def presets(self, slot):
        return []

    def select(self, channel, slot, bank, program):
        self.calls.append(("select", channel, slot, bank, program))
        return True

    def note_on(self, channel, note, velocity):
        self.calls.append(("note_on", channel, note, velocity))

    def note_off(self, channel, note):
        self.calls.append(("note_off", channel, note))

    def cc(self, channel, num, value):
        self.calls.append(("cc", channel, num, value))

    def pitch_bend(self, channel, value):
        self.calls.append(("bend", channel, value))

    def all_notes_off(self):
        pass

    def all_sounds_off(self):
        pass

    def reset_controllers(self):
        pass

    def render(self, out):
        pass

    def render_copy(self):
        return FakeBankEngine(self.bank_select)

    def close(self):
        pass


class FakeTimer:
    created = []

    def __init__(self, interval, fn, args=None):
        self.interval, self.fn, self.args = interval, fn, list(args or [])
        self.started = False
        FakeTimer.created.append(self)

    def start(self):
        self.started = True


@pytest.fixture(autouse=True)
def _fake_timer(monkeypatch):
    """Seul track_router voit FakeTimer : threading global intact."""
    FakeTimer.created = []
    monkeypatch.setattr(tr_mod, "threading",
                        types.SimpleNamespace(Timer=FakeTimer, Thread=threading.Thread))


SYNTH_SLOT = 1
BANK_SLOT  = 2
SF         = "/fake/FluidR3_GM.sf2"


def _wav(tmp_path, name="a.wav", value=0.3, n=4410):
    path = str(tmp_path / name)
    sf.write(path, np.full(n, value, dtype=np.float32), 44100)
    return path


def _synth(tmp_path, driver):
    eng = SynthEngine(str(tmp_path), driver=driver)
    eng.load_single_sample(_wav(tmp_path, "synth.wav"), root_midi=60)
    return eng


def _sound_manager(tmp_path, driver):
    click = _wav(tmp_path, "click.wav", 0.1, 100)
    pads  = [_wav(tmp_path, f"pad{i}.wav", 0.2 + i / 100, 2000) for i in range(16)]
    sm = SoundManager(pads, click, click, driver=driver)
    sm.load_sounds()
    return sm


def _rack():
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT, "Kit", {})
    rack.set_slot(SYNTH_SLOT, InstrumentType.SYNTH, "Synth", {"patch": "p"})
    rack.set_slot(BANK_SLOT, InstrumentType.BANK, "GM", {"bank_slot": 0})
    rack.set_bank_file(0, SF)
    return rack


def _router(snd=None, bank=None, driver=None, schedule=None):
    r = TrackRouter(_rack(), "/fake/synths", snd or MagicMock(), lambda m: None,
                    driver=driver or MagicMock(), bank_engine=bank, schedule=schedule)
    r.set_playback_kb("major", 48)
    return r


class Recorder:
    """Ordonnanceur de test : enregistre (delay_ms, fn, args)."""

    def __init__(self):
        self.calls = []

    def __call__(self, delay_ms, fn, *args):
        self.calls.append((delay_ms, fn, args))

    def fire_all(self):
        for _, fn, args in self.calls:
            fn(*args)


# ---------------------------------------------------------------------------
# Ordonnanceur des fins de note
# ---------------------------------------------------------------------------

def test_default_schedule_is_wall_clock_timer():
    bank = FakeBankEngine()
    r = _router(bank=bank)
    r.bank_note(3, 60, 100, 250)
    (t,) = FakeTimer.created
    assert t.interval == pytest.approx(0.25)
    assert t.fn == bank.note_off and t.args == [3, 60]
    assert t.started


def test_bank_note_uses_injected_schedule():
    bank, sched = FakeBankEngine(), Recorder()
    r = _router(bank=bank, schedule=sched)
    r.bank_note(3, 60, 100, 250)
    assert FakeTimer.created == []
    assert sched.calls == [(250, bank.note_off, (3, 60))]
    sched.fire_all()
    assert ("note_off", 3, 60) in bank.calls


def test_bank_note_held_is_not_scheduled():
    sched = Recorder()
    r = _router(bank=FakeBankEngine(), schedule=sched)
    r.bank_note(0, 60, 100, 0)                  # jeu direct : tenue
    assert sched.calls == []


def test_grid_on_synth_track_schedules_stop(tmp_path):
    mixer, sched = Mixer(), Recorder()
    r = _router(driver=mixer, schedule=sched)
    eng = _synth(tmp_path, mixer)
    r._track_slots[0] = SYNTH_SLOT
    r._slot_synths[SYNTH_SLOT] = eng
    r.on_play(0, 0, 1.0, 0, 300)
    midi = r._kb_notes_play[0]
    assert sched.calls == [(300, eng.stop, (midi,))]
    assert FakeTimer.created == []


def test_patch_tape_schedules_stop_default_duration(tmp_path):
    mixer, sched = Mixer(), Recorder()
    r = _router(driver=mixer, schedule=sched)
    eng = _synth(tmp_path, mixer)
    r._track_slots[2] = SYNTH_SLOT
    r._slot_synths[SYNTH_SLOT] = eng
    r.on_patch_tape(2, 60, 100, 0)              # sans durée : 500 ms
    assert sched.calls == [(500, eng.stop, (60,))]
    assert mixer.voice_count() == 1


# ---------------------------------------------------------------------------
# TrackRouter.render_copy
# ---------------------------------------------------------------------------

def _live_router(tmp_path):
    live_drv = Mixer()
    snd  = _sound_manager(tmp_path, live_drv)
    bank = FakeBankEngine("mma")
    r = _router(snd=snd, bank=bank, driver=live_drv)
    eng = _synth(tmp_path, live_drv)
    r._track_slots[1] = SYNTH_SLOT
    r._slot_synths[SYNTH_SLOT] = eng
    r._slot_synths[5] = eng                     # même moteur sur deux slots
    r._track_slots[3] = BANK_SLOT
    r.toggle_track_mute(4)
    r.toggle_track_solo(6)
    r._track_volumes[1] = 70
    r._track_pans[1] = -40
    r._track_channels[3] = 5
    r._track_cur_channels[3] = 7
    r._chan_prog[7] = 33
    r.master_pan = 20
    return r, live_drv, snd, bank, eng


def test_render_copy_copies_playback_state(tmp_path):
    r, *_ = _live_router(tmp_path)
    c = r.render_copy(Mixer(), FakeBankEngine())
    for attr in ("_track_slots", "_track_mutes", "_track_solos", "_track_volumes",
                 "_track_pans", "_track_channels", "_track_cur_channels",
                 "_chan_prog", "_chan_msb", "_chan_lsb", "_kb_notes_play"):
        assert getattr(c, attr) == getattr(r, attr), attr
        assert getattr(c, attr) is not getattr(r, attr), attr
    assert c.master_pan == 20
    assert c._rack is r._rack


def test_render_copy_state_is_independent(tmp_path):
    r, *_ = _live_router(tmp_path)
    c = r.render_copy(Mixer(), FakeBankEngine())
    c._track_volumes[1] = 10
    c.toggle_track_mute(1)
    c._track_cur_channels[3] = 0
    r._track_pans[1] = 90
    assert r._track_volumes[1] == 70 and not r._track_mutes[1]
    assert r._track_cur_channels[3] == 7
    assert c._track_pans[1] == -40


def test_render_copy_engines_on_render_driver(tmp_path):
    r, live_drv, snd, bank, eng = _live_router(tmp_path)
    mixer, rbank, sched = Mixer(), FakeBankEngine(), Recorder()
    c = r.render_copy(mixer, rbank, sched)
    assert c._driver is mixer and c.bank_engine is rbank
    assert c._schedule is sched
    assert c._snd is not snd and c._snd._driver is mixer
    copy_eng = c._slot_synths[SYNTH_SLOT]
    assert copy_eng is not eng and copy_eng._driver is mixer
    assert c._slot_synths[5] is copy_eng       # une seule copie du moteur partagé
    # l'écoute n'a pas bougé
    assert r._driver is live_drv and r.bank_engine is bank
    assert r._snd is snd and snd._driver is live_drv
    assert r._slot_synths[SYNTH_SLOT] is eng and eng._driver is live_drv


def test_render_copy_plays_on_render_mixer_only(tmp_path):
    r, live_drv, *_ = _live_router(tmp_path)
    mixer, sched = Mixer(), Recorder()
    c = r.render_copy(mixer, FakeBankEngine(), sched)
    c.unsolo_all_tracks()                       # la piste 6 en solo rendrait 0 et 1 muettes
    c.on_play(0, 2, 1.0, 0, 100)                # piste 0 : kit
    c.on_play(1, 0, 1.0, 0, 100)                # piste 1 : synthé
    assert mixer.voice_count() == 2
    assert live_drv.voice_count() == 0
    assert len(sched.calls) == 1 and FakeTimer.created == []


def test_render_copy_respects_mute_solo_of_live(tmp_path):
    r, *_ = _live_router(tmp_path)
    c = r.render_copy(Mixer(), FakeBankEngine())
    assert not c._track_is_audible(4)           # muette
    assert c._track_is_audible(6)               # en solo
    assert not c._track_is_audible(0)           # hors solo


def test_render_copy_bank_engine_loads_rack_files_on_chase(tmp_path):
    r, _, _, bank, _ = _live_router(tmp_path)
    rbank = FakeBankEngine()
    c = r.render_copy(Mixer(), rbank)
    bank.calls.clear()
    c.chase([[] for _ in range(16)], 0.0)
    assert rbank.loaded_path(0) == SF
    assert any(call[0] == "select" for call in rbank.calls)
    assert bank.calls == []                     # moteur de l'écoute intact


def test_render_copy_status_ignored_by_default(tmp_path):
    r, *_ = _live_router(tmp_path)
    c = r.render_copy(Mixer(), FakeBankEngine())
    c._status_cb("message")                     # sans erreur, sans effet
    seen = []
    c2 = r.render_copy(Mixer(), FakeBankEngine(), status_cb=seen.append)
    c2._status_cb("x")
    assert seen == ["x"]


def test_render_copy_default_schedule_is_timer(tmp_path):
    r, *_ = _live_router(tmp_path)
    rbank = FakeBankEngine()
    c = r.render_copy(Mixer(), rbank)
    c.bank_note(0, 60, 100, 100)
    assert len(FakeTimer.created) == 1


# ---------------------------------------------------------------------------
# SoundManager.render_copy
# ---------------------------------------------------------------------------

def test_sound_manager_copy_shares_sounds_copies_tables(tmp_path):
    live = Mixer()
    sm = _sound_manager(tmp_path, live)
    sm.note_map = {36 + i: s for i, s in enumerate(sm.drum_sounds)}
    sm.set_pad_mute_group(0, 1)
    sm.set_pad_mute_group(1, 1)
    mixer = Mixer()
    c = sm.render_copy(mixer)
    assert c._driver is mixer and sm._driver is live
    assert c.drum_sounds is not sm.drum_sounds
    assert all(a is b for a, b in zip(c.drum_sounds, sm.drum_sounds))
    assert c.note_map == sm.note_map and c.note_map is not sm.note_map
    assert c._group_sounds == sm._group_sounds
    assert c._group_sounds[1] is not sm._group_sounds[1]
    sm.drum_sounds[0] = sm._silent_sound()      # kit changé pendant le rendu
    sm.note_map.clear()
    assert c.drum_sounds[0] is not sm.drum_sounds[0] and len(c.note_map) == 16


def test_sound_manager_copy_plays_on_mixer_with_mute_group(tmp_path):
    live = Mixer()
    sm = _sound_manager(tmp_path, live)
    sm.set_pad_mute_group(0, 1)
    sm.set_pad_mute_group(1, 1)
    mixer = Mixer()
    c = sm.render_copy(mixer)
    c.play_sound(0)
    assert mixer.voice_count() == 1 and live.voice_count() == 0
    c.play_sound(1)                             # coupe le pad 0, même groupe
    assert mixer.voice_count() == 1


# ---------------------------------------------------------------------------
# SynthEngine.render_copy
# ---------------------------------------------------------------------------

def test_synth_copy_same_patch_fresh_state(tmp_path):
    live = Mixer()
    eng = _synth(tmp_path, live)
    eng.play(60, 1.0, 0, 200)
    eng.pitch_bend, eng.mod_wheel, eng.sustain = 4096, 64, True
    eng._sustained_notes.add(60)
    mixer = Mixer()
    c = eng.render_copy(mixer)
    assert c._driver is mixer and eng._driver is live
    assert c.is_loaded() and c._patch_name == eng._patch_name
    assert c._active_voices == {} and eng._active_voices != {}
    assert (c.pitch_bend, c.mod_wheel, c.sustain) == (0, 0, False)
    assert c._sustained_notes == set() and eng._sustained_notes == {60}
    assert c.pitch_bend_range == eng.pitch_bend_range


def test_synth_copy_reuses_computed_sounds_independent_caches(tmp_path):
    eng = _synth(tmp_path, Mixer())
    eng.get_sound(60, 200)
    c = eng.render_copy(Mixer())
    assert c._cache[(60, 200)] is eng._cache[(60, 200)]
    for attr in ("_cache", "_raw_cache", "_loop_cache", "_samples"):
        assert getattr(c, attr) is not getattr(eng, attr), attr
    c.stop_all_voices()                         # vide le _loop_cache de la copie
    c.clear_cache()
    assert (60, 200) in eng._cache


def test_synth_copy_plays_on_mixer_only(tmp_path):
    live = Mixer()
    eng = _synth(tmp_path, live)
    mixer = Mixer()
    c = eng.render_copy(mixer)
    c.play(60, 1.0, 0, 200)
    assert mixer.voice_count() == 1 and live.voice_count() == 0
    c.stop(60)
    assert mixer.voice_count() == 0


# ---------------------------------------------------------------------------
# FluidSynthEngine.render_copy
# ---------------------------------------------------------------------------

def test_bank_engine_contract_has_render_copy():
    with pytest.raises(NotImplementedError):
        BankEngine().render_copy()


@pytest.mark.skipif(not fs_mod.fluidsynth_available(), reason="libfluidsynth absente")
def test_fluidsynth_copy_same_settings_no_bank(tmp_path):
    eng = fs_mod.FluidSynthEngine(samplerate=48000, bank_select="mma", gain=0.3)
    try:
        c = eng.render_copy()
        try:
            assert isinstance(c, fs_mod.FluidSynthEngine) and c is not eng
            assert (c._samplerate, c.bank_select, c._gain) == (48000, "mma", 0.3)
            assert c._synth != eng._synth
            assert all(c.loaded_path(i) is None for i in range(c.NUM_BANK_SLOTS))
        finally:
            c.close()
    finally:
        eng.close()


# ---------------------------------------------------------------------------
# player/tape_events : événements et jeu partagés
# ---------------------------------------------------------------------------

def _tape():
    tape = [[] for _ in range(16)]
    tape[0].append(TapeEvent(ETYPE_GRID, dur=120, payload={"pad": 3, "vel": 90}, time=4))
    tape[1].append(TapeEvent(ETYPE_KIT, dur=50, payload={"note": 38, "vel": 100}, time=2))
    tape[2].append(TapeEvent(ETYPE_PATCH, dur=0, payload={"note": 64, "vel": 80}, time=8))
    tape[2].append(TapeEvent(ETYPE_BEND, payload={"value": 1000}, time=8))
    tape[3].append(TapeEvent(ETYPE_CC, channel=4, payload={"cc_num": 64, "value": 127}, time=0))
    tape[3].append(TapeEvent(ETYPE_PGM, channel=5, payload={"program": 12}, time=0))
    tape[4].append(TapeEvent(ETYPE_GRID, payload={"pad": 0, "vel": 100}, time=20))
    return tape


def test_markers_shared_with_player():
    assert PlaybackLoopMixin.GRID_EVENT == te.GRID_EVENT
    assert PlaybackLoopMixin.KIT_TAPE_EVENT == te.KIT_TAPE_EVENT
    assert PlaybackLoopMixin.PATCH_TAPE_EVENT == te.PATCH_TAPE_EVENT
    assert PlaybackLoopMixin.BEND_TAPE_EVENT == te.BEND_TAPE_EVENT
    assert PlaybackLoopMixin.CC_TAPE_EVENT == te.CC_TAPE_EVENT
    assert PlaybackLoopMixin.PGM_TAPE_EVENT == te.PGM_TAPE_EVENT
    assert len({te.GRID_EVENT, te.KIT_TAPE_EVENT, te.PATCH_TAPE_EVENT, te.BEND_TAPE_EVENT,
                te.CC_TAPE_EVENT, te.PGM_TAPE_EVENT, PlaybackLoopMixin.NR_EVENT,
                PlaybackLoopMixin.TEMPO_EVENT}) == 8


def test_tape_events_window_and_conversion():
    evs = te.tape_events(_tape(), 0, 15, lambda s: s * 0.1)
    assert (0.4, te.GRID_EVENT, (0, 3, 120), 90) in evs
    assert (0.2, te.KIT_TAPE_EVENT, (1, 38, 50), 100) in evs
    assert (0.8, te.PATCH_TAPE_EVENT, (2, 64, 0), 80) in evs
    assert (0.8, te.BEND_TAPE_EVENT, (2, 1000), 0) in evs
    assert (0.0, te.CC_TAPE_EVENT, (3, 64, 127, 4), 0) in evs
    assert (0.0, te.PGM_TAPE_EVENT, (3, 12, 5), 0) in evs
    assert len(evs) == 6                        # temps 20 hors fenêtre


def test_tape_events_relative_to_window_start():
    evs = te.tape_events(_tape(), 4, 20, lambda s: s)
    assert sorted(e[0] for e in evs) == [0, 4, 4, 16]


def test_tape_events_min_sec_excludes_past():
    evs = te.tape_events(_tape(), 0, 15, lambda s: s * 0.1, min_sec=0.2)
    assert sorted(e[0] for e in evs) == [0.4, 0.8, 0.8]


def test_sort_events_stable_on_time_and_marker():
    evs = [(1.0, te.CC_TAPE_EVENT, (0, 121, 0, 0), 0),
           (1.0, te.CC_TAPE_EVENT, (0, 64, 127, 0), 0),
           (0.5, te.GRID_EVENT, (0, 1, 0), 100),
           (1.0, te.BEND_TAPE_EVENT, (0, 0), 0)]
    out = te.sort_events(list(evs))
    assert out[0][0] == 0.5
    assert out[1][1] == te.CC_TAPE_EVENT and out[1][2][1] == 121   # CC121 reste avant CC64
    assert out[2][2][1] == 64
    assert out[3][1] == te.BEND_TAPE_EVENT


def test_grid_hit_volume_pan_duration():
    vm = VoiceManager()
    vm._voices[2].volume = 80
    vm._voices[2].pan = -70
    vm._voices[2].duration_ms = 250
    assert te.grid_hit(vm, 2, 50, 0, 0) == (pytest.approx(0.4), -70, 250)
    assert te.grid_hit(vm, 2, 200, 0, -50) == (1.0, -100, 250)    # bornés
    assert te.grid_hit(vm, 2, 100, 90, 0)[2] == 90                 # durée propre


def test_grid_hit_mute_and_solo():
    vm = VoiceManager()
    vm._voices[1].mute = True
    assert te.grid_hit(vm, 1, 100, 0, 0) is None
    vm._voices[1].mute = False
    vm._voices[5].solo = True
    assert te.grid_hit(vm, 1, 100, 0, 0) is None
    assert te.grid_hit(vm, 5, 100, 0, 0) is not None


def test_play_event_dispatches_like_playback():
    router, vm = MagicMock(), VoiceManager()
    vm._voices[3].pan = 10
    for ev in te.sort_events(te.tape_events(_tape(), 0, 15, lambda s: s)):
        te.play_event(router, vm, 5, *ev[1:])
    router.on_play.assert_called_once_with(0, 3, pytest.approx(0.9), 15, 120)   # durée propre
    router.on_kit_tape.assert_called_once_with(1, 38, 100, 50)
    router.on_patch_tape.assert_called_once_with(2, 64, 80, 0)
    router.on_bend_tape.assert_called_once_with(2, 1000)
    router.on_cc_tape.assert_called_once_with(3, 64, 127, 4)
    router.on_program_change_tape.assert_called_once_with(3, 12, 5)


def test_play_event_skips_inaudible_pad():
    router, vm = MagicMock(), VoiceManager()
    vm._voices[3].mute = True
    te.play_event(router, vm, 0, te.GRID_EVENT, (0, 3, 0), 100)
    router.on_play.assert_not_called()


def test_play_event_and_player_dispatch_agree():
    """Même case de grille : le player et play_event appellent le routeur
    avec les mêmes volume, pan et durée."""
    from player.drum_player import DrumPlayer
    p = DrumPlayer.__new__(DrumPlayer)
    p.voice_manager = VoiceManager()
    p.voice_manager._voices[3].volume = 60
    p.voice_manager._voices[3].pan = 40
    p.pan = 70
    p._cur_track = 9
    p._erase_active_pads = set()
    p.replace_recording = False
    seen = []
    p._on_track_play_cb = lambda *a: seen.append(("player",) + a)
    p._dispatch_event(te.GRID_EVENT, (0, 3, 0), 80, 0.0)
    router = MagicMock()
    router.on_play.side_effect = lambda *a: seen.append(("render",) + a)
    te.play_event(router, p.voice_manager, p.pan, te.GRID_EVENT, (0, 3, 0), 80)
    assert seen[0][1:] == seen[1][1:]
    assert seen[0][1:] == (0, 3, pytest.approx(0.48), 100, 500)
