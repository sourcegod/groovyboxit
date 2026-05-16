#python3
"""
    File: synth_engine.py
    Moteur Synthé : chargement de patch, pitch shifting (pyrubberband),
    gestion des gammes, cache par note MIDI, lecture via pygame.
    Date: Fri, 16/05/2026
    Author: Coolbrother
"""
import os
import json
import numpy as np
import soundfile as sf
import pyrubberband as rb
import pygame


# ======================================================================
# Gammes disponibles (intervalles en demi-tons depuis la tonique)
# ======================================================================

SCALES = {
    "chromatic":        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    "major":            [0, 2, 4, 5, 7, 9, 11],
    "minor":            [0, 2, 3, 5, 7, 8, 10],
    "pentatonic_major": [0, 2, 4, 7, 9],
    "pentatonic_minor": [0, 3, 5, 7, 10],
}

SCALE_NAMES = list(SCALES.keys())   # ordre canonique pour / et *

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
    à la note demandée par pitch shifting (pyrubberband) et les met en
    cache comme pygame.Sound pour une lecture sans latence.
    """

    def __init__(self, synths_dir):
        self._synths_dir  = synths_dir
        self._patch_name  = None
        self._patch_meta  = {}
        self._samples     = []    # [{"root_midi", "data", "sr", "path"}]
        self._cache       = {}    # {midi_note: pygame.Sound}
        self._loop        = False
        self._mixer_freq  = None  # fréquence du mixer pygame (vérifiée au 1er usage)

    # ------------------------------------------------------------------
    # Chargement de patch
    # ------------------------------------------------------------------

    def load_patch(self, patch_name):
        """Charge synths/<patch_name>/patch.json et les WAVs associés."""
        patch_dir = os.path.join(self._synths_dir, patch_name)
        json_path = os.path.join(patch_dir, "patch.json")

        with open(json_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        self._patch_name = patch_name
        self._patch_meta = meta
        self._loop       = meta.get("loop", False)
        self._samples    = []
        self._cache      = {}

        for s in meta.get("samples", []):
            wav_path = os.path.join(patch_dir, s["file"])
            data, sr = sf.read(wav_path, dtype="float64", always_2d=False)
            root_midi = note_name_to_midi(s["root"])
            self._samples.append({"root_midi": root_midi, "data": data, "sr": sr, "path": wav_path})

        # Tri par note racine pour accès plus lisible
        self._samples.sort(key=lambda s: s["root_midi"])

    # ------------------------------------------------------------------
    # Génération et cache
    # ------------------------------------------------------------------

    def _find_nearest_sample(self, midi_note):
        """Sample dont la note racine est la plus proche de midi_note."""
        if not self._samples:
            return None
        return min(self._samples, key=lambda s: abs(s["root_midi"] - midi_note))

    def _to_pygame_sound(self, data, sr):
        """Convertit un tableau numpy float64 en pygame.Sound 16-bit stéréo."""
        # Vérification (une seule fois) de la cohérence avec le mixer
        if self._mixer_freq is None:
            self._mixer_freq, _, _ = pygame.mixer.get_init()

        # Rééchantillonnage si le WAV n'est pas à la fréquence du mixer
        if sr != self._mixer_freq and self._mixer_freq:
            ratio = self._mixer_freq / sr
            n_out = max(1, round(len(data) * ratio))
            if data.ndim == 1:
                data = np.interp(
                    np.linspace(0, len(data) - 1, n_out),
                    np.arange(len(data)),
                    data,
                )
            else:
                data = np.column_stack([
                    np.interp(np.linspace(0, len(data) - 1, n_out),
                              np.arange(len(data)), data[:, ch])
                    for ch in range(data.shape[1])
                ])

        # Normalisation douce
        peak = np.max(np.abs(data))
        if peak > 0:
            data = data / peak * 0.9

        arr = (data * 32767).clip(-32768, 32767).astype(np.int16)

        # Forcer stéréo (pygame attend 2 canaux par défaut)
        if arr.ndim == 1:
            arr = np.column_stack([arr, arr])
        elif arr.shape[1] == 1:
            arr = np.column_stack([arr[:, 0], arr[:, 0]])
        elif arr.shape[1] > 2:
            arr = arr[:, :2]

        return pygame.sndarray.make_sound(np.ascontiguousarray(arr))

    def _build_sound(self, midi_note):
        """Crée et met en cache le pygame.Sound pour midi_note."""
        sample = self._find_nearest_sample(midi_note)
        if sample is None:
            return None
        n_steps = midi_note - sample["root_midi"]
        data    = rb.pitch_shift(sample["data"], sample["sr"], n_steps=n_steps) \
                  if n_steps != 0 else sample["data"]
        sound = self._to_pygame_sound(data, sample["sr"])
        self._cache[midi_note] = sound
        return sound

    def get_sound(self, midi_note):
        """Retourne le pygame.Sound pour midi_note (cache ou calcul à la volée)."""
        return self._cache.get(midi_note) or self._build_sound(midi_note)

    def precompute(self, midi_notes):
        """Pré-calcule et met en cache une liste de notes MIDI."""
        for note in midi_notes:
            if note not in self._cache:
                self._build_sound(note)

    def clear_cache(self):
        self._cache = {}

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    def play(self, midi_note, volume_factor=1.0, pan=0):
        """Joue midi_note. Retourne le channel pygame ou None."""
        sound = self.get_sound(midi_note)
        if sound is None:
            return None
        loops   = -1 if self._loop else 0
        channel = sound.play(loops)
        if channel is not None and (volume_factor != 1.0 or pan != 0):
            pan_norm = pan / 100.0
            left  = volume_factor * (1.0 - max(0.0, pan_norm))
            right = volume_factor * (1.0 + min(0.0, pan_norm))
            channel.set_volume(left, right)
        return channel

    def stop(self, midi_note):
        """Arrête la note (utile pour les instruments en loop/sustain)."""
        sound = self._cache.get(midi_note)
        if sound:
            sound.stop()

    # ------------------------------------------------------------------
    # Informations
    # ------------------------------------------------------------------

    def is_loaded(self):
        return bool(self._samples)

    def __repr__(self):
        cached = len(self._cache)
        return f"SynthEngine(patch={self._patch_name!r}, samples={len(self._samples)}, cached={cached})"


#=========================================

if __name__ == "__main__":
    # Test sans patch réel : vérifier les utilitaires note/gamme
    assert note_name_to_midi("C4")  == 60   # 12*(4+1)+0
    assert note_name_to_midi("G#3") == 56   # 12*(3+1)+8
    assert note_name_to_midi("Bb2") == 46   # Bb2=A#2 : 12*(2+1)+10
    assert note_name_to_midi("Db4") == 61   # Db4=C#4 : 12*(4+1)+1
    assert midi_to_note_name(60) == "C4"
    print("note_name_to_midi / midi_to_note_name : OK")

    notes_major = scale_midi_notes("major", 48, 16)  # C3
    print("Gamme majeure C3 (16 notes) :", [midi_to_note_name(n) for n in notes_major])

    notes_penta = scale_midi_notes("pentatonic_minor", 48, 16)
    print("Pentatonique mineure C3 :", [midi_to_note_name(n) for n in notes_penta])

    input("OK")
