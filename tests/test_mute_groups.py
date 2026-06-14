#python3
"""
    File: tests/test_mute_groups.py
    Tests unitaires — groupes mute exclusif (Phase 5 étape 4)
    Couvre : Voice.mute_group, VoiceManager get/set/reset/sérialisation,
             DrumPlayer._play_kit_sound (logique d'exclusion de groupe).
    Date: Mon, 15/06/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from voice_manager import Voice, VoiceManager
from drum_player import DrumPlayer


# ---------------------------------------------------------------------------
# Mock SoundManager
# ---------------------------------------------------------------------------

class MockSoundManager:
    """Enregistre les appels play_sound / stop_sound_by_pad pour assertions."""

    def __init__(self, num_pads=16):
        self.played   = []   # liste de pad_idx joués
        self.stopped  = []   # liste de pad_idx stoppés
        self.drum_sounds = [object() for _ in range(num_pads)]

    def play_sound(self, pad_idx, vol=1.0, pan=0):
        self.played.append(pad_idx)

    def stop_sound_by_pad(self, pad_idx):
        self.stopped.append(pad_idx)

    def reset(self):
        self.played.clear()
        self.stopped.clear()


def make_player(num_pads=16):
    snd = MockSoundManager(num_pads)
    dp  = DrumPlayer(sound_manager=snd)
    return dp, snd


def ok(msg):
    print(f"  {msg} : OK")


# ---------------------------------------------------------------------------
# Voice.mute_group — valeurs initiales
# ---------------------------------------------------------------------------

def test_voice_mute_group_default_zero():
    v = Voice()
    assert v.mute_group == 0
    ok("Voice().mute_group == 0 (défaut)")


# ---------------------------------------------------------------------------
# VoiceManager — get_mute_group / set_mute_group
# ---------------------------------------------------------------------------

def test_get_mute_group_default():
    vm = VoiceManager()
    assert vm.get_mute_group(0) == 0
    ok("get_mute_group(0) == 0 (défaut)")

def test_set_mute_group_basic():
    vm = VoiceManager()
    vm.set_mute_group(0, 3)
    assert vm.get_mute_group(0) == 3
    ok("set_mute_group(0, 3) → get_mute_group(0) == 3")

def test_set_mute_group_negative_clamped_to_zero():
    vm = VoiceManager()
    vm.set_mute_group(1, -5)
    assert vm.get_mute_group(1) == 0
    ok("set_mute_group(1, -5) → clampé à 0")

def test_set_mute_group_pads_independent():
    vm = VoiceManager()
    vm.set_mute_group(0, 1)
    vm.set_mute_group(1, 2)
    assert vm.get_mute_group(0) == 1
    assert vm.get_mute_group(1) == 2
    ok("set_mute_group : pads indépendants")

def test_set_mute_group_does_not_affect_others():
    vm = VoiceManager()
    vm.set_mute_group(5, 3)
    for i in range(16):
        if i != 5:
            assert vm.get_mute_group(i) == 0, f"pad {i} devrait être 0"
    ok("set_mute_group(5, 3) ne modifie pas les autres pads")


# ---------------------------------------------------------------------------
# VoiceManager — reset / reset_pad
# ---------------------------------------------------------------------------

def test_reset_clears_mute_group():
    vm = VoiceManager()
    vm.set_mute_group(0, 2)
    vm.reset()
    assert vm.get_mute_group(0) == 0
    ok("reset() remet mute_group à 0")

def test_reset_clears_all_mute_groups():
    vm = VoiceManager()
    for i in range(16):
        vm.set_mute_group(i, i % 4 + 1)
    vm.reset()
    for i in range(16):
        assert vm.get_mute_group(i) == 0, f"pad {i} non remis à 0 après reset()"
    ok("reset() efface mute_group de tous les pads")

def test_reset_pad_clears_mute_group():
    vm = VoiceManager()
    vm.set_mute_group(3, 1)
    vm.reset_pad(3)
    assert vm.get_mute_group(3) == 0
    ok("reset_pad(3) remet mute_group à 0")

def test_reset_pad_does_not_affect_others():
    vm = VoiceManager()
    vm.set_mute_group(0, 1)
    vm.set_mute_group(1, 1)
    vm.reset_pad(0)
    assert vm.get_mute_group(0) == 0
    assert vm.get_mute_group(1) == 1
    ok("reset_pad(0) ne touche pas le mute_group du pad 1")


# ---------------------------------------------------------------------------
# VoiceManager — sérialisation to_list / from_list
# ---------------------------------------------------------------------------

def test_to_list_contains_mute_group():
    vm = VoiceManager()
    lst = vm.to_list()
    assert "mute_group" in lst[0]
    ok('to_list()[0] contient la clé "mute_group"')

def test_to_list_preserves_mute_group():
    vm = VoiceManager()
    vm.set_mute_group(2, 5)
    lst = vm.to_list()
    assert lst[2]["mute_group"] == 5
    ok('to_list()[2]["mute_group"] == 5')

def test_from_list_restores_mute_group():
    vm = VoiceManager()
    data = [{"name": "", "volume": 100, "pan": 0, "mute": False,
             "solo": False, "duration_ms": 500, "mute_group": 7}] + \
           [{"name": "", "volume": 100, "pan": 0, "mute": False,
             "solo": False, "duration_ms": 500}] * 15
    vm.from_list(data)
    assert vm.get_mute_group(0) == 7
    ok("from_list() restaure mute_group == 7")

def test_from_list_missing_mute_group_defaults_zero():
    vm = VoiceManager()
    vm.set_mute_group(0, 3)
    data = [{"name": "", "volume": 100, "pan": 0, "mute": False,
             "solo": False, "duration_ms": 500}] * 16
    vm.from_list(data)
    assert vm.get_mute_group(0) == 0
    ok("from_list() sans clé mute_group → 0 (rétrocompat)")

def test_roundtrip_mute_group():
    vm1 = VoiceManager()
    for i in range(16):
        vm1.set_mute_group(i, i % 5)
    vm2 = VoiceManager()
    vm2.from_list(vm1.to_list())
    for i in range(16):
        assert vm2.get_mute_group(i) == i % 5, f"pad {i} différent"
    ok("to_list() → from_list() : aller-retour fidèle pour mute_group")


# ---------------------------------------------------------------------------
# DrumPlayer._play_kit_sound — logique mute exclusif
# ---------------------------------------------------------------------------

def test_play_kit_sound_no_group_no_stop():
    dp, snd = make_player()
    dp._play_kit_sound(0, 1.0, 0)
    assert 0 in snd.played
    assert snd.stopped == []
    ok("_play_kit_sound sans groupe → aucun stop")

def test_play_kit_sound_group_stops_peer():
    dp, snd = make_player()
    dp.voice_manager.set_mute_group(0, 1)
    dp.voice_manager.set_mute_group(1, 1)
    dp._play_kit_sound(0, 1.0, 0)
    assert 1 in snd.stopped
    assert 0 not in snd.stopped   # ne se stoppe pas lui-même
    ok("_play_kit_sound groupe 1 → stoppe le pair (pad 1)")

def test_play_kit_sound_group_plays_after_stop():
    dp, snd = make_player()
    dp.voice_manager.set_mute_group(2, 2)
    dp.voice_manager.set_mute_group(3, 2)
    dp._play_kit_sound(2, 0.8, 0)
    assert snd.stopped == [3]
    assert snd.played  == [2]
    ok("_play_kit_sound : stop peer avant play (ordre correct)")

def test_play_kit_sound_group_stops_all_peers():
    dp, snd = make_player()
    for i in [0, 1, 2, 3]:
        dp.voice_manager.set_mute_group(i, 1)
    dp._play_kit_sound(0, 1.0, 0)
    assert set(snd.stopped) == {1, 2, 3}
    assert 0 not in snd.stopped
    ok("_play_kit_sound groupe 1 avec 4 pads → stoppe les 3 pairs")

def test_play_kit_sound_different_groups_not_stopped():
    dp, snd = make_player()
    dp.voice_manager.set_mute_group(0, 1)
    dp.voice_manager.set_mute_group(1, 2)   # groupe différent
    dp._play_kit_sound(0, 1.0, 0)
    assert snd.stopped == []   # pad 1 (groupe 2) ne doit pas être stoppé
    ok("_play_kit_sound : groupes différents → pas d'exclusion")

def test_play_kit_sound_group_zero_no_stop():
    dp, snd = make_player()
    dp.voice_manager.set_mute_group(0, 0)
    dp.voice_manager.set_mute_group(1, 0)
    dp._play_kit_sound(0, 1.0, 0)
    assert snd.stopped == []
    ok("_play_kit_sound groupe 0 → aucun stop (groupe neutre)")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        # Voice
        test_voice_mute_group_default_zero,
        # VoiceManager get/set
        test_get_mute_group_default,
        test_set_mute_group_basic,
        test_set_mute_group_negative_clamped_to_zero,
        test_set_mute_group_pads_independent,
        test_set_mute_group_does_not_affect_others,
        # reset
        test_reset_clears_mute_group,
        test_reset_clears_all_mute_groups,
        test_reset_pad_clears_mute_group,
        test_reset_pad_does_not_affect_others,
        # sérialisation
        test_to_list_contains_mute_group,
        test_to_list_preserves_mute_group,
        test_from_list_restores_mute_group,
        test_from_list_missing_mute_group_defaults_zero,
        test_roundtrip_mute_group,
        # DrumPlayer._play_kit_sound
        test_play_kit_sound_no_group_no_stop,
        test_play_kit_sound_group_stops_peer,
        test_play_kit_sound_group_plays_after_stop,
        test_play_kit_sound_group_stops_all_peers,
        test_play_kit_sound_different_groups_not_stopped,
        test_play_kit_sound_group_zero_no_stop,
    ]

    print("=== test_mute_groups ===")
    failed = []
    for t in tests:
        try:
            t()
        except Exception as e:
            import traceback
            print(f"  ÉCHEC {t.__name__}: {e}")
            traceback.print_exc()
            failed.append(t.__name__)

    print("Tous les tests : OK" if not failed else f"{len(failed)} ÉCHEC(S) : {failed}")
