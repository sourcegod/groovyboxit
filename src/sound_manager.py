#python3
"""
    File: soundmanager.py
    Sound manager from pygame
    Date: Sat, 05/04/2025
    Author: Coolbrother
"""
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

    def play_sound(self, index):
         self.drum_sounds[index].play()

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
