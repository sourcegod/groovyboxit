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

    def _chase(self, pos):
        """Poursuite des instruments de banque à la position pos, en pas
        (Phase 7 étape 17f1, docs/DESIGN.md § 17e3 O4)."""
        if self._on_play_start_cb:
            with self._pattern._lock:
                tape = [list(track_list) for track_list in self._pattern._tape]
            self._on_play_start_cb(tape, pos)

    def _play_stopped(self):
        """Fin d'une lecture qui tournait : contrôleurs des banques à zéro
        (Phase 7 étape 18d3, docs/DESIGN.md § 18d2 P2)."""
        if self._on_play_stop_cb:
            self._on_play_stop_cb()

    def play_pattern(self):
        self._chase(self._resume_offset or 0.0)
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
        was_playing            = self.playing
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
        if was_playing:
            self._play_stopped()

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
        self._resume_offset = self._position_at(time.perf_counter())   # 19d1
        self.playing   = False
        self._count_in = 0
        if not self._note_repeat_active and not self.clicking:
            self.stop_thread()
        else:
            self._wakeup.set()
        self._play_stopped()

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
        was_playing              = self.playing
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
        if was_playing:
            self._play_stopped()

    #--------------------------------------------------------------------------

    def set_bpm(self, bpm):
        """Tempo de départ. En lecture, la position musicale est gardée
        (Phase 7 étape 19d1)."""
        if 1 <= bpm <= 600:
            self._keep_position()
            self.bpm = bpm
            self._pattern._bpm = bpm      # pattern live à jour (dialogues, 19d1)
            self._update_step_duration()
            self._wakeup.set()

    def _keep_position(self):
        """Avant un changement de tempo en lecture : note la position
        courante, sur laquelle le thread se recale (19d1, T8)."""
        if self.playing or self.clicking or self._note_repeat_active:
            if self._measure_start is not None:
                self._resync_offset = self._current_offset()
