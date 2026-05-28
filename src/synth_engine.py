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
from audio_tools import AudioTools


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
    à la note demandée par pitch shifting (pyrubberband) et les met en
    cache comme pygame.Sound pour une lecture sans latence.
    """

    SUSTAIN_SECONDS = 8    # durée max du buffer de sustain pré-rendu

    def __init__(self, synths_dir, driver=None):
        if driver is None:
            from pygame_driver import PygameDriver
            driver = PygameDriver()
        self._driver      = driver
        self._synths_dir  = synths_dir
        self._patch_name  = None
        self._patch_meta  = {}
        self._samples     = []    # [{"root_midi","data","sr","path","loop_start","loop_end"}]
        self._raw_cache   = {}    # {midi_note: (data, sr)} — pitch-shifté, pleine durée
        self._cache       = {}    # {(midi_note, duration_ms): sound}
        self._loop        = False

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
        self._loop       = meta.get("loop", False)
        self._samples    = []
        self._raw_cache  = {}
        self._cache      = {}

        sounds         = meta.get("sounds", meta.get("samples", []))
        top_loop_start = meta.get("loop_start")
        top_loop_end   = meta.get("loop_end")

        for s in sounds:
            filename   = s.get("filename", s.get("file", ""))
            rootnote   = s.get("rootnote", s.get("root", "C4"))
            wav_path   = os.path.normpath(os.path.join(json_dir, filename))
            data, sr   = sf.read(wav_path, dtype="float64", always_2d=False)
            root_midi  = note_name_to_midi(rootnote)
            loop_start = s.get("loop_start", top_loop_start)
            loop_end   = s.get("loop_end",   top_loop_end)
            self._samples.append({
                "root_midi":  root_midi,
                "data":       data,
                "sr":         sr,
                "path":       wav_path,
                "loop_start": loop_start,
                "loop_end":   loop_end,
            })

        self._samples.sort(key=lambda s: s["root_midi"])

    def load_single_sample(self, wav_path, root_midi=60):
        """Charge un WAV unique comme patch mono-sample (sans patch.json).
        Utilisé pour le mode Keyboard/Kit : pitcher un pad de batterie."""
        data, sr = sf.read(wav_path, dtype="float64", always_2d=False)
        self._patch_name = os.path.basename(wav_path)
        self._patch_meta = {}
        self._loop       = False
        self._raw_cache  = {}
        self._cache      = {}
        self._samples    = [{
            "root_midi":  root_midi,
            "data":       data,
            "sr":         sr,
            "path":       wav_path,
            "loop_start": None,
            "loop_end":   None,
        }]

    # ------------------------------------------------------------------
    # Génération et cache
    # ------------------------------------------------------------------

    def _find_nearest_sample(self, midi_note):
        """Sample dont la note racine est la plus proche de midi_note."""
        if not self._samples:
            return None
        return min(self._samples, key=lambda s: abs(s["root_midi"] - midi_note))

    def _make_sound(self, data, sr):
        """Délègue la création du son (numpy → sound object) au driver."""
        return self._driver.make_sound_from_array(data, sr)

    def _build_looped_data(self, data, sr, loop_start, loop_end):
        """
        Construit un buffer sustain : [0 → loop_end] + [loop_start → loop_end] × N.

        On inclut l'échantillon loop_end lui-même (passage à zéro montant) dans
        la région de boucle, de sorte que loop_region[-1] ≈ 0 comme loop_region[0].
        La jonction est ainsi zero→zero : pas de discontinuité, pas de clic.
        """
        n   = len(data)
        ls  = min(loop_start, n - 1)
        le  = min(loop_end + 1, n)    # +1 : inclure l'échantillon au passage à zéro
        if le <= ls:
            return data
        attack      = data[:le]
        loop_region = data[ls:le]
        loop_len    = len(loop_region)
        if loop_len == 0:
            return attack
        target    = int(self.SUSTAIN_SECONDS * sr)
        remaining = target - len(attack)
        if remaining <= 0:
            return attack

        n_rep     = max(1, (remaining + loop_len - 1) // loop_len)
        sustained = np.concatenate([attack] + [loop_region] * n_rep)[:target].copy()

        # Fadeout sur les 300 ms finaux pour éviter la coupure abrupte
        fade_samples = min(int(0.3 * sr), len(sustained) // 8)
        if fade_samples > 1:
            fade = np.linspace(1.0, 0.0, fade_samples)
            if data.ndim > 1:
                fade = fade[:, np.newaxis]
            sustained[-fade_samples:] *= fade

        return sustained

    FADEOUT_MS = 50   # durée du fondu final appliqué aux données (ms)

    def _get_raw(self, midi_note):
        """Retourne (data, sr) pitch-shifté pour midi_note, avec cache."""
        if midi_note in self._raw_cache:
            return self._raw_cache[midi_note]
        sample = self._find_nearest_sample(midi_note)
        if sample is None:
            return None, None
        n_steps = midi_note - sample["root_midi"]
        data    = rb.pitch_shift(sample["data"], sample["sr"], n_steps=n_steps) \
                  if n_steps != 0 else sample["data"]
        if self._loop \
                and sample["loop_start"] is not None \
                and sample["loop_end"]   is not None:
            ls, le = AudioTools.snap_loop_to_zero_crossings(
                data, sample["loop_start"], sample["loop_end"]
            )
            data = self._build_looped_data(data, sample["sr"], ls, le)
        self._raw_cache[midi_note] = (data, sample["sr"])
        return data, sample["sr"]

    def _apply_duration(self, data, sr, duration_ms):
        """Tronque data à duration_ms ms et applique un fadeout final."""
        n_total   = int(duration_ms / 1000.0 * sr)
        n_fadeout = min(int(self.FADEOUT_MS / 1000.0 * sr), max(1, n_total // 4))
        out = data[:n_total].copy() if len(data) > n_total else data.copy()
        if n_fadeout > 1:
            fade = np.linspace(1.0, 0.0, n_fadeout)
            if out.ndim > 1:
                fade = fade[:, np.newaxis]
            out[-n_fadeout:] *= fade
        return out

    def _build_sound(self, midi_note, duration_ms):
        """Crée et met en cache le pygame.Sound pour (midi_note, duration_ms)."""
        data, sr = self._get_raw(midi_note)
        if data is None:
            return None
        trimmed = self._apply_duration(data, sr, duration_ms) \
                  if duration_ms > 0 else data
        sound = self._make_sound(trimmed, sr)
        self._cache[(midi_note, duration_ms)] = sound
        return sound

    def get_sound(self, midi_note, duration_ms=500):
        """Retourne le pygame.Sound pour (midi_note, duration_ms), avec cache."""
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
        """Arrête la note sustain (utile pour les instruments en loop)."""
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
