#python3
"""
    File: synth_engine.py
    Moteur Synthé : chargement de patch, pitch shifting, cache par note MIDI,
    lecture via SoundDeviceDriver.
    Boucle, crossfade et ADSR délégués à AudioSampler.
    Date: Fri, 16/05/2026
    Author: Coolbrother
"""
import os
import json
import numpy as np
from audio_sampler import AudioSampler, PlayMode


# ======================================================================
# Gammes disponibles (intervalles en demi-tons depuis la tonique)
# ======================================================================

SCALES = {
    "chromatic":        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    "major":            [0, 2, 4, 5, 7, 9, 11],
    "minor_nat":        [0, 2, 3, 5, 7, 8, 10],   # mineure naturelle
    "minor_harm_1":     [0, 2, 3, 5, 7, 8, 11],   # mineure harmonique (7e maj)
    "pentatonic_major": [0, 2, 4, 7, 9],
    "pentatonic_minor": [0, 3, 5, 7, 10],
}

SCALE_NAMES = list(SCALES.keys())   # ordre canonique pour / et *

# Étiquettes d'affichage pour la listbox (même ordre que SCALE_NAMES)
SCALE_LABELS = [
    "Scale_01 - Chromatic",
    "Scale_02 - Major",
    "Scale_03 - Minor Nat",
    "Scale_04 - Minor Harm 1",
    "Scale_05 - Pentatonic Major",
    "Scale_06 - Pentatonic Minor",
]

# Noms de notes (dièses uniquement, bémols normalisés à l'entrée)
_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_FLAT_MAP   = {"Db": "C#", "Eb": "D#", "Fb": "E", "Gb": "F#",
               "Ab": "G#", "Bb": "A#", "Cb": "B"}


# ======================================================================
# Utilitaires notes MIDI ↔ noms
# ======================================================================

def note_name_to_midi(name):
    """'C4' → 60, 'G#3' → 56, 'Bb2' → 34.  Convention : C4 = 60."""
    name = name.strip()
    for flat, sharp in _FLAT_MAP.items():
        if name.startswith(flat):
            name = sharp + name[len(flat):]
            break
    if len(name) >= 3 and name[1] == "#":
        note, octave = name[:2], int(name[2:])
    else:
        note, octave = name[0], int(name[1:])
    return 12 * (octave + 1) + _NOTE_NAMES.index(note)


def midi_to_note_name(midi):
    """60 → 'C4'."""
    octave = (midi // 12) - 1
    return f"{_NOTE_NAMES[midi % 12]}{octave}"


def scale_midi_notes(scale_name, root_midi, count=16):
    """Retourne 'count' notes MIDI consécutives de la gamme à partir de root_midi."""
    intervals = SCALES.get(scale_name, SCALES["chromatic"])
    n = len(intervals)
    return [root_midi + (i // n) * 12 + intervals[i % n] for i in range(count)]


# ======================================================================
# SynthEngine
# ======================================================================

class SynthEngine:
    """
    Charge un patch (répertoire de WAVs + patch.json), génère les sons
    à la note demandée par pitch shifting et les met en cache comme SdSound
    pour une lecture sans latence via SoundDeviceDriver.

    Boucle, crossfade FluidSynth-style et ADSR sont délégués à AudioSampler.
    """

    def __init__(self, synths_dir, driver=None):
        if driver is None:
            from sound_device_driver import SoundDeviceDriver
            driver = SoundDeviceDriver()
        self._driver      = driver
        self._synths_dir  = synths_dir
        self._patch_name  = None
        self._patch_meta  = {}
        self._samples     = []   # [{"root_midi", "sampler", "path"}]
        self._raw_cache   = {}   # {midi_note: AudioSampler} — pitch-shifté
        self._cache       = {}   # {(midi_note, duration_ms): SdSound}

    # ------------------------------------------------------------------
    # Chargement de patch
    # ------------------------------------------------------------------

    def load_patch(self, patch_ref):
        """Charge un patch depuis un nom de dossier ou un chemin JSON complet.

        Formats supportés (avec fallback rétrocompatible) :
          Nouveau : "sounds" / "filename" / "rootnote", loop_start/loop_end top-level
          Ancien  : "samples" / "file" / "root", loop_start/loop_end par sample

        Les chemins WAV sont résolus relativement au fichier JSON.
        """
        if os.path.isabs(patch_ref) or patch_ref.endswith(".json"):
            json_path = patch_ref
        else:
            patch_dir = os.path.join(self._synths_dir, patch_ref)
            json_path = os.path.join(patch_dir, "patch.json")

        json_path = os.path.abspath(json_path)
        json_dir  = os.path.dirname(json_path)

        with open(json_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        self._patch_name = meta.get("name", os.path.splitext(os.path.basename(json_path))[0])
        self._patch_meta = meta
        self._samples    = []
        self._raw_cache  = {}
        self._cache      = {}

        loop           = meta.get("loop", False)
        sounds         = meta.get("sounds", meta.get("samples", []))
        top_loop_start = meta.get("loop_start")
        top_loop_end   = meta.get("loop_end")

        for s in sounds:
            filename  = s.get("filename", s.get("file", ""))
            rootnote  = s.get("rootnote", s.get("root", "C4"))
            wav_path  = os.path.normpath(os.path.join(json_dir, filename))
            root_midi = note_name_to_midi(rootnote)

            sampler    = AudioSampler.from_file(wav_path)
            loop_start = s.get("loop_start", top_loop_start)
            loop_end   = s.get("loop_end",   top_loop_end)

            if loop and loop_start is not None and loop_end is not None:
                # loop_start/loop_end stockés en samples dans le JSON
                sr = sampler.samplerate
                sampler.set_mode(PlayMode.LOOP)
                sampler.set_loop(float(loop_start) / sr, float(loop_end) / sr)
            else:
                sampler.set_mode(PlayMode.ONESHOT)

            self._samples.append({
                "root_midi": root_midi,
                "sampler":   sampler,
                "path":      wav_path,
            })

        self._samples.sort(key=lambda s: s["root_midi"])

    def load_single_sample(self, wav_path, root_midi=60):
        """Charge un WAV unique comme patch mono-sample (sans patch.json).
        Utilisé pour le mode Keyboard/Kit : pitcher un pad de batterie."""
        sampler = AudioSampler.from_file(wav_path)
        sampler.set_mode(PlayMode.ONESHOT)
        self._patch_name = os.path.basename(wav_path)
        self._patch_meta = {}
        self._raw_cache  = {}
        self._cache      = {}
        self._samples    = [{"root_midi": root_midi, "sampler": sampler, "path": wav_path}]

    # ------------------------------------------------------------------
    # Génération et cache
    # ------------------------------------------------------------------

    def _find_nearest_sample(self, midi_note):
        """Entrée dont la note racine est la plus proche de midi_note."""
        if not self._samples:
            return None
        return min(self._samples, key=lambda s: abs(s["root_midi"] - midi_note))

    def _make_sound(self, data, sr):
        """Délègue la création du son (numpy → SdSound) au driver."""
        return self._driver.make_sound_from_array(data, sr)

    def _get_pitched_sampler(self, midi_note):
        """Retourne l'AudioSampler pitch-shifté pour midi_note, avec cache."""
        if midi_note in self._raw_cache:
            return self._raw_cache[midi_note]
        entry = self._find_nearest_sample(midi_note)
        if entry is None:
            return None
        n_steps = midi_note - entry["root_midi"]
        pitched = entry["sampler"].pitch_shift(n_steps)
        self._raw_cache[midi_note] = pitched
        return pitched

    def _build_sound(self, midi_note, duration_ms):
        """Crée et met en cache le son pour (midi_note, duration_ms)."""
        sampler = self._get_pitched_sampler(midi_note)
        if sampler is None:
            return None
        data  = sampler.render(duration_ms)
        sound = self._make_sound(data, sampler.samplerate)
        self._cache[(midi_note, duration_ms)] = sound
        return sound

    def get_sound(self, midi_note, duration_ms=500):
        """Retourne le son pour (midi_note, duration_ms), avec cache."""
        key = (midi_note, duration_ms)
        return self._cache.get(key) or self._build_sound(midi_note, duration_ms)

    def precompute(self, midi_notes, duration_ms=500):
        """Pré-calcule et met en cache une liste de notes MIDI."""
        for note in midi_notes:
            if (note, duration_ms) not in self._cache:
                self._build_sound(note, duration_ms)

    def clear_cache(self):
        self._raw_cache = {}
        self._cache     = {}

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    def play(self, midi_note, volume_factor=1.0, pan=0, maxtime_ms=500):
        """Joue midi_note. maxtime_ms=0 → durée complète du WAV."""
        sound = self.get_sound(midi_note, maxtime_ms)
        if sound is None:
            return
        self._driver.play(sound, volume_factor, pan)

    def stop(self, midi_note):
        """Arrête la note sustain (utile pour les instruments en loop/gate)."""
        sound = self._cache.get((midi_note, 0))
        if sound:
            self._driver.stop_sound(sound)

    # ------------------------------------------------------------------
    # Informations
    # ------------------------------------------------------------------

    def is_loaded(self):
        return bool(self._samples)

    def __repr__(self):
        return (f"SynthEngine(patch={self._patch_name!r}, "
                f"samples={len(self._samples)}, cached={len(self._cache)})")


#=========================================

if __name__ == "__main__":
    assert note_name_to_midi("C4")  == 60
    assert note_name_to_midi("G#3") == 56
    assert note_name_to_midi("Bb2") == 46
    assert note_name_to_midi("Db4") == 61
    assert midi_to_note_name(60) == "C4"
    print("note_name_to_midi / midi_to_note_name : OK")

    notes_major = scale_midi_notes("major", 48, 16)
    print("Gamme majeure C3 (16 notes) :", [midi_to_note_name(n) for n in notes_major])

    notes_penta = scale_midi_notes("pentatonic_minor", 48, 16)
    print("Pentatonique mineure C3 :", [midi_to_note_name(n) for n in notes_penta])

    input("OK")
