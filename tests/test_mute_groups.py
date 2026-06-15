#python3
"""
    File: tests/test_mute_groups.py
    Tests unitaires — groupes mute exclusif (Phase 5 étape 4)
    Couvre : Voice.mute_group, VoiceManager get/set/reset/sérialisation,
             SoundManager._apply_mute_group (play_sound et play_note).
    Date: Mon, 15/06/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from voice_manager import Voice, VoiceManager
from sound_manager import SoundManager


# ---------------------------------------------------------------------------
# MockDriver et helpers SoundManager
# ---------------------------------------------------------------------------

class _S:
    """Sentinelle imitant un SdSound sans audio réel."""
    pass


class MockDriver:
    def __init__(self):
        self.played  = []   # objets son joués
        self.stopped = []   # objets son stoppés

    def load(self, path):           return _S()
    def make_silent(self):          return _S()
    def play(self, sound, vol=1.0, pan=0, **kw):
        self.played.append(sound)
    def stop_sound(self, sound):
        self.stopped.append(sound)
    def stop_all(self):             pass
    def set_master_volume(self, v): pass
    def set_sound_volume(self, s, v): pass

    def reset(self):
        self.played.clear()
        self.stopped.clear()


def make_sm(group_map=None):
    """Crée un SoundManager minimal avec groupes pré-configurés (sans kit JSON).

    group_map : {pad_idx: group_id} pour les drum_sounds
    Retourne (sm, driver, sounds[16]).
    """
    driver = MockDriver()
    sm = SoundManager.__new__(SoundManager)
    sm._driver        = driver
    sm._sound_group   = {}
    sm._group_sounds  = {}
    sm.mute_groups    = [0] * 16
    sm.note_map       = {}
    sm.note_labels    = {}
    sm._kit_name      = ""
    sm.kit_base       = 36
    sm.kit_offset     = 0
    sm.media_lst      = []
    sounds = [_S() for _ in range(16)]
    sm.drum_sounds = sounds
    for pad_idx, group in (group_map or {}).items():
        sound = sounds[pad_idx]
        sm._sound_group[id(sound)]  = group
        sm._group_sounds.setdefault(group, set()).add(sound)
        sm.mute_groups[pad_idx]     = group
    return sm, driver, sounds


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
# SoundManager._apply_mute_group — via play_sound (pads)
# ---------------------------------------------------------------------------

def test_play_sound_no_group_no_stop():
    sm, drv, sounds = make_sm()
    sm.play_sound(0, 1.0, 0)
    assert sounds[0] in drv.played
    assert drv.stopped == []
    ok("play_sound sans groupe → aucun stop")

def test_play_sound_group_stops_peer():
    sm, drv, sounds = make_sm({0: 1, 1: 1})
    sm.play_sound(0, 1.0, 0)
    assert sounds[1] in drv.stopped
    assert sounds[0] not in drv.stopped
    ok("play_sound groupe 1 → stoppe le pair (pad 1)")

def test_play_sound_group_plays_after_stop():
    sm, drv, sounds = make_sm({2: 2, 3: 2})
    sm.play_sound(2, 0.8, 0)
    assert drv.stopped == [sounds[3]]
    assert drv.played  == [sounds[2]]
    ok("play_sound : stop peer avant play (ordre correct)")

def test_play_sound_group_stops_all_peers():
    sm, drv, sounds = make_sm({0: 1, 1: 1, 2: 1, 3: 1})
    sm.play_sound(0, 1.0, 0)
    assert set(drv.stopped) == {sounds[1], sounds[2], sounds[3]}
    assert sounds[0] not in drv.stopped
    ok("play_sound groupe 1 avec 4 pads → stoppe les 3 pairs")

def test_play_sound_different_groups_not_stopped():
    sm, drv, sounds = make_sm({0: 1, 1: 2})
    sm.play_sound(0, 1.0, 0)
    assert drv.stopped == []
    ok("play_sound : groupes différents → pas d'exclusion")

def test_play_sound_group_zero_no_stop():
    sm, drv, sounds = make_sm({0: 0, 1: 0})
    sm.play_sound(0, 1.0, 0)
    assert drv.stopped == []
    ok("play_sound groupe 0 → aucun stop (groupe neutre)")


# ---------------------------------------------------------------------------
# SoundManager._apply_mute_group — via play_note (MIDI live)
# ---------------------------------------------------------------------------

def test_play_note_no_group_no_stop():
    sm, drv, sounds = make_sm()
    note_sound = _S()
    sm.note_map[42] = note_sound
    sm.play_note(42, 1.0)
    assert note_sound in drv.played
    assert drv.stopped == []
    ok("play_note sans groupe → aucun stop")

def test_play_note_group_stops_peer():
    sm, drv, sounds = make_sm()
    s42, s44 = _S(), _S()
    sm.note_map = {42: s42, 44: s44}
    sm._sound_group  = {id(s42): 1, id(s44): 1}
    sm._group_sounds = {1: {s42, s44}}
    sm.play_note(42, 1.0)
    assert s44 in drv.stopped
    assert s42 not in drv.stopped
    ok("play_note groupe 1 → stoppe le pair (note 44)")

def test_play_note_shared_sound_stops_pad_voice():
    """Un même SdSound partagé entre note_map et drum_sounds :
    play_note doit stopper la voix quelle que soit son origine."""
    sm, drv, sounds = make_sm()
    shared = sounds[7]               # pad 7 et note 42 partagent le même objet
    sm.note_map[42] = shared
    sm.note_map[44] = sounds[9]
    sm._sound_group  = {id(shared): 1, id(sounds[9]): 1}
    sm._group_sounds = {1: {shared, sounds[9]}}
    sm.play_note(42, 1.0)            # déclenche note 42 → doit stopper note 44 (sons[9])
    assert sounds[9] in drv.stopped
    assert shared not in drv.stopped
    ok("play_note : son partagé pad/note → peer stoppé correctement")


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
        # SoundManager.play_sound
        test_play_sound_no_group_no_stop,
        test_play_sound_group_stops_peer,
        test_play_sound_group_plays_after_stop,
        test_play_sound_group_stops_all_peers,
        test_play_sound_different_groups_not_stopped,
        test_play_sound_group_zero_no_stop,
        # SoundManager.play_note
        test_play_note_no_group_no_stop,
        test_play_note_group_stops_peer,
        test_play_note_shared_sound_stops_pad_voice,
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
