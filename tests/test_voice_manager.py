#python3
"""
    File: tests/test_voice_manager.py
    Tests unitaires de VoiceManager — champ name :
    valeurs initiales, get/set, reset, reset_pad, indépendance des pads,
    sérialisation to_list/from_list (avec et sans clé "name").
    Date: Thu, 22/05/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from voice_manager import Voice, VoiceManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_vm(num_pads=16):
    return VoiceManager(num_pads)


def ok(msg):
    print(f"  {msg} : OK")


# ---------------------------------------------------------------------------
# Voice — valeurs initiales
# ---------------------------------------------------------------------------

def test_voice_name_default():
    v = Voice()
    assert v.name == ""
    ok('Voice().name == ""')

def test_voice_name_is_str():
    v = Voice()
    assert isinstance(v.name, str)
    ok("Voice().name est une str")


# ---------------------------------------------------------------------------
# get_name / set_name
# ---------------------------------------------------------------------------

def test_get_name_default():
    vm = make_vm()
    assert vm.get_name(0) == ""
    ok('get_name(0) == "" (défaut)')

def test_set_name_basic():
    vm = make_vm()
    vm.set_name(0, "Caisse")
    assert vm.get_name(0) == "Caisse"
    ok('set_name(0, "Caisse") → get_name(0) == "Caisse"')

def test_set_name_converts_to_str():
    vm = make_vm()
    vm.set_name(3, 42)
    assert vm.get_name(3) == "42"
    ok("set_name(3, 42) → get_name(3) == \"42\" (conversion str)")

def test_set_name_empty_string():
    vm = make_vm()
    vm.set_name(0, "Grosse caisse")
    vm.set_name(0, "")
    assert vm.get_name(0) == ""
    ok('set_name(0, "") efface le nom')

def test_set_name_last_pad():
    vm = make_vm()
    vm.set_name(15, "Cymbale")
    assert vm.get_name(15) == "Cymbale"
    ok('set_name(15, "Cymbale") → get_name(15) == "Cymbale"')


# ---------------------------------------------------------------------------
# Indépendance des pads
# ---------------------------------------------------------------------------

def test_names_independent():
    vm = make_vm()
    vm.set_name(0, "Caisse")
    vm.set_name(1, "Charley")
    assert vm.get_name(0) == "Caisse"
    assert vm.get_name(1) == "Charley"
    ok("Les noms des pads sont indépendants")

def test_set_name_does_not_affect_other_pads():
    vm = make_vm()
    vm.set_name(5, "Rimshot")
    for i in range(16):
        if i != 5:
            assert vm.get_name(i) == "", f"pad {i} devrait être vide"
    ok("set_name(5) ne modifie pas les autres pads")


# ---------------------------------------------------------------------------
# reset() — tous les pads
# ---------------------------------------------------------------------------

def test_reset_clears_name():
    vm = make_vm()
    vm.set_name(0, "Caisse")
    vm.reset()
    assert vm.get_name(0) == ""
    ok('reset() remet name à ""')

def test_reset_clears_all_names():
    vm = make_vm()
    for i in range(16):
        vm.set_name(i, f"Pad{i+1}")
    vm.reset()
    for i in range(16):
        assert vm.get_name(i) == "", f"pad {i} non effacé après reset()"
    ok("reset() efface les noms de tous les pads")

def test_reset_preserves_other_fields():
    vm = make_vm()
    vm.set_name(0, "Caisse")
    vm.set_volume(0, 80)
    vm.reset()
    assert vm.get_name(0) == ""
    assert vm._voices[0].volume == 100
    ok("reset() remet name ET volume à leurs valeurs par défaut")


# ---------------------------------------------------------------------------
# reset_pad() — un seul pad
# ---------------------------------------------------------------------------

def test_reset_pad_clears_name():
    vm = make_vm()
    vm.set_name(2, "Tom")
    vm.reset_pad(2)
    assert vm.get_name(2) == ""
    ok('reset_pad(2) remet name à ""')

def test_reset_pad_does_not_affect_others():
    vm = make_vm()
    vm.set_name(0, "Caisse")
    vm.set_name(1, "Charley")
    vm.reset_pad(0)
    assert vm.get_name(0) == ""
    assert vm.get_name(1) == "Charley"
    ok("reset_pad(0) ne touche pas le pad 1")


# ---------------------------------------------------------------------------
# to_list() — sérialisation
# ---------------------------------------------------------------------------

def test_to_list_contains_name_key():
    vm = make_vm()
    lst = vm.to_list()
    assert "name" in lst[0]
    ok('to_list()[0] contient la clé "name"')

def test_to_list_name_default_empty():
    vm = make_vm()
    lst = vm.to_list()
    assert lst[0]["name"] == ""
    ok('to_list()[0]["name"] == "" (défaut)')

def test_to_list_preserves_name():
    vm = make_vm()
    vm.set_name(3, "Clap")
    lst = vm.to_list()
    assert lst[3]["name"] == "Clap"
    ok('to_list()[3]["name"] == "Clap"')

def test_to_list_all_pads_have_name():
    vm = make_vm()
    for i in range(16):
        vm.set_name(i, f"Son{i}")
    lst = vm.to_list()
    for i in range(16):
        assert lst[i]["name"] == f"Son{i}", f"pad {i} incorrect"
    ok("to_list() contient les noms de tous les pads")


# ---------------------------------------------------------------------------
# from_list() — désérialisation
# ---------------------------------------------------------------------------

def test_from_list_restores_name():
    vm = make_vm()
    data = [{"name": "Caisse", "volume": 100, "pan": 0,
             "mute": False, "solo": False, "duration_ms": 500}] + \
           [{"volume": 100, "pan": 0, "mute": False, "solo": False, "duration_ms": 500}] * 15
    vm.from_list(data)
    assert vm.get_name(0) == "Caisse"
    ok('from_list() restaure name == "Caisse"')

def test_from_list_missing_name_defaults_empty():
    vm = make_vm()
    vm.set_name(0, "Ancien nom")
    data = [{"volume": 80, "pan": 0, "mute": False, "solo": False, "duration_ms": 500}] * 16
    vm.from_list(data)
    assert vm.get_name(0) == ""
    ok('from_list() sans clé "name" → "" (rétrocompat)')

def test_from_list_converts_name_to_str():
    vm = make_vm()
    data = [{"name": 99, "volume": 100, "pan": 0,
             "mute": False, "solo": False, "duration_ms": 500}] + \
           [{"volume": 100, "pan": 0, "mute": False, "solo": False, "duration_ms": 500}] * 15
    vm.from_list(data)
    assert vm.get_name(0) == "99"
    ok('from_list() convertit name entier → "99"')

def test_from_list_roundtrip():
    vm1 = make_vm()
    for i in range(16):
        vm1.set_name(i, f"Instrument{i+1}")
    vm2 = make_vm()
    vm2.from_list(vm1.to_list())
    for i in range(16):
        assert vm2.get_name(i) == f"Instrument{i+1}", f"pad {i} différent"
    ok("to_list() → from_list() : aller-retour fidèle pour tous les noms")

def test_from_list_shorter_data_ignored():
    vm = make_vm()
    vm.set_name(5, "Initial")
    data = [{"name": "Nouveau", "volume": 100, "pan": 0,
             "mute": False, "solo": False, "duration_ms": 500}]
    vm.from_list(data)
    assert vm.get_name(0) == "Nouveau"
    assert vm.get_name(5) == "Initial"
    ok("from_list() avec 1 élément ne touche pas les pads 1..15")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_voice_name_default,
        test_voice_name_is_str,
        test_get_name_default,
        test_set_name_basic,
        test_set_name_converts_to_str,
        test_set_name_empty_string,
        test_set_name_last_pad,
        test_names_independent,
        test_set_name_does_not_affect_other_pads,
        test_reset_clears_name,
        test_reset_clears_all_names,
        test_reset_preserves_other_fields,
        test_reset_pad_clears_name,
        test_reset_pad_does_not_affect_others,
        test_to_list_contains_name_key,
        test_to_list_name_default_empty,
        test_to_list_preserves_name,
        test_to_list_all_pads_have_name,
        test_from_list_restores_name,
        test_from_list_missing_name_defaults_empty,
        test_from_list_converts_name_to_str,
        test_from_list_roundtrip,
        test_from_list_shorter_data_ignored,
    ]

    print("=== test_voice_manager ===")
    failed = []
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"  ÉCHEC {t.__name__}: {e}")
            failed.append(t.__name__)

    print("Tous les tests : OK" if not failed else f"{len(failed)} ÉCHEC(S) : {failed}")
