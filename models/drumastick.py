#!/usr/bin/python3
"""
    File: drumastick.py
    Mini Drum Machine for test
    Date: Mon, 31/03/2025
    Author: Coolbrother
"""

import os
import time
import curses
import threading
from soundmanager import SoundManager
DEBUG = 1
curdir = os.path.dirname(__file__) # directory for the current script
_basedir = os.path.dirname(curdir) # base directory for the application
_mediadir = os.path.join(_basedir, "media")
_medialist = [os.path.join(_mediadir, f"{i}.wav") for i in range(1, 17)]
_clickname1 = os.path.join(_mediadir, "hi_wood_block_mono.wav")
_clickname2 = os.path.join(_mediadir, "low_wood_block_mono.wav")

# Mappage des touches du clavier aux pads
key_mapping_1 = {
    ord('q'): 0, ord('s'): 1, ord('d'): 2, ord('f'): 3,
    ord('g'): 4, ord('h'): 5, ord('j'): 6, ord('k'): 7,
    ord('a'): 8, ord('z'): 9, ord('e'): 10, ord('r'): 11,
    ord('t'): 12, ord('y'): 13, ord('u'): 14, ord('i'): 15
}

# Mappage des touches du clavier en majuscule aux pads
key_mapping_2 = {
    ord('Q'): 0, ord('S'): 1, ord('D'): 2, ord('F'): 3,
    ord('G'): 4, ord('H'): 5, ord('J'): 6, ord('K'): 7,
    ord('A'): 8, ord('Z'): 9, ord('E'): 10, ord('R'): 11,
    ord('T'): 12, ord('Y'): 13, ord('U'): 14, ord('I'): 15
}


# Motif rythmique (True si le pad est activé, False sinon)
pattern = [[False] * 16 for _ in range(16)]

# Motif prédéfini pattern_01
pattern_01 = [[False] * 16 for _ in range(16)]
pattern_01[0][0] = True  # 1.1
pattern_01[0][4] = True  # 1.5
pattern_01[0][8] = True  # 1.9
pattern_01[0][12] = True  # 1.13
pattern_01[4][2] = True  # 5.3
pattern_01[4][6] = True  # 5.7
pattern_01[4][10] = True  # 5.11
pattern_01[5][1:4] = [True] * 3  # 6.2-4
pattern_01[5][5:8] = [True] * 3  # 6.6-8
pattern_01[5][9:12] = [True] * 3  # 6.10-12
pattern_01[5][13:16] = [True] * 3  # 6.14-16
pattern_01[7][15] = True  # 8.16
pattern_01[8][14] = True  # 9.15
pattern_01[9][13] = True  # 10.14
pattern_01[10][0] = True  # 11.1

def debug(msg="", title="", bell=True):
    if DEBUG:
        print("%s: %s" % (title, msg))
        if bell:
            print("\a")

#------------------------------------------------------------------------------

def beep():
    curses.beep()

#------------------------------------------------------------------------------

class DrumPlayer(object):
    """ Manage the player in a thread """
    def __init__(self, sound_manager=None, ui_app=None):
        self._play_thread = None
        self.stop_event = threading.Event()
        self.sound_man = sound_manager
        self.ui_app = ui_app
        self.playing = False
        self.clicking = False
        self.bpm = 100
        self.current_step =0
        self.step_duration = 60.0 / self.bpm / 4
        self.beat_counter =0
        self.cycle_counter =0
        self.volume = 80
        # self.drum_pads = [[False] * 16 for _ in range(16)]
        self.pattern = pattern
        self.last_played_pad =0
        self.auto_played_pad = True

    #------------------------------------------------------------------------------
    def start_thread(self):
        if self._play_thread: return
        self.stop_event.clear()
        self._play_thread = threading.Thread(target=self._run_thread)
        self._play_thread.start()

    #------------------------------------------------------------------------------

    def stop_thread(self):
        self.stop_event.set()
        if self._play_thread:
            self._play_thread.join()
            self._play_thread = None
        
    #------------------------------------------------------------------------------


    def play_pattern(self):
        clicked =0
        if self.clicking:
            self.stop_thread()
            self.stop_click()
            clicked =1
        
        self.playing = True
        if clicked:
            self.play_click()
        self.start_thread()

    #------------------------------------------------------------------------------

    def stop_pattern(self):
        self.playing = False
        if not self.clicking:
            self.stop_thread()
           
    #------------------------------------------------------------------------------


    def play_click(self):
        self.clicking = True
        if self.playing:
            self.cycle_counter = self.current_step
            if self.cycle_counter == 0: 
                self.beat_counter = 0
            else:
                self.beat_counter = self.cycle_counter // 4

        elif not self.playing and not self._play_thread:
            self.start_thread()

    #------------------------------------------------------------------------------
    
    def stop_click(self):
        self.clicking = False
        if not self.playing:
            self.stop_thread()
        self.beat_counter =0
        self.cycle_counter =0

    #------------------------------------------------------------------------------
    
    def stop_all(self):      
        self.playing = False
        self.clicking = False
        self.stop_thread()
        self.current_step =0
        self.beat_counter =0
        self.cycle_counter =0

    #------------------------------------------------------------------------------

    def _run_thread(self):
        while (self.playing or self.clicking) and not self.stop_event.is_set():
            if self.playing:
                for i in range(16):
                    if self.stop_event.is_set():
                        return
                    # self.ui_app.show_status(f"Playing line: {i}")
                    if self.pattern[i][self.current_step]:
                        self.sound_man.play_sound(i)
                        # sounds[i].play()
                # avance le sequencer d'un pas
                self.current_step = (self.current_step +1) % 16
 
            if self.clicking and self.cycle_counter % 4 == 0:
                self.sound_man.play_metronome(self.beat_counter)
                self.beat_counter = (self.beat_counter + 1) % 4

            self.cycle_counter = (self.cycle_counter + 1) % 16
            if self.cycle_counter == 0:
                self.beat_counter = 0

                
            # attendre le temps d'un pas
            time.sleep(self.step_duration)
        # self.ui_app.show_status("Stopped Player")

    #------------------------------------------------------------------------------

    def play_sound(self, index):
        self.sound_man.play_sound(index)

    #------------------------------------------------------------------------------

    def set_bpm(self, bpm):
        if bpm >= 5 and bpm <= 600:
            self.bpm = bpm
            self.step_duration = 60.0 / self.bpm / 4

    #------------------------------------------------------------------------------

    def set_volume(self, volume):
        if volume >=0 and volume <=100:
            self.volume = volume
            self.sound_man.set_volume(volume)

    #------------------------------------------------------------------------------

#=========================================


class MainApp(object):
    def __init__(self, stdscr):
        self.stdscr = stdscr
        sound_man = SoundManager(_medialist, _clickname1, _clickname2)
        sound_man.load_sounds()
        self.player = DrumPlayer(sound_man)
        # self.player = Player()
        self.cursor_pos = [0, 0]
        self.player.last_played_pad = self.cursor_pos[0]
        self.player.auto_played_pad = True
        self.mode_lst = ["Normal", "Select", "Transport"]  # Liste des modes
        self.mode_index = 0  # Index du mode actuel
        self.curmode = self.mode_lst[self.mode_index] # le mode courant
        
        curses.curs_set(0)
        # self.stdscr.timeout(100) # pour rafraîchir l'écran chaque 100 milisecondes
        self.stdscr.nodelay(0) # blocking getch until key is pressed

    #----------------------------------------

    def show_status(self, message):
        """Affiche un message de statut en bas de l'écran."""
        height, width = self.stdscr.getmaxyx()
        self.stdscr.addstr(height - 1, 0, message)
        self.stdscr.clrtoeol()  # Efface la fin de la ligne
        self.stdscr.refresh()
        time.sleep(0.1)

    #----------------------------------------

    def update_screen(self):
        """Redessine l'écran."""
        self.stdscr.clear()
        for i in range(16):
            for j in range(16):
                if self.player.pattern[i][j]:
                    self.stdscr.addch(i + 1, j * 2, '#')
                else:
                    self.stdscr.addch(i + 1, j * 2, '.')
        self.stdscr.addch(self.cursor_pos[0] + 1, self.cursor_pos[1] * 2, 'X')
        self.stdscr.refresh()

    #----------------------------------------

    def main(self):
        """Boucle principale de l'application."""
        
        running = True
        self.player.playing = False
        self.update_screen()
        
        # curses.raw() # for no interrupt mode like suspend, quit
        while running:
            
            key = self.stdscr.getch()

            # To debug keycode
            # self.show_status(f"Key: {key}")
            if key == ord('X'):
                self.player.stop_all()
                running = False
            elif key == 17:
                running = False
            elif key == ord(' '):
                self.player.playing = not self.player.playing
                if self.player.playing:
                    self.player.play_pattern()
                else:
                    self.player.stop_pattern()
                self.show_status("Playing" if self.player.playing else "Paused")
            elif key == ord('c'):
                self.player.clicking = not self.player.clicking
                if self.player.clicking:
                    self.player.play_click()
                else:
                    self.player.stop_click()
                self.show_status("Start Clicking" if self.player.playing else "Stop Clicking")
            elif key == ord('v'):
                self.player.stop_all()
                self.show_status("Stopped All")
            elif key == curses.KEY_LEFT:
                if  self.curmode == "Normal"\
                        or self.curmode == "Select":
                    if self.cursor_pos[1] > 0:
                        self.cursor_pos[1] -= 1
                    else:
                        beep()
                    self.show_status(f"Pad {self.cursor_pos[0] + 1}/{self.cursor_pos[1] + 1}: {'Activé' if self.player.pattern[self.cursor_pos[0]][self.cursor_pos[1]] else 'Désactivé'}")
            elif key == curses.KEY_RIGHT:
                if  self.curmode == "Normal"\
                        or self.curmode == "Select":
                    if self.cursor_pos[1] < 15:
                        self.cursor_pos[1] += 1
                    else:
                        beep()
                    self.show_status(f"Pad {self.cursor_pos[0] + 1}/{self.cursor_pos[1] + 1}: {'Activé' if self.player.pattern[self.cursor_pos[0]][self.cursor_pos[1]] else 'Désactivé'}")
            elif key == curses.KEY_UP:
                if  self.curmode == "Normal"\
                        or self.curmode == "Select":
                    if self.cursor_pos[0] > 0:
                        self.cursor_pos[0] -= 1
                        if self.player.auto_played_pad:
                            self.player.play_sound(self.cursor_pos[0])
                    else:
                        beep()
                    self.show_status(f"Pad {self.cursor_pos[0] + 1}/{self.cursor_pos[1] + 1}: {'Activé' if self.player.pattern[self.cursor_pos[0]][self.cursor_pos[1]] else 'Désactivé'}")
            elif key == curses.KEY_DOWN:
                if  self.curmode == "Normal"\
                        or self.curmode == "Select":
                    if self.cursor_pos[0] < 15:
                        self.cursor_pos[0] += 1
                        if self.player.auto_played_pad:
                            self.player.play_sound(self.cursor_pos[0])
                    else:
                        beep()
                    self.show_status(f"Pad {self.cursor_pos[0] + 1}/{self.cursor_pos[1] + 1}: {'Activé' if self.player.pattern[self.cursor_pos[0]][self.cursor_pos[1]] else 'Désactivé'}")
            elif key == curses.KEY_ENTER or key == 10:
                if  self.curmode == "Normal"\
                        or self.curmode == "Select":
                    self.player.pattern[self.cursor_pos[0]][self.cursor_pos[1]] = True
                    if self.player.auto_played_pad:
                        self.player.play_sound(self.cursor_pos[0])
                    self.show_status(f"Pad {self.cursor_pos[0] + 1}/{self.cursor_pos[1] + 1}: Activé")
            elif key == curses.KEY_BACKSPACE:
                if  self.curmode == "Normal"\
                        or self.curmode == "Select":
                    self.player.pattern[self.cursor_pos[0]][self.cursor_pos[1]] = False
                    self.show_status(f"Pad {self.cursor_pos[0] + 1}/{self.cursor_pos[1] + 1}: Désactivé")
            # Pads Audition
            elif key in key_mapping_1\
                    and self.curmode == "Normal":
                self.player.play_sound(key_mapping_1[key])
                self.player.last_played_pad = key_mapping_1[key]
            
            # Pads selection
            elif key in key_mapping_1\
                    and self.curmode == "Select":
                self.player.pattern[self.cursor_pos[0]][key_mapping_1[key]] = True
                self.show_status(f"Pad {self.cursor_pos[0] + 1}/{self.cursor_pos[1] + 1}: Activé")

            # Pads deselection
            elif key in key_mapping_2\
                    and self.curmode == "Select":
                        # self.player.pattern[self.cursor_pos[0]][self.cursor_pos[1]] = False
                self.player.pattern[self.cursor_pos[0]][key_mapping_2[key]] = False
                self.show_status(f"Pad {self.cursor_pos[0] + 1}/{self.cursor_pos[1] + 1}: Désactivé")

            elif key == ord('l'): # play current pad
                index = self.cursor_pos[0]
                self.player.play_sound(index)
                self.player.last_played_pad = index
            elif key == ord('m'): # play last Pad
                if self.player.last_played_pad is not None:
                    self.player.play_sound(self.player.last_played_pad)
            elif key == 12:  # Ctrl + l
                self.player.play_click()
            elif key == ord('L'):  # Shift + l
                self.player.stop_click()
            
            elif key == curses.KEY_F4:  # Touche F4 pour charger pattern_01
                self.player.pattern = [row[:] for row in pattern_01]
                self.show_status("Pattern 01 chargé")
            elif key == ord('+'):  # Augmenter le BPM
                self.player.set_volume(self.player.volume + 10)
                self.show_status(f"Volume: {self.player.volume}")
            elif key == ord('-'):  # Diminuer le BPM
                self.player.set_volume(self.player.volume -10)
                self.show_status(f"Volume: {self.player.volume}")
            elif key == ord('('):  # Augmenter le BPM
                self.player.set_bpm(self.player.bpm + 5)
                self.show_status(f"BPM: {self.player.bpm}")
            elif key == ord(')'):  # Diminuer le BPM
                self.player.set_bpm(self.player.bpm -5)
                self.show_status(f"BPM: {self.player.bpm}")


            elif key == 9:  # Tab pour passer d'un mode à un autre
                if self.mode_index < len(self.mode_lst) -1:
                    self.mode_index += 1
                    self.curmode = self.mode_lst[self.mode_index]
                    self.show_status(f"Mode: {self.curmode}")
                else:
                    beep()
            elif key == 353:  # Shift+Tab pour passer d'un mode à un autre
                if self.mode_index >0:
                    self.mode_index -= 1
                    self.curmode = self.mode_lst[self.mode_index]
                    self.show_status(f"Mode: {self.curmode}")
                else:
                    beep()

            # beep()


    #----------------------------------------

#=========================================

def main(stdscr):
    app = MainApp(stdscr)
    app.main()

#----------------------------------------

if __name__ == "__main__":
    curses.wrapper(main)

#----------------------------------------

