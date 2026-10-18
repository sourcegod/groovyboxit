import time

from pattern import ETYPE_PATCH


class EraseMixin:
    """DrumPlayer — mode Erase : effacement au passage et ciblé."""

    def toggle_erase(self):
        """Bascule le mode Erase. Retourne True si Erase vient d'être activé."""
        if self.erasing:
            self.erasing = False
            self._erase_active_pads.clear()
            self._erase_active_midi_notes.clear()
            if self._erase_was_recording:
                self.recording         = True
                self.replace_recording = self._erase_was_replace
        else:
            self._erase_was_recording = self.recording
            self._erase_was_replace   = self.replace_recording
            self.erasing = True
            self._erase_active_midi_notes.clear()
            if self.recording:
                self.stop_record()
        return self.erasing

    #--------------------------------------------------------------------------

    def _erase_tape_event(self, track_idx, midi_note, t_sec, etype):
        """Efface un événement tape au passage (appelé par _run_thread en mode Erase)."""
        total_steps = self._pattern._num_bars * self._pattern._num_steps
        float_off   = t_sec / self.step_duration
        time_val    = float(round(float_off) % total_steps)
        with self._pattern._lock:
            if track_idx >= len(self._pattern._tape):
                return
            track_list = self._pattern._tape[track_idx]
            track_list[:] = [e for e in track_list
                              if not (e.time == time_val and e.etype == etype
                                      and e.payload.get("note") == midi_note)]

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
            self._pattern.set_cell(self._cur_track, pad_idx, bar_idx, step_idx, 0)

        return bar_idx, step_idx

    def erase_patch_tape_note(self, track_idx, midi_note):
        """Efface l'événement patch tape le plus proche du temps courant pour midi_note."""
        total_steps  = self._pattern._num_bars * self._pattern._num_steps

        if self._measure_start is not None:
            measure_secs = total_steps * self.step_duration
            now     = time.perf_counter()
            current = ((now - self._measure_start) % measure_secs) / self.step_duration
        else:
            current = 0.0   # hors lecture : efface le premier événement trouvé

        def circ_dist(step_f):
            d = abs(step_f - current) % total_steps
            return min(d, total_steps - d)

        if track_idx >= len(self._pattern._tape):
            return None

        best_dist = float('inf')
        best_ev   = None

        for ev in self._pattern._tape[track_idx]:
            if ev.etype == ETYPE_PATCH and ev.payload.get("note") == midi_note:
                dist = circ_dist(ev.time)
                if dist < best_dist:
                    best_dist = dist
                    best_ev   = ev

        if best_ev is None:
            return None

        with self._pattern._lock:
            track_list = self._pattern._tape[track_idx]
            for i, ev in enumerate(track_list):
                if ev is best_ev:
                    del track_list[i]
                    break
            else:
                return None

        return self._pattern._time_to_bar_step(best_ev.time)   # bar_idx, step_idx

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
            self._pattern.set_cell(self._cur_track, pad_idx, bar_idx, step_idx, 0)
        if self._on_replaced_cb:
            self._on_replaced_cb(pad_idx, bar_idx, step_idx)
