import time
import threading


class DrumPlayer:
    def __init__(self, sound_manager=None):
        self._play_thread = None
        self.stop_event = threading.Event()
        self.sound_man = sound_manager
        self.playing = False
        self.clicking = False
        self.bpm = 100
        self.current_step = 0
        self.step_duration = 60.0 / self.bpm / 4
        self.beat_counter = 0
        self.cycle_counter = 0
        self.volume = 80
        self.pattern = [[False] * 16 for _ in range(16)]
        self.last_played_pad = 0

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

    #--------------------------------------------------------------------------

    def play_click(self):
        self.clicking = True
        if self.playing:
            self.cycle_counter = self.current_step
            self.beat_counter = 0 if self.cycle_counter == 0 else self.cycle_counter // 4
        elif not self._play_thread:
            self.start_thread()

    #--------------------------------------------------------------------------

    def stop_click(self):
        self.clicking = False
        if not self.playing:
            self.stop_thread()
        self.beat_counter = 0
        self.cycle_counter = 0

    #--------------------------------------------------------------------------

    def stop_all(self):
        self.playing = False
        self.clicking = False
        self.stop_thread()
        self.current_step = 0
        self.beat_counter = 0
        self.cycle_counter = 0
        self.sound_man.stop_all()

    #--------------------------------------------------------------------------

    def _run_thread(self):
        while (self.playing or self.clicking) and not self.stop_event.is_set():
            if self.playing:
                for i in range(16):
                    if self.stop_event.is_set():
                        return
                    if self.pattern[i][self.current_step]:
                        self.sound_man.play_sound(i)
                self.current_step = (self.current_step + 1) % 16

            if self.clicking and self.cycle_counter % 4 == 0:
                self.sound_man.play_metronome(self.beat_counter)
                self.beat_counter = (self.beat_counter + 1) % 4

            self.cycle_counter = (self.cycle_counter + 1) % 16
            if self.cycle_counter == 0:
                self.beat_counter = 0

            time.sleep(self.step_duration)

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
