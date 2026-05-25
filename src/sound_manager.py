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
        self.media_lst = media_lst
        self.drum_sounds = []

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

        Retourne (labels, wav_paths) — deux listes de 16 éléments.
        Les pads sans fichier ou avec fichier manquant reçoivent un son silencieux.
        """
        json_path = os.path.abspath(json_path)
        json_dir  = os.path.dirname(json_path)
        with open(json_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        pad_map = {p["pad"]: p for p in meta.get("pads", [])}

        labels    = []
        wav_paths = []
        new_sounds = []

        for i in range(1, 17):
            entry    = pad_map.get(i, {})
            label    = entry.get("label", f"Pad {i:02d}")
            filename = entry.get("filename", "")
            if filename:
                wav_path = os.path.normpath(os.path.join(json_dir, filename))
            else:
                wav_path = ""
            labels.append(label)
            wav_paths.append(wav_path)
            if wav_path and os.path.exists(wav_path):
                new_sounds.append(pygame.mixer.Sound(wav_path))
            else:
                new_sounds.append(self._silent_sound())

        self.drum_sounds = new_sounds
        self.media_lst   = wav_paths
        self._kit_name   = meta.get("name", "")
        return labels, wav_paths

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
