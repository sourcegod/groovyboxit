#python3
"""
    File: soundmanager.py
    Sound manager from pygame
    Date: Sat, 05/04/2025
    Author: Coolbrother
"""
import os
import json
import numpy as np
import pygame

class SoundManager(object):
    """ Sound manager """
    def __init__(self, media_lst, click_name1, click_name2):
        pygame.init()
        self.media_lst   = media_lst
        self.drum_sounds = []
        self.note_map    = {}   # {midi_note: pygame.Sound} — tous les sons du kit
        self.kit_base    = 36  # première note du kit (note MIDI)
        self.kit_offset  = 0   # décalage courant en demi-tons (multiples de 8)

        # Load metronome sounds
        self.sound_click1 = pygame.mixer.Sound(click_name1)
        self.sound_click2 = pygame.mixer.Sound(click_name2)


    #----------------------------------------

    def load_sounds(self):
        self.drum_sounds = [
                pygame.mixer.Sound(item)
                for item in self.media_lst
        ]

    #----------------------------------------

    def _silent_sound(self):
        """Son silencieux (1 échantillon stéréo) pour pad sans fichier."""
        arr = np.zeros((2, 2), dtype=np.int16)
        return pygame.sndarray.make_sound(arr)

    def load_kit(self, json_path):
        """Charge un kit depuis un fichier JSON.

        Chaque entrée peut avoir :
          "pad"      (1-16) → son assigné au Numpad
          "note"     (MIDI) → son déclenché par note MIDI (note_map)
          "filename" et "label"

        Retourne (labels, wav_paths) — deux listes de 16 éléments (pads Numpad).
        Construit aussi self.note_map {midi_note: Sound} pour le routage MIDI.
        """
        json_path = os.path.abspath(json_path)
        json_dir  = os.path.dirname(json_path)
        with open(json_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        # Cache son par chemin WAV pour éviter de charger deux fois le même fichier
        sound_cache = {}

        def _load_sound(filename):
            if not filename:
                return None, ""
            wav_path = os.path.normpath(os.path.join(json_dir, filename))
            if not os.path.exists(wav_path):
                return None, wav_path
            if wav_path not in sound_cache:
                sound_cache[wav_path] = pygame.mixer.Sound(wav_path)
            return sound_cache[wav_path], wav_path

        pad_map = {p["pad"]: p for p in meta.get("pads", []) if "pad" in p}

        # ── Pads Numpad (1-16) ──────────────────────────────────────────
        labels     = []
        wav_paths  = []
        new_sounds = []
        for i in range(1, 17):
            entry    = pad_map.get(i, {})
            label    = entry.get("label", f"Pad {i:02d}")
            sound, wav_path = _load_sound(entry.get("filename", ""))
            labels.append(label)
            wav_paths.append(wav_path)
            new_sounds.append(sound if sound else self._silent_sound())

        self.drum_sounds = new_sounds
        self.media_lst   = wav_paths

        # ── note_map + note_labels : tous les sons avec "note" (MIDI) ────
        self.note_map    = {}
        self.note_labels = {}
        for entry in meta.get("pads", []):
            note = entry.get("note")
            if note is None:
                continue
            label = entry.get("label", f"Note {note}")
            sound, _ = _load_sound(entry.get("filename", ""))
            if sound:
                self.note_map[note]    = sound
                self.note_labels[note] = label

        self._kit_name  = meta.get("name", "")
        self.kit_base   = meta.get("base_note", 36)
        self.kit_offset = 0
        return labels, wav_paths

    #----------------------------------------

    def shift_kit(self, delta):
        """Décale la fenêtre de 16 pads de delta demi-tons.
        Retourne la liste des 16 nouveaux labels.
        """
        notes = sorted(self.note_map.keys())
        if not notes:
            return [f"Pad {i:02d}" for i in range(1, 17)]
        min_note = notes[0]
        max_note = notes[-1]
        new_offset = self.kit_offset + delta
        # Bornes : la fenêtre [base+offset, base+offset+15] doit rester dans [min, max]
        new_offset = max(min_note - self.kit_base, new_offset)
        new_offset = min(max_note - self.kit_base - 15, new_offset)
        self.kit_offset = new_offset
        return self._rebuild_drum_sounds()

    def _rebuild_drum_sounds(self):
        """Reconstruit drum_sounds[16] à partir de note_map selon kit_base+kit_offset."""
        labels = []
        for i in range(16):
            note  = self.kit_base + self.kit_offset + i
            sound = self.note_map.get(note)
            self.drum_sounds[i] = sound if sound else self._silent_sound()
            labels.append(self.note_labels.get(note, f"Note {note}"))
        return labels

    #----------------------------------------

    def play_note(self, midi_note, volume_factor=1.0, pan=0):
        """Joue un son par note MIDI (utilise note_map)."""
        sound = self.note_map.get(midi_note)
        if sound is None:
            return
        channel = sound.play()
        if channel is not None and (volume_factor != 1.0 or pan != 0):
            pan_norm = pan / 100.0
            left  = volume_factor * (1.0 - max(0.0, pan_norm))
            right = volume_factor * (1.0 + min(0.0, pan_norm))
            channel.set_volume(left, right)

    #----------------------------------------

    def play_sound(self, index, volume_factor=1.0, pan=0):
        channel = self.drum_sounds[index].play()
        if channel is not None and (volume_factor != 1.0 or pan != 0):
            pan_norm = pan / 100.0
            left  = volume_factor * (1.0 - max(0.0, pan_norm))
            right = volume_factor * (1.0 + min(0.0, pan_norm))
            channel.set_volume(left, right)

    #----------------------------------------
     
    def preview_sound(self, sound_name):
        if sound_name in self.drum_sounds:
            self.play_sound(sound_name)

    #----------------------------------------

    def play_metronome(self, beat_counter):
        """Joue le son du métronome."""
        if beat_counter == 0:
            self.sound_click1.play()
        else:
            self.sound_click2.play()

    #----------------------------------------
 
    def stop_all(self):
        pygame.mixer.stop()

    #----------------------------------------

    def set_volume(self, volume):
        for sound in self.drum_sounds:
            sound.set_volume(volume / 100)
        self.sound_click1.set_volume(volume / 100)
        self.sound_click2.set_volume(volume / 100)

    #----------------------------------------

#=========================================

if __name__ == "__main__":
    input("It's OK...")
#----------------------------------------
