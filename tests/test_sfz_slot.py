#python3
"""
    File: tests/test_sfz_slot.py
    Slot Synth SFZ (Phase 8 étapes 7e1 et 7g1, docs/DESIGN.md § 7a2 Z10,
    Z11, Z12, § 7a3 Z16-Z25 ; avancement 7d1, 7f1, 7f2) : type SFZ du Rack
    (source, programme GM, gain, .gvp),
    routeur à deux moteurs (slots à canaux Banque / SFZ, moteur de chaque
    slot) avec un moteur sfizz factice : fichiers des slots, sélection des
    canaux, notes de grille / KIT / PATCH, Bend, modulation, CC, pédale,
    volume et pan, Program Change (canal sans changement de son), poursuite,
    canal partagé, coupures, préécoute (BankPreview), mode Rack, copie de
    rendu ; exports MIDI (_midi_params) et WAV (_Session) ; rendu de bout en
    bout avec le vrai sfizz (sauté sans libsfizz) ; banque de programmes
    (7g1) : Program Change qui choisit le programme, préchargement à la
    poursuite, canaux libérés, gain du slot, noms des programmes, nom de
    piste sans préfixe.
    Date: Wed, 04/11/2026
    Author: Coolbrother
"""
import sys
import os
import types
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest

import audio_export as ax
from rack import Rack, InstrumentSlot, InstrumentType
from track_router import TrackRouter
from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_CC
from midi.midi_export import build_pattern_midi, volume_to_cc7, pan_to_cc10
from sound_device_driver import Mixer
from sound_manager import SoundManager
from voice_manager import VoiceManager
from ui.mw_project import ProjectMixin
from engines.sfizz_engine import SfzEngine, sfizz_available

# Moteur de banque factice, son du kit, minuteries : ceux des tests du slot Banque
from test_bank_slot import (FakeBankEngine, FakeSoundManager, FakeTimer,
                            _fake_timer_and_synth, _tape, _pgm, _ev)

NUM_TRACKS = TrackRouter.NUM_TRACKS
KIT_CH     = Pattern.KIT_CHANNEL
SFZ_DIR    = "/fake/sfz"

SFZ_A = 6       # slot Synth SFZ (chemin relatif à sfz_dir)
SFZ_B = 7       # slot Synth SFZ (chemin absolu)
BANK  = 2       # slot Banque, emplacement 1


class FakeSfzEngine(FakeBankEngine):
    """Moteur sfizz factice : emplacement = slot du Rack (16), comme
    SfzEngine ; enregistre les appels, ses copies de rendu et sa fermeture."""

    NUM_BANK_SLOTS = 16

    def __init__(self, refuse=()):
        super().__init__(refuse=refuse)
        self.copies = []
        self.closed = False
        self.voices = 0

    def presets(self, slot):
        """Trois programmes par source : « 001-<nom> », « 002-<nom> »,
        « 049-<nom> » (0, 1, 48)."""
        path = self.paths[slot]
        if not path:
            return []
        stem = os.path.splitext(os.path.basename(path))[0]
        return [(0, 0, f"001-{stem}"), (0, 1, f"002-{stem}"), (0, 48, f"049-{stem}")]

    def select(self, channel, slot, bank, program):
        self.calls.append(("select", channel, slot, bank, program))
        return self.paths[slot] is not None and program in (0, 1, 48)

    def set_slot_gain(self, slot, gain_db):
        self.calls.append(("gain", slot, gain_db))

    def prefetch(self, channel, slot, programs):
        self.calls.append(("prefetch", channel, slot, list(programs)))

    def release_channel(self, channel):
        self.calls.append(("release", channel))

    stale = ()                       # emplacements dont la source a changé (7j1)

    def source_stale(self, slot):
        return slot in self.stale

    def program_change(self, channel, program):
        self.calls.append(("pgm", channel, program))

    def active_voices(self):
        return self.voices

    def render_copy(self):
        copy = FakeSfzEngine()
        copy.paths = list(self.paths)
        self.copies.append(copy)
        return copy

    def close(self):
        self.closed = True


class CopyableSoundManager(FakeSoundManager):
    """Son du kit factice qui sait se copier (TrackRouter.render_copy)."""

    def render_copy(self, driver):
        return CopyableSoundManager()


def _make_rack():
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT,   "Default Kit", {})
    rack.set_slot(1, InstrumentType.SYNTH, "Piano WAV",   {"patch": "piano_1"})
    rack.set_slot(BANK, InstrumentType.BANK, "FluidR3_GM", {"bank_slot": 0})
    rack.set_bank_file(0, "/fake/FluidR3_GM.sf2")
    rack.set_slot(SFZ_A, InstrumentType.SFZ, "Headroom Piano",
                  {"sfz_file": "Headroom/Headroom Piano.sfz"})
    rack.set_slot(SFZ_B, InstrumentType.SFZ, "SamsSonor",
                  {"sfz_file": "/abs/SamsSonor.sfz"})
    return rack


def _make_router(sfz=None, bank=None, cur_track=0):
    rack = _make_rack()
    snd = CopyableSoundManager()
    statuses = []
    sfz = FakeSfzEngine() if sfz is None else sfz
    bank = FakeBankEngine() if bank is None else bank
    holder = {"track": cur_track}
    router = TrackRouter(rack, "/fake/synths", snd, statuses.append,
                         bank_engine=bank or None, cur_track=lambda: holder["track"],
                         sfz_engine=sfz or None, sfz_dir=SFZ_DIR)
    router.update_kb_notes("major", 48)
    router.set_playback_kb("major", 48)
    return router, sfz, bank, snd, statuses, holder


def _on_sfz(router, track=0, slot=SFZ_A, channel=None):
    """Piste track sur un slot SFZ (au canal channel), moteurs remis à zéro."""
    if channel is not None:
        router.set_track_channel(track, channel)
    router.assign_slot(track, slot)
    for engine in router._chan_engines():
        engine.calls.clear()


def _fire_timers():
    for t in list(FakeTimer.created):
        t.fire()
    FakeTimer.created.clear()


# ---------------------------------------------------------------------------
# Rack : type SFZ, fichier, programme GM, .gvp (Z10, Z12)
# ---------------------------------------------------------------------------

def test_sfz_type_is_listed():
    assert InstrumentType.SFZ == "sfz"
    assert InstrumentType.SFZ in InstrumentType.ALL


def test_sfz_slot_plays_notes():
    rack = _make_rack()
    assert rack.get_slot(SFZ_A).plays_notes
    assert rack.get_slot(BANK).plays_notes and rack.get_slot(1).plays_notes
    assert not rack.get_slot(0).plays_notes


def test_sfz_file_read_and_stripped():
    s = InstrumentSlot(3)
    s.type, s.config = InstrumentType.SFZ, {"sfz_file": "  a/b.sfz  "}
    assert s.sfz_file() == "a/b.sfz"
    for bad in ({}, {"sfz_file": ""}, {"sfz_file": "   "}, {"sfz_file": 3}):
        s.config = bad
        assert s.sfz_file() is None


def test_sfz_file_only_for_sfz_slots():
    s = InstrumentSlot(0)
    s.type, s.config = InstrumentType.SYNTH, {"sfz_file": "a.sfz"}
    assert s.sfz_file() is None


def test_sfz_slot_has_a_gm_program_for_export():
    s = InstrumentSlot(0)
    s.type, s.name = InstrumentType.SFZ, "Electric Bass (finger)"
    assert s.gm_program() == 33                 # deviné du nom
    s.set_gm_program(40)
    assert s.gm_program() == 40


def test_sfz_slot_gm_tuning():
    s = InstrumentSlot(0)
    s.type, s.name = InstrumentType.SFZ, "Piano"
    s.config = {"gm_transpose": 12, "gm_gain_db": -6}
    assert s.gm_transpose() == 0                # notes réelles : pas de transposition
    assert s.gm_gain_db() == -6                 # gain GM gardé (programme deviné)


def test_rack_round_trip_keeps_sfz_slot():
    rack = _make_rack()
    other = Rack()
    other.from_dict(rack.to_dict())
    s = other.get_slot(SFZ_A)
    assert s.type == InstrumentType.SFZ and s.name == "Headroom Piano"
    assert s.sfz_file() == "Headroom/Headroom Piano.sfz"


# ---------------------------------------------------------------------------
# Routeur : chemins, moteur de chaque slot (Z11)
# ---------------------------------------------------------------------------

def test_sfz_path_relative_absolute_and_missing():
    router, *_ = _make_router()
    rack = router._rack
    assert router.sfz_path(rack.get_slot(SFZ_A)) == os.path.join(SFZ_DIR, "Headroom/Headroom Piano.sfz")
    assert router.sfz_path(rack.get_slot(SFZ_B)) == "/abs/SamsSonor.sfz"
    assert router.sfz_path(rack.get_slot(BANK)) is None
    router.sfz_dir = ""
    assert router.sfz_path(rack.get_slot(SFZ_A)) == "Headroom/Headroom Piano.sfz"


def test_engine_of_each_slot_type():
    router, sfz, bank, *_ = _make_router()
    rack = router._rack
    assert router._engine_of(rack.get_slot(SFZ_A)) is sfz
    assert router._engine_of(rack.get_slot(BANK)) is bank
    assert router._engine_of(rack.get_slot(1)) is None
    assert router._engine_of(None) is None
    assert router._chan_engines() == [bank, sfz]


def test_chan_slot_of_bank_and_sfz_only():
    router, *_ = _make_router()
    router.assign_slot(0, SFZ_A)
    router.assign_slot(1, BANK)
    router.assign_slot(2, 1)
    assert router._chan_slot_of(0).type == InstrumentType.SFZ
    assert router._chan_slot_of(1).type == InstrumentType.BANK
    assert router._chan_slot_of(2) is None
    assert router._bank_slot_of(0) is None       # propre à la banque


def test_sync_registers_sfz_file_of_each_slot():
    router, sfz, *_ = _make_router()
    router.sync_bank_files()
    assert sfz.loaded_path(SFZ_A) == os.path.join(SFZ_DIR, "Headroom/Headroom Piano.sfz")
    assert sfz.loaded_path(SFZ_B) == "/abs/SamsSonor.sfz"
    assert sfz.loaded_path(BANK) is None
    assert router.bank_slot_ready(SFZ_A) and router.bank_slot_ready(BANK)
    assert not router.bank_slot_ready(1) and not router.bank_slot_ready(None)


def test_sync_reloads_changed_file_and_forgets_cleared_slot():
    router, sfz, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A)
    router._rack.set_slot(SFZ_A, InstrumentType.SFZ, "Autre", {"sfz_file": "autre.sfz"})
    router._rack.clear_slot(SFZ_B)
    router.sync_banks()
    assert ("load", SFZ_A, os.path.join(SFZ_DIR, "autre.sfz")) in sfz.calls
    assert ("unload", SFZ_B) in sfz.calls
    assert sfz.selects(0)                        # le canal resélectionne le nouveau fichier


def test_missing_sfz_source_reported():
    sfz = FakeSfzEngine(refuse={"/abs/SamsSonor.sfz"})
    router, _, _, _, statuses, _ = _make_router(sfz=sfz)
    router.sync_bank_files()
    assert sfz.loaded_path(SFZ_B) is None
    assert any("Slot 08: source SFZ introuvable ou vide" in m for m in statuses)


def test_assign_sfz_selects_channel_and_sends_mix_to_sfz_only():
    router, sfz, bank, *_ = _make_router()
    router.set_track_channel(0, 4)
    bank.calls.clear()
    router.assign_slot(0, SFZ_A)
    assert sfz.selects(4) == [("select", 4, SFZ_A, 0, 0)]
    assert sfz.ccs(4, 7) and sfz.ccs(4, 10)
    assert not bank.selects(4) and not bank.ccs(4)


def test_select_sent_once_per_channel():
    router, sfz, *_ = _make_router()
    router.assign_slot(0, SFZ_A)
    router.sync_banks()
    router.sync_banks()
    assert len(sfz.selects(0)) == 1


def test_sfz_engine_absent_slot_is_silent():
    router, _, bank, snd, *_ = _make_router(sfz=False)
    router.assign_slot(0, SFZ_A)
    router.on_play(0, 0, 1.0, 0)
    router.on_patch_tape(0, 60, 100, 200)
    router.on_bend_tape(0, 4000)
    assert not bank.of("note_on") and not snd.played and not snd.played_notes


# ---------------------------------------------------------------------------
# Notes, contrôleurs, mixage
# ---------------------------------------------------------------------------

def test_grid_note_plays_keyboard_scale_on_sfz():
    router, sfz, bank, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A)
    router.on_play(0, 2, 1.0, 0, duration_ms=300)
    note = router._kb_notes_play[2]
    assert sfz.of("note_on") == [("note_on", 0, note, 127)]
    assert not bank.of("note_on")
    _fire_timers()
    assert sfz.of("note_off") == [("note_off", 0, note)]


def test_grid_on_channel_10_is_drum_note():
    router, sfz, *_ = _make_router()
    _on_sfz(router, 0, SFZ_B, channel=KIT_CH)
    router.on_play(0, 2, 0.5, 0)
    assert sfz.of("note_on") == [("note_on", KIT_CH, 36 + 2, 64)]


def test_sfz_keeps_channel_10_when_assigned():
    router, *_ = _make_router()
    assert router.channel_after_slot(0, SFZ_B, KIT_CH) == KIT_CH
    assert router.channel_after_slot(0, SFZ_B, 3) == 3
    assert router.channel_after_slot(0, 0, 3) == KIT_CH      # un kit, lui, passe au 10


def test_muted_sfz_track_is_silent():
    router, sfz, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A)
    router.toggle_track_mute(0)
    router.on_play(0, 0, 1.0, 0)
    router.on_patch_tape(0, 60, 100)
    assert not sfz.of("note_on")


def test_kit_and_patch_notes_go_as_is():
    router, sfz, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=2)
    router.on_kit_tape(0, 38, 90)
    router.on_patch_tape(0, 67, 80, 250)
    assert sfz.of("note_on") == [("note_on", 2, 38, 90), ("note_on", 2, 67, 80)]


def test_bend_mod_and_cc_go_to_sfz_channel():
    router, sfz, bank, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=5)
    router.on_bend_tape(0, 4096)
    router.on_mod_tape(0, 70)
    router.on_cc_tape(0, 11, 90)
    router.on_cc_tape(0, 64, 127)
    assert ("bend", 5, 4096) in sfz.calls
    assert sfz.ccs(5, 1) == [("cc", 5, 1, 70)]
    assert sfz.ccs(5, 11) == [("cc", 5, 11, 90)]
    assert sfz.ccs(5, 64) == [("cc", 5, 64, 127)]
    assert not bank.calls


def test_bank_select_kept_but_not_sent_for_sfz():
    router, sfz, bank, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=5)
    router.on_cc_tape(0, 0, 8)
    router.on_cc_tape(0, 32, 1)
    assert router._chan_msb[5] == 8 and router._chan_lsb[5] == 1
    assert not sfz.ccs(5, 0) and not sfz.ccs(5, 32) and not bank.calls


def test_volume_pan_and_master_pan_to_sfz():
    router, sfz, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=1)
    router.set_track_volume(0, 50)
    router.set_track_pan(0, -40)
    router.set_master_pan(20)
    assert sfz.ccs(1, 7)[-1] == ("cc", 1, 7, volume_to_cc7(50))
    assert sfz.ccs(1, 10)[-1] == ("cc", 1, 10, pan_to_cc10(-20))


def test_program_change_selects_program_and_moves_channel():
    router, sfz, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=0)
    assert router.program_change(0, 48, channel=6) is True
    assert router.track_channel_now(0) == 6
    assert router.slot_for_track(0) == SFZ_A     # pas de pont program % 16
    assert sfz.selects(6) == [("select", 6, SFZ_A, 0, 48)]
    assert sfz.ccs(6, 7) and sfz.ccs(6, 10)      # mixage suivi sur le nouveau canal
    sfz.calls.clear()
    router.program_change(0, 1)                   # même canal : nouveau programme
    assert sfz.selects(6) == [("select", 6, SFZ_A, 0, 1)]
    sfz.calls.clear()
    router.program_change(0, 1)                   # Program Change : toujours renvoyé
    assert sfz.selects(6) == [("select", 6, SFZ_A, 0, 1)]


def test_chase_follows_program_change_of_sfz_track():
    router, sfz, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=0)
    tape = _tape(t0=[_pgm(0, 48, 3), _ev(ETYPE_CC, 0, {"cc_num": 1, "value": 33}, 3)])
    router.chase(tape)
    assert router.track_channel_now(0) == 3
    assert ("select", 3, SFZ_A, 0, 48) in sfz.calls
    assert ("cc", 3, 1, 33) in sfz.calls          # modulation poursuivie


def test_chase_and_play_stop_reset_both_engines():
    router, sfz, bank, *_ = _make_router()
    router.chase(_tape())
    for engine in (sfz, bank):
        assert len(engine.of("bend")) == 16
    sfz.calls.clear()
    bank.calls.clear()
    router.on_play_stop()
    for engine in (sfz, bank):
        assert len(engine.of("bend")) == 16 and len(engine.ccs(num=64)) == 16


def test_shared_channel_bank_and_sfz_warns():
    router, sfz, bank, _, statuses, _ = _make_router()
    router.set_track_channel(0, 4)
    router.set_track_channel(1, 4)
    router.assign_slot(0, BANK)
    router.assign_slot(1, SFZ_A)
    assert any("Canal 5: pistes 1 et 2 sur des sons différents" in m for m in statuses)


# ---------------------------------------------------------------------------
# Coupures (Phase 8 étape 6, étendues au SFZ)
# ---------------------------------------------------------------------------

def test_cut_track_notes_cuts_sfz_channel_only():
    router, sfz, bank, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=3)
    router.cut_track_notes(0)
    assert sfz.ccs(3, 120) and sfz.ccs(3, 64) == [("cc", 3, 64, 0)]
    assert not bank.ccs(3)


def test_cut_all_notes_and_globals_reach_both_engines():
    router, sfz, bank, *_ = _make_router()
    router.cut_all_notes()
    router.stop_all_synth_voices()
    router.stop_all_sounds()
    router.reset_all_controls()
    router.set_sustain(True)
    for engine in (sfz, bank):
        assert engine.of("all_sounds_off") and engine.of("all_notes_off")
        assert engine.of("reset_controllers")
        assert len(engine.ccs(num=64, channel=None)) >= 32       # coupure + pédale


# ---------------------------------------------------------------------------
# Préécoute (BankPreview) sur un slot SFZ
# ---------------------------------------------------------------------------

def test_preview_plays_on_sfz_engine():
    router, sfz, bank, _, _, holder = _make_router()
    router.set_track_channel(0, 2)
    router.load_slot_preview(SFZ_A)
    assert router.synth is router._bank_preview
    assert router.synth.is_loaded()
    router.synth.play(64, 1.0, 0, 0)              # tenue
    assert sfz.of("note_on")[-1] == ("note_on", 2, 64, 127)
    assert not bank.of("note_on")


def test_held_preview_note_stops_on_its_engine_after_slot_change():
    router, sfz, bank, *_ = _make_router()
    router.load_slot_preview(SFZ_A)
    router.synth.play(64, 1.0, 0, 0)
    router.load_slot_preview(BANK)                # préécoute passée sur la banque
    router.synth.stop(64)
    assert ("note_off", 0, 64) in sfz.calls
    assert not bank.of("note_off")


def test_preview_bend_and_mod_on_sfz():
    router, sfz, *_ = _make_router()
    router.load_slot_preview(SFZ_A)
    router.synth.pitch_bend = 2000
    router.synth.apply_pitch_bend()
    router.synth.set_mod_wheel(50)
    assert ("bend", 0, 2000) in sfz.calls and ("cc", 0, 1, 50) in sfz.calls


# ---------------------------------------------------------------------------
# Mode Rack : canal N → slot N (Phase 8 étape 5)
# ---------------------------------------------------------------------------

def test_rack_mode_channel_plays_sfz_slot():
    router, sfz, *_ = _make_router()
    router.rack_mode = True
    router.set_track_channel(0, SFZ_A)            # canal 7 → slot 7 (SFZ)
    router.sync_banks()
    assert router.slot_for_track(0) == SFZ_A
    router.on_patch_tape(0, 60, 100)
    assert ("note_on", SFZ_A, 60, 100) in sfz.calls


def test_rack_mode_fallback_is_a_bank_never_a_sfz():
    router, *_ = _make_router()
    assert router.fallback_bank_idx() == BANK
    router._rack.clear_slot(BANK)
    assert router.fallback_bank_idx() is None     # un SFZ ne sert pas de repli (M5)


# ---------------------------------------------------------------------------
# Copie de rendu, exports (Z12)
# ---------------------------------------------------------------------------

def test_render_copy_carries_sfz_engine_and_dir():
    router, sfz, *_ = _make_router()
    copy_engine = FakeSfzEngine()
    r = router.render_copy(Mixer(), sfz_engine=copy_engine)
    assert r.sfz_engine is copy_engine and r.sfz_dir == SFZ_DIR


def test_wav_session_copies_sfz_engine_and_closes_it():
    router, sfz, *_ = _make_router(bank=False)
    session = ax._Session(router, Mixer.SAMPLERATE, 1.0)
    copy = session.sfz
    assert sfz.copies == [copy] and session.router.sfz_engine is copy
    assert copy.render in session.mixer._render_sources
    copy.voices = 3
    assert session.voices() == 3
    session.close()
    assert copy.closed and session.sfz is None and not sfz.closed
    assert copy.render not in session.mixer._render_sources


def _midi_window(rack, router):
    snd = types.SimpleNamespace(pad_notes=[36 + i for i in range(16)], gm_note_map={})
    return types.SimpleNamespace(_rack=rack, _router=router, _snd=snd)


def test_midi_params_sfz_track_is_channel_track_with_gm_program():
    router, *_ = _make_router()
    rack = router._rack
    rack.get_slot(SFZ_A).set_gm_program(1)
    slots = [SFZ_A, BANK, 1] + [0] * 13
    prm = ProjectMixin._midi_params(
        _midi_window(rack, router), name="P", bpm=120, track_slots=slots,
        channels=list(range(16)), volumes=[100] * 16, pans=[0] * 16,
        audible=[True] * 16, vm=VoiceManager(), kb_notes=list(range(60, 76)),
        preset_name=lambda t: f"Preset {t}")
    assert prm["track_is_bank"][:3] == [True, True, False]
    assert prm["track_programs"][0] == 1 and prm["track_programs"][1] is None
    # nom de piste : programme du canal, pour une banque comme pour un SFZ (7f1)
    assert prm["track_names"][:3] == ["Preset 0", "Preset 1", "Piano WAV"]


def test_midi_export_sfz_drum_grid_and_program():
    p = Pattern()
    p.new_pattern(1, 16)
    p._tape[0] = [_ev(ETYPE_GRID, 0, {"pad": 3, "vel": 100})]
    n = p._num_tracks
    channels = list(range(16))
    channels[0] = KIT_CH
    mid = build_pattern_midi(
        p, name="P", bpm=120, track_channels=channels, track_is_synth=[False] * n,
        track_names=[""] * n, kit_pad_notes=[50 + i for i in range(16)],
        synth_grid_notes=[60 + i for i in range(16)], voice_durations=[500] * 16,
        track_programs=[25] + [None] * 15, track_is_bank=[True] + [False] * 15)
    msgs = [m for m in mid.tracks[1] if m.type in ("program_change", "note_on")]
    assert msgs[0].type == "program_change" and msgs[0].program == 25 \
        and msgs[0].channel == KIT_CH
    assert msgs[1].note == 36 + 3 and msgs[1].channel == KIT_CH    # 36 + pad, pas le kit


# ---------------------------------------------------------------------------
# De bout en bout avec le vrai sfizz : rendu WAV d'une piste SFZ
# ---------------------------------------------------------------------------

def _write_sine(path, freq=440.0, sr=Mixer.SAMPLERATE, seconds=2.0):
    t = np.arange(int(seconds * sr)) / sr
    pcm = (np.cos(2 * np.pi * freq * t) * 0.5 * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


@pytest.mark.skipif(not sfizz_available(), reason="libsfizz absente")
def test_render_pattern_with_real_sfizz(tmp_path):
    sr = Mixer.SAMPLERATE
    _write_sine(tmp_path / "a440.wav")
    (tmp_path / "sine.sfz").write_text(
        "<region> sample=a440.wav pitch_keycenter=69 lokey=0 hikey=127 ampeg_release=0.05\n")
    pads = []
    for i in range(16):                          # sons du kit : silence
        path = tmp_path / f"pad{i}.wav"
        _write_sine(path, seconds=0.01)
        pads.append(str(path))
    driver = Mixer()
    snd = SoundManager(pads, pads[0], pads[0], driver=driver)
    snd.load_sounds()
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT, "Kit", {})
    rack.set_slot(SFZ_A, InstrumentType.SFZ, "Sine", {"sfz_file": "sine.sfz"})
    live_sfz = SfzEngine(sr)
    router = TrackRouter(rack, str(tmp_path), snd, lambda m: None, driver=driver,
                         sfz_engine=live_sfz, sfz_dir=str(tmp_path))
    router.set_playback_kb("major", 57)          # pad 0 = la 2 (note 57) = 220 Hz
    router.assign_slot(1, SFZ_A)
    pat = Pattern()
    pat._bpm, pat._num_bars = 120, 1
    pat._tape[1].append(TapeEvent(ETYPE_GRID, payload={"pad": 0, "vel": 100}, time=0, dur=1000))
    try:
        res = ax.render_pattern(pat, pat.tempo_map(), router, VoiceManager(), end=ax.END_TAIL)
    finally:
        live_sfz.close()
    x = res.data[sr // 10: sr // 2, 0]
    assert float(np.abs(x).max()) > 0.01
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freq = np.argmax(spec) * sr / len(x)
    assert abs(freq - 220.0) < 5.0
    assert live_sfz.channel_path(0) is None       # le moteur de l'écoute n'a pas servi


# ---------------------------------------------------------------------------
# Banque de programmes côté routeur (Phase 8 étapes 7f1, 7f2 ; § 7a3)
# ---------------------------------------------------------------------------

def test_sfz_source_key_and_legacy_sfz_file():
    s = InstrumentSlot(0)
    s.type = InstrumentType.SFZ
    s.config = {"sfz_source": "Discord GM/Melodic", "sfz_file": "ancien.sfz"}
    assert s.sfz_source() == "Discord GM/Melodic"     # la nouvelle clé l'emporte
    s.config = {"sfz_file": "ancien.sfz"}
    assert s.sfz_source() == "ancien.sfz" == s.sfz_file()


def test_sfz_gain_db_bounded_and_sfz_only():
    s = InstrumentSlot(0)
    s.type = InstrumentType.SFZ
    assert s.sfz_gain_db() == 0
    s.set_sfz_gain_db(-40)
    assert s.sfz_gain_db() == -24 and s.config["sfz_gain_db"] == -24
    s.set_sfz_gain_db(30)
    assert s.sfz_gain_db() == 12
    s.config = {"sfz_gain_db": "fort"}
    assert s.sfz_gain_db() == 0
    s.type = InstrumentType.SYNTH
    s.config = {"sfz_gain_db": -6}
    assert s.sfz_gain_db() == 0


def test_sync_sends_slot_gain():
    router, sfz, *_ = _make_router()
    router._rack.get_slot(SFZ_A).set_sfz_gain_db(-10)
    router.sync_bank_files()
    assert ("gain", SFZ_A, -10) in sfz.calls and ("gain", SFZ_B, 0) in sfz.calls
    assert not [c for c in sfz.of("gain") if c[1] not in (SFZ_A, SFZ_B)]


def test_select_key_of_sfz_is_program_of_channel():
    router, sfz, *_ = _make_router()
    router._chan_prog[2] = 48
    _on_sfz(router, 0, SFZ_A, channel=2)
    router.sync_banks(force=True)
    assert sfz.selects(2) == [("select", 2, SFZ_A, 0, 48)]


def test_missing_program_reported():
    router, sfz, _, _, statuses, _ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=0)
    router.program_change(0, 77)
    assert any("Piste 1: slot SFZ 07 sans source ou programme 77 introuvable" in m
               for m in statuses)


def test_preset_and_program_names_of_sfz():
    router, sfz, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=0)
    router.program_change(0, 48)
    assert router.bank_preset_name(0) == "049-Headroom Piano"
    names = router.program_names(SFZ_A, 0, 99, 99)      # MSB / LSB sans objet
    assert names[0] == "001-Headroom Piano" and names[48] == "049-Headroom Piano"
    assert names[2] is None and len(names) == 128
    router.program_change(0, 77)
    assert router.bank_preset_name(0) == "(preset absent)"


def test_program_names_refreshed_when_source_changes():
    router, sfz, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=0)
    assert router.bank_preset_name(0) == "001-Headroom Piano"
    router._rack.set_slot(SFZ_A, InstrumentType.SFZ, "Autre", {"sfz_source": "autre.sfz"})
    router.sync_banks()
    assert router.bank_preset_name(0) == "001-autre"


def test_chase_prefetches_programs_of_the_whole_pattern():
    router, sfz, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=0)
    tape = _tape(t0=[_pgm(0, 1, 0), _pgm(8, 48, 0), _pgm(16, 1, 0)])
    router.chase(tape, 0.0)
    assert ("prefetch", 0, SFZ_A, [1, 48]) in sfz.calls
    assert ("select", 0, SFZ_A, 0, 1) in sfz.calls     # programme à la position


def test_chase_prefetch_includes_current_program_and_follows_channels():
    router, sfz, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=0)
    _on_sfz(router, 1, SFZ_B, channel=5)
    tape = _tape(t0=[_pgm(8, 48, 3)])                  # passe au canal 4 à la mesure 1, pas 9
    router.chase(tape, 0.0)
    prefetch = {c[1]: (c[2], c[3]) for c in sfz.of("prefetch")}
    assert prefetch[0] == (SFZ_A, [0])                 # programme courant du canal 1
    assert prefetch[3] == (SFZ_A, [48])                # celui du Program Change, canal 4
    assert prefetch[5] == (SFZ_B, [0])


def test_chase_releases_channels_without_sfz():
    router, sfz, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=0)
    router.assign_slot(1, BANK)
    router.chase(_tape())
    released = {c[1] for c in sfz.of("release")}
    assert 0 not in released and released == set(range(1, 16))
    assert router._chan_sel[0] is not None             # canal SFZ gardé


def test_chase_does_not_prefetch_bank_program_changes():
    router, sfz, *_ = _make_router()
    router.assign_slot(0, BANK)
    router.chase(_tape(t0=[_pgm(0, 33, 0)]))
    assert not sfz.of("prefetch")


def test_rack_mode_prefetch_uses_slot_of_channel():
    router, sfz, *_ = _make_router()
    router.rack_mode = True
    router.set_track_channel(0, SFZ_A)                 # canal 7 → slot 7 (SFZ)
    tape = _tape(t0=[_pgm(4, 48, SFZ_A)])
    router.chase(tape, 0.0)
    assert ("prefetch", SFZ_A, SFZ_A, [0, 48]) in sfz.calls


def test_chase_without_sfz_engine_is_harmless():
    router, *_ = _make_router(sfz=False)
    router.assign_slot(0, SFZ_A)
    router.chase(_tape(t0=[_pgm(0, 1, 0)]))            # aucune erreur


# ---------------------------------------------------------------------------
# Nom de piste sans préfixe (7f2) : liste des pistes seulement
# ---------------------------------------------------------------------------

def _label_window(router):
    from ui.mw_tracks import TrackMixin
    win = types.SimpleNamespace(
        _router=router, _rack=router._rack,
        _track_editor=types.SimpleNamespace(is_selected=lambda i: False),
        _player=types.SimpleNamespace(voice_manager=VoiceManager(), _cur_track=1,
                                      recording=False))
    win._rack_channel_desc = lambda ch: f"Slot_{ch + 1:02d}"
    return win, TrackMixin._track_label


def test_track_label_shows_sfz_program_without_prefix():
    router, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=0)
    router.program_change(0, 48)
    win, label = _label_window(router)
    assert label(win, 0) == "  Track_01 - Slot_07 - Headroom Piano"
    # la liste des programmes garde le nom complet
    assert router.program_names(SFZ_A, 0, 0, 0)[48] == "049-Headroom Piano"


def test_track_label_keeps_bank_preset_name():
    router, _, bank, *_ = _make_router()
    router.assign_slot(0, BANK)
    win, label = _label_window(router)
    assert label(win, 0) == "  Track_01 - Slot_03 - " + router.bank_preset_name(0)



# ---------------------------------------------------------------------------
# Source modifiée : relue à la synchronisation (correction de l'essai de 7j1)
# ---------------------------------------------------------------------------

def test_sync_reloads_stale_source_and_refreshes_names():
    router, sfz, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=0)
    assert router.bank_preset_name(0) == "001-Headroom Piano"
    loads = len(sfz.of("load"))
    sfz.stale = (SFZ_A,)
    sfz.presets = lambda slot: [(0, 0, "Nouveau")] if slot == SFZ_A else []
    router.sync_banks()
    assert len(sfz.of("load")) == loads + 1               # relue
    assert ("select", 0, SFZ_A, 0, 0) in sfz.calls        # canal resélectionné
    assert router.bank_preset_name(0) == "Nouveau"        # noms rafraîchis


def test_sync_does_not_reload_unchanged_source():
    router, sfz, *_ = _make_router()
    router.sync_bank_files()
    loads = len(sfz.of("load"))
    router.sync_bank_files()
    assert len(sfz.of("load")) == loads
