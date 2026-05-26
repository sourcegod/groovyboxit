import time
import threading

from pattern import Pattern
from voice_manager import VoiceManager


class DrumPlayer:
    QUANT_LIST  = ["1/1", "1/2", "1/3", "1/4", "1/6", "1/8", "1/12", "1/16",
                   "1/24", "1/32", "1/48", "1/64", "1/96", "1/128"]
    QUANT_STEPS = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128]
    # Étiquettes d'affichage pour la listbox (même ordre que QUANT_LIST)
    QUANT_LABELS = [f"Quant_{i + 1:02d} - {q}" for i, q in enumerate(QUANT_LIST)]
    NR_EVENT       = -100   # marqueur interne pour les événements Note Repeat dans la liste
    KIT_TAPE_EVENT   = -2    # marqueur interne pour les événements kit_tape (MIDI brut)
    PATCH_TAPE_EVENT = -3    # marqueur interne pour les événements patch_tape (MIDI brut)

    def __init__(self, sound_manager=None):
        self._play_thread = None
        self.stop_event = threading.Event()
        self._wakeup = threading.Event()   # réveil mid-mesure si clicking/playing change
        self.sound_man = sound_manager
        self.playing = False
        self.clicking = False
        self.bpm = 100
        self.volume = 80
        self.pan = 0
        self._pattern      = Pattern()
        self._cur_track       = 0
        self._all_offsets     = [
            [[] for _ in range(self._pattern._num_pads)]
            for _ in range(self._pattern._num_tracks)
        ]
        self._on_track_play_cb = None  # callback(track_idx, pad_idx, vol, pan)
        self.last_played_pad = None
        self.voice_manager = VoiceManager(self._pattern._num_pads)
        self.step_duration = 60.0 / self.bpm / 4
        self.quant_idx = 7  # défaut: 1/16
        # Note Repeat (intégré dans _run_thread, synchronisé sur l'horloge de mesure)
        self._nr_quant_idx       = 7
        self._nr_get_pad         = None
        self._nr_play_cb         = None   # callback(pad_idx) optionnel pour le NR (ex. Synth)
        self._note_repeat_active = False
        self.recording            = False
        self.replace_recording    = False
        self._erase_active_pads   = set()   # pads MIDI tenus en mode Erase
        self.erasing              = False
        self._erase_was_recording = False
        self._erase_was_replace   = False
        self.click_in_recording   = True
        self.count_in_bars        = 1     # 0, 1, 2, 4 ou 8 mesures
        self._click_before_rec    = False  # état du click avant d'entrer en Rec
        self._measure_start       = None
        self._on_recorded_cb      = None  # callback(pad_idx, bar_idx, step_idx) pour l'UI
        self._on_replaced_cb      = None  # callback(pad_idx, bar_idx, step_idx) note effacée
        self._on_kit_tape_cb      = None  # callback(track_idx, midi_note, velocity, duration_ms) lecture kit_tape
        self._on_patch_tape_cb    = None  # callback(track_idx, midi_note, velocity, duration_ms) lecture patch_tape
        self._pending_patch       = {}    # {midi_note: (key, entry_idx, t_start)} — note_on en attente de note_off
        self._count_in            = 0     # mesures de count-in restantes avant Rec
        self._on_count_in_done_cb = None  # callback() quand le count-in est écoulé
        self._quant_in_recording  = True  # caler les hits enregistrés sur la grille de quantize

    #--------------------------------------------------------------------------

    @property
    def float_offsets(self):
        """Offsets du track courant — alias lecture/écriture dans _all_offsets."""
        return self._all_offsets[self._cur_track]

    @float_offsets.setter
    def float_offsets(self, value):
        self._all_offsets[self._cur_track] = value

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
        self.playing           = False
        self.clicking          = False
        self._count_in         = 0
        self.recording         = False
        self.replace_recording = False
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
        self.replace_recording   = False
        self.erasing             = False
        self._erase_active_pads.clear()
        self._count_in           = 0
        self.stop_thread()
        self.sound_man.stop_all()

    #--------------------------------------------------------------------------

    def _run_thread(self):
        measure_start = time.perf_counter()

        while (self.playing or self.clicking or self._note_repeat_active) \
                and not self.stop_event.is_set():
            self._wakeup.clear()
            # Pendant le count-in, on boucle par mesure unitaire (1 bar)
            # pour déclencher l'enregistrement exactement après 1 mesure musicale.
            if self._count_in > 0:
                loop_bars = 1
            else:
                loop_bars = self._pattern._num_bars
            total_steps  = loop_bars * self._pattern._num_steps
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
                num_steps = self._pattern._num_steps
                for track_idx, track_offsets in enumerate(self._all_offsets):
                    for pad_idx, pad_off in enumerate(track_offsets):
                        for offset in pad_off:
                            t_sec = offset * self.step_duration
                            if t_sec > elapsed - 0.002:
                                step     = int(round(offset)) % total_steps
                                bar_idx  = step // num_steps
                                step_idx = step % num_steps
                                raw      = self._pattern._curpattern[track_idx][pad_idx][bar_idx][step_idx]
                                velocity = 100 if isinstance(raw, bool) and raw else int(raw)
                                events.append((t_sec, track_idx, pad_idx, velocity))
            if self.playing:
                num_steps = self._pattern._num_steps
                for (t_idx, bar_idx, step_idx), note_list in self._pattern._kit_tape.items():
                    float_off = bar_idx * num_steps + step_idx
                    t_sec = float_off * self.step_duration
                    if t_sec > elapsed - 0.002:
                        for midi_note, vel, dur in note_list:
                            events.append((t_sec, self.KIT_TAPE_EVENT, (t_idx, midi_note, dur), vel))
                for (t_idx, bar_idx, step_idx), note_list in self._pattern._patch_tape.items():
                    float_off = bar_idx * num_steps + step_idx
                    t_sec = float_off * self.step_duration
                    if t_sec > elapsed - 0.002:
                        for midi_note, vel, dur in note_list:
                            events.append((t_sec, self.PATCH_TAPE_EVENT, (t_idx, midi_note, dur), vel))
            if self.clicking:
                steps_per_beat = self._pattern._num_steps // self._pattern._num_beats
                for bar_idx in range(loop_bars):
                    for beat in range(self._pattern._num_beats):
                        t_sec = (bar_idx * self._pattern._num_steps + beat * steps_per_beat) * self.step_duration
                        if t_sec > elapsed - 0.002:
                            events.append((t_sec, -1, beat, 0))
            if self._note_repeat_active:
                denom    = self.QUANT_STEPS[self._nr_quant_idx]
                nr_step  = 0.0
                interval = 16.0 / denom   # en pas (float)
                while nr_step < total_steps:
                    t_sec = nr_step * self.step_duration
                    if t_sec > elapsed - 0.002:
                        events.append((t_sec, self.NR_EVENT, 0, 100))
                    nr_step += interval
            events.sort()

            for t_sec, track_or_type, evt_data, velocity in events:
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
                if track_or_type >= 0:
                    track_idx = track_or_type
                    pad_idx   = evt_data
                    if track_idx == self._cur_track \
                            and pad_idx in self._erase_active_pads:
                        self._clear_offset(pad_idx, t_sec / self.step_duration)
                    elif self.voice_manager.is_audible(pad_idx):
                        vol = min(1.0, self.voice_manager.get_volume_factor(pad_idx)
                                  * velocity / 100.0)
                        pan = self._mix_pan(self.voice_manager.get_pan(pad_idx))
                        dur = self.voice_manager.get_duration_ms(pad_idx)
                        if self._on_track_play_cb:
                            self._on_track_play_cb(track_idx, pad_idx, vol, pan, dur)
                        else:
                            self.sound_man.play_sound(pad_idx, vol, pan)
                        if track_idx == self._cur_track and self.replace_recording:
                            self._clear_offset(pad_idx, t_sec / self.step_duration)
                elif track_or_type == self.KIT_TAPE_EVENT:
                    t_idx, midi_note, dur = evt_data
                    if self._on_kit_tape_cb:
                        self._on_kit_tape_cb(t_idx, midi_note, velocity, dur)
                    else:
                        self.sound_man.play_note(midi_note, velocity / 127.0)
                elif track_or_type == self.PATCH_TAPE_EVENT:
                    t_idx, midi_note, dur = evt_data
                    if self._on_patch_tape_cb:
                        self._on_patch_tape_cb(t_idx, midi_note, velocity, dur)
                elif track_or_type == self.NR_EVENT:
                    pad = self._nr_get_pad() if self._nr_get_pad else self.last_played_pad
                    if pad is not None and self.voice_manager.is_audible(pad):
                        if self._nr_play_cb:
                            self._nr_play_cb(pad)
                        else:
                            self.sound_man.play_sound(
                                pad,
                                self.voice_manager.get_volume_factor(pad),
                                self._mix_pan(self.voice_manager.get_pan(pad)),
                            )
                        if self.recording:
                            self._record_nr_hit(pad, t_sec / self.step_duration)
                else:
                    self.sound_man.play_metronome(evt_data)
            else:
                # Pré-armer l'enregistrement sur le DERNIER bar de count-in
                # (avant l'attente) pour capturer les frappes anticipées sur
                # le premier temps : l'utilisateur réagit au dernier click
                # (~150-300 ms avant la fin de mesure) donc recording doit
                # être True AVANT que la mesure se termine.
                was_last_count_in  = (self._count_in == 1)
                next_measure_start = measure_start + measure_secs
                if was_last_count_in:
                    self.playing        = True
                    self.recording      = True
                    self._measure_start = next_measure_start
                    if self._on_count_in_done_cb:
                        self._on_count_in_done_cb()

                # Tous les événements joués → attendre la fin de mesure
                while not self.stop_event.is_set() and not self._wakeup.is_set():
                    remaining = next_measure_start - time.perf_counter()
                    if remaining <= 0:
                        break
                    time.sleep(min(remaining, 0.010))
                if self._count_in > 0 and not self._wakeup.is_set() and not self.stop_event.is_set():
                    self._count_in -= 1
                    if self._count_in == 0:
                        if was_last_count_in:
                            measure_start = next_measure_start
                        else:
                            self.playing   = True
                            self.recording = True
                            measure_start  = time.perf_counter()
                            if self._on_count_in_done_cb:
                                self._on_count_in_done_cb()
                elif not self._wakeup.is_set() and not self.stop_event.is_set():
                    if not self._pattern._looping and self.playing:
                        self.playing = False

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

    def double_pattern(self):
        """Double les mesures du pattern courant. Retourne False si impossible."""
        half_steps = self._pattern._num_bars * self._pattern._num_steps
        if not self._pattern.double_bars():
            return False
        for track_offsets in self._all_offsets:
            for pad_idx in range(len(track_offsets)):
                orig    = track_offsets[pad_idx]
                shifted = [f + half_steps for f in orig]
                track_offsets[pad_idx] = sorted(orig + shifted)
        self._wakeup.set()
        return True

    #--------------------------------------------------------------------------

    def halve_pattern(self):
        """Divise par deux les mesures du pattern. Retourne False si impossible."""
        if self._pattern._num_bars < 2:
            return False
        half_steps = (self._pattern._num_bars // 2) * self._pattern._num_steps
        self._pattern.halve_bars()
        for track_offsets in self._all_offsets:
            for pad_idx in range(len(track_offsets)):
                track_offsets[pad_idx] = [
                    f for f in track_offsets[pad_idx] if f < half_steps
                ]
        self._wakeup.set()
        return True

    #--------------------------------------------------------------------------

    def apply_quant_to_pattern(self, quant_idx=None):
        if quant_idx is None:
            quant_idx = self.quant_idx
        if quant_idx < 0:
            return
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
            pad    = self._pattern._curpattern[self._cur_track][pad_idx]
            active = self.float_offsets[pad_idx]
            # effacer
            for bar in pad:
                bar[:] = [False] * len(bar)
            if not active:
                continue
            # snap chaque float vers le point de grille le plus proche
            snapped = set()
            for pos in active:
                nearest = min(full_grid, key=lambda p: abs(p - pos))
                snapped.add(nearest)
            # écrire dans le pattern
            for fp in snapped:
                bar_idx  = int(fp // num_steps)
                step_idx = round(fp % num_steps) % num_steps
                if bar_idx < self._pattern._num_bars:
                    pad[bar_idx][step_idx] = True
            self.float_offsets[pad_idx] = sorted(snapped)

    #--------------------------------------------------------------------------

    def _compute_offsets(self):
        num_tracks = self._pattern._num_tracks
        all_offsets = []
        for track_idx in range(num_tracks):
            track_offsets = []
            for pad in self._pattern._curpattern[track_idx]:
                offsets = []
                base = 0
                for bar in pad:
                    for step_idx, active in enumerate(bar):
                        if active:
                            offsets.append(float(base + step_idx))
                    base += len(bar)
                track_offsets.append(offsets)
            all_offsets.append(track_offsets)
        self._all_offsets = all_offsets   # assignation atomique
        if self.playing or self.clicking or self._note_repeat_active:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def load_pattern(self, pattern):
        self._pattern.load_pattern(pattern)
        self._compute_offsets()

    #--------------------------------------------------------------------------

    def play_sound(self, index, velocity=100):
        self.last_played_pad = index
        if self.voice_manager.is_audible(index):
            vol = min(1.0, self.voice_manager.get_volume_factor(index) * velocity / 100.0)
            self.sound_man.play_sound(
                index,
                vol,
                self._mix_pan(self.voice_manager.get_pan(index)),
            )

    #--------------------------------------------------------------------------

    def start_note_repeat(self, quant_idx, get_pad_func=None, play_cb=None):
        self._nr_quant_idx       = quant_idx
        self._nr_get_pad         = get_pad_func or (lambda: self.last_played_pad)
        self._nr_play_cb         = play_cb
        self._note_repeat_active = True
        if not (self._play_thread and self._play_thread.is_alive()):
            self.start_thread()
        else:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def stop_note_repeat(self):
        self._note_repeat_active = False
        self._nr_play_cb         = None
        if not (self.playing or self.clicking):
            self.stop_thread()
        else:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def update_nr_rate(self, quant_idx):
        """Change le taux NR à chaud sans modifier le pad en cours."""
        self._nr_quant_idx = quant_idx
        if self._note_repeat_active:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def record_pattern(self):
        self._click_before_rec = self.clicking
        self.recording = True
        if self.click_in_recording and not self.clicking:
            self.play_click()
        if not self.playing:
            self.play_pattern()

    #--------------------------------------------------------------------------

    def record_pattern_with_count_in(self, bars=None):
        bars = self.count_in_bars if bars is None else bars
        if bars == 0:
            self.record_pattern()
            return
        self._click_before_rec = self.clicking
        self.recording = False
        self.playing   = False
        self._count_in = bars
        self.clicking  = True
        self.stop_thread()
        self.start_thread()

    #--------------------------------------------------------------------------

    def stop_record(self):
        self.recording         = False
        self.replace_recording = False
        self._count_in         = 0
        if self.click_in_recording and not self._click_before_rec:
            self.stop_click()

    #--------------------------------------------------------------------------

    def start_replace_recording(self):
        self._click_before_rec = self.clicking
        self.replace_recording = True
        self.recording         = True
        if self.click_in_recording and not self.clicking:
            self.play_click()
        if not self.playing:
            self.play_pattern()

    #--------------------------------------------------------------------------

    def toggle_erase(self):
        """Bascule le mode Erase. Retourne True si Erase vient d'être activé."""
        if self.erasing:
            self.erasing = False
            self._erase_active_pads.clear()
            if self._erase_was_recording:
                self.recording         = True
                self.replace_recording = self._erase_was_replace
        else:
            self._erase_was_recording = self.recording
            self._erase_was_replace   = self.replace_recording
            self.erasing = True
            if self.recording:
                self.stop_record()
        return self.erasing

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
        self._pattern._curpattern[self._cur_track][pad_idx][bar_idx][step_idx] = 100

        if not any(abs(f - float_offset) < 0.5 for f in self.float_offsets[pad_idx]):
            self.float_offsets[pad_idx].append(float_offset)
            self.float_offsets[pad_idx].sort()

        if self._on_recorded_cb:
            self._on_recorded_cb(pad_idx, bar_idx, step_idx)

    #--------------------------------------------------------------------------

    def _clear_offset(self, pad_idx, float_offset):
        if not self.float_offsets[pad_idx]:
            return
        total_steps = self._pattern._num_bars * self._pattern._num_steps
        num_steps   = self._pattern._num_steps
        idx = min(range(len(self.float_offsets[pad_idx])),
                  key=lambda i: abs(self.float_offsets[pad_idx][i] - float_offset))
        removed  = self.float_offsets[pad_idx].pop(idx)
        step     = round(removed) % total_steps
        bar_idx  = step // num_steps
        step_idx = step % num_steps
        if not any(round(f) % total_steps == step for f in self.float_offsets[pad_idx]):
            self._pattern._curpattern[self._cur_track][pad_idx][bar_idx][step_idx] = 0
        if self._on_replaced_cb:
            self._on_replaced_cb(pad_idx, bar_idx, step_idx)

    #--------------------------------------------------------------------------

    def record_hit(self, pad_idx, velocity=100):
        now = time.perf_counter()
        total_steps  = self._pattern._num_bars * self._pattern._num_steps
        measure_secs = total_steps * self.step_duration
        ref = self._measure_start if self._measure_start is not None else now
        if now < ref:
            # Frappe anticipée durant le pré-armement du count-in : snap step 0.
            float_offset = 0.0
        else:
            float_offset = ((now - ref) % measure_secs) / self.step_duration

        if self._quant_in_recording and self.quant_idx >= 0:
            quant_size   = self._pattern._num_steps / self.QUANT_STEPS[self.quant_idx]
            float_offset = round(float_offset / quant_size) * quant_size % total_steps

        if round(float_offset) >= total_steps:
            float_offset = 0.0
        step     = round(float_offset) % total_steps
        bar_idx  = step // self._pattern._num_steps
        step_idx = step % self._pattern._num_steps
        self._pattern._curpattern[self._cur_track][pad_idx][bar_idx][step_idx] = \
            max(1, min(127, int(velocity)))

        if not any(abs(f - float_offset) < 0.5 for f in self.float_offsets[pad_idx]):
            self.float_offsets[pad_idx].append(float_offset)
            self.float_offsets[pad_idx].sort()

        return bar_idx, step_idx

    #--------------------------------------------------------------------------

    def record_patch_note(self, midi_note, velocity=100, duration_ms=None):
        """Enregistre une note MIDI brute dans patch_tape.

        duration_ms=None → durée mesurée jusqu'au note_off via record_patch_note_off().
        duration_ms>=0   → durée fixe (numpad).
        """
        now = time.perf_counter()
        total_steps  = self._pattern._num_bars * self._pattern._num_steps
        measure_secs = total_steps * self.step_duration
        ref = self._measure_start if self._measure_start is not None else now
        float_offset = 0.0 if now < ref else \
                       ((now - ref) % measure_secs) / self.step_duration
        if self._quant_in_recording and self.quant_idx >= 0:
            quant_size   = self._pattern._num_steps / self.QUANT_STEPS[self.quant_idx]
            float_offset = round(float_offset / quant_size) * quant_size % total_steps
        if round(float_offset) >= total_steps:
            float_offset = 0.0
        step     = round(float_offset) % total_steps
        bar_idx  = step // self._pattern._num_steps
        step_idx = step % self._pattern._num_steps
        vel = max(1, min(127, int(velocity)))
        dur = 0 if duration_ms is None else max(0, int(duration_ms))
        key    = (self._cur_track, bar_idx, step_idx)
        events = self._pattern._patch_tape.setdefault(key, [])
        # remplace une entrée existante pour ce midi_note, sinon ajoute
        for i, entry in enumerate(events):
            if entry[0] == midi_note:
                events[i]   = (midi_note, vel, dur)
                entry_idx   = i
                break
        else:
            events.append((midi_note, vel, dur))
            entry_idx = len(events) - 1
        if duration_ms is None:
            self._pending_patch[midi_note] = (key, entry_idx, now)
        else:
            self._pending_patch.pop(midi_note, None)
        return bar_idx, step_idx

    def record_patch_note_off(self, midi_note):
        """Finalise la durée d'une note patch_tape après le note_off MIDI."""
        pending = self._pending_patch.pop(midi_note, None)
        if pending is None:
            return
        key, entry_idx, t_start = pending
        events = self._pattern._patch_tape.get(key)
        if events is None or entry_idx >= len(events):
            return
        duration_ms = max(1, int((time.perf_counter() - t_start) * 1000))
        note, vel, _ = events[entry_idx]
        events[entry_idx] = (note, vel, duration_ms)

    #--------------------------------------------------------------------------

    def record_kit_note(self, midi_note, velocity=100):
        """Enregistre une note MIDI brute dans kit_tape sans passer par la grille."""
        now = time.perf_counter()
        total_steps  = self._pattern._num_bars * self._pattern._num_steps
        measure_secs = total_steps * self.step_duration
        ref = self._measure_start if self._measure_start is not None else now
        float_offset = 0.0 if now < ref else \
                       ((now - ref) % measure_secs) / self.step_duration
        if self._quant_in_recording and self.quant_idx >= 0:
            quant_size   = self._pattern._num_steps / self.QUANT_STEPS[self.quant_idx]
            float_offset = round(float_offset / quant_size) * quant_size % total_steps
        if round(float_offset) >= total_steps:
            float_offset = 0.0
        step     = round(float_offset) % total_steps
        bar_idx  = step // self._pattern._num_steps
        step_idx = step % self._pattern._num_steps
        vel = max(1, min(127, int(velocity)))
        key = (self._cur_track, bar_idx, step_idx)
        events = self._pattern._kit_tape.setdefault(key, [])
        if not any(e[0] == midi_note for e in events):
            events.append((midi_note, vel, 0))
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

    def set_pan(self, pan):
        self.pan = max(-100, min(100, int(pan)))

    def _mix_pan(self, pad_pan):
        return max(-100, min(100, self.pan + pad_pan))

    #--------------------------------------------------------------------------
