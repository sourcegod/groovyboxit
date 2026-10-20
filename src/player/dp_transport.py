import time
import threading


class TransportMixin:
    """DrumPlayer — thread de lecture, play/stop/pause, song, click, BPM."""

    def start_thread(self):
        if self._play_thread and self._play_thread.is_alive():
            return
        self.stop_event.clear()
        self._play_thread = threading.Thread(target=self._run_thread, daemon=True)
        self._play_thread.start()

    #--------------------------------------------------------------------------

    def stop_thread(self):
        self.stop_event.set()
        self._wakeup.set()   # déverrouille immédiatement tout sleep en cours
        if self._play_thread:
            self._play_thread.join()
            self._play_thread = None

    #--------------------------------------------------------------------------

    def play_pattern(self):
        clicked = 0
        if self.clicking:
            self.stop_thread()
            self.stop_click()
            clicked = 1
        self.playing = True
        self._lm.init_from_pattern(self._pattern)
        if clicked:
            self.play_click()
        self.start_thread()

    #--------------------------------------------------------------------------

    def stop_pattern(self):
        self.playing           = False
        self.clicking          = False
        self._count_in         = 0
        self.recording         = False
        self.replace_recording = False
        self._resume_offset    = None
        self._song_mode        = False
        if not self._note_repeat_active:
            self.stop_thread()
        else:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def play_song(self, sequence, pattern_list_ref, looping=False):
        """Lance la lecture d'un song (liste ordonnée d'indices de patterns)."""
        if not sequence:
            return
        self._song_sequence    = list(sequence)
        self._pattern_list_ref = pattern_list_ref
        self._song_pos         = 0
        self._song_mode        = True
        self._song_looping     = looping
        self._pattern._looping = False
        self.play_pattern()

    #--------------------------------------------------------------------------

    def pause_pattern(self):
        """Arrête la lecture à la position courante (reprise via play_pattern)."""
        if not self.playing:
            return
        now = time.perf_counter()
        if self._cur_loop_steps > 0:
            measure_secs = self._cur_loop_steps * self.step_duration
        else:
            measure_secs = self._pattern._num_bars * self._pattern._num_steps * self.step_duration
        ref = self._measure_start if self._measure_start is not None else now
        self._resume_offset = self._cur_lp_start + ((now - ref) % measure_secs) / self.step_duration
        self.playing   = False
        self._count_in = 0
        if not self._note_repeat_active and not self.clicking:
            self.stop_thread()
        else:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def play_click(self):
        self.clicking = True
        if not (self._play_thread and self._play_thread.is_alive()):
            self.start_thread()
        else:
            self._wakeup.set()   # réveille le thread pour intégrer le click

    #--------------------------------------------------------------------------

    def stop_click(self):
        self.clicking = False
        if not (self.playing or self._note_repeat_active):
            self.stop_thread()
        else:
            self._wakeup.set()   # réveille le thread pour retirer le click

    #--------------------------------------------------------------------------

    def stop_all(self):
        self.playing             = False
        self.clicking            = False
        self._note_repeat_active = False
        self.recording           = False
        self.replace_recording   = False
        self.erasing             = False
        self._erase_active_pads.clear()
        self._erase_active_midi_notes.clear()
        self._count_in           = 0
        self.stop_thread()
        self.sound_man.stop_all()

    #--------------------------------------------------------------------------

    def set_bpm(self, bpm):
        if 1 <= bpm <= 600:
            self.bpm = bpm
            self._update_step_duration()
            self._wakeup.set()
