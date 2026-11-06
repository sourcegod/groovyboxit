"""
    File: test_rack_mode.py
    Mode Rack 16 canaux, moteur (Phase 8 étape 5c1, tests de 5b1 ;
    docs/DESIGN.md § Phase 8 étape 5a, M1, M3, M5, M6, M9-M13) : dans un
    pattern en mode Rack, le canal courant N d'une piste joue le slot N.
    Date: Sun, 01/11/2026
    Author: Coolbrother
"""

import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

import track_router as tr_mod
from rack import Rack, InstrumentType
from track_router import TrackRouter
from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH, ETYPE_PGM, ETYPE_CC
from audio.engines.bank_engine import BankEngine
from audio.sound_manager import SoundManager
from song import frozen_pattern
from ui.mw_pads import PadMixin
from ui.mw_patterns import PatternMixin
from ui.mw_songs import SongMixin
import audio_export


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

SF = "/fake/FluidR3_GM.sf2"


class FakeBankEngine(BankEngine):
    """Moteur de banque sans son : enregistre les appels."""

    def __init__(self):
        super().__init__("gs")
        self.paths = [None] * self.NUM_BANK_SLOTS
        self.calls = []

    def load(self, slot, path):
        self.paths[slot] = path
        return True

    def unload(self, slot):
        self.paths[slot] = None

    def loaded_path(self, slot):
        return self.paths[slot]

    def presets(self, slot):
        return [(0, 0, "Piano"), (0, 33, "Fingered Bass"), (128, 0, "Standard")]

    def select(self, channel, slot, bank, program):
        self.calls.append(("select", channel, slot, bank, program))
        return True

    def note_on(self, channel, note, velocity):
        self.calls.append(("note_on", channel, note, velocity))

    def note_off(self, channel, note):
        pass

    def cc(self, channel, num, value):
        self.calls.append(("cc", channel, num, value))

    def pitch_bend(self, channel, value):
        self.calls.append(("bend", channel, value))

    def program_change(self, channel, program):
        pass

    def all_notes_off(self):
        pass

    def all_sounds_off(self):
        pass

    def reset_controllers(self):
        pass

    def render(self, out):
        pass

    def close(self):
        pass

    def of(self, kind):
        return [c for c in self.calls if c[0] == kind]


class FakeSynthEngine:
    """Remplace SynthEngine : chargé dès load_patch, joue dans plays."""
    created = []

    def __init__(self, synths_dir=None, driver=None):
        self.patch  = None
        self.plays  = []
        self.pitch_bend = 0
        self.pitch_bend_semitones = 0.0
        self.mods   = []
        FakeSynthEngine.created.append(self)

    def load_patch(self, name):
        self.patch = name

    def is_loaded(self):
        return self.patch is not None

    def has_full_range(self):
        return True

    def precompute(self, notes):
        pass

    def play(self, midi, vol, pan, dur):
        self.plays.append(midi)

    def stop(self, midi):
        pass

    def apply_pitch_bend(self):
        pass

    def set_mod_wheel(self, value):
        self.mods.append(value)


class FakeSoundManager:
    """Sons du kit : enregistre pads et notes joués."""

    def __init__(self, gm_note_map=None, note_map=None):
        self.played       = []
        self.played_notes = []
        self.gm_note_map  = gm_note_map or {}
        self.note_map     = note_map or {}

    def play_sound(self, pad_idx, vol, pan):
        self.played.append(pad_idx)

    def play_note(self, note, vol):
        self.played_notes.append(note)

    kit_note_of_gm = SoundManager.kit_note_of_gm

    def stop_all(self):
        pass

    def render_copy(self, driver):
        return self


@pytest.fixture(autouse=True)
def _fake_synth(monkeypatch):
    FakeSynthEngine.created = []
    monkeypatch.setattr(tr_mod, "SynthEngine", FakeSynthEngine)


# Rack d'essai : slot 2 synthé (canal 2), slot 6 banque (canal 6), slot 10
# kit (canal 10), slot 12 second kit ; les autres vides.
SYNTH, BANK, KIT, KIT2 = 1, 5, 9, 11


def _rack(bank=True):
    rack = Rack()
    rack.set_slot(SYNTH, InstrumentType.SYNTH, "Piano WAV", {"patch": "piano_1"})
    rack.set_slot(KIT,   InstrumentType.KIT,   "808",       {"kit": ""})
    rack.set_slot(KIT2,  InstrumentType.KIT,   "909",       {"kit": ""})
    if bank:
        rack.set_slot(BANK, InstrumentType.BANK, "FluidR3", {"bank_slot": 0})
        rack.set_bank_file(0, SF)
    return rack


def _router(rack=None, snd=None, rack_mode=True, slots=BANK):
    rack = rack or _rack()
    r = TrackRouter(rack, "/synths", snd or FakeSoundManager(), lambda m: None,
                    bank_engine=FakeBankEngine(), schedule=lambda *a: None)
    r._track_slots[:] = [slots] * 16
    r.rack_mode = rack_mode
    r.sync_bank_files()                  # emplacements chargés, comme au démarrage
    return r


def _set_channels(r, channels):
    for t, ch in enumerate(channels):
        r._track_channels[t] = ch
        r._track_cur_channels[t] = ch


def _note(note=60, ch=0, time=0):
    return TapeEvent(ETYPE_PATCH, payload={"note": note, "vel": 100}, time=time, channel=ch)


def _pgm(program, ch, time=0):
    return TapeEvent(ETYPE_PGM, payload={"program": program}, time=time, channel=ch)


def _tape(**tracks):
    tape = [[] for _ in range(16)]
    for k, events in tracks.items():
        tape[int(k[1:])] = events
    return tape


# ---------------------------------------------------------------------------
# Pattern._rack_mode (M2, M13)
# ---------------------------------------------------------------------------

def test_pattern_rack_mode_default_false():
    assert Pattern()._rack_mode is False
    assert Pattern().to_dict()["rack_mode"] is False


def test_pattern_rack_mode_round_trip():
    p = Pattern()
    p._rack_mode = True
    q = Pattern()
    q.from_dict(p.to_dict())
    assert q._rack_mode is True


def test_pattern_rack_mode_survives_json():
    p = Pattern()
    p._rack_mode = True
    q = Pattern()
    q.from_dict(json.loads(json.dumps(p.to_dict())))
    assert q._rack_mode is True


def test_pattern_rack_mode_absent_key_is_normal_mode():
    p = Pattern()
    p._rack_mode = True
    d = Pattern().to_dict()
    del d["rack_mode"]
    p.from_dict(d)                       # projet d'avant 5b1, rechargé dans un Pattern existant
    assert p._rack_mode is False


@pytest.mark.parametrize("value", [1, "true", None, [True]])
def test_pattern_rack_mode_non_bool_is_normal_mode(value):
    d = Pattern().to_dict()
    d["rack_mode"] = value
    p = Pattern()
    p.from_dict(d)
    assert p._rack_mode is False


def test_pattern_copy_from_copies_rack_mode():
    src = Pattern()
    src._rack_mode = True
    dst = Pattern()
    dst.copy_from(src)
    assert dst._rack_mode is True
    src._rack_mode = False
    dst.copy_from(src)
    assert dst._rack_mode is False


def test_frozen_pattern_keeps_rack_mode():
    p = Pattern()
    p._rack_mode = True
    assert frozen_pattern(p)._rack_mode is True


# ---------------------------------------------------------------------------
# Slot effectif (M1, M5, M9)
# ---------------------------------------------------------------------------

def test_rack_slot_idx_filled_slot_is_its_number():
    r = _router()
    assert r.rack_slot_idx(SYNTH) == SYNTH
    assert r.rack_slot_idx(KIT) == KIT
    assert r.rack_slot_idx(BANK) == BANK


def test_rack_slot_idx_empty_slot_falls_back_to_first_bank():
    rack = _rack()
    rack.set_slot(14, InstrumentType.BANK, "Autre", {"bank_slot": 1})
    r = _router(rack)
    assert r.fallback_bank_idx() == BANK
    assert r.rack_slot_idx(0) == BANK
    assert r.rack_slot_idx(3) == BANK


def test_rack_slot_idx_without_bank_is_the_empty_slot():
    r = _router(_rack(bank=False))
    assert r.fallback_bank_idx() is None
    assert r.rack_slot_idx(3) == 3


def test_slot_for_track_follows_channel_in_rack_mode():
    r = _router(slots=KIT)
    _set_channels(r, [SYNTH, KIT, BANK, 0])
    assert [r.slot_for_track(t) for t in range(4)] == [SYNTH, KIT, BANK, BANK]
    assert r.slot_name(0) == "Piano WAV"


def test_slot_for_track_is_own_slot_in_normal_mode():
    r = _router(rack_mode=False, slots=KIT)
    _set_channels(r, [SYNTH, KIT, BANK, 0])
    assert [r.slot_for_track(t) for t in range(4)] == [KIT] * 4


def test_track_slots_untouched_by_rack_mode():
    """Décocher le mode rend à chaque piste son propre slot (M9)."""
    r = _router(slots=KIT)
    _set_channels(r, [SYNTH])
    r.chase(_tape(t0=[_note(ch=SYNTH)]))
    assert r._track_slots[0] == KIT
    r.rack_mode = False
    assert r.slot_for_track(0) == KIT


def test_track_channel_now_in_rack_mode_for_any_slot():
    r = _router(slots=KIT)
    _set_channels(r, [SYNTH])
    r._track_cur_channels[0] = 4
    assert r.track_channel_now(0) == 4
    r.rack_mode = False
    assert r.track_channel_now(0) == SYNTH       # kit en mode normal : canal de la piste


# ---------------------------------------------------------------------------
# Lecture (M1, M5, M11)
# ---------------------------------------------------------------------------

def _loaded_synth(r):
    r._ensure_slot_synth(SYNTH)
    r.wait_loaded()
    return r._slot_synths[SYNTH]


def test_patch_note_on_synth_channel_plays_synth_slot():
    r = _router()
    _set_channels(r, [SYNTH])
    engine = _loaded_synth(r)
    r.on_patch_tape(0, 64, 100)
    assert engine.plays == [64]
    assert r.bank_engine.of("note_on") == []


def test_patch_note_on_bank_channel_plays_bank():
    r = _router(slots=SYNTH)
    _set_channels(r, [BANK])
    r.on_patch_tape(0, 64, 100, 200)
    assert r.bank_engine.of("note_on") == [("note_on", BANK, 64, 100)]


def test_patch_note_on_empty_channel_plays_fallback_bank_on_its_channel():
    r = _router(slots=SYNTH)
    _set_channels(r, [3])
    r.on_patch_tape(0, 64, 100, 200)
    assert r.bank_engine.of("note_on") == [("note_on", 3, 64, 100)]


def test_patch_note_on_empty_channel_without_bank_is_silent():
    snd = FakeSoundManager()
    r = _router(_rack(bank=False), snd=snd, slots=KIT)
    _set_channels(r, [3])
    r.on_patch_tape(0, 64, 100)
    r.on_kit_tape(0, 36, 100)
    r.on_play(0, 0, 1.0, 0)
    assert snd.played == [] and snd.played_notes == []
    assert r.bank_engine.of("note_on") == []


def test_patch_note_on_kit_channel_plays_kit_note_of_gm():
    snd = FakeSoundManager(gm_note_map={60: 36, 61: 38, 62: 36}, note_map={60: "a", 61: "b", 62: "c"})
    r = _router(snd=snd)
    _set_channels(r, [KIT])
    r.on_patch_tape(0, 36, 100)                  # GM 36 → plus basse note du kit : 60
    r.on_patch_tape(0, 38, 100)                  # GM 38 → 61
    r.on_patch_tape(0, 42, 100)                  # sans correspondance : telle quelle
    assert snd.played_notes == [60, 61, 42]


def test_patch_note_on_kit_in_normal_mode_plays_too():
    """M11 vaut dans les deux modes : une note PATCH n'est plus muette sur un kit."""
    snd = FakeSoundManager(gm_note_map={60: 36}, note_map={60: "a"})
    r = _router(snd=snd, rack_mode=False, slots=KIT)
    r.on_patch_tape(0, 36, 100)
    assert snd.played_notes == [60]


def test_kit_note_on_synth_channel_plays_synth():
    snd = FakeSoundManager()
    r = _router(snd=snd, slots=KIT)
    _set_channels(r, [SYNTH])
    engine = _loaded_synth(r)
    r.on_kit_tape(0, 40, 100)
    assert engine.plays == [40] and snd.played_notes == []


def test_kit_note_on_kit_channel_plays_kit():
    snd = FakeSoundManager()
    r = _router(snd=snd, slots=SYNTH)
    _set_channels(r, [KIT])
    r.on_kit_tape(0, 40, 100)
    assert snd.played_notes == [40]


def test_grid_cell_on_kit_channel_plays_pad():
    snd = FakeSoundManager()
    r = _router(snd=snd, slots=SYNTH)
    _set_channels(r, [KIT])
    r.on_play(0, 3, 1.0, 0)
    assert snd.played == [3]


def test_grid_cell_on_synth_channel_plays_scale_note():
    r = _router(slots=KIT)
    _set_channels(r, [SYNTH])
    engine = _loaded_synth(r)
    r.set_playback_kb("major", 48)               # gamme du pattern, posée à son chargement
    r.on_play(0, 0, 1.0, 0)
    assert engine.plays == [48]


def test_grid_cell_on_bank_drum_channel_plays_gm_drum_note():
    rack = _rack()
    rack.clear_slot(KIT)                         # canal 10 vide → repli banque, batterie
    r = _router(rack, slots=SYNTH)
    _set_channels(r, [KIT])
    r.on_play(0, 2, 1.0, 0)
    assert r.bank_engine.of("note_on")[0][1:3] == (KIT, TrackRouter.DRUM_GRID_BASE + 2)


def test_bend_and_mod_go_to_synth_of_channel():
    r = _router(slots=KIT)
    _set_channels(r, [SYNTH])
    engine = _loaded_synth(r)
    r.on_bend_tape(0, 4096)
    r.on_mod_tape(0, 90)
    assert engine.pitch_bend == 4096 and engine.mods == [90]


def test_bend_on_fallback_bank_goes_to_track_channel():
    r = _router(slots=SYNTH)
    _set_channels(r, [4])
    r.on_bend_tape(0, 1000)
    assert ("bend", 4, 1000) in r.bank_engine.calls


def test_muted_track_stays_silent_in_rack_mode():
    r = _router()
    _set_channels(r, [BANK])
    r.toggle_track_mute(0)
    r.on_patch_tape(0, 64, 100)
    assert r.bank_engine.of("note_on") == []


# ---------------------------------------------------------------------------
# Program Change (M3, O3)
# ---------------------------------------------------------------------------

def test_program_change_has_no_bridge_in_rack_mode():
    r = _router(slots=KIT)
    _set_channels(r, [KIT])
    assert r.program_change(0, 3, KIT) is False
    assert r._track_slots[0] == KIT              # pas d'assign_slot(program % 16)
    assert r.slot_for_track(0) == KIT


def test_program_change_bridge_kept_in_normal_mode():
    r = _router(rack_mode=False, slots=KIT)
    r.program_change(0, 17)
    assert r._track_slots[0] == 1                # 17 % 16


def test_program_change_moves_track_to_its_channel_and_slot():
    r = _router(slots=KIT)
    _set_channels(r, [KIT])
    r.program_change(0, 0, SYNTH)
    r.wait_loaded()
    assert r.track_channel_now(0) == SYNTH
    assert r.slot_for_track(0) == SYNTH
    assert SYNTH in r._slot_synths and r._slot_synths[SYNTH].is_loaded()


def test_program_change_on_synth_channel_is_ignored_for_sound():
    r = _router(slots=KIT)
    _set_channels(r, [SYNTH])
    engine = _loaded_synth(r)
    assert r.program_change(0, 40, SYNTH) is False
    assert r._slot_synths[SYNTH] is engine and engine.patch == "piano_1"
    assert r.bank_engine.of("select") == []
    assert r.channel_instrument(SYNTH)[0] == 40  # mais l'état du canal le retient


def test_program_change_on_bank_channel_selects_instrument():
    r = _router(slots=KIT)
    _set_channels(r, [BANK])
    assert r.program_change(0, 33, BANK) is True
    assert r.bank_engine.of("select")[-1] == ("select", BANK, 0, 0, 33)


def test_program_change_on_empty_channel_selects_on_fallback_bank():
    r = _router(slots=KIT)
    _set_channels(r, [KIT])
    assert r.program_change(0, 33, 4) is True
    assert r.track_channel_now(0) == 4
    assert r.bank_engine.of("select")[-1] == ("select", 4, 0, 0, 33)
    assert r.bank_preset_name(0) == "Fingered Bass"


def test_program_change_tape_replay_uses_event_channel():
    r = _router(slots=KIT)
    _set_channels(r, [KIT])
    r.on_program_change_tape(0, 0, SYNTH)
    assert r.slot_for_track(0) == SYNTH


# ---------------------------------------------------------------------------
# Poursuite et moteurs (M10)
# ---------------------------------------------------------------------------

def test_chase_covers_tracks_on_any_slot():
    r = _router(slots=KIT)
    _set_channels(r, [KIT])
    tape = _tape(t0=[_pgm(0, SYNTH, time=4)])
    r.chase(tape, 8.0)
    assert r.track_channel_now(0) == SYNTH
    r.chase(tape, 2.0)
    assert r.track_channel_now(0) == KIT


def test_chase_normal_mode_skips_non_bank_tracks():
    r = _router(rack_mode=False, slots=KIT)
    r.chase(_tape(t0=[_pgm(0, SYNTH, time=0)]), 8.0)
    assert r._track_cur_channels[0] == r._track_channels[0]


def test_chase_selects_instrument_of_channel_from_any_track():
    r = _router(slots=SYNTH)
    _set_channels(r, [4])
    tape = _tape(t0=[TapeEvent(ETYPE_CC, payload={"cc_num": 0, "value": 8}, time=0, channel=4),
                     _pgm(1, 4)])
    r.chase(tape, 0.0)
    assert r.channel_instrument(4) == (1, 8, 0)
    assert ("select", 4, 0, 8, 1) in r.bank_engine.calls


def test_chase_loads_synths_of_played_channels():
    r = _router(slots=KIT)
    _set_channels(r, [0, 0])
    r.chase(_tape(t1=[_pgm(0, SYNTH, time=12)]), 0.0)   # canal d'un Program Change à venir
    r.wait_loaded()
    assert SYNTH in r._slot_synths


def test_chase_does_not_load_synth_of_empty_track_channel():
    r = _router(slots=KIT)
    _set_channels(r, [0, SYNTH])                 # piste 2 au canal du synthé, mais vide
    r.chase(_tape(t0=[_note(ch=0)]), 0.0)
    assert SYNTH not in r._slot_synths


def test_chase_normal_mode_does_not_load_rack_synths():
    r = _router(rack_mode=False, slots=KIT)
    _set_channels(r, [SYNTH])
    r.chase(_tape(t0=[_note(ch=SYNTH)]), 0.0)
    assert SYNTH not in r._slot_synths


def test_set_track_channel_loads_synth_of_new_channel():
    r = _router(slots=KIT)
    r.set_track_channel(0, SYNTH)
    r.wait_loaded()
    assert r.slot_for_track(0) == SYNTH and SYNTH in r._slot_synths


def test_rack_channels_of():
    r = _router()
    _set_channels(r, [2, 7, 9])
    tape = _tape(t0=[_note(ch=2), _pgm(0, 5, time=4)], t2=[_note(ch=9)])
    assert r.rack_channels_of(tape) == [2, 5, 9]


def test_render_copy_keeps_rack_mode():
    r = _router()
    assert r.render_copy(driver=None).rack_mode is True
    r.rack_mode = False
    assert r.render_copy(driver=None).rack_mode is False


# ---------------------------------------------------------------------------
# Kit du pattern et avertissements (M5, M6)
# ---------------------------------------------------------------------------

def test_rack_report_prefers_channel_10_kit():
    r = _router()
    _set_channels(r, [KIT2, KIT])
    tape = _tape(t0=[_note(ch=KIT2)], t1=[_note(ch=KIT)])
    rep = r.rack_report(tape)
    assert rep["kit"] == KIT and rep["other_kits"] == [KIT2] and rep["muted"] == []


def test_rack_report_first_kit_without_channel_10():
    r = _router()
    _set_channels(r, [KIT2])
    rep = r.rack_report(_tape(t0=[_note(ch=KIT2)]))
    assert rep["kit"] == KIT2 and rep["other_kits"] == []


def test_rack_report_no_kit():
    r = _router()
    _set_channels(r, [SYNTH])
    assert r.rack_report(_tape(t0=[_note(ch=SYNTH)]))["kit"] is None


def test_rack_report_muted_channels_without_bank():
    r = _router(_rack(bank=False))
    _set_channels(r, [3, SYNTH, 6])
    tape = _tape(t0=[_note(ch=3)], t1=[_note(ch=SYNTH)], t2=[_note(ch=6)])
    assert r.rack_report(tape)["muted"] == [3, 6]


def test_rack_report_no_muted_channel_with_fallback_bank():
    r = _router()
    _set_channels(r, [3])
    assert r.rack_report(_tape(t0=[_note(ch=3)]))["muted"] == []


# --- SoundManager : kit_note_of_gm, kit_path -------------------------------

class _FakeDriver:
    def load(self, path):
        return ("sound", path)

    def make_silent(self, *a):
        return ("silent",)


def _kit_file(tmp_path):
    (tmp_path / "kick.wav").write_bytes(b"")
    (tmp_path / "snare.wav").write_bytes(b"")
    kit = {"name": "Test", "base_note": 36, "pads": [
        {"pad": 1, "note": 60, "filename": "kick.wav",  "label": "Kick",  "gm_note": 36},
        {"pad": 2, "note": 61, "filename": "snare.wav", "label": "Snare", "gm_note": 38}]}
    path = tmp_path / "kit.json"
    path.write_text(json.dumps(kit))
    return str(path)


def test_sound_manager_kit_note_of_gm_and_kit_path(tmp_path):
    snd = SoundManager([], "c1", "c2", driver=_FakeDriver())
    assert snd.kit_path is None
    path = _kit_file(tmp_path)
    snd.load_kit(path)
    assert snd.kit_path == os.path.abspath(path)
    assert snd.kit_note_of_gm(36) == 60
    assert snd.kit_note_of_gm(38) == 61
    assert snd.kit_note_of_gm(42) == 42
    snd.load_sounds()
    assert snd.kit_path is None


# --- _apply_rack_kit (mw_pads.py) ------------------------------------------

class _FakeSnd:
    def __init__(self):
        self.kit_path    = None
        self.loaded      = []
        self.defaults    = 0
        self.mute_groups = [0] * 16

    def load_kit(self, path):
        self.loaded.append(path)
        self.kit_path = os.path.abspath(path)
        return [], []

    def load_sounds(self):
        self.defaults += 1
        self.kit_path = None


class _FakeVM:
    def __init__(self):
        self.names  = {}
        self.groups = {}

    def set_name(self, i, name):
        self.names[i] = name

    def set_mute_group(self, i, group):
        self.groups[i] = group


class _KitWindow(PadMixin):
    def __init__(self, router, rack):
        self._router  = router
        self._rack    = rack
        self._snd     = _FakeSnd()
        self._player  = types.SimpleNamespace(voice_manager=_FakeVM())
        self.statuses = []

    def _show_status(self, msg):
        self.statuses.append(msg)


def _kit_window(tmp_path, rack=None, rack_mode=True):
    rack = rack or _rack()
    path = _kit_file(tmp_path)
    rack.get_slot(KIT).config = {"kit": path}
    rack.get_slot(KIT2).config = {"kit": path.replace("kit.json", "kit2.json")}
    r = _router(rack, rack_mode=rack_mode)
    return _KitWindow(r, rack), r, path


def test_apply_rack_kit_loads_kit_without_renaming_pads(tmp_path):
    win, r, path = _kit_window(tmp_path)
    _set_channels(r, [KIT])
    win._apply_rack_kit(_tape(t0=[_note(ch=KIT)]))
    assert win._snd.loaded == [path]
    assert win._player.voice_manager.names == {}           # M12
    assert len(win._player.voice_manager.groups) == 16
    assert win.statuses == []


def test_apply_rack_kit_does_not_reload_same_kit(tmp_path):
    win, r, path = _kit_window(tmp_path)
    _set_channels(r, [KIT])
    tape = _tape(t0=[_note(ch=KIT)])
    win._apply_rack_kit(tape)
    win._apply_rack_kit(tape)
    assert win._snd.loaded == [path]


def test_apply_rack_kit_warns_other_kits(tmp_path):
    win, r, path = _kit_window(tmp_path)
    _set_channels(r, [KIT2, KIT])
    win._apply_rack_kit(_tape(t0=[_note(ch=KIT2)], t1=[_note(ch=KIT)]))
    assert win._snd.loaded == [path]
    assert win.statuses == [f"Mode Rack : un seul kit à la fois — slot {KIT2 + 1} "
                            f"joue le kit du slot {KIT + 1}"]


def test_apply_rack_kit_warns_muted_channels(tmp_path):
    win, r, _ = _kit_window(tmp_path, rack=_rack(bank=False))
    _set_channels(r, [3, 6])
    win._apply_rack_kit(_tape(t0=[_note(ch=3)], t1=[_note(ch=6)]))
    assert win.statuses == ["Mode Rack : canaux 4, 7 muets (slot vide, aucun slot Banque)"]


def test_apply_rack_kit_missing_file_loads_default_sounds(tmp_path):
    win, r, _ = _kit_window(tmp_path)
    r._rack.get_slot(KIT).config = {"kit": "/absent/kit.json"}
    win._snd.kit_path = "/old/kit.json"
    _set_channels(r, [KIT])
    win._apply_rack_kit(_tape(t0=[_note(ch=KIT)]))
    assert win._snd.loaded == [] and win._snd.defaults == 1


def test_apply_rack_kit_does_nothing_in_normal_mode(tmp_path):
    win, r, _ = _kit_window(tmp_path, rack_mode=False)
    _set_channels(r, [KIT])
    win._apply_rack_kit(_tape(t0=[_note(ch=KIT)]))
    assert win._snd.loaded == [] and win.statuses == []


# ---------------------------------------------------------------------------
# Le mode suit le pattern chargé (M2, M13)
# ---------------------------------------------------------------------------

class _FakePlayer:
    def __init__(self):
        self._pattern      = Pattern()
        self.voice_manager = types.SimpleNamespace(from_list=lambda v: None)
        self.bpm           = 120

    def set_bpm(self, bpm):
        self.bpm = bpm

    def _current_offset(self):
        return 0.0


class _LoadWindow(PatternMixin, SongMixin):
    def __init__(self, router):
        self._router   = router
        self._player   = _FakePlayer()
        self._bpm_ctrl = types.SimpleNamespace(SetValue=lambda v: None)
        self._pattern_listbox = types.SimpleNamespace(SetSelection=lambda i: None)
        self._song_window = None
        self.kit_calls = []
        self.statuses  = []

    def _apply_rack_kit(self, tape):
        self.kit_calls.append(self._router.rack_mode)

    def _show_status(self, msg):
        self.statuses.append(msg)


def _rack_pattern(rack_mode):
    p = Pattern()
    p._rack_mode = rack_mode
    return p


def test_apply_pattern_from_store_sets_router_mode_and_loads_kit():
    win = _LoadWindow(_router(rack_mode=False))
    win._apply_pattern_from_store(_rack_pattern(True))
    assert win._router.rack_mode is True and win._player._pattern._rack_mode is True
    assert win.kit_calls == [True]
    win._apply_pattern_from_store(_rack_pattern(False))
    assert win._router.rack_mode is False and win.kit_calls == [True]


def test_song_advance_sets_router_mode_and_loads_kit():
    win = _LoadWindow(_router(rack_mode=False))
    win._pattern_list = [_rack_pattern(False), _rack_pattern(True)]
    win._cur_pattern_idx = 0
    win._on_song_advance(1)
    assert win._router.rack_mode is True and win.kit_calls == [True]
    win._on_song_advance(0)
    assert win._router.rack_mode is False and win.kit_calls == [True]


def test_audio_export_state_sets_router_mode():
    r = _router(rack_mode=False)
    p = _rack_pattern(True)
    audio_export._PatternState(p, p._tape).apply(r)
    assert r.rack_mode is True
    q = _rack_pattern(False)
    audio_export._PatternState(q, q._tape).apply(r)
    assert r.rack_mode is False
