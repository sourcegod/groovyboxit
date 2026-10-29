#python3
"""
    File: tests/test_bank_slot.py
    Tests du slot Banque, modèle « orchestre » (Phase 7 étapes 17e1, 17g1 ;
    docs/DESIGN.md § 17e3) : Rack et .gvp (slot = emplacement, 4
    emplacements), instrument par canal (O1) tiré des CC0 / CC32 / Program
    Change (O2), canal porté par le Program Change (O3), poursuite (O4),
    choix B (le canal impose son instrument), canal 10 = batterie (R3),
    routage de tous les événements vers un moteur de banque factice, jeu
    direct (BankPreview), poursuite déclenchée par le player, export (O8).
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
from pattern import (Pattern, TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH,
                     ETYPE_CC, ETYPE_PGM, ETYPE_BEND)
from project_manager import ProjectManager
from engines.bank_engine import BankEngine
from midi.midi_export import build_pattern_midi, volume_to_cc7, pan_to_cc10
from synth_engine import scale_midi_notes
from player.drum_player import DrumPlayer

NUM_TRACKS = TrackRouter.NUM_TRACKS
KIT_CH     = Pattern.KIT_CHANNEL


# ---------------------------------------------------------------------------
# Moteur de banque factice
# ---------------------------------------------------------------------------

PRESETS = [(0, 0, "Piano"), (0, 33, "Fingered Bass"), (0, 48, "Strings"),
           (8, 1, "Piano 2"), (128, 0, "Standard"), (128, 8, "Room")]


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
        return list(PRESETS) if self.paths[slot] else []

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

    def selects(self, channel):
        return [c for c in self.of("select") if c[1] == channel]

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

SF  = "/fake/FluidR3_GM.sf2"
SF2 = "/fake/GeneralUser_GS.sf2"

BANK_A = 2      # slot Banque, emplacement 1 (SF)
BANK_B = 3      # slot Banque, emplacement 2 (SF2)


def _make_rack():
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT,   "Default Kit", {})
    rack.set_slot(1, InstrumentType.SYNTH, "Piano WAV",   {"patch": "piano_1"})
    rack.set_slot(BANK_A, InstrumentType.BANK, "FluidR3_GM",     {"bank_slot": 0})
    rack.set_slot(BANK_B, InstrumentType.BANK, "GeneralUser_GS", {"bank_slot": 1})
    rack.set_bank_file(0, SF)
    rack.set_bank_file(1, SF2)
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


def _ev(etype, time_val, payload, channel=0, dur=0):
    return TapeEvent(etype, dur=dur, channel=channel, payload=payload, time=time_val)


def _pgm(time_val, program, channel):
    return _ev(ETYPE_PGM, time_val, {"program": program}, channel)


def _cc(time_val, num, value, channel):
    return _ev(ETYPE_CC, time_val, {"cc_num": num, "value": value}, channel)


def _tape(**tracks):
    """Tape de 16 pistes ; tracks = {"t3": [événements], ...}."""
    tape = [[] for _ in range(NUM_TRACKS)]
    for key, events in tracks.items():
        tape[int(key[1:])] = list(events)
    return tape


# ---------------------------------------------------------------------------
# Rack : type, emplacement, .gvp (R1)
# ---------------------------------------------------------------------------

def test_bank_type_is_listed():
    assert InstrumentType.BANK == "bank"
    assert InstrumentType.BANK in InstrumentType.ALL


def test_plays_notes_synth_and_bank_only():
    rack = _make_rack()
    assert rack.get_slot(1).plays_notes
    assert rack.get_slot(BANK_A).plays_notes
    assert not rack.get_slot(0).plays_notes
    assert not rack.get_slot(15).plays_notes          # slot vide


def test_bank_slot_bounded_and_defaults():
    s = InstrumentSlot(0)
    s.type, s.config = InstrumentType.BANK, {"bank_slot": 9}
    assert s.bank_slot() == Rack.NUM_BANK_SLOTS - 1
    s.config = {"bank_slot": True}
    assert s.bank_slot() == 0
    s.config = {}
    assert s.bank_slot() == 0


def test_bank_slot_has_no_program_of_its_own():
    """Ancienne config de 17d1 (programme, MSB, drums) : ignorée (R1)."""
    s = InstrumentSlot(0)
    s.type = InstrumentType.BANK
    s.config = {"bank_slot": 0, "program": 40, "bank_msb": 8, "drums": True, "gm_gain_db": -12}
    assert s.gm_program() is None
    assert s.gm_gain_db() == 0
    for name in ("bank_msb", "bank_lsb", "bank_program", "bank_drums"):
        assert not hasattr(s, name)


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
    assert other.bank_files == [SF, SF2, None, SF2]
    s = other.get_slot(BANK_B)
    assert s.type == InstrumentType.BANK and s.bank_slot() == 1


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
    assert other.get_slot(BANK_A).to_dict() == rack.get_slot(BANK_A).to_dict()


def test_header_events_survive_pattern_roundtrip():
    """L'entête (O2) est fait d'événements ordinaires de _tape."""
    p = Pattern()
    p.new_pattern(1, 16)
    p._tape[3] = [_cc(0, 0, 8, 3), _cc(0, 32, 1, 3), _pgm(0, 33, 3)]
    q = Pattern()
    q.from_dict(p.to_dict())
    got = [(e.etype, e.channel, e.payload) for e in q._tape[3]]
    assert got == [(ETYPE_CC, 3, {"cc_num": 0, "value": 8}),
                   (ETYPE_CC, 3, {"cc_num": 32, "value": 1}),
                   (ETYPE_PGM, 3, {"program": 33})]


# ---------------------------------------------------------------------------
# Emplacements
# ---------------------------------------------------------------------------

def test_assign_bank_slot_loads_files_and_selects_default_instrument():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    assert eng.of("load") == [("load", 0, SF), ("load", 1, SF2)]
    assert eng.selects(2) == [("select", 2, 0, 0, 0)]       # GM par défaut (O1)
    assert eng.ccs(2, 7)  == [("cc", 2, 7,  volume_to_cc7(100))]
    assert eng.ccs(2, 10) == [("cc", 2, 10, pan_to_cc10(0))]


def test_sync_bank_files_loads_only_changed_files():
    router, eng, *_ = _make_router()
    router.sync_bank_files()
    router.sync_bank_files()
    assert len(eng.of("load")) == 2
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


def test_select_failure_warns_in_status():
    router, eng, _, statuses, _ = _make_router(FakeBankEngine(missing={(0, 0, 0)}))
    router.assign_slot(2, BANK_A)
    assert any("Piste 3" in s and "0:0" in s for s in statuses)


def test_same_channel_different_bank_files_warns_last_wins():
    router, eng, _, statuses, _ = _make_router()
    router.assign_slot(2, BANK_A)
    router.assign_slot(5, BANK_B)
    router.set_track_channel(5, 2)
    assert any("Canal 3" in s and "piste 6 l'emporte" in s for s in statuses)
    assert eng.selects(2)[-1][2] == 1                       # emplacement 2


# ---------------------------------------------------------------------------
# Instrument par canal (O1), Program Change et Bank Select (O3)
# ---------------------------------------------------------------------------

def test_channel_instrument_default_is_gm_reset():
    router, *_ = _make_router()
    assert all(router.channel_instrument(c) == (0, 0, 0) for c in range(16))


def test_program_change_sets_channel_instrument():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    assert router.program_change(2, 48) is True
    assert router.channel_instrument(2) == (48, 0, 0)
    assert eng.selects(2)[-1] == ("select", 2, 0, 0, 48)
    assert router.slot_for_track(2) == BANK_A                # pas de pont program % 16


def test_program_change_always_resent():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.program_change(2, 48)
    router.program_change(2, 48)
    assert len(eng.selects(2)) == 3


def test_program_change_with_channel_moves_track():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.program_change(2, 11, channel=4)
    assert router.track_channel_now(2) == 4
    assert router.get_track_channel(2) == 2                  # canal de base inchangé
    assert eng.selects(4)[-1] == ("select", 4, 0, 0, 11)
    assert eng.ccs(4, 7)                                     # mixage suivi sur le canal 4
    router.on_play(2, 0, 1.0, 0)
    assert eng.of("note_on")[-1][1] == 4


def test_program_change_tape_carries_channel():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.on_program_change_tape(2, 33, 6)
    assert router.track_channel_now(2) == 6
    assert router.channel_instrument(6)[0] == 33


def test_program_change_on_other_track_keeps_bridge():
    router, eng, *_ = _make_router()
    assert router.program_change(1, 17) is False
    assert router.slot_for_track(1) == 1                     # 17 % 16
    assert eng.of("select") == []


def test_bank_select_applies_at_next_program_gs():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.bank_select(2, 0, 8)
    router.bank_select(2, 32, 3)
    assert ("cc", 2, 0, 8) in eng.calls and ("cc", 2, 32, 3) in eng.calls
    assert len(eng.selects(2)) == 1                          # pas encore de programme
    router.program_change(2, 1)
    assert eng.selects(2)[-1] == ("select", 2, 0, 8, 1)      # GS : MSB seul


def test_bank_select_mma_mode():
    router, eng, *_ = _make_router(FakeBankEngine(bank_select="mma"))
    router.assign_slot(2, BANK_A)
    router.bank_select(2, 0, 8)
    router.bank_select(2, 32, 3)
    router.program_change(2, 1)
    assert eng.selects(2)[-1] == ("select", 2, 0, 8 * 128 + 3, 1)


def test_bank_select_on_its_own_channel():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.bank_select(2, 0, 8, channel=5)
    assert router.channel_instrument(5) == (0, 8, 0)
    assert router.channel_instrument(2) == (0, 0, 0)


def test_cc_tape_bank_select_uses_event_channel():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.on_cc_tape(2, 0, 8, 5)
    router.on_cc_tape(2, 32, 2)                              # sans canal : canal courant
    assert router.channel_instrument(5) == (0, 8, 0)
    assert router.channel_instrument(2) == (0, 0, 2)


def test_channel_10_plays_drum_bank_whatever_msb():
    router, eng, *_ = _make_router()
    router.assign_slot(5, BANK_A)
    router.set_track_channel(5, KIT_CH)
    router.bank_select(5, 0, 8)
    router.program_change(5, 8)
    assert eng.selects(KIT_CH)[-1] == ("select", KIT_CH, 0, 128, 8)
    assert router.bank_preset_name(5) == "Room"


# ---------------------------------------------------------------------------
# Choix B : le canal impose son instrument (O5)
# ---------------------------------------------------------------------------

def test_moving_track_to_channel_takes_its_instrument():
    router, eng, *_ = _make_router()
    router.assign_slot(0, BANK_A)
    router.assign_slot(3, BANK_A)
    router.program_change(0, 0)                    # piano au canal 1
    router.set_track_channel(3, 3)
    router.program_change(3, 33)                   # basse au canal 4
    assert router.bank_preset_name(3) == "Fingered Bass"
    router.set_track_channel(3, 0)                 # la basse rejoint le canal 1
    assert router.track_channel_now(3) == 0
    assert router.bank_preset_name(3) == "Piano"
    assert router.bank_preset_name(0) == "Piano"   # le piano n'a pas changé
    router.on_play(3, 0, 1.0, 0)
    assert eng.of("note_on")[-1][1] == 0


def test_last_track_number_does_not_win_anymore():
    """Le défaut constaté à l'essai de 17d1 / 17f1 (la piste de plus grand
    numéro imposait son instrument) a disparu."""
    router, eng, *_ = _make_router()
    router.assign_slot(0, BANK_A)
    router.assign_slot(3, BANK_A)
    router.program_change(0, 48)
    router.set_track_channel(3, 3)
    router.program_change(3, 33)
    router.set_track_channel(0, 3)                 # le piano (piste 1) va au canal 4
    assert router.bank_preset_name(0) == "Fingered Bass"
    assert router.bank_preset_name(3) == "Fingered Bass"


def test_set_track_channel_also_sets_current_channel():
    router, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.program_change(2, 1, channel=7)
    router.set_track_channel(2, 11)
    assert router.track_channel_now(2) == router.get_track_channel(2) == 11


# ---------------------------------------------------------------------------
# Libellé : nom du preset (R7)
# ---------------------------------------------------------------------------

def test_preset_name_absent_and_none_cases():
    router, *_ = _make_router()
    assert router.bank_preset_name(1) is None                # slot synthé
    router.assign_slot(2, BANK_A)
    router.program_change(2, 99)
    assert router.bank_preset_name(2) == "(preset absent)"
    router._rack.set_bank_file(0, None)
    router.sync_bank_files()
    assert router.bank_preset_name(2) is None                # emplacement vide


def test_preset_names_reread_after_file_change():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    assert router.bank_preset_name(2) == "Piano"
    PRESETS[0] = (0, 0, "Autre piano")
    try:
        assert router.bank_preset_name(2) == "Piano"         # en cache
        router._rack.set_bank_file(0, SF2)
        router.sync_bank_files()
        assert router.bank_preset_name(2) == "Autre piano"
    finally:
        PRESETS[0] = (0, 0, "Piano")


# ---------------------------------------------------------------------------
# Poursuite (O4)
# ---------------------------------------------------------------------------

def test_chase_applies_headers_and_moves_tracks():
    router, eng, *_ = _make_router()
    for t in (0, 1, 3):
        router.assign_slot(t, BANK_A)
    router._track_channels[1] = KIT_CH
    router.chase(_tape(t0=[_cc(0, 0, 0, 0), _cc(0, 32, 0, 0), _pgm(0, 0, 0)],
                       t1=[_pgm(0, 8, KIT_CH)],
                       t3=[_cc(0, 0, 8, 3), _pgm(0, 1, 3)]), 0.0)
    assert router.channel_instrument(0) == (0, 0, 0)
    assert router.channel_instrument(KIT_CH)[0] == 8
    assert router.channel_instrument(3) == (1, 8, 0)
    assert eng.selects(3)[-1] == ("select", 3, 0, 8, 1)
    assert router.bank_preset_name(3) == "Piano 2"
    assert router.bank_preset_name(1) == "Room"


def test_chase_ignores_events_after_position():
    router, *_ = _make_router()
    router.assign_slot(0, BANK_A)
    tape = _tape(t0=[_pgm(0, 0, 0), _pgm(16, 11, 4)])
    router.chase(tape, 8.0)
    assert router.track_channel_now(0) == 0
    router.chase(tape, 16.0)                       # position comprise
    assert router.track_channel_now(0) == 4
    assert router.channel_instrument(4)[0] == 11


def test_chase_resets_state_and_live_changes():
    """Un Program Change en direct (Q2) ne survit pas à la relance."""
    router, *_ = _make_router()
    router.assign_slot(0, BANK_A)
    tape = _tape(t0=[_pgm(0, 0, 0)])
    router.chase(tape, 0.0)
    router.program_change(0, 40)                   # contrôleur
    router.bank_select(0, 0, 8, channel=6)
    assert router.channel_instrument(0)[0] == 40
    router.chase(tape, 0.0)
    assert router.channel_instrument(0) == (0, 0, 0)
    assert router.channel_instrument(6) == (0, 0, 0)


def test_chase_restores_base_channel_without_program_change():
    router, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.program_change(2, 5, channel=9)
    router.chase(_tape(), 0.0)
    assert router.track_channel_now(2) == 2


def test_chase_orders_by_time_then_track():
    router, *_ = _make_router()
    router.assign_slot(0, BANK_A)
    router.assign_slot(1, BANK_A)
    router._track_channels[1] = 0
    router.chase(_tape(t0=[_pgm(4, 10, 0)], t1=[_pgm(0, 20, 0), _pgm(4, 30, 0)]), 8.0)
    assert router.channel_instrument(0)[0] == 30      # temps égal : piste 2 après piste 1
    router.chase(_tape(t0=[_pgm(6, 10, 0)], t1=[_pgm(4, 30, 0)]), 8.0)
    assert router.channel_instrument(0)[0] == 10      # le plus tardif l'emporte


def test_chase_ignores_non_bank_tracks():
    router, eng, *_ = _make_router()
    router.assign_slot(1, 1)                       # synthé WAV
    router.chase(_tape(t1=[_pgm(0, 3, 5)]), 0.0)
    assert router.slot_for_track(1) == 1           # pas de pont pendant la poursuite
    assert router.channel_instrument(5) == (0, 0, 0)


def test_chase_forces_reselection():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    n = len(eng.selects(2))
    router.chase(_tape(), 0.0)
    assert len(eng.selects(2)) == n + 1


# ---------------------------------------------------------------------------
# Canal 10 (R3) et règle du canal à l'assignation
# ---------------------------------------------------------------------------

def test_channel_after_slot_bank_keeps_channel_10():
    router, *_ = _make_router()
    assert router.channel_after_slot(3, BANK_A, KIT_CH) == KIT_CH
    assert router.channel_after_slot(3, BANK_A, 7) == 7


def test_channel_after_slot_kit_and_synth_unchanged_rules():
    router, *_ = _make_router()
    assert router.channel_after_slot(3, 0, 3) == KIT_CH
    assert router.channel_after_slot(3, 1, KIT_CH) == 3


def test_assign_by_user_sets_current_channel():
    router, eng, *_ = _make_router()
    router.program_change(6, 0)                    # pont : slot 0 (kit)
    router.assign_slot_by_user(6, 0)
    assert router.get_track_channel(6) == KIT_CH
    router.assign_slot_by_user(6, BANK_A)          # banque : garde le canal 10
    assert router.track_channel_now(6) == KIT_CH
    assert eng.selects(KIT_CH)[-1] == ("select", KIT_CH, 0, 128, 0)


# ---------------------------------------------------------------------------
# Mixage (D11, D13)
# ---------------------------------------------------------------------------

def test_track_volume_and_pan_sent_as_cc7_cc10():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.set_track_volume(2, 50)
    router.set_track_pan(2, -40)
    assert eng.ccs(2, 7)[-1]  == ("cc", 2, 7, volume_to_cc7(50))
    assert eng.ccs(2, 10)[-1] == ("cc", 2, 10, pan_to_cc10(-40))


def test_volume_of_non_bank_track_not_sent():
    router, eng, *_ = _make_router()
    router.assign_slot(2, 1)                  # synthé WAV
    router.set_track_volume(2, 50)
    assert eng.of("cc") == []


def test_mix_follows_current_channel():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.program_change(2, 0, channel=8)
    router.set_track_volume(2, 30)
    assert eng.ccs(8, 7)[-1] == ("cc", 8, 7, volume_to_cc7(30))


def test_master_pan_added_to_track_pan_and_bounded():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.set_track_pan(2, 70)
    router.set_master_pan(50)
    assert eng.ccs(2, 10)[-1] == ("cc", 2, 10, pan_to_cc10(100))
    router.set_master_pan(-30)
    assert eng.ccs(2, 10)[-1] == ("cc", 2, 10, pan_to_cc10(40))


# ---------------------------------------------------------------------------
# Rejeu : notes de grille, _tape, contrôles (D11, D12)
# ---------------------------------------------------------------------------

def test_grid_note_melodic_uses_playback_scale():
    router, eng, snd, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.on_play(2, 4, 1.0, 0, 300)
    note = scale_midi_notes("major", 48, TrackRouter.KB_NUMPAD_NOTES)[4]
    assert eng.of("note_on") == [("note_on", 2, note, 127)]
    assert snd.played == []
    assert FakeTimer.created[-1].interval == pytest.approx(0.3)
    FakeTimer.created[-1].fire()
    assert eng.of("note_off") == [("note_off", 2, note)]


def test_grid_note_on_current_channel_10_is_36_plus_pad():
    router, eng, *_ = _make_router()
    router.assign_slot(5, BANK_A)
    router.program_change(5, 0, channel=KIT_CH)    # la piste passe à la batterie
    router.on_play(5, 2, 1.0, 0)
    assert eng.of("note_on") == [("note_on", KIT_CH, 38, 127)]


def test_grid_velocity_from_volume_factor_not_track_volume():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.set_track_volume(2, 10)            # au canal par CC7, pas dans la vélocité
    router.on_play(2, 0, 0.5, 0)
    assert eng.of("note_on")[0][3] == round(127 * 0.5)
    router.on_play(2, 0, 0.0, 0)
    assert eng.of("note_on")[1][3] == 1


def test_grid_default_duration_when_zero():
    router, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.on_play(2, 0, 1.0, 0, 0)
    assert FakeTimer.created[-1].interval == pytest.approx(0.5)


def test_grid_pad_out_of_scale_is_silent():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router._kb_notes_play = [60, 62]
    router.on_play(2, 5, 1.0, 0)
    assert eng.of("note_on") == []


def test_mute_and_solo_silence_bank_track():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.assign_slot(3, BANK_A)
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


def test_kit_and_patch_tape_notes_on_current_channel():
    router, eng, snd, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.program_change(2, 0, channel=7)
    router.on_kit_tape(2, 42, 90)
    router.on_patch_tape(2, 67, 80, 250)
    assert eng.of("note_on") == [("note_on", 7, 42, 90), ("note_on", 7, 67, 80)]
    assert snd.played_notes == []
    assert FakeTimer.created[-1].interval == pytest.approx(0.25)


def test_bend_mod_and_other_cc_to_current_channel():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.program_change(2, 0, channel=7)
    router.on_bend_tape(2, -4096)
    router.on_mod_tape(2, 64)
    router.on_cc_tape(2, 74, 30, 0)               # canal de l'événement ignoré (hors Bank Select)
    assert ("bend", 7, -4096) in eng.calls
    assert ("cc", 7, 1, 64) in eng.calls
    assert ("cc", 7, 74, 30) in eng.calls


def test_cc_tape_volume_and_pan_go_through_track_mix():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.on_cc_tape(2, 7, 127)
    router.on_cc_tape(2, 10, 0)
    assert router.get_track_volume(2) == 100
    assert router.get_track_pan(2) == -100
    assert eng.ccs(2, 10)[-1] == ("cc", 2, 10, pan_to_cc10(-100))


def test_global_controls_reach_engine():
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
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
    router.assign_slot(2, BANK_A)
    router.on_play(2, 0, 1.0, 0)
    router.on_kit_tape(2, 40, 100)
    router.on_bend_tape(2, 100)
    router.on_cc_tape(2, 0, 8)
    router.set_track_volume(2, 30)
    router.set_master_pan(20)
    router.chase(_tape(t2=[_pgm(0, 5, 2)]), 0.0)
    router.panic()
    assert router.program_change(2, 5) is True
    assert router.bank_preset_name(2) is None
    assert snd.played == [] and snd.played_notes == []
    assert not router.bank_slot_ready(BANK_A)


# ---------------------------------------------------------------------------
# Jeu direct : BankPreview, input_note
# ---------------------------------------------------------------------------

def test_load_slot_preview_on_bank_uses_bank_preview():
    router, eng, *_ = _make_router()
    router.load_slot_preview(BANK_A)
    assert isinstance(router.synth, BankPreview)
    assert router.synth_ready()
    assert eng.loaded_path(0) == SF


def test_bank_preview_not_ready_when_slot_file_missing():
    router, *_ = _make_router()
    router._rack.set_bank_file(1, None)
    router.load_slot_preview(BANK_B)
    assert not router.synth_ready()


def test_bank_preview_plays_on_current_track_current_channel():
    router, eng, _, _, holder = _make_router(cur_track=4)
    router.assign_slot(4, BANK_A)
    router.load_slot_preview(BANK_A)
    router.program_change(4, 0, channel=12)
    router.synth.play(60, 0.5)
    holder["track"] = 6
    router.synth.stop(60)
    assert ("note_on", 12, 60, round(127 * 0.5)) in eng.calls
    assert ("note_off", 6, 60) in eng.calls


def test_bank_preview_held_note_without_timer():
    router, eng, *_ = _make_router()
    router.load_slot_preview(BANK_A)
    router.synth.play(60, 1.0, 0, 0)
    assert FakeTimer.created == []


def test_bank_preview_bend_and_mod():
    router, eng, *_ = _make_router(cur_track=3)
    router.load_slot_preview(BANK_A)
    router.synth.pitch_bend = 2048
    router.synth.apply_pitch_bend()
    router.synth.set_mod_wheel(90)
    assert ("bend", 3, 2048) in eng.calls
    assert ("cc", 3, 1, 90) in eng.calls


def test_preview_back_to_synth_slot_leaves_bank_preview():
    router, *_ = _make_router()
    router.load_slot_preview(BANK_A)
    router.load_slot_preview(1)
    router.wait_loaded()
    assert isinstance(router.synth, FakeSynthEngine)


def test_input_note_drums_on_current_channel_10():
    router, _, _, _, holder = _make_router(cur_track=7)
    router.assign_slot(7, BANK_A)
    router.load_slot_preview(BANK_A)
    assert router.input_note(3) == router.kb_notes_input[3]
    router.program_change(7, 0, channel=KIT_CH)
    assert router.input_note(3) == 39


# ---------------------------------------------------------------------------
# Player : poursuite au démarrage et aux sauts (O4)
# ---------------------------------------------------------------------------

class _SilentSoundManager:
    def stop_all(self):           pass
    def play_sound(self, *a):     pass
    def play_note(self, *a):      pass
    def play_metronome(self, *a): pass


def _player_with_chase(monkeypatch):
    pl = DrumPlayer(_SilentSoundManager())
    monkeypatch.setattr(pl, "start_thread", lambda: None)
    monkeypatch.setattr(pl, "stop_thread", lambda: None)
    got = []
    pl._on_play_start_cb = lambda tape, pos: got.append((tape, pos))
    pl._pattern._tape[2].append(_pgm(0, 33, 2))
    return pl, got


def test_play_pattern_chases_from_resume_position(monkeypatch):
    pl, got = _player_with_chase(monkeypatch)
    pl._resume_offset = 12.0
    pl.play_pattern()
    tape, pos = got[-1]
    assert pos == 12.0
    assert [e.payload for e in tape[2]] == [{"program": 33}]
    assert tape[2] is not pl._pattern._tape[2]            # instantané


def test_play_pattern_chases_from_start_by_default(monkeypatch):
    pl, got = _player_with_chase(monkeypatch)
    pl.play_pattern()
    assert got[-1][1] == 0.0


def test_goto_while_playing_chases(monkeypatch):
    pl, got = _player_with_chase(monkeypatch)
    pl.play_pattern()
    pl._go_to_offset(20.0)
    assert got[-1][1] == 20.0
    pl.goto_start()
    assert got[-1][1] == 0.0


def test_goto_while_stopped_does_not_chase(monkeypatch):
    pl, got = _player_with_chase(monkeypatch)
    pl._go_to_offset(20.0)
    assert got == []


# ---------------------------------------------------------------------------
# Export : Bank Select avant le programme, canal qui suit la piste (O8)
# ---------------------------------------------------------------------------

SYNTH_NOTES = [60 + i for i in range(16)]


def _export(p, *, channels=None, is_bank=None, programs=None, gm_map=None):
    n = p._num_tracks
    return build_pattern_midi(
        p, name="P", bpm=120, track_channels=channels or list(range(16)),
        track_is_synth=[False] * n, track_names=[""] * n,
        kit_pad_notes=[36 + i for i in range(16)], synth_grid_notes=SYNTH_NOTES,
        voice_durations=[500] * 16, track_programs=programs,
        kit_gm_map=gm_map, track_is_bank=is_bank)


def _pattern_with(track, *events):
    p = Pattern()
    p.new_pattern(1, 16)
    p._tape[track] = list(events)
    return p


def _grid(time_val, pad):
    return _ev(ETYPE_GRID, time_val, {"pad": pad, "vel": 100})


def _abs(track):
    out, now = [], 0
    for m in track:
        now += m.time
        out.append((now, m))
    return out


def _msgs(track, types=("control_change", "program_change", "note_on")):
    out = []
    for at, m in _abs(track):
        if m.type in types and not (m.type == "control_change" and m.control in (91, 93)):
            value = m.control if m.type == "control_change" else \
                m.program if m.type == "program_change" else m.note
            out.append((at, m.type, m.channel, value))
    return out


def _bank_tracks(*tracks):
    return [t in tracks for t in range(16)]


def test_export_bank_select_before_program_even_if_tape_order_differs():
    p = _pattern_with(2, _pgm(0, 1, 2), _cc(0, 32, 3, 2), _cc(0, 0, 8, 2), _grid(0, 0))
    msgs = _msgs(_export(p, is_bank=_bank_tracks(2)).tracks[1],
                 ("control_change", "program_change"))
    assert msgs[:3] == [(0, "control_change", 2, 32), (0, "control_change", 2, 0),
                        (0, "program_change", 2, 1)]


def test_export_bank_select_before_program_on_any_track():
    p = _pattern_with(4, _pgm(0, 1, 4), _cc(0, 0, 8, 4), _grid(0, 0))
    msgs = _msgs(_export(p).tracks[1], ("control_change", "program_change"))
    assert [m[1] for m in msgs[:2]] == ["control_change", "program_change"]


def test_export_channel_follows_program_change():
    p = _pattern_with(0, _pgm(0, 0, 0), _grid(0, 7), _cc(8, 0, 0, 4), _pgm(8, 11, 4),
                      _grid(8, 7), _ev(ETYPE_CC, 9, {"cc_num": 74, "value": 9}, 0))
    msgs = _msgs(_export(p, is_bank=_bank_tracks(0)).tracks[1])
    tick8 = [m for m in msgs if m[0] > 0]
    assert (0, "note_on", 0, SYNTH_NOTES[7]) in msgs
    assert [m[2] for m in tick8] == [4, 4, 4, 4]          # CC0, PGM, note, CC74
    assert ("program_change", 11) in [(m[1], m[3]) for m in tick8]


def test_export_header_on_other_channel_carries_mix():
    p = _pattern_with(2, _pgm(0, 5, 6), _grid(0, 0))
    mid = build_pattern_midi(
        p, name="P", bpm=120, track_channels=list(range(16)),
        track_is_synth=[False] * 16, track_names=[""] * 16,
        kit_pad_notes=list(range(36, 52)), synth_grid_notes=SYNTH_NOTES,
        voice_durations=[500] * 16, track_volumes=[100] * 16, track_pans=[0] * 16,
        track_is_bank=_bank_tracks(2))
    assert {m.channel for m in mid.tracks[1] if hasattr(m, "channel")} == {6}


def test_export_drums_on_current_channel_10():
    p = _pattern_with(5, _grid(0, 2), _pgm(4, 0, KIT_CH), _grid(4, 2))
    notes = _msgs(_export(p, is_bank=_bank_tracks(5)).tracks[1], ("note_on",))
    assert notes == [(0, "note_on", 5, SYNTH_NOTES[2]), (480, "note_on", KIT_CH, 38)]  # 4 pas = 1 temps


def test_export_same_note_on_two_channels_not_cut():
    p = _pattern_with(0, _grid(0, 0), _pgm(1, 0, 3), _grid(1, 0))
    track = _export(p, is_bank=_bank_tracks(0)).tracks[1]
    offs = [(at, m.channel) for at, m in _abs(track) if m.type == "note_off"]
    assert sorted(ch for _, ch in offs) == [0, 3]
    assert all(at > 120 for at, _ in offs)                # durée entière (500 ms)


def test_export_bank_kit_notes_not_mapped_and_patch_kept():
    p = _pattern_with(2, _ev(ETYPE_KIT, 0, {"note": 50, "vel": 100}),
                         _ev(ETYPE_PATCH, 4, {"note": 72, "vel": 100}))
    mid = _export(p, is_bank=_bank_tracks(2), gm_map={50: 38})
    assert sorted(m[3] for m in _msgs(mid.tracks[1], ("note_on",))) == [50, 72]


def test_export_non_bank_track_ignores_program_change_channel():
    """Pistes hors banque (et anciens projets, PGM au canal du contrôleur) :
    le Program Change ne déplace pas la piste."""
    p = _pattern_with(2, _ev(ETYPE_KIT, 0, {"note": 50, "vel": 100}), _pgm(2, 3, 5),
                      _ev(ETYPE_KIT, 4, {"note": 50, "vel": 100}))
    mid = _export(p, gm_map={50: 38})
    assert {m.channel for m in mid.tracks[1] if hasattr(m, "channel")} == {2}
    assert [m[3] for m in _msgs(mid.tracks[1], ("note_on",))] == [38, 38]


# ---------------------------------------------------------------------------
# Pédale, Pitch Bend et modulation des banques (Phase 7 étape 18e1,
# docs/DESIGN.md § 18d2 P1-P3)
# ---------------------------------------------------------------------------

def _bend(time_val, value, channel=0):
    return _ev(ETYPE_BEND, time_val, {"value": value}, channel)


def test_cc64_bank_track_goes_to_its_current_channel_only():
    """P1 : la pédale d'une piste Banque ne tient que son canal."""
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.program_change(2, 0, channel=7)
    eng.calls.clear()
    router.on_cc_tape(2, 64, 127, 0)
    assert eng.ccs(num=64) == [("cc", 7, 64, 127)]


def test_cc64_bank_track_sent_even_when_muted():
    """P1 : un relâchement de pédale ne se perd pas sur une piste muette."""
    router, eng, *_ = _make_router()
    router.assign_slot(2, BANK_A)
    router.toggle_track_mute(2)
    eng.calls.clear()
    router.on_cc_tape(2, 64, 0, 0)
    assert eng.ccs(num=64) == [("cc", 2, 64, 0)]


def test_cc64_synth_track_keeps_global_sustain():
    """P1 : sur un synthé WAV, la pédale reste globale (set_sustain)."""
    router, eng, *_ = _make_router()
    router.assign_slot(1, 1)
    got = []
    router.set_sustain = got.append
    router.on_cc_tape(1, 64, 100, 0)
    assert got == [True]


def test_on_play_stop_zeroes_pedal_bend_mod_on_16_channels():
    """P2 : Zero Controllers à l'arrêt."""
    router, eng, *_ = _make_router()
    eng.calls.clear()
    router.on_play_stop()
    assert sorted(c[1] for c in eng.ccs(num=64)) == list(range(16))
    assert sorted(c[1] for c in eng.ccs(num=1)) == list(range(16))
    assert all(c[3] == 0 for c in eng.ccs())
    assert sorted(eng.of("bend")) == [("bend", ch, 0) for ch in range(16)]


def test_on_play_stop_without_engine():
    router, *_ = _make_router(with_engine=False)
    router.on_play_stop()                       # sans erreur


def _last(eng, kind, channel, num=None):
    if kind == "bend":
        return [c for c in eng.of("bend") if c[1] == channel][-1][2]
    return eng.ccs(channel, num)[-1][3]


def test_chase_restores_pedal_bend_and_mod_before_position():
    """P3 : dernière valeur avant la position, position comprise."""
    router, eng, *_ = _make_router()
    router.assign_slot(0, BANK_A)
    tape = _tape(t0=[_cc(0, 64, 127, 0), _cc(4, 64, 0, 0), _cc(8, 64, 127, 0),
                     _bend(2, -2000), _cc(3, 1, 90, 0), _cc(12, 1, 10, 0)])
    router.chase(tape, 6.0)
    assert (_last(eng, "cc", 0, 64), _last(eng, "bend", 0), _last(eng, "cc", 0, 1)) == (0, -2000, 90)
    router.chase(tape, 8.0)
    assert (_last(eng, "cc", 0, 64), _last(eng, "cc", 0, 1)) == (127, 90)


def test_chase_zeroes_controllers_without_events():
    """P3 : une pédale enfoncée par une lecture précédente ne survit pas."""
    router, eng, *_ = _make_router()
    router.assign_slot(0, BANK_A)
    router.on_cc_tape(0, 64, 127, 0)
    router.chase(_tape(), 0.0)
    for ch in range(16):
        assert (_last(eng, "cc", ch, 64), _last(eng, "cc", ch, 1), _last(eng, "bend", ch)) == (0, 0, 0)


def test_chase_controllers_follow_track_channel_at_their_time():
    """P3 : le canal d'une pédale est celui de la piste à son instant (O3)."""
    router, eng, *_ = _make_router()
    router.assign_slot(0, BANK_A)
    tape = _tape(t0=[_cc(0, 64, 127, 0), _pgm(4, 5, 6), _cc(6, 64, 100, 0), _bend(6, 512)])
    router.chase(tape, 8.0)
    assert _last(eng, "cc", 0, 64) == 127
    assert _last(eng, "cc", 6, 64) == 100
    assert _last(eng, "bend", 6) == 512 and _last(eng, "bend", 0) == 0


def test_chase_controllers_sent_after_instruments():
    """P3 : un changement d'instrument ne remet pas la pédale poursuivie à 0."""
    router, eng, *_ = _make_router()
    router.assign_slot(0, BANK_A)
    eng.calls.clear()
    router.chase(_tape(t0=[_pgm(0, 3, 0), _cc(0, 64, 127, 0)]), 0.0)
    kinds = [c[0] for c in eng.calls]
    assert kinds.index("select") < eng.calls.index(("cc", 0, 64, 127))


def test_chase_controllers_ignore_non_bank_tracks():
    router, eng, *_ = _make_router()
    router.assign_slot(1, 1)                       # synthé WAV
    router.chase(_tape(t1=[_cc(0, 64, 127, 1)]), 0.0)
    assert _last(eng, "cc", 1, 64) == 0


# ---------------------------------------------------------------------------
# Player : rappel de fin de lecture (§ 18d2 P2)
# ---------------------------------------------------------------------------

def _player_with_stop(monkeypatch):
    pl, _got = _player_with_chase(monkeypatch)
    stops = []
    pl._on_play_stop_cb = lambda: stops.append(True)
    return pl, stops


@pytest.mark.parametrize("stop", ["stop_pattern", "pause_pattern", "stop_all"])
def test_stop_calls_play_stop_cb_when_playing(monkeypatch, stop):
    pl, stops = _player_with_stop(monkeypatch)
    pl.play_pattern()
    getattr(pl, stop)()
    assert stops == [True]


@pytest.mark.parametrize("stop", ["stop_pattern", "pause_pattern", "stop_all"])
def test_stop_without_playback_does_not_call_play_stop_cb(monkeypatch, stop):
    pl, stops = _player_with_stop(monkeypatch)
    getattr(pl, stop)()
    assert stops == []


def test_stop_after_pause_calls_play_stop_cb_once(monkeypatch):
    pl, stops = _player_with_stop(monkeypatch)
    pl.play_pattern()
    pl.pause_pattern()
    pl.stop_pattern()
    assert stops == [True]
