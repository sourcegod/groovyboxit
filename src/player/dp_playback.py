import time

from metronome import Metronome
from pattern import Pattern, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH, ETYPE_CC, ETYPE_PGM, ETYPE_BEND


class PlaybackLoopMixin:
    """DrumPlayer — boucle de lecture (_run_thread) et marqueurs internes d'événements."""

    NR_EVENT         = -100  # marqueur interne pour les événements Note Repeat dans la liste
    GRID_EVENT       = -6   # marqueur interne pour les événements grille (etype ETYPE_GRID de _tape)
    KIT_TAPE_EVENT   = -2   # marqueur interne pour les événements kit_tape (MIDI brut)
    PATCH_TAPE_EVENT = -3   # marqueur interne pour les événements patch_tape (MIDI brut)
    BEND_TAPE_EVENT  = -4   # marqueur interne pour les événements Pitch Bend (etype ETYPE_BEND de _tape)
    # MOD_TAPE_EVENT (-5) supprimé en Phase 7 étape 5h : CC#1 rejoué via
    # CC_TAPE_EVENT (_tape), qui délègue déjà à on_mod_tape (TrackRouter.on_cc_tape).
    CC_TAPE_EVENT    = -7   # marqueur interne pour les événements CC générique (etype ETYPE_CC de _tape)
    PGM_TAPE_EVENT   = -8   # marqueur interne pour les événements Program Change (etype ETYPE_PGM de _tape)

    def _run_thread(self):
        if self._resume_offset is not None:
            measure_start = time.perf_counter() - self._resume_offset * self.step_duration
            self._resume_offset = None
        else:
            measure_start = time.perf_counter()

        while (self.playing or self.clicking or self._note_repeat_active) \
                and not self.stop_event.is_set():
            self._wakeup.clear()
            num_steps = self._pattern._num_steps
            # Pendant le count-in, on boucle par mesure unitaire (1 bar)
            # pour déclencher l'enregistrement exactement après 1 mesure musicale.
            if self._count_in > 0:
                lp_start    = 0
                lp_end      = num_steps - 1
                total_steps = num_steps
                loop_bars   = 1
                self._cur_lp_start   = 0
                self._cur_loop_steps = 0
            else:
                win = self._lm.compute_window(self._pattern)
                lp_start, lp_end       = win.lp_start, win.lp_end
                total_steps, loop_bars = win.total_steps, win.loop_bars
                self._cur_lp_start   = win.cur_lp_start
                self._cur_loop_steps = win.cur_loop_steps
            measure_secs = total_steps * self.step_duration
            now = time.perf_counter()

            # Avancer measure_start si la mesure précédente est terminée
            while measure_start + measure_secs <= now:
                measure_start += measure_secs
            self._measure_start = measure_start
            elapsed = now - measure_start

            events = self._build_measure_events(lp_start, lp_end, total_steps,
                                                loop_bars, elapsed)

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
                self._dispatch_event(track_or_type, evt_data, velocity, t_sec)
            else:
                measure_start = self._on_measure_end(measure_start, measure_secs, lp_start)

    #--------------------------------------------------------------------------

    def _build_measure_events(self, lp_start, lp_end, total_steps, loop_bars, elapsed):
        """Événements restant à jouer dans la mesure courante, triés par temps
        (t_sec, marqueur, données, vélocité) : tape, métronome, Note Repeat."""
        # Construire les événements restants dans cette mesure
        # (on exclut ceux déjà passés avec une petite tolérance)
        events = []
        if self.playing:
            # Snapshot atomique sous verrou — immunise contre les modifications
            # concurrentes (record_*, erase_*) pendant l'itération.
            with self._pattern._lock:
                tape_snap = [list(track_list) for track_list in self._pattern._tape]
            for t_idx, note_list in enumerate(tape_snap):
                for ev in note_list:
                    float_off = ev.time
                    if not (lp_start <= float_off <= lp_end):
                        continue
                    t_sec = (float_off - lp_start) * self.step_duration
                    if t_sec > elapsed - 0.002:
                        if ev.etype == ETYPE_GRID:
                            events.append((t_sec, self.GRID_EVENT,
                                           (t_idx, ev.payload.get("pad"), ev.dur), ev.payload.get("vel")))
                        elif ev.etype == ETYPE_KIT:
                            events.append((t_sec, self.KIT_TAPE_EVENT,
                                           (t_idx, ev.payload.get("note"), ev.dur), ev.payload.get("vel")))
                        elif ev.etype == ETYPE_PATCH:
                            events.append((t_sec, self.PATCH_TAPE_EVENT,
                                           (t_idx, ev.payload.get("note"), ev.dur),
                                           ev.payload.get("vel")))
                        elif ev.etype == ETYPE_CC:
                            events.append((t_sec, self.CC_TAPE_EVENT,
                                           (t_idx, ev.payload.get("cc_num"), ev.payload.get("value")), 0))
                        elif ev.etype == ETYPE_PGM:
                            events.append((t_sec, self.PGM_TAPE_EVENT,
                                           (t_idx, ev.payload.get("program")), 0))
                        elif ev.etype == ETYPE_BEND:
                            events.append((t_sec, self.BEND_TAPE_EVENT,
                                           (t_idx, ev.payload.get("value")), 0))
        events.extend(self._metro.build_events(
            loop_bars, self._pattern._num_steps, self._pattern._num_beats,
            self.step_duration, elapsed))
        if self._note_repeat_active:
            denom    = Pattern.QUANT_STEPS[self._nr_quant_idx]
            nr_step  = 0.0
            interval = 16.0 / denom   # en pas (float)
            while nr_step < total_steps:
                t_sec = nr_step * self.step_duration
                if t_sec > elapsed - 0.002:
                    events.append((t_sec, self.NR_EVENT, 0, 100))
                nr_step += interval
        events.sort()
        return events

    #--------------------------------------------------------------------------

    def _dispatch_event(self, track_or_type, evt_data, velocity, t_sec):
        """Joue (ou efface, en mode Erase) un événement de la mesure selon son marqueur."""
        if track_or_type == self.GRID_EVENT:
            t_idx, pad_idx, dur_override = evt_data
            if t_idx == self._cur_track \
                    and pad_idx in self._erase_active_pads:
                self._clear_offset(pad_idx, t_sec / self.step_duration)
            elif self.voice_manager.is_audible(pad_idx):
                vol = min(1.0, self.voice_manager.get_volume_factor(pad_idx)
                          * velocity / 100.0)
                pan = self._mix_pan(self.voice_manager.get_pan(pad_idx))
                # dur_override>0 (Numpad1/3, Phase 7 étape 1k) prime sur la
                # durée de la voix, pour cette occurrence uniquement.
                dur = dur_override if dur_override > 0 else self.voice_manager.get_duration_ms(pad_idx)
                if self._on_track_play_cb:
                    self._on_track_play_cb(t_idx, pad_idx, vol, pan, dur)
                else:
                    self.sound_man.play_sound(pad_idx, vol, pan)
                if t_idx == self._cur_track and self.replace_recording:
                    self._clear_offset(pad_idx, t_sec / self.step_duration)
        elif track_or_type == self.KIT_TAPE_EVENT:
            t_idx, midi_note, dur = evt_data
            if self.erasing and t_idx == self._cur_track \
                    and midi_note in self._erase_active_midi_notes:
                self._erase_tape_event(t_idx, midi_note, t_sec, ETYPE_KIT)
            elif self._on_kit_tape_cb:
                self._on_kit_tape_cb(t_idx, midi_note, velocity, dur)
            else:
                self.sound_man.play_note(midi_note, velocity / 127.0)
        elif track_or_type == self.PATCH_TAPE_EVENT:
            # Plus de bend par note (Phase 7 étape 7f1) : un ETYPE_BEND
            # au même temps est rejoué avant (BEND_TAPE_EVENT=-4 trié
            # avant PATCH_TAPE_EVENT=-3 par events.sort()).
            t_idx, midi_note, dur = evt_data
            if self.erasing and t_idx == self._cur_track \
                    and midi_note in self._erase_active_midi_notes:
                self._erase_tape_event(t_idx, midi_note, t_sec, ETYPE_PATCH)
            elif self._on_patch_tape_cb:
                self._on_patch_tape_cb(t_idx, midi_note, velocity, dur)
        elif track_or_type == self.BEND_TAPE_EVENT:
            t_idx, bend_val = evt_data
            if self._on_bend_tape_cb:
                self._on_bend_tape_cb(t_idx, bend_val)
        elif track_or_type == self.CC_TAPE_EVENT:
            t_idx, cc_num, value = evt_data
            if self._on_cc_tape_cb:
                self._on_cc_tape_cb(t_idx, cc_num, value)
        elif track_or_type == self.PGM_TAPE_EVENT:
            t_idx, program = evt_data
            if self._on_program_change_tape_cb:
                self._on_program_change_tape_cb(t_idx, program)
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
        elif track_or_type == Metronome.METRO_EVENT:
            self.sound_man.play_metronome(evt_data)

    #--------------------------------------------------------------------------

    def _on_measure_end(self, measure_start, measure_secs, lp_start):
        """Fin de mesure : pré-armement du count-in, attente de la fin de mesure,
        puis count-in, compteur de boucle, enchaînement du song ou pause en fin
        de pattern. Retourne le measure_start de la mesure suivante."""
        # Pré-armer l'enregistrement sur le DERNIER bar de count-in
        # (avant l'attente) pour capturer les frappes anticipées sur
        # le premier temps : l'utilisateur réagit au dernier click
        # (~150-300 ms avant la fin de mesure) donc recording doit
        # être True AVANT que la mesure se termine.
        was_last_count_in  = (self._count_in == 1)
        next_measure_start = measure_start + measure_secs
        if was_last_count_in:
            self.playing   = True
            self.recording = True
            offset_secs    = (self._count_in_resume_offset or 0.0) * self.step_duration
            self._measure_start = next_measure_start - offset_secs
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
                offset_secs = (self._count_in_resume_offset or 0.0) * self.step_duration
                self._count_in_resume_offset = None
                if was_last_count_in:
                    measure_start = next_measure_start - offset_secs
                else:
                    self.playing   = True
                    self.recording = True
                    measure_start  = time.perf_counter() - offset_secs
                    if self._on_count_in_done_cb:
                        self._on_count_in_done_cb()
        elif not self._wakeup.is_set() and not self.stop_event.is_set():
            # Décrémenter le compteur de boucle si actif (loop_count > 0)
            if self._lm.remaining > 0 and self.playing:
                if self._lm.on_measure_end():
                    self._resume_offset = float(lp_start)
                    self.playing = False
                    if self._song_mode:
                        self._song_mode = False
                        if self._on_song_advance_cb:
                            self._on_song_advance_cb(-1)
            elif not self._pattern._looping and self.playing:
                if (self._song_mode and self._pattern_list_ref
                        and self._song_pos + 1 < len(self._song_sequence)):
                    self._song_pos += 1
                    next_idx = self._song_sequence[self._song_pos]
                    next_pat = self._pattern_list_ref[next_idx]
                    self._pattern.copy_from(next_pat)
                    self._pattern._looping = False
                    if next_pat._bpm != self.bpm:
                        self.bpm           = next_pat._bpm
                        self.step_duration = 60.0 / self.bpm / 4
                    self._compute_offsets()
                    measure_start = next_measure_start
                    if self._on_song_advance_cb:
                        self._on_song_advance_cb(next_idx)
                else:
                    if self._song_mode and self._song_looping and self._pattern_list_ref:
                        # Boucle : repart du 1er pattern sans interruption
                        self._song_pos = 0
                        first_idx = self._song_sequence[0]
                        first_pat = self._pattern_list_ref[first_idx]
                        self._pattern.copy_from(first_pat)
                        self._pattern._looping = False
                        if first_pat._bpm != self.bpm:
                            self.bpm           = first_pat._bpm
                            self.step_duration = 60.0 / self.bpm / 4
                        self._compute_offsets()
                        measure_start = next_measure_start
                        if self._on_song_advance_cb:
                            self._on_song_advance_cb(first_idx)
                    else:
                        # Pause à la fin (dernier tick) plutôt qu'arrêt complet :
                        # _resume_offset conserve la position → navigate_bar fonctionne.
                        total_steps = self._pattern._num_bars * self._pattern._num_steps
                        self._resume_offset = float(total_steps - 1)
                        self.playing = False
                        if self._song_mode:
                            self._song_mode = False
                            if self._on_song_advance_cb:
                                self._on_song_advance_cb(-1)
        return measure_start
