#python3
"""
    File: test_synth_utils.py
    Test des utilitaires SynthEngine sans patch réel :
    conversions notes MIDI ↔ noms, génération de gammes.
    Date: Fri, 16/05/2026
    Author: Coolbrother
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from synth_engine import (
    note_name_to_midi, midi_to_note_name,
    scale_midi_notes, SCALE_NAMES,
)


def test_note_name_to_midi():
    assert note_name_to_midi("C4")  == 60,  "C4 doit être 60"
    assert note_name_to_midi("G#3") == 56,  "G#3 doit être 56"
    assert note_name_to_midi("Bb2") == 46,  "Bb2 (=A#2) doit être 46"
    assert note_name_to_midi("Db4") == 61,  "Db4 (=C#4) doit être 61"
    assert note_name_to_midi("C0")  == 12,  "C0 doit être 12"
    assert note_name_to_midi("B8")  == 119, "B8 doit être 119"
    print("  note_name_to_midi : OK")


def test_midi_to_note_name():
    assert midi_to_note_name(60) == "C4"
    assert midi_to_note_name(56) == "G#3"
    assert midi_to_note_name(46) == "A#2"
    assert midi_to_note_name(12) == "C0"
    print("  midi_to_note_name : OK")


def test_round_trip():
    for midi in range(21, 109):   # A0 → C8 (plage piano)
        assert note_name_to_midi(midi_to_note_name(midi)) == midi, \
            f"Aller-retour échoué pour MIDI {midi}"
    print("  round-trip midi ↔ nom (88 notes) : OK")


def test_scale_notes():
    # Gamme majeure de C3 (MIDI 48) : 16 notes
    notes = scale_midi_notes("major", 48, 16)
    assert len(notes) == 16
    # Les 8 premières : C D E F G A B C (octave suivante)
    expected_names = ["C3", "D3", "E3", "F3", "G3", "A3", "B3", "C4",
                      "D4", "E4", "F4", "G4", "A4", "B4", "C5", "D5"]
    actual_names   = [midi_to_note_name(n) for n in notes]
    assert actual_names == expected_names, f"Majeure C3 : {actual_names}"
    print("  gamme majeure C3 (16 notes) : OK")

    # Chromatique : 12 notes consécutives puis octave suivante
    notes_chrom = scale_midi_notes("chromatic", 48, 12)
    assert notes_chrom == list(range(48, 60))
    print("  gamme chromatique : OK")

    # Pentatonique mineure
    notes_pm = scale_midi_notes("pentatonic_minor", 48, 5)
    assert [midi_to_note_name(n) for n in notes_pm] == ["C3", "D#3", "F3", "G3", "A#3"]
    print("  pentatonique mineure C3 : OK")


def test_all_scale_names():
    for name in SCALE_NAMES:
        notes = scale_midi_notes(name, 60, 16)
        assert len(notes) == 16
        assert notes[0] == 60
    print(f"  toutes les gammes ({len(SCALE_NAMES)}) : OK")


if __name__ == "__main__":
    print("=== test_synth_utils ===")
    test_note_name_to_midi()
    test_midi_to_note_name()
    test_round_trip()
    test_scale_notes()
    test_all_scale_names()
    print("Tous les tests : OK")
