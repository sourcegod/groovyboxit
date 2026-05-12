import time
import threading

from pattern import Pattern


class DrumPlayer:
    QUANT_LIST  = ["1/1", "1/2", "1/3", "1/4", "1/6", "1/8", "1/12", "1/16",
                   "1/24", "1/32", "1/48", "1/64", "1/96", "1/128"]
    QUANT_STEPS = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128]
    NR_EVENT    = -100   # marqueur interne pour les événements Note Repeat dans la liste

    def __init__(self, sound_manager=None):
        self._play_thread = None
        self.stop_event = threading.Event()
        self._wakeup = threading.Event()   # réveil mid-mesure si clicking/playing change
        self.sound_man = sound_manager
        self.playing = False
        self.clicking = False
        self.bpm = 100
        self.volume = 80
        self._pattern   = Pattern()
        self._cur_track = 0
        self.float_offsets = [[] for _ in range(self._pattern._num_pads)]
        self.last_played_pad = None
        self.step_duration = 60.0 / self.bpm / 4
        self.quant_idx = 7  # défaut: 1/16
        # Note Repeat (intégré dans _run_thread, synchronisé sur l'horloge de mesure)
        self._nr_quant_idx       = 7
        self._nr_get_pad         = None
        self._note_repeat_active = False
        self.recording            = False
        self.erasing              = False
        self._measure_start       = None
        self._on_recorded_cb      = None  # callback(pad_idx, bar_idx, step_idx) pour l'UI
        self._count_in            = 0     # mesures de count-in restantes avant Rec
        self._on_count_in_done_cb = None  # callback() quand le count-in est écoulé

    #--------------------------------------------------------------------------

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
        if clicked:
            self.play_click()
        self.start_thread()

    #--------------------------------------------------------------------------

    def stop_pattern(self):
        self.playing   = False
        self.clicking  = False
        self._count_in = 0
        if not self._note_repeat_active:
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
        self.erasing             = False
        self._count_in           = 0
        self.stop_thread()
        self.sound_man.stop_all()

    #--------------------------------------------------------------------------

    def _run_thread(self):
        measure_start = time.perf_counter()

        while (self.playing or self.clicking or self._note_repeat_active) \
                and not self.stop_event.is_set():
            self._wakeup.clear()
            total_steps  = self._pattern._num_bars * self._pattern._num_steps
            measure_secs = total_steps * self.step_duration
            now = time.perf_counter()

            # Avancer measure_start si la mesure précédente est terminée
            while measure_start + measure_secs <= now:
                measure_start += measure_secs
            self._measure_start = measure_start
            elapsed = now - measure_start

            # Construire les événements restants dans cette mesure
            # (on exclut ceux déjà passés avec une petite tolérance)
            events = []
            if self.playing:
                for pad in range(self._pattern._num_pads):
                    for offset in self.float_offsets[pad]:
                        t_sec = offset * self.step_duration
                        if t_sec > elapsed - 0.002:
                            events.append((t_sec, pad))
            if self.clicking:
                for beat in range(4):
                    t_sec = beat * 4 * self.step_duration
                    if t_sec > elapsed - 0.002:
                        events.append((t_sec, -(beat + 1)))
            if self._note_repeat_active:
                denom    = self.QUANT_STEPS[self._nr_quant_idx]
                nr_step  = 0.0
                interval = 16.0 / denom   # en pas (float)
                while nr_step < total_steps:
                    t_sec = nr_step * self.step_duration
                    if t_sec > elapsed - 0.002:
                        events.append((t_sec, self.NR_EVENT))
                    nr_step += interval
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
                elif row == self.NR_EVENT:
                    pad = self._nr_get_pad() if self._nr_get_pad else self.last_played_pad
                    if pad is not None:
                        self.sound_man.play_sound(pad)
                        if self.recording:
                            self._record_nr_hit(pad, t_sec / self.step_duration)
                else:
                    self.sound_man.play_metronome(-row - 1)
            else:
                # Tous les événements joués → attendre la fin de mesure
                while not self.stop_event.is_set() and not self._wakeup.is_set():
                    remaining = measure_start + measure_secs - time.perf_counter()
                    if remaining <= 0:
                        break
                    time.sleep(min(remaining, 0.010))
                if self._count_in > 0 and not self._wakeup.is_set() and not self.stop_event.is_set():
                    self._count_in -= 1
                    if self._count_in == 0:
                        self.playing   = True
                        self.recording = True
                        if self._on_count_in_done_cb:
                            self._on_count_in_done_cb()

    #--------------------------------------------------------------------------

    def apply_quant_row(self, quant_idx, row):
        denom     = self.QUANT_STEPS[quant_idx]
        num_steps = self._pattern._num_steps
        grid      = [i * num_steps / denom for i in range(denom)]
        pad       = self._pattern._curpattern[self._cur_track][row]
        for c in range(num_steps):
            pad[0][c] = False
        for fp in grid:
            c = min(num_steps - 1, round(fp))
            pad[0][c] = True
        self.float_offsets[row] = sorted(grid)

    #--------------------------------------------------------------------------

    def apply_quant_to_pattern(self, quant_idx=None):
        if quant_idx is None:
            quant_idx = self.quant_idx
        denom     = self.QUANT_STEPS[quant_idx]
        num_steps = self._pattern._num_steps
        # grille de quantisation par mesure (positions flottantes)
        grid_per_bar = [i * num_steps / denom for i in range(denom)]
        # grille étendue sur toutes les mesures
        full_grid = [
            bar_idx * num_steps + gp
            for bar_idx in range(self._pattern._num_bars)
            for gp in grid_per_bar
        ]

        for pad_idx in range(self._pattern._num_pads):
            pad = self._pattern._curpattern[self._cur_track][pad_idx]
            # collecter les positions actives (globales)
            active = [
                bar_idx * num_steps + step_idx
                for bar_idx, bar in enumerate(pad)
                for step_idx, val in enumerate(bar)
                if val
            ]
            # effacer
            for bar in pad:
                bar[:] = [False] * len(bar)
            if not active:
                self.float_offsets[pad_idx] = []
                continue
            # snap chaque note vers le point de grille le plus proche
            snapped = set()
            for pos in active:
                nearest = min(full_grid, key=lambda p: abs(p - pos))
                snapped.add(nearest)
            # écrire dans le pattern
            for fp in snapped:
                bar_idx  = int(fp // num_steps)
                step_idx = min(num_steps - 1, round(fp % num_steps))
                if bar_idx < self._pattern._num_bars:
                    pad[bar_idx][step_idx] = True
            self.float_offsets[pad_idx] = sorted(snapped)

    #--------------------------------------------------------------------------

    def _compute_offsets(self):
        self.float_offsets = []
        for pad in self._pattern._curpattern[self._cur_track]:
            offsets = []
            base = 0
            for bar in pad:
                for step_idx, active in enumerate(bar):
                    if active:
                        offsets.append(float(base + step_idx))
                base += len(bar)
            self.float_offsets.append(offsets)

    #--------------------------------------------------------------------------

    def load_pattern(self, pattern):
        self._pattern.load_pattern(pattern)
        self._compute_offsets()

    #--------------------------------------------------------------------------

    def play_sound(self, index):
        self.last_played_pad = index
        self.sound_man.play_sound(index)

    #--------------------------------------------------------------------------

    def start_note_repeat(self, quant_idx, get_pad_func=None):
        self._nr_quant_idx       = quant_idx
        self._nr_get_pad         = get_pad_func or (lambda: self.last_played_pad)
        self._note_repeat_active = True
        if not (self._play_thread and self._play_thread.is_alive()):
            self.start_thread()
        else:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def stop_note_repeat(self):
        self._note_repeat_active = False
        if not (self.playing or self.clicking):
            self.stop_thread()
        else:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def record_pattern(self):
        self.recording = True
        if not self.playing:
            self.play_pattern()

    #--------------------------------------------------------------------------

    def record_pattern_with_count_in(self, bars=1):
        self.recording = False
        self.playing   = False
        self._count_in = bars
        self.clicking  = True
        self.stop_thread()
        self.start_thread()

    #--------------------------------------------------------------------------

    def stop_record(self):
        self.recording = False
        self._count_in = 0

    #--------------------------------------------------------------------------

    def erase_hit(self, pad_idx):
        if not self.float_offsets[pad_idx]:
            return None
        now = time.perf_counter()
        total_steps  = self._pattern._num_bars * self._pattern._num_steps
        measure_secs = total_steps * self.step_duration
        ref = self._measure_start if self._measure_start is not None else now
        current = ((now - ref) % measure_secs) / self.step_duration

        def circ_dist(a):
            d = abs(a - current) % total_steps
            return min(d, total_steps - d)

        idx = min(range(len(self.float_offsets[pad_idx])),
                  key=lambda i: circ_dist(self.float_offsets[pad_idx][i]))
        removed = self.float_offsets[pad_idx].pop(idx)

        step     = min(round(removed), total_steps - 1)
        bar_idx  = step // self._pattern._num_steps
        step_idx = step % self._pattern._num_steps

        if not any(min(round(f), total_steps - 1) == step for f in self.float_offsets[pad_idx]):
            self._pattern._curpattern[self._cur_track][pad_idx][bar_idx][step_idx] = False

        return bar_idx, step_idx

    #--------------------------------------------------------------------------

    def _record_nr_hit(self, pad_idx, float_offset):
        total_steps  = self._pattern._num_bars * self._pattern._num_steps
        float_offset = float_offset % total_steps

        if round(float_offset) >= total_steps:
            float_offset = 0.0
        step     = round(float_offset) % total_steps
        bar_idx  = step // self._pattern._num_steps
        step_idx = step % self._pattern._num_steps
        self._pattern._curpattern[self._cur_track][pad_idx][bar_idx][step_idx] = True

        if not any(abs(f - float_offset) < 0.5 for f in self.float_offsets[pad_idx]):
            self.float_offsets[pad_idx].append(float_offset)
            self.float_offsets[pad_idx].sort()

        if self._on_recorded_cb:
            self._on_recorded_cb(pad_idx, bar_idx, step_idx)

    #--------------------------------------------------------------------------

    def record_hit(self, pad_idx):
        now = time.perf_counter()
        total_steps  = self._pattern._num_bars * self._pattern._num_steps
        measure_secs = total_steps * self.step_duration
        ref = self._measure_start if self._measure_start is not None else now
        float_offset = ((now - ref) % measure_secs) / self.step_duration

        if round(float_offset) >= total_steps:
            float_offset = 0.0
        step     = round(float_offset) % total_steps
        bar_idx  = step // self._pattern._num_steps
        step_idx = step % self._pattern._num_steps
        self._pattern._curpattern[self._cur_track][pad_idx][bar_idx][step_idx] = True

        if not any(abs(f - float_offset) < 0.5 for f in self.float_offsets[pad_idx]):
            self.float_offsets[pad_idx].append(float_offset)
            self.float_offsets[pad_idx].sort()

        return bar_idx, step_idx

    #--------------------------------------------------------------------------

    def set_bpm(self, bpm):
        if 5 <= bpm <= 600:
            self.bpm = bpm
            self.step_duration = 60.0 / self.bpm / 4
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def set_volume(self, volume):
        if 0 <= volume <= 100:
            self.volume = volume
            self.sound_man.set_volume(volume)

    #--------------------------------------------------------------------------
