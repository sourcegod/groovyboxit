#python3
"""
    File: tests/test_midi_constants.py
    Tests unitaires de midi_constants :
    tailles des tables (CC_NAMES, GM_PATCH_NAMES, GM2_DRUMKIT_NAMES) et
    quelques valeurs connues.
    Date: Mon, 21/09/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import midi_constants as mc


# ---------------------------------------------------------------------------
# CC_NAMES
# ---------------------------------------------------------------------------

def test_cc_names_known_values():
    assert mc.CC_NAMES[1] == "Modulation Wheel"
    assert mc.CC_NAMES[7] == "Channel Volume"
    assert mc.CC_NAMES[10] == "Pan"
    assert mc.CC_NAMES[64] == "Sustain Pedal"
    assert mc.CC_NAMES[120] == "All Sound Off"
    assert mc.CC_NAMES[123] == "All Notes Off"


def test_cc_names_unlisted_cc_absent():
    # CC#3, 9, 14, 15 : réservés/non définis en MIDI 1.0, absents de la table.
    assert 3 not in mc.CC_NAMES
    assert 9 not in mc.CC_NAMES


def test_cc_names_keys_in_range():
    assert all(0 <= cc <= 127 for cc in mc.CC_NAMES)


# ---------------------------------------------------------------------------
# GM_PATCH_NAMES
# ---------------------------------------------------------------------------

def test_gm_patch_names_size():
    assert len(mc.GM_PATCH_NAMES) == 128


def test_gm_patch_names_known_values():
    assert mc.GM_PATCH_NAMES[0] == "Acoustic Grand Piano"
    assert mc.GM_PATCH_NAMES[24] == "Acoustic Guitar (nylon)"
    assert mc.GM_PATCH_NAMES[40] == "Violin"
    assert mc.GM_PATCH_NAMES[56] == "Trumpet"
    assert mc.GM_PATCH_NAMES[127] == "Gunshot"


def test_gm_patch_names_all_strings():
    assert all(isinstance(name, str) and name for name in mc.GM_PATCH_NAMES)


# ---------------------------------------------------------------------------
# GM2_DRUMKIT_NAMES
# ---------------------------------------------------------------------------

def test_gm2_drumkit_names_size():
    assert len(mc.GM2_DRUMKIT_NAMES) == 128


def test_gm2_drumkit_names_known_kits():
    assert mc.GM2_DRUMKIT_NAMES[0] == "Standard Kit"
    assert mc.GM2_DRUMKIT_NAMES[8] == "Room Kit"
    assert mc.GM2_DRUMKIT_NAMES[16] == "Power Kit"
    assert mc.GM2_DRUMKIT_NAMES[24] == "Electronic Kit"
    assert mc.GM2_DRUMKIT_NAMES[25] == "TR-808 Kit"
    assert mc.GM2_DRUMKIT_NAMES[32] == "Jazz Kit"
    assert mc.GM2_DRUMKIT_NAMES[40] == "Brush Kit"
    assert mc.GM2_DRUMKIT_NAMES[48] == "Orchestra Kit"
    assert mc.GM2_DRUMKIT_NAMES[56] == "SFX Kit"


def test_gm2_drumkit_names_unnamed_index_is_int_itself():
    # Program numbers sans kit GM2 standard : l'entrée reste l'entier lui-même.
    assert mc.GM2_DRUMKIT_NAMES[1] == 1
    assert mc.GM2_DRUMKIT_NAMES[63] == 63
    assert mc.GM2_DRUMKIT_NAMES[127] == 127
