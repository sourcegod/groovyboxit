#python3
"""
    File: tests/test_sfz_slot.py
    Slot Synth SFZ (Phase 8 étape 7e1, docs/DESIGN.md § 7a2 Z10, Z11, Z12 ;
    avancement 7d1) : type SFZ du Rack (fichier, programme GM, .gvp),
    routeur à deux moteurs (slots à canaux Banque / SFZ, moteur de chaque
    slot) avec un moteur sfizz factice : fichiers des slots, sélection des
    canaux, notes de grille / KIT / PATCH, Bend, modulation, CC, pédale,
    volume et pan, Program Change (canal sans changement de son), poursuite,
    canal partagé, coupures, préécoute (BankPreview), mode Rack, copie de
    rendu ; exports MIDI (_midi_params) et WAV (_Session) ; rendu de bout en
    bout avec le vrai sfizz (sauté sans libsfizz).
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
        path = self.paths[slot]
        return [(0, 0, os.path.splitext(os.path.basename(path))[0])] if path else []

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


def test_missing_sfz_file_reported():
    sfz = FakeSfzEngine(refuse={"/abs/SamsSonor.sfz"})
    router, _, _, _, statuses, _ = _make_router(sfz=sfz)
    router.sync_bank_files()
    assert sfz.loaded_path(SFZ_B) is None
    assert any("Slot 08: fichier SFZ introuvable" in m for m in statuses)


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


def test_program_change_moves_channel_without_changing_sound():
    router, sfz, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=0)
    assert router.program_change(0, 40, channel=6) is True
    assert router.track_channel_now(0) == 6
    assert router.slot_for_track(0) == SFZ_A     # pas de pont program % 16
    assert sfz.selects(6) == [("select", 6, SFZ_A, 0, 0)]
    assert not sfz.of("pgm")
    assert sfz.ccs(6, 7) and sfz.ccs(6, 10)      # mixage suivi sur le nouveau canal
    sfz.calls.clear()
    router.program_change(0, 41)                  # même canal : rien à resélectionner
    assert not sfz.of("select")


def test_chase_follows_program_change_of_sfz_track():
    router, sfz, *_ = _make_router()
    _on_sfz(router, 0, SFZ_A, channel=0)
    tape = _tape(t0=[_pgm(0, 5, 3), _ev(ETYPE_CC, 0, {"cc_num": 1, "value": 33}, 3)])
    router.chase(tape)
    assert router.track_channel_now(0) == 3
    assert ("select", 3, SFZ_A, 0, 0) in sfz.calls
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
        preset_name=lambda t: "Preset banque")
    assert prm["track_is_bank"][:3] == [True, True, False]
    assert prm["track_programs"][0] == 1 and prm["track_programs"][1] is None
    assert prm["track_names"][0] == "Headroom Piano"       # nom du slot
    assert prm["track_names"][1] == "Preset banque"        # preset de la banque


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
