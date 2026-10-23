#python3
"""
    File: tests/test_midi_constants.py
    Tests unitaires de midi_constants :
    tailles des tables (CC_NAMES, GM_PATCH_NAMES, GM2_DRUMKIT_NAMES) et
    quelques valeurs connues ; noms des percussions GM et note GM devinée
    d'après le libellé d'un son de kit (Phase 7 étape 11c1, docs/DESIGN.md
    § 11a1 D3).
    Date: Mon, 21/09/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

import midi.midi_constants as mc


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


# ---------------------------------------------------------------------------
# GM_DRUM_NAMES (Phase 7 étape 11c1)
# ---------------------------------------------------------------------------

def test_gm_drum_names_range():
    assert mc.GM_DRUM_FIRST == 35
    assert mc.GM_DRUM_LAST == 81
    assert len(mc.GM_DRUM_NAMES) == 81 - 35 + 1


def test_gm_drum_names_known_values():
    def name(note):
        return mc.GM_DRUM_NAMES[note - mc.GM_DRUM_FIRST]
    assert name(35) == "Acoustic Bass Drum"
    assert name(36) == "Bass Drum 1"
    assert name(42) == "Closed Hi-Hat"
    assert name(44) == "Pedal Hi-Hat"
    assert name(46) == "Open Hi-Hat"
    assert name(49) == "Crash Cymbal 1"
    assert name(56) == "Cowbell"
    assert name(81) == "Open Triangle"


def test_gm_drum_names_unique_strings():
    assert all(isinstance(n, str) and n for n in mc.GM_DRUM_NAMES)
    assert len(set(mc.GM_DRUM_NAMES)) == len(mc.GM_DRUM_NAMES)


# ---------------------------------------------------------------------------
# _drum_words : normalisation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label", ["Hi-Hat", "hi hat", "HiHat", "hihat", "HH"])
def test_drum_words_hihat_variants_fused(label):
    assert mc._drum_words(label) == {"hihat"}


def test_drum_words_hi_alone_means_high():
    # « Hi » hors de « Hi-Hat » vise « High » : Hi Mid Tom ≈ High Mid Tom
    assert mc._drum_words("Hi Mid Tom") == {"high", "mid", "tom"}
    assert mc._drum_words("Closed Hi-Hat") == {"closed", "hihat"}


@pytest.mark.parametrize("label, words", [
    ("Kick",    {"bass", "drum"}),
    ("BD",      {"bass", "drum"}),
    ("Rimshot", {"side", "stick"}),
    ("Rim",     {"side", "stick"}),
    ("Clap",    {"hand", "clap"}),
    ("Tamb",    {"tambourine"}),
    ("Tom Med", {"tom", "mid"}),
    ("SD",      {"snare"}),
    ("Cym",     {"cymbal"}),
    ("CB",      {"cowbell"}),
])
def test_drum_words_synonyms(label, words):
    assert mc._drum_words(label) == words


def test_drum_words_digits_and_separators_ignored():
    assert mc._drum_words("Snare_2") == {"snare"}
    assert mc._drum_words("Crash Cymbal 1") == {"crash", "cymbal"}


def test_drum_words_camel_case_split():
    assert mc._drum_words("BassDrum1") == {"bass", "drum"}


# ---------------------------------------------------------------------------
# guess_gm_drum_note
# ---------------------------------------------------------------------------

# Tableau de docs/DESIGN.md § 11a1 D3 : kit TR-707 (note du kit, libellé,
# note GM attendue).
TR_707 = [
    (35, "Kick 2",     35), (36, "Kick 1",    36), (37, "Rimshot",    37),
    (38, "Snare 1",    38), (39, "Hand Clap", 39), (40, "Snare 2",    40),
    (41, "Tom Low",    41), (42, "HH Closed", 42), (43, "Tom Mid",    47),
    (44, "HH Open",    46), (45, "Tom Hi",    50), (46, "Crash",      49),
    (47, "Ride",       51), (48, "Tambourine", 54), (49, "Cowbell",   56),
]


@pytest.mark.parametrize("kit_note, label, gm", TR_707)
def test_guess_tr_707(kit_note, label, gm):
    assert mc.guess_gm_drum_note(label, kit_note) == gm


def test_guess_tr_707_notes_distinct():
    gms = [mc.guess_gm_drum_note(label, kn) for kn, label, _ in TR_707]
    assert len(set(gms)) == len(gms)


def test_guess_gm_names_are_fixed_points():
    # Un kit déjà GM, libellés = noms GM : chaque note reste en place.
    for i, name in enumerate(mc.GM_DRUM_NAMES):
        note = mc.GM_DRUM_FIRST + i
        assert mc.guess_gm_drum_note(name, note) == note, name


def test_guess_kit_note_bonus_breaks_tie():
    # « Snare » : Acoustic Snare (38) et Electric Snare (40) à égalité
    assert mc.guess_gm_drum_note("Snare", 40) == 40
    assert mc.guess_gm_drum_note("Snare", 38) == 38


def test_guess_tie_without_kit_note_gives_lowest():
    assert mc.guess_gm_drum_note("Snare") == 38
    assert mc.guess_gm_drum_note("Crash") == 49
    assert mc.guess_gm_drum_note("Ride") == 51


def test_guess_shared_words_beat_kit_note_bonus():
    # HH Open sur la note 44 (Pedal Hi-Hat, un seul mot commun) : Open Hi-Hat
    # (deux mots communs) l'emporte malgré le bonus.
    assert mc.guess_gm_drum_note("HH Open", 44) == 46


def test_guess_fewer_extra_words_wins():
    # « Tom Hi » : High Tom (50) sans mot en trop, devant High Floor Tom (43)
    # et Hi-Mid Tom (48)
    assert mc.guess_gm_drum_note("Tom Hi") == 50


def test_guess_kit_note_outside_gm_range():
    assert mc.guess_gm_drum_note("Cowbell", 100) == 56


@pytest.mark.parametrize("label", ["Zap", "---", "", None, "123"])
def test_guess_unknown_label_is_none(label):
    assert mc.guess_gm_drum_note(label, 49) is None


def test_guess_result_in_gm_range():
    for label in ("Kick", "Clap", "Conga", "Whistle", "Triangle", "Agogo"):
        assert mc.GM_DRUM_FIRST <= mc.guess_gm_drum_note(label) <= mc.GM_DRUM_LAST
