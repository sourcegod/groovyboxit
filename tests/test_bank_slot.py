#python3
"""
    File: tests/test_bank_slot.py
    Tests du slot Banque (Phase 7 étape 17e1, docs/DESIGN.md § 17a1) :
    Rack et .gvp (InstrumentType.BANK, config, 4 emplacements), routage de
    tous les événements vers un moteur de banque factice (D8, D11, D12, D13,
    D18), canal 10 (D9), avertissement de canal partagé (D10), jeu direct
    (BankPreview), export CC0 / CC32 (D18).
    Date: Mon, 26/10/2026
    Author: Coolbrother
"""
import sys
import os
import threading
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

import track_router as tr_mod
from rack import Rack, InstrumentSlot, InstrumentType
from track_router import TrackRouter, BankPreview
from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH
from project_manager import ProjectManager
from engines.bank_engine import BankEngine
from midi.midi_export import build_pattern_midi, volume_to_cc7, pan_to_cc10
from synth_engine import scale_midi_notes

NUM_TRACKS = TrackRouter.NUM_TRACKS
KIT_CH     = Pattern.KIT_CHANNEL


# ---------------------------------------------------------------------------
# Moteur de banque factice
# ---------------------------------------------------------------------------

class FakeBankEngine(BankEngine):
    """Moteur sans son : enregistre les appels. refuse : chemins refusés
    par load ; missing : (emplacement, banque, programme) introuvables."""

    def __init__(self, bank_select="gs", refuse=(), missing=()):
        super().__init__(bank_select)
        self.paths   = [None] * self.NUM_BANK_SLOTS
        self.calls   = []
        self.refuse  = set(refuse)
        self.missing = set(missing)

    def load(self, slot, path):
        self.calls.append(("load", slot, path))
        if path in self.refuse:
            return False
        self.paths[slot] = path
        return True

    def unload(self, slot):
        self.calls.append(("unload", slot))
        self.paths[slot] = None

    def loaded_path(self, slot):
        return self.paths[slot]

    def presets(self, slot):
        return []

    def select(self, channel, slot, bank, program):
        self.calls.append(("select", channel, slot, bank, program))
        return self.paths[slot] is not None and (slot, bank, program) not in self.missing

    def note_on(self, channel, note, velocity):
        self.calls.append(("note_on", channel, note, velocity))

    def note_off(self, channel, note):
        self.calls.append(("note_off", channel, note))

    def cc(self, channel, num, value):
        self.calls.append(("cc", channel, num, value))

    def pitch_bend(self, channel, value):
        self.calls.append(("bend", channel, value))

    def program_change(self, channel, program):
        self.calls.append(("pgm", channel, program))

    def all_notes_off(self):
        self.calls.append(("all_notes_off",))

    def all_sounds_off(self):
        self.calls.append(("all_sounds_off",))

    def reset_controllers(self):
        self.calls.append(("reset_controllers",))

    def render(self, out):
        pass

    def close(self):
        pass

    # -- aides des tests --

    def of(self, kind):
        return [c for c in self.calls if c[0] == kind]

    def ccs(self, channel=None, num=None):
        return [c for c in self.of("cc")
                if (channel is None or c[1] == channel) and (num is None or c[2] == num)]


class FakeSoundManager:
    def __init__(self):
        self.played       = []
        self.played_notes = []

    def play_sound(self, pad_idx, vol, pan):
        self.played.append((pad_idx, vol, pan))

    def play_note(self, note, vol):
        self.played_notes.append((note, vol))

    def stop_all(self):
        pass


class FakeTimer:
    """Remplace threading.Timer dans track_router : la coupure de note est
    enregistrée, et exécutée par fire()."""
    created = []

    def __init__(self, interval, fn, args=None):
        self.interval, self.fn, self.args = interval, fn, args or []
        FakeTimer.created.append(self)

    def start(self):
        pass

    def fire(self):
        self.fn(*self.args)


class FakeSynthEngine:
    """Remplace SynthEngine : le vrai, sans pilote, ouvre un flux audio
    (SoundDeviceDriver) jamais fermé, qui fait planter la sortie de pytest."""
    _cache = {}

    def __init__(self, synths_dir=None, driver=None):
        pass

    def is_loaded(self):
        return False

    def has_full_range(self):
        return True

    def load_patch(self, name):
        pass

    def precompute(self, notes):
        pass


@pytest.fixture(autouse=True)
def _fake_timer_and_synth(monkeypatch):
    """Seul track_router voit FakeTimer : le module threading global reste
    intact (wx et pytest s'en servent). Aucun SynthEngine réel."""
    FakeTimer.created = []
    monkeypatch.setattr(tr_mod, "threading",
                        types.SimpleNamespace(Timer=FakeTimer, Thread=threading.Thread))
    monkeypatch.setattr(tr_mod, "SynthEngine", FakeSynthEngine)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SF = "/fake/FluidR3_GM.sf2"
SF2 = "/fake/GeneralUser_GS.sf2"


def _bank_config(bank_slot=0, msb=0, lsb=0, program=0, drums=False):
    return {"bank_slot": bank_slot, "bank_msb": msb, "bank_lsb": lsb,
            "program": program, "drums": drums}


def _make_rack():
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT,   "Default Kit", {})
    rack.set_slot(1, InstrumentType.SYNTH, "Piano WAV",   {"patch": "piano_1"})
    rack.set_slot(2, InstrumentType.BANK,  "Acoustic Grand Piano", _bank_config(program=0))
    rack.set_slot(3, InstrumentType.BANK,  "Violin",   _bank_config(program=40))
    rack.set_slot(4, InstrumentType.BANK,  "Standard", _bank_config(drums=True))
    rack.set_slot(5, InstrumentType.BANK,  "Piano 2",  _bank_config(bank_slot=1, msb=8, lsb=3, program=1))
    rack.set_bank_file(0, SF)
    return rack


def _make_router(engine=None, cur_track=0, with_engine=True):
    rack     = _make_rack()
    snd      = FakeSoundManager()
    statuses = []
    if engine is None and with_engine:
        engine = FakeBankEngine()
    holder = {"track": cur_track}
    router = TrackRouter(rack, "/fake/synths", snd, statuses.append,
                         bank_engine=engine, cur_track=lambda: holder["track"])
    router.update_kb_notes("major", 48)
    router.set_playback_kb("major", 48)
    return router, engine, snd, statuses, holder


# ---------------------------------------------------------------------------
# Rack : type, config, emplacements
# ---------------------------------------------------------------------------

def test_bank_type_is_listed():
    assert InstrumentType.BANK == "bank"
    assert InstrumentType.BANK in InstrumentType.ALL


def test_plays_notes_synth_and_bank_only():
    rack = _make_rack()
    assert rack.get_slot(1).plays_notes
    assert rack.get_slot(2).plays_notes
    assert not rack.get_slot(0).plays_notes
    assert not rack.get_slot(15).plays_notes          # slot vide


def test_bank_config_read_and_bounded():
    s = InstrumentSlot(0)
    s.type, s.config = InstrumentType.BANK, _bank_config(bank_slot=9, msb=200, lsb=-1, program=300)
    assert s.bank_slot() == Rack.NUM_BANK_SLOTS - 1
    assert (s.bank_msb(), s.bank_lsb(), s.bank_program()) == (127, 0, 127)


def test_bank_config_defaults_and_invalid_values():
    s = InstrumentSlot(0)
    s.type, s.config = InstrumentType.BANK, {"program": "12", "bank_msb": True, "drums": 1}
    assert (s.bank_slot(), s.bank_msb(), s.bank_lsb(), s.bank_program()) == (0, 0, 0, 0)
    assert s.bank_drums() is False                     # seul True compte


def test_gm_program_of_bank_is_real_program_and_no_gm_gain():
    rack = _make_rack()
    slot = rack.get_slot(3)
    slot.config["gm_gain_db"] = -12
    assert slot.gm_program() == 40
    assert slot.gm_gain_db() == 0


def test_bank_files_default_empty():
    assert Rack().bank_files == [None] * Rack.NUM_BANK_SLOTS == [None] * 4


def test_set_bank_file_replaces_list_not_in_place():
    rack = Rack()
    before = rack.bank_files
    rack.set_bank_file(2, SF)
    assert rack.bank_files == [None, None, SF, None]
    assert before == [None] * 4                        # instantané d'Undo intact
    rack.set_bank_file(2, "")
    assert rack.bank_files[2] is None


def test_rack_dict_roundtrip_keeps_bank_slots_and_files():
    rack = _make_rack()
    rack.set_bank_file(3, SF2)
    other = Rack()
    other.from_dict(rack.to_dict())
    assert other.bank_files == [SF, None, None, SF2]
    s = other.get_slot(5)
    assert s.type == InstrumentType.BANK
    assert (s.bank_slot(), s.bank_msb(), s.bank_lsb(), s.bank_program()) == (1, 8, 3, 1)
    assert other.get_slot(4).bank_drums()


def test_rack_from_old_project_without_bank_files():
    rack = _make_rack()
    d = rack.to_dict()
    del d["bank_files"]
    rack.from_dict(d)
    assert rack.bank_files == [None] * 4


def test_rack_from_dict_bank_files_sanitized():
    rack = Rack()
    rack.from_dict({"slots": [], "bank_files": [SF, 3, "", SF2, "/trop.sf2"]})
    assert rack.bank_files == [SF, None, None, SF2]
    rack.from_dict({"slots": [], "bank_files": [SF]})
    assert rack.bank_files == [SF, None, None, None]
    rack.from_dict({"slots": [], "bank_files": "pas une liste"})
    assert rack.bank_files == [None] * 4


def test_gvp_roundtrip_keeps_bank_slots(tmp_path):
    rack = _make_rack()
    path = str(tmp_path / "banque.gvp")
    ProjectManager.save(path, {"version": ProjectManager.VERSION, "rack": rack.to_dict()})
    other = Rack()
    other.from_dict(ProjectManager.load(path)["rack"])
    assert other.bank_files == rack.bank_files
    assert other.get_slot(3).to_dict() == rack.get_slot(3).to_dict()


# ---------------------------------------------------------------------------
# Emplacements et sélection des instruments (D4, D10, D11, D13)
# ---------------------------------------------------------------------------

def test_assign_bank_slot_loads_file_and_selects_on_track_channel():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 3)
    assert eng.of("load") == [("load", 0, SF)]
    assert ("select", 2, 0, 0, 40) in eng.calls
    assert eng.ccs(2, 7)  == [("cc", 2, 7,  volume_to_cc7(100))]
    assert eng.ccs(2, 10) == [("cc", 2, 10, pan_to_cc10(0))]


def test_sync_bank_files_loads_only_changed_files():
    router, eng, *_ = _make_router()
    router.sync_bank_files()
    router.sync_bank_files()
    assert eng.of("load") == [("load", 0, SF)]
    router._rack.set_bank_file(0, SF2)
    router.sync_bank_files()
    assert eng.of("load")[-1] == ("load", 0, SF2)


def test_sync_bank_files_unloads_removed_file():
    router, eng, *_ = _make_router()
    router.sync_bank_files()
    router._rack.set_bank_file(0, None)
    router.sync_bank_files()
    assert eng.of("unload") == [("unload", 0)]
    assert eng.loaded_path(0) is None


def test_refused_bank_file_unloads_and_warns():
    router, eng, _, statuses, _ = _make_router(FakeBankEngine(refuse={SF}))
    router.sync_bank_files()
    assert eng.loaded_path(0) is None
    assert ("unload", 0) in eng.calls
    assert any("Banque 1" in s and SF in s for s in statuses)


def test_select_sent_once_then_cached():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 3)
    router.sync_banks()
    assert len([c for c in eng.of("select") if c[1] == 2]) == 1


def test_play_start_forces_reselection():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 3)
    router.on_play_start()
    assert len([c for c in eng.of("select") if c[1] == 2]) == 2


def test_select_failure_warns_in_status():
    router, eng, _, statuses, _ = _make_router(FakeBankEngine(missing={(0, 0, 40)}))
    router.assign_slot(2, 3)
    assert any("Piste 3" in s and "0:40" in s for s in statuses)


def test_bank_number_follows_bank_select_mode():
    router, eng, *_ = _make_router()
    router._rack.set_bank_file(1, SF2)
    router.assign_slot(4, 5)                  # MSB 8, LSB 3
    assert ("select", 4, 1, 8, 1) in eng.calls
    router2, eng2, *_ = _make_router(FakeBankEngine(bank_select="mma"))
    router2._rack.set_bank_file(1, SF2)
    router2.assign_slot(4, 5)
    assert ("select", 4, 1, 8 * 128 + 3, 1) in eng2.calls


def test_drum_preset_selects_bank_128():
    router, eng, *_ = _make_router()
    router.assign_slot_by_user(6, 4)
    assert router.get_track_channel(6) == KIT_CH
    assert ("select", KIT_CH, 0, 128, 0) in eng.calls


def test_shared_channel_different_instruments_warns_last_wins():
    router, eng, _, statuses, _ = _make_router()
    router.assign_slot(2, 2)
    router.assign_slot(3, 3)
    router.set_track_channel(3, 2)            # piste 4 sur le canal de la piste 3
    assert any("Canal 3" in s and "piste 4 l'emporte" in s for s in statuses)
    assert [c for c in eng.of("select") if c[1] == 2][-1] == ("select", 2, 0, 0, 40)


def test_shared_channel_same_instrument_no_warning():
    router, eng, _, statuses, _ = _make_router()
    router.assign_slot(2, 3)
    router.assign_slot(3, 3)
    router.set_track_channel(3, 2)
    assert not any("l'emporte" in s for s in statuses)


def test_track_volume_and_pan_sent_as_cc7_cc10():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 3)
    router.set_track_volume(2, 50)
    router.set_track_pan(2, -40)
    assert eng.ccs(2, 7)[-1]  == ("cc", 2, 7, volume_to_cc7(50))
    assert eng.ccs(2, 10)[-1] == ("cc", 2, 10, pan_to_cc10(-40))


def test_volume_of_non_bank_track_not_sent():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 1)                  # synthé WAV
    router.set_track_volume(2, 50)
    assert eng.of("cc") == []


def test_master_pan_added_to_track_pan_and_bounded():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 3)
    router.set_track_pan(2, 70)
    router.set_master_pan(50)
    assert eng.ccs(2, 10)[-1] == ("cc", 2, 10, pan_to_cc10(100))
    router.set_master_pan(-30)
    assert eng.ccs(2, 10)[-1] == ("cc", 2, 10, pan_to_cc10(40))


def test_track_channel_change_resyncs_on_new_channel():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 3)
    router.set_track_channel(2, 11)
    assert ("select", 11, 0, 0, 40) in eng.calls
    assert eng.ccs(11, 7)


# ---------------------------------------------------------------------------
# Canal 10 (D9)
# ---------------------------------------------------------------------------

def test_channel_after_slot_drum_bank_goes_to_channel_10():
    router, *_ = _make_router()
    assert router.channel_after_slot(3, 4, 3) == KIT_CH


def test_channel_after_slot_melodic_bank_leaves_channel_10():
    router, *_ = _make_router()
    assert router.channel_after_slot(3, 3, KIT_CH) == Pattern.default_channel(3)
    assert router.channel_after_slot(3, 3, 7) == 7


def test_assign_by_user_drum_then_melodic_bank():
    router, *_ = _make_router()
    router.assign_slot_by_user(3, 4)
    assert router.get_track_channel(3) == KIT_CH
    router.assign_slot_by_user(3, 3)
    assert router.get_track_channel(3) == 3


# ---------------------------------------------------------------------------
# Rejeu : notes de grille, _tape, contrôles (D11, D12, D18)
# ---------------------------------------------------------------------------

def test_grid_note_melodic_uses_playback_scale():
    router, eng, snd, *_ = _make_router()
    router.assign_slot(2, 3)
    router.on_play(2, 4, 1.0, 0, 300)
    note = scale_midi_notes("major", 48, TrackRouter.KB_NUMPAD_NOTES)[4]
    assert eng.of("note_on") == [("note_on", 2, note, 127)]
    assert snd.played == []
    assert FakeTimer.created[-1].interval == pytest.approx(0.3)
    FakeTimer.created[-1].fire()
    assert eng.of("note_off") == [("note_off", 2, note)]


def test_grid_note_on_channel_10_is_36_plus_pad():
    router, eng, *_ = _make_router()
    router.assign_slot_by_user(5, 4)
    router.on_play(5, 2, 1.0, 0)
    assert eng.of("note_on") == [("note_on", KIT_CH, 38, 127)]


def test_grid_velocity_from_volume_factor_not_track_volume():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 3)
    router.set_track_volume(2, 10)            # au canal par CC7, pas dans la vélocité
    router.on_play(2, 0, 0.5, 0)
    assert eng.of("note_on")[0][3] == round(127 * 0.5)
    router.on_play(2, 0, 0.0, 0)
    assert eng.of("note_on")[1][3] == 1


def test_grid_default_duration_when_zero():
    router, *_ = _make_router()
    router.assign_slot(2, 3)
    router.on_play(2, 0, 1.0, 0, 0)
    assert FakeTimer.created[-1].interval == pytest.approx(0.5)


def test_grid_pad_out_of_scale_is_silent():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 3)
    router._kb_notes_play = [60, 62]
    router.on_play(2, 5, 1.0, 0)
    assert eng.of("note_on") == []


def test_mute_and_solo_silence_bank_track():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 3)
    router.assign_slot(3, 2)
    router.toggle_track_mute(2)
    router.on_play(2, 0, 1.0, 0)
    router.toggle_track_mute(2)
    router.toggle_track_solo(3)
    router.on_play(2, 0, 1.0, 0)
    router.on_kit_tape(2, 40, 100)
    router.on_patch_tape(2, 60, 100)
    assert eng.of("note_on") == []
    router.on_play(3, 0, 1.0, 0)
    assert len(eng.of("note_on")) == 1


def test_kit_and_patch_tape_notes_go_as_is():
    router, eng, snd, *_ = _make_router()
    router.assign_slot(2, 3)
    router.on_kit_tape(2, 42, 90)
    router.on_patch_tape(2, 67, 80, 250)
    assert eng.of("note_on") == [("note_on", 2, 42, 90), ("note_on", 2, 67, 80)]
    assert snd.played_notes == []
    assert FakeTimer.created[-1].interval == pytest.approx(0.25)


def test_bend_and_mod_tape_to_channel():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 3)
    router.on_bend_tape(2, -4096)
    router.on_mod_tape(2, 64)
    assert ("bend", 2, -4096) in eng.calls
    assert ("cc", 2, 1, 64) in eng.calls


def test_cc_tape_other_cc_to_channel():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 3)
    router.on_cc_tape(2, 74, 30)
    assert ("cc", 2, 74, 30) in eng.calls


def test_cc_tape_bank_select_invalidates_channel_cache():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 3)
    router.on_cc_tape(2, 0, 8)
    router.on_cc_tape(2, 32, 1)
    assert ("cc", 2, 0, 8) in eng.calls and ("cc", 2, 32, 1) in eng.calls
    assert router._chan_sel[2] is None
    router.sync_banks()                       # instrument du slot renvoyé
    assert len([c for c in eng.of("select") if c[1] == 2]) == 2


def test_cc_tape_volume_and_pan_go_through_track_mix():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 3)
    router.on_cc_tape(2, 7, 127)
    router.on_cc_tape(2, 10, 0)
    assert router.get_track_volume(2) == 100
    assert router.get_track_pan(2) == -100
    assert eng.ccs(2, 10)[-1] == ("cc", 2, 10, pan_to_cc10(-100))


def test_program_change_on_bank_track_goes_to_engine():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 3)
    assert router.program_change(2, 56) is True
    assert ("pgm", 2, 56) in eng.calls
    assert router.slot_for_track(2) == 3      # pas de pont program % 16
    assert router._chan_sel[2] is None


def test_program_change_tape_on_bank_track():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 3)
    router.on_program_change_tape(2, 19)
    assert ("pgm", 2, 19) in eng.calls
    assert router.slot_for_track(2) == 3


def test_program_change_on_other_track_keeps_bridge():
    router, eng, *_ = _make_router()
    assert router.program_change(1, 17) is False
    assert router.slot_for_track(1) == 1      # 17 % 16
    assert eng.of("pgm") == []


def test_global_controls_reach_engine():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 3)
    eng.calls.clear()
    router.stop_all_sounds()
    router.reset_all_controls()
    router.set_sustain(True)
    assert ("all_notes_off",) in eng.calls
    assert ("all_sounds_off",) in eng.calls
    assert ("reset_controllers",) in eng.calls
    assert eng.ccs(2, 7) and eng.ccs(2, 10)   # mixage de piste rétabli
    assert len(eng.ccs(num=64)) == 16


def test_without_engine_bank_tracks_are_silent():
    router, eng, snd, *_ = _make_router(with_engine=False)
    router.assign_slot(2, 3)
    router.on_play(2, 0, 1.0, 0)
    router.on_kit_tape(2, 40, 100)
    router.on_bend_tape(2, 100)
    router.set_track_volume(2, 30)
    router.set_master_pan(20)
    router.panic()
    assert router.program_change(2, 5) is True
    assert snd.played == [] and snd.played_notes == []
    assert not router.bank_slot_ready(3)


# ---------------------------------------------------------------------------
# Jeu direct : BankPreview, input_note
# ---------------------------------------------------------------------------

def test_load_slot_preview_on_bank_uses_bank_preview():
    router, eng, *_ = _make_router()
    router.load_slot_preview(3)
    assert isinstance(router.synth, BankPreview)
    assert router.synth_ready()
    assert eng.loaded_path(0) == SF


def test_bank_preview_not_ready_when_slot_file_missing():
    router, *_ = _make_router()
    router.load_slot_preview(5)               # emplacement 2 vide
    assert not router.synth_ready()


def test_bank_preview_plays_on_current_track_channel():
    router, eng, _, _, holder = _make_router(cur_track=4)
    router.load_slot_preview(3)
    router.set_track_channel(4, 12)
    router.synth.play(60, 0.5)
    holder["track"] = 6
    router.synth.stop(60)
    assert ("note_on", 12, 60, round(127 * 0.5)) in eng.calls
    assert ("note_off", 6, 60) in eng.calls


def test_bank_preview_held_note_without_timer():
    router, eng, *_ = _make_router()
    router.load_slot_preview(3)
    router.synth.play(60, 1.0, 0, 0)
    assert FakeTimer.created == []


def test_bank_preview_bend_and_mod():
    router, eng, *_ = _make_router(cur_track=3)
    router.load_slot_preview(3)
    router.synth.pitch_bend = 2048
    router.synth.apply_pitch_bend()
    router.synth.set_mod_wheel(90)
    assert ("bend", 3, 2048) in eng.calls
    assert ("cc", 3, 1, 90) in eng.calls


def test_preview_back_to_synth_slot_leaves_bank_preview():
    router, *_ = _make_router()
    router.load_slot_preview(3)
    router.load_slot_preview(1)
    router.wait_loaded()
    assert isinstance(router.synth, FakeSynthEngine)


def test_input_note_drums_on_channel_10():
    router, _, _, _, holder = _make_router(cur_track=7)
    router.assign_slot_by_user(7, 4)
    router.load_slot_preview(4)
    assert router.input_note(3) == 39


def test_input_note_melodic_bank_uses_input_scale():
    router, *_ = _make_router(cur_track=2)
    router.load_slot_preview(3)
    assert router.input_note(3) == router.kb_notes_input[3]


# ---------------------------------------------------------------------------
# Export : CC0 / CC32 avant le Program Change (D18), notes D12
# ---------------------------------------------------------------------------

SYNTH_NOTES = [60 + i for i in range(16)]


def _export(p, *, channels, banks, programs, is_synth=None, gm_map=None):
    n = p._num_tracks
    return build_pattern_midi(
        p, name="P", bpm=120, track_channels=channels,
        track_is_synth=is_synth or [False] * n, track_names=[""] * n,
        kit_pad_notes=[36 + i for i in range(16)], synth_grid_notes=SYNTH_NOTES,
        voice_durations=[500] * 16, track_programs=programs,
        kit_gm_map=gm_map, track_banks=banks)


def _pattern_with(track, *events):
    p = Pattern()
    p.new_pattern(1, 16)
    for etype, time_val, payload in events:
        p._tape[track].append(TapeEvent(etype, dur=0, channel=0, payload=payload, time=time_val))
    return p


def _tick0(track):
    out, now = [], 0
    for m in track:
        now += m.time
        if now == 0 and m.type in ("control_change", "program_change"):
            out.append(m)
    return out


def _note_ons(track):
    return [(m.channel, m.note) for m in track if m.type == "note_on"]


def test_export_bank_writes_cc0_cc32_before_program():
    p = _pattern_with(2, (ETYPE_GRID, 0, {"pad": 0, "vel": 100}))
    banks = [None] * 16
    banks[2] = (8, 3, False)
    programs = [None] * 16
    programs[2] = 40
    mid = _export(p, channels=list(range(16)), banks=banks, programs=programs)
    msgs = [(m.type, getattr(m, "control", None), getattr(m, "value", getattr(m, "program", None)))
            for m in _tick0(mid.tracks[1])]
    assert msgs[:3] == [("control_change", 0, 8), ("control_change", 32, 3),
                        ("program_change", None, 40)]
    assert all(m.channel == 2 for m in _tick0(mid.tracks[1]))


def test_export_drum_bank_no_bank_select_and_36_plus_pad():
    p = _pattern_with(5, (ETYPE_GRID, 0, {"pad": 2, "vel": 100}))
    banks = [None] * 16
    banks[5] = (0, 0, True)
    channels = list(range(16))
    channels[5] = KIT_CH
    mid = _export(p, channels=channels, banks=banks, programs=[0] * 16)
    tick0 = _tick0(mid.tracks[1])
    assert not [m for m in tick0 if m.type == "control_change" and m.control in (0, 32)]
    assert _note_ons(mid.tracks[1]) == [(KIT_CH, 38)]


def test_export_melodic_bank_grid_uses_scale_notes():
    p = _pattern_with(2, (ETYPE_GRID, 0, {"pad": 4, "vel": 100}))
    banks = [None] * 16
    banks[2] = (0, 0, False)
    mid = _export(p, channels=list(range(16)), banks=banks, programs=None)
    assert _note_ons(mid.tracks[1]) == [(2, SYNTH_NOTES[4])]


def test_export_bank_kit_notes_not_mapped_and_patch_kept():
    p = _pattern_with(2, (ETYPE_KIT, 0, {"note": 50, "vel": 100}),
                         (ETYPE_PATCH, 4, {"note": 72, "vel": 100}))
    banks = [None] * 16
    banks[2] = (0, 0, False)
    mid = _export(p, channels=list(range(16)), banks=banks, programs=None,
                  gm_map={50: 38})
    assert sorted(_note_ons(mid.tracks[1])) == [(2, 50), (2, 72)]


def test_export_without_banks_unchanged_for_kit_track():
    p = _pattern_with(2, (ETYPE_KIT, 0, {"note": 50, "vel": 100}),
                         (ETYPE_PATCH, 4, {"note": 72, "vel": 100}))
    mid = _export(p, channels=list(range(16)), banks=None, programs=None,
                  gm_map={50: 38})
    assert _note_ons(mid.tracks[1]) == [(2, 38)]       # KIT mappé, PATCH muette
    assert not [m for m in _tick0(mid.tracks[1])
                if m.type == "control_change" and m.control in (0, 32)]
