import time
import threading


class DrumPlayer:
    def __init__(self, sound_manager=None):
        self._play_thread = None
        self.stop_event = threading.Event()
        self._wakeup = threading.Event()   # réveil mid-mesure si clicking/playing change
        self.sound_man = sound_manager
        self.playing = False
        self.clicking = False
        self.bpm = 100
        self.volume = 80
        self.pattern = [[False] * 16 for _ in range(16)]
        self.float_offsets = [[] for _ in range(16)]
        self.last_played_pad = 0
        self.step_duration = 60.0 / self.bpm / 4

    #--------------------------------------------------------------------------

    def start_thread(self):
        if self._play_thread:
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
        if clicked:
            self.play_click()
        self.start_thread()

    #--------------------------------------------------------------------------

    def stop_pattern(self):
        self.playing = False
        if not self.clicking:
            self.stop_thread()
        else:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def play_click(self):
        self.clicking = True
        if not self._play_thread:
            self.start_thread()
        else:
            self._wakeup.set()   # réveille le thread pour intégrer le click

    #--------------------------------------------------------------------------

    def stop_click(self):
        self.clicking = False
        if not self.playing:
            self.stop_thread()
        else:
            self._wakeup.set()   # réveille le thread pour retirer le click

    #--------------------------------------------------------------------------

    def stop_all(self):
        self.playing = False
        self.clicking = False
        self.stop_thread()
        self.sound_man.stop_all()

    #--------------------------------------------------------------------------

    def _run_thread(self):
        measure_secs = 16 * self.step_duration
        measure_start = time.perf_counter()

        while (self.playing or self.clicking) and not self.stop_event.is_set():
            self._wakeup.clear()
            now = time.perf_counter()

            # Avancer measure_start si la mesure précédente est terminée
            while measure_start + measure_secs <= now:
                measure_start += measure_secs
            elapsed = now - measure_start

            # Construire les événements restants dans cette mesure
            # (on exclut ceux déjà passés avec une petite tolérance)
            events = []
            if self.playing:
                for row in range(16):
                    for offset in self.float_offsets[row]:
                        t_sec = offset * self.step_duration
                        if t_sec > elapsed - 0.002:
                            events.append((t_sec, row))
            if self.clicking:
                for beat in range(4):
                    t_sec = beat * 4 * self.step_duration
                    if t_sec > elapsed - 0.002:
                        events.append((t_sec, -(beat + 1)))
            events.sort()

            for t_sec, row in events:
                if self.stop_event.is_set():
                    return
                if self._wakeup.is_set():
                    break   # état changé → reconstruire les événements
                target = measure_start + t_sec
                while not self.stop_event.is_set() and not self._wakeup.is_set():
                    remaining = target - time.perf_counter()
                    if remaining <= 0:
                        break
                    time.sleep(min(remaining, 0.005))
                if self.stop_event.is_set():
                    return
                if self._wakeup.is_set():
                    break
                if row >= 0:
                    self.sound_man.play_sound(row)
                else:
                    self.sound_man.play_metronome(-row - 1)
            else:
                # Tous les événements joués → attendre la fin de mesure
                while not self.stop_event.is_set() and not self._wakeup.is_set():
                    remaining = measure_start + measure_secs - time.perf_counter()
                    if remaining <= 0:
                        break
                    time.sleep(min(remaining, 0.010))

    #--------------------------------------------------------------------------

    def load_pattern(self, pattern):
        self.pattern = [row[:] for row in pattern]
        self.float_offsets = [
            [float(c) for c in range(len(row)) if row[c]]
            for row in pattern
        ]

    #--------------------------------------------------------------------------

    def play_sound(self, index):
        self.sound_man.play_sound(index)

    #--------------------------------------------------------------------------

    def set_bpm(self, bpm):
        if 5 <= bpm <= 600:
            self.bpm = bpm
            self.step_duration = 60.0 / self.bpm / 4

    #--------------------------------------------------------------------------

    def set_volume(self, volume):
        if 0 <= volume <= 100:
            self.volume = volume
            self.sound_man.set_volume(volume)

    #--------------------------------------------------------------------------
