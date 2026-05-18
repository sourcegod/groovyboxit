#python3
"""
    File: tests/test_track_router.py
    Tests unitaires de TrackRouter : routing piste→slot, gestion des SynthEngines,
    dispatch sonore et play_kit_pitched.
    Date: Mon, 18/05/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import patch
from rack import Rack, InstrumentType
from track_router import TrackRouter
from synth_engine import scale_midi_notes


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class FakeSynthEngine:
    """Remplace SynthEngine — aucun fichier audio chargé."""

    def __init__(self, synths_dir=None):
        self._loaded     = False
        self._cache      = {}
        self._played     = []   # (midi, vol, pan)
        self._precomputed = []

    def is_loaded(self):
        return self._loaded

    def load_patch(self, patch_name):
        self._loaded = True
        self._cache  = {60: b""}

    def load_single_sample(self, wav_path, root_midi=60):
        self._loaded = True

    def precompute(self, notes):
        self._precomputed = notes[:]

    def play(self, midi, vol=1.0, pan=0):
        self._played.append((midi, vol, pan))


class FakeSoundManager:
    def __init__(self):
        self.played = []   # (pad_idx, vol, pan)

    def play_sound(self, pad_idx, vol, pan):
        self.played.append((pad_idx, vol, pan))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rack():
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT,   "Default Kit", {})
    rack.set_slot(1, InstrumentType.SYNTH, "Piano",       {"patch": "piano_1"})
    rack.set_slot(2, InstrumentType.SYNTH, "Guitar",      {"patch": "guitar_1"})
    return rack


def _make_router():
    rack     = _make_rack()
    snd      = FakeSoundManager()
    statuses = []
    router   = TrackRouter(rack, "/fake/synths", snd, lambda msg: statuses.append(msg))
    router.update_kb_notes("major", 48)
    return router, snd, statuses


# ---------------------------------------------------------------------------
# État initial
# ---------------------------------------------------------------------------

def test_initial_state():
    router, _, _ = _make_router()
    assert router._track_slots == [0] * 8
    assert router._slot_synths == {}
    assert router._synth is None
    assert router._kit_synth is None
    assert router.kb_last_midi is None
    assert router.kb_notes != []
    print("  initial_state : OK")


# ---------------------------------------------------------------------------
# update_kb_notes
# ---------------------------------------------------------------------------

def test_update_kb_notes_major():
    router, _, _ = _make_router()
    router.update_kb_notes("major", 60)
    assert router.kb_notes == scale_midi_notes("major", 60, 16)
    assert router._kb_scale     == "major"
    assert router._kb_root_midi == 60
    print("  update_kb_notes (major, C4) : OK")


def test_update_kb_notes_minor():
    router, _, _ = _make_router()
    router.update_kb_notes("minor", 48)
    assert router.kb_notes == scale_midi_notes("minor", 48, 16)
    print("  update_kb_notes (minor, C3) : OK")


def test_precompute_async_noop_when_no_synth():
    """precompute_async ne doit pas lever si _synth est None."""
    router, _, _ = _make_router()
    router.precompute_async()   # ne doit pas lever
    assert router._synth is None
    print("  precompute_async (pas de synth) : OK")


def test_precompute_async_noop_when_not_loaded():
    router, _, _ = _make_router()
    router._synth = FakeSynthEngine()   # _loaded = False
    router.precompute_async()           # ne doit pas lever
    assert router._synth._precomputed == []
    print("  precompute_async (non chargé) : OK")


# ---------------------------------------------------------------------------
# slot_for_track / slot_name
# ---------------------------------------------------------------------------

def test_slot_for_track_defaults_to_zero():
    router, _, _ = _make_router()
    for t in range(8):
        assert router.slot_for_track(t) == 0
    print("  slot_for_track (défaut 0) : OK")


def test_slot_name_follows_track_slots():
    router, _, _ = _make_router()
    assert router.slot_name(0) == "Default Kit"
    router._track_slots[3] = 1
    assert router.slot_name(3) == "Piano"
    print("  slot_name : OK")


# ---------------------------------------------------------------------------
# assign_slot
# ---------------------------------------------------------------------------

@patch("track_router.SynthEngine", FakeSynthEngine)
def test_assign_slot_kit_no_synth_created():
    """Un slot KIT ne doit pas déclencher de création de SynthEngine."""
    router, _, _ = _make_router()
    router.assign_slot(0, 0)   # slot 0 = KIT
    assert router._track_slots[0] == 0
    assert 0 not in router._slot_synths
    print("  assign_slot KIT (pas de SynthEngine) : OK")


@patch("track_router.SynthEngine", FakeSynthEngine)
def test_assign_slot_synth_anchors_loaded_preview():
    """Si _synth est déjà chargé pour ce slot, assign_slot l'ancre dans _slot_synths."""
    router, _, _ = _make_router()
    fake = FakeSynthEngine()
    fake._loaded = True
    router._synth          = fake
    router._synth_slot_idx = 1
    router.assign_slot(0, 1)   # slot 1 = SYNTH "Piano"
    assert router._slot_synths.get(1) is fake, "Le moteur chargé doit être ancré"
    print("  assign_slot SYNTH ancrage preview chargée : OK")


@patch("track_router.SynthEngine", FakeSynthEngine)
def test_assign_slot_synth_creates_engine_when_preview_absent():
    """Sans preview chargée, _ensure_slot_synth réserve immédiatement une place."""
    router, _, _ = _make_router()
    router.assign_slot(0, 1)
    assert 1 in router._slot_synths, "_ensure_slot_synth doit réserver la place"
    assert isinstance(router._slot_synths[1], FakeSynthEngine)
    print("  assign_slot SYNTH _ensure_slot_synth : OK")


@patch("track_router.SynthEngine", FakeSynthEngine)
def test_assign_slot_synth_idempotent():
    """Assigner deux fois le même slot commis ne recrée pas le moteur."""
    router, _, _ = _make_router()
    router.assign_slot(0, 1)
    engine1 = router._slot_synths.get(1)
    router.assign_slot(1, 1)   # même slot, autre piste
    engine2 = router._slot_synths.get(1)
    assert engine1 is engine2, "Le moteur ne doit pas être remplacé"
    print("  assign_slot SYNTH idempotent : OK")


@patch("track_router.SynthEngine", FakeSynthEngine)
def test_assign_slot_updates_track_slots():
    router, _, _ = _make_router()
    router.assign_slot(3, 2)
    assert router._track_slots[3] == 2
    print("  assign_slot met à jour _track_slots : OK")


# ---------------------------------------------------------------------------
# load_slot_preview
# ---------------------------------------------------------------------------

@patch("track_router.SynthEngine", FakeSynthEngine)
def test_load_slot_preview_kit_is_noop():
    router, _, _ = _make_router()
    router.load_slot_preview(0)   # slot 0 = KIT
    assert router._synth is None
    print("  load_slot_preview KIT (noop) : OK")


@patch("track_router.SynthEngine", FakeSynthEngine)
def test_load_slot_preview_reuses_committed_engine():
    """Si le slot est déjà commis, load_slot_preview réutilise son moteur."""
    router, _, _ = _make_router()
    router.assign_slot(0, 1)
    committed = router._slot_synths[1]
    router.load_slot_preview(1)
    assert router._synth is committed
    assert router._synth_slot_idx == 1
    print("  load_slot_preview réutilise moteur commis : OK")


@patch("track_router.SynthEngine", FakeSynthEngine)
def test_load_slot_preview_creates_preview_engine():
    """Slot non commis → crée un moteur de preview sans commiter."""
    router, _, _ = _make_router()
    router.load_slot_preview(1)
    assert router._synth is not None
    assert router._synth_slot_idx == 1
    assert 1 not in router._slot_synths, "Preview seule ≠ commit"
    print("  load_slot_preview crée moteur preview : OK")


@patch("track_router.SynthEngine", FakeSynthEngine)
def test_load_slot_preview_does_not_clobber_committed():
    """Changer de preview ne doit pas écraser un moteur déjà commis."""
    router, _, _ = _make_router()
    router.assign_slot(0, 1)
    committed = router._slot_synths[1]
    router.load_slot_preview(2)          # browse slot 2
    assert router._slot_synths.get(1) is committed
    assert router._synth is not committed
    print("  load_slot_preview ne clobbe pas moteur commis : OK")


@patch("track_router.SynthEngine", FakeSynthEngine)
def test_load_slot_preview_replaces_stale_committed_synth():
    """Si _synth pointe sur un moteur commis, on crée un nouveau pour la preview."""
    router, _, _ = _make_router()
    router.assign_slot(0, 1)
    # _synth est None ici ; on y met le moteur commis manuellement
    router._synth = router._slot_synths[1]
    router.load_slot_preview(2)           # slot 2 = Guitar, non commis
    # _synth doit être un nouveau moteur, pas celui du slot 1
    assert router._synth is not router._slot_synths[1]
    print("  load_slot_preview remplace _synth commis par preview fraîche : OK")


# ---------------------------------------------------------------------------
# reset_kit_pad
# ---------------------------------------------------------------------------

def test_reset_kit_pad():
    router, _, _ = _make_router()
    router._kb_kit_pad = 5
    router.reset_kit_pad()
    assert router._kb_kit_pad is None
    print("  reset_kit_pad : OK")


# ---------------------------------------------------------------------------
# synth_ready
# ---------------------------------------------------------------------------

def test_synth_ready_false_when_none():
    router, _, _ = _make_router()
    assert not router.synth_ready()
    print("  synth_ready (None) : OK")


def test_synth_ready_false_when_not_loaded():
    router, _, _ = _make_router()
    router._synth = FakeSynthEngine()   # _loaded = False
    assert not router.synth_ready()
    print("  synth_ready (non chargé) : OK")


def test_synth_ready_true_when_loaded():
    router, _, _ = _make_router()
    fake = FakeSynthEngine()
    fake._loaded = True
    router._synth = fake
    assert router.synth_ready()
    print("  synth_ready (chargé) : OK")


# ---------------------------------------------------------------------------
# on_play
# ---------------------------------------------------------------------------

def test_on_play_kit_dispatches_to_sound_manager():
    router, snd, _ = _make_router()
    router._track_slots[0] = 0   # KIT
    router.on_play(0, 3, 0.8, 10)
    assert snd.played == [(3, 0.8, 10)]
    print("  on_play KIT → SoundManager : OK")


def test_on_play_synth_uses_committed_engine():
    router, snd, _ = _make_router()
    fake = FakeSynthEngine()
    fake._loaded = True
    router._slot_synths[1] = fake
    router._track_slots[0] = 1   # piste 0 → slot 1 SYNTH
    router.on_play(0, 0, 1.0, 0)
    expected_midi = router.kb_notes[0]
    assert len(fake._played) == 1
    assert fake._played[0][0] == expected_midi
    assert snd.played == [], "SoundManager ne doit pas être appelé pour SYNTH"
    print("  on_play SYNTH → moteur commis : OK")


def test_on_play_synth_silent_when_not_committed():
    """Pas de moteur commis → silence, pas de crash."""
    router, snd, _ = _make_router()
    router._track_slots[0] = 1   # SYNTH mais pas dans _slot_synths
    router.on_play(0, 0, 1.0, 0)
    assert snd.played == []
    print("  on_play SYNTH non commis → silence : OK")


def test_on_play_synth_silent_when_not_loaded():
    router, snd, _ = _make_router()
    fake = FakeSynthEngine()    # _loaded = False
    router._slot_synths[1] = fake
    router._track_slots[0] = 1
    router.on_play(0, 0, 1.0, 0)
    assert fake._played == []
    print("  on_play SYNTH non chargé → silence : OK")


def test_on_play_two_synth_tracks_independent():
    """Deux pistes SYNTH avec des moteurs différents jouent leurs propres notes."""
    router, snd, _ = _make_router()
    fake1 = FakeSynthEngine(); fake1._loaded = True
    fake2 = FakeSynthEngine(); fake2._loaded = True
    router._slot_synths[1] = fake1
    router._slot_synths[2] = fake2
    router._track_slots[0] = 1
    router._track_slots[1] = 2
    router.on_play(0, 0, 1.0, 0)
    router.on_play(1, 0, 1.0, 0)
    assert len(fake1._played) == 1
    assert len(fake2._played) == 1
    assert fake1._played[0][0] == router.kb_notes[0]
    assert fake2._played[0][0] == router.kb_notes[0]
    print("  on_play deux pistes SYNTH indépendantes : OK")


# ---------------------------------------------------------------------------
# play_kit_pitched
# ---------------------------------------------------------------------------

@patch("track_router.SynthEngine", FakeSynthEngine)
def test_play_kit_pitched_no_wav_path_noop():
    router, _, _ = _make_router()
    called = []
    router.play_kit_pitched(0, 0, None, lambda p: called.append(p))
    assert called == []
    assert router._kit_synth is None
    print("  play_kit_pitched (wav_path vide) : OK")


@patch("track_router.SynthEngine", FakeSynthEngine)
def test_play_kit_pitched_new_pad_calls_fallback():
    """Premier appel sur un pad → fallback immédiat + début de chargement."""
    router, _, _ = _make_router()
    called = []
    router.play_kit_pitched(0, 3, "/fake/3.wav", lambda p: called.append(p))
    assert called == [3], "Le fallback doit être appelé immédiatement"
    assert router._kb_kit_pad == 3
    assert router._kit_synth is not None
    print("  play_kit_pitched nouveau pad → fallback : OK")


@patch("track_router.SynthEngine", FakeSynthEngine)
def test_play_kit_pitched_same_pad_loaded_plays_midi():
    """Même pad déjà chargé → joue la note MIDI et met à jour kb_last_midi."""
    router, _, _ = _make_router()
    fake_kit       = FakeSynthEngine()
    fake_kit._loaded = True
    router._kit_synth  = fake_kit
    router._kb_kit_pad = 2   # même pad que l'appel suivant
    router.play_kit_pitched(0, 2, "/fake/2.wav", lambda p: None)
    expected_midi = router.kb_notes[0]   # note_idx=0
    assert len(fake_kit._played) == 1
    assert fake_kit._played[0][0] == expected_midi
    assert router.kb_last_midi == expected_midi
    print("  play_kit_pitched même pad chargé → note MIDI + kb_last_midi : OK")


@patch("track_router.SynthEngine", FakeSynthEngine)
def test_play_kit_pitched_same_pad_not_loaded_fallback():
    """Même pad mais kit non chargé → fallback sans jouer de note MIDI."""
    router, _, _ = _make_router()
    fake_kit       = FakeSynthEngine()   # _loaded = False
    router._kit_synth  = fake_kit
    router._kb_kit_pad = 5
    called = []
    router.play_kit_pitched(1, 5, "/fake/5.wav", lambda p: called.append(p))
    assert called == [5]
    assert fake_kit._played == []
    print("  play_kit_pitched même pad non chargé → fallback : OK")


@patch("track_router.SynthEngine", FakeSynthEngine)
def test_play_kit_pitched_new_pad_resets_kit_pad():
    """Jouer un pad différent du précédent réinitialise _kb_kit_pad."""
    router, _, _ = _make_router()
    router._kb_kit_pad = 1
    fake_kit       = FakeSynthEngine()
    fake_kit._loaded = True
    router._kit_synth = fake_kit
    called = []
    router.play_kit_pitched(0, 4, "/fake/4.wav", lambda p: called.append(p))
    assert router._kb_kit_pad == 4
    assert called == [4], "Nouveau pad → fallback"
    print("  play_kit_pitched changement de pad → reset + fallback : OK")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_track_router ===")
    test_initial_state()
    test_update_kb_notes_major()
    test_update_kb_notes_minor()
    test_precompute_async_noop_when_no_synth()
    test_precompute_async_noop_when_not_loaded()
    test_slot_for_track_defaults_to_zero()
    test_slot_name_follows_track_slots()
    test_assign_slot_kit_no_synth_created()
    test_assign_slot_synth_anchors_loaded_preview()
    test_assign_slot_synth_creates_engine_when_preview_absent()
    test_assign_slot_synth_idempotent()
    test_assign_slot_updates_track_slots()
    test_load_slot_preview_kit_is_noop()
    test_load_slot_preview_reuses_committed_engine()
    test_load_slot_preview_creates_preview_engine()
    test_load_slot_preview_does_not_clobber_committed()
    test_load_slot_preview_replaces_stale_committed_synth()
    test_reset_kit_pad()
    test_synth_ready_false_when_none()
    test_synth_ready_false_when_not_loaded()
    test_synth_ready_true_when_loaded()
    test_on_play_kit_dispatches_to_sound_manager()
    test_on_play_synth_uses_committed_engine()
    test_on_play_synth_silent_when_not_committed()
    test_on_play_synth_silent_when_not_loaded()
    test_on_play_two_synth_tracks_independent()
    test_play_kit_pitched_no_wav_path_noop()
    test_play_kit_pitched_new_pad_calls_fallback()
    test_play_kit_pitched_same_pad_loaded_plays_midi()
    test_play_kit_pitched_same_pad_not_loaded_fallback()
    test_play_kit_pitched_new_pad_resets_kit_pad()
    print("Tous les tests : OK")
