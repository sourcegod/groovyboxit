import time

from pattern import Pattern, TapeEvent, ETYPE_KIT, ETYPE_PATCH, ETYPE_CC, ETYPE_PGM, ETYPE_BEND
from bend_log import bend_log


class RecordingMixin:
    """DrumPlayer — armement de l'enregistrement, positions de capture, record_*."""

    def record_pattern(self):
        self._metro.save_rec_state()
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
        self._metro.save_rec_state()
        self._count_in_resume_offset = self._current_offset()
        self._resume_offset = None   # count-in repart toujours du beat 0
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
        if self._metro.should_stop_after_rec():
            self.stop_click()

    #--------------------------------------------------------------------------

    def start_replace_recording(self):
        self._metro.save_rec_state()
        self.replace_recording = True
        self.recording         = True
        if self.click_in_recording and not self.clicking:
            self.play_click()
        if not self.playing:
            self.play_pattern()

    #--------------------------------------------------------------------------

    def _record_nr_hit(self, pad_idx, float_offset):
        total_steps  = self._pattern._num_bars * self._pattern._num_steps
        float_offset = float_offset % total_steps

        if round(float_offset) >= total_steps:
            float_offset = 0.0
        step     = round(float_offset) % total_steps
        bar_idx  = step // self._pattern._num_steps
        step_idx = step % self._pattern._num_steps
        vel = self._rec_velocity(100)
        if self._rec_dedupe():                                   # 13d2
            self._pattern.set_cell(self._cur_track, pad_idx, bar_idx, step_idx, vel)
        else:                            # toutes les frappes gardées (13b1, V5)
            self._pattern.add_grid_note(self._cur_track, pad_idx, bar_idx, step_idx, vel)

        if not any(abs(f - float_offset) < 0.5 for f in self.float_offsets[pad_idx]):
            self.float_offsets[pad_idx].append(float_offset)
            self.float_offsets[pad_idx].sort()

        if self._on_recorded_cb:
            self._on_recorded_cb(pad_idx, bar_idx, step_idx)

    #--------------------------------------------------------------------------

    def _compute_record_offset(self):
        """Calcule la position d'enregistrement courante dans le pattern.

        Retourne (float_offset, bar_idx, step_idx) en tenant compte de la
        quantisation si _quant_in_recording est actif.
        float_offset = 0.0 pour les frappes anticipées (count-in pré-armé).
        """
        now          = time.perf_counter()
        total_steps  = self._pattern._num_bars * self._pattern._num_steps
        ref          = self._measure_start if self._measure_start is not None else now
        float_offset = 0.0 if now < ref else self._position_at(now)    # 19d1
        res = self._record_quant_res()
        if res >= 0:                     # réglages d'Alt+Shift+Q (Phase 8 étape 13d2)
            float_offset = self._qm.snap_position(
                float_offset, res, self._rq_force_idx, self._rq_swing_idx,
                self._rq_window_idx, self._rq_direction_idx) % total_steps
        if round(float_offset) >= total_steps:
            float_offset = 0.0
        step     = round(float_offset) % total_steps
        bar_idx  = step // self._pattern._num_steps
        step_idx = step % self._pattern._num_steps
        return float_offset, bar_idx, step_idx

    def _record_quant_res(self):
        """Résolution de la quantisation à l'enregistrement (13d2) : -1 si la
        case est décochée ou s'il n'y a pas de résolution."""
        if not self._quant_in_recording:
            return -1
        res = getattr(self, "_rq_res_idx", -3)
        if res == -3:                                # Quant courante
            return self.quant_idx
        if res == -2:                                # grille courante
            _, kind, val = Pattern.GRID_RESOLUTIONS[self._grid_idx]
            return Pattern.QUANT_STEPS.index(val) \
                if kind == "snaps" and val in Pattern.QUANT_STEPS else -1
        return res

    def _rec_velocity(self, velocity):
        """Vélocité enregistrée : celle de « Quantiser la vélocité »
        d'Alt+Shift+Q si cochée (avec « Quantiser à l'enregistrement »),
        sinon la frappe (13d2)."""
        if self._quant_in_recording and getattr(self, "_rq_velocity", False):
            return max(1, min(127, int(self._rq_velocity_value)))
        return max(1, min(127, int(velocity)))

    def _rec_dedupe(self):
        """« Enlever les doublons » à l'enregistrement (13d2, cochée par
        défaut) : la frappe remplace la note de même hauteur au même temps."""
        return self._quant_in_recording and getattr(self, "_rq_dedupe", False)

    def _compute_float_offset(self):
        """Position d'enregistrement brute (en pas, flottante) pour les
        contrôleurs continus (CC, Pitch Bend) : ni arrondie au pas, ni
        quantifiée — contrairement à _compute_record_offset, réservé aux
        notes (Phase 7 étape 5a décision 1, factorisé en 6b1).

        0.0 pour un événement anticipé (count-in pré-armé) et pour l'arrondi
        flottant en toute fin de boucle (time_val >= total_steps).
        """
        now          = time.perf_counter()
        total_steps  = self._pattern._num_bars * self._pattern._num_steps
        ref          = self._measure_start if self._measure_start is not None else now
        time_val     = 0.0 if now < ref else self._position_at(now)    # 19d1
        if time_val >= total_steps:
            time_val = 0.0
        return time_val

    #--------------------------------------------------------------------------

    def record_hit(self, pad_idx, velocity=100, channel=0):
        float_offset, bar_idx, step_idx = self._compute_record_offset()
        vel = self._rec_velocity(velocity)                      # 13d2
        if self._rec_dedupe():           # doublons enlevés à l'enregistrement (13d2)
            self._pattern.set_cell(self._cur_track, pad_idx, bar_idx, step_idx, vel,
                                   channel=channel)
        else:                            # overdub comme Sonar (13b1, § 13a V5)
            self._pattern.add_grid_note(self._cur_track, pad_idx, bar_idx, step_idx, vel,
                                        channel=channel)
        if not any(abs(f - float_offset) < 0.5 for f in self.float_offsets[pad_idx]):
            self.float_offsets[pad_idx].append(float_offset)
            self.float_offsets[pad_idx].sort()
        return bar_idx, step_idx

    #--------------------------------------------------------------------------

    def record_patch_note(self, midi_note, velocity=100, duration_ms=None, bend=0, channel=0):
        """Enregistre une note MIDI brute dans _tape (etype=ETYPE_PATCH).

        duration_ms=None → durée mesurée jusqu'au note_off via record_patch_note_off().
        duration_ms>=0   → durée fixe (numpad).
        bend             → valeur pitch bend live au moment du note_on
                           (-8192..+8191) ; pas stockée dans la note (Phase 7
                           étape 7f1) : si elle diffère de l'état de bend de la
                           piste à ce temps, un ETYPE_BEND est posé au temps de
                           la note (Pattern._chase_bend).
        channel          → canal MIDI d'origine (0..15), capturé depuis l'entrée live.
        """
        float_offset, bar_idx, step_idx = self._compute_record_offset()
        now = time.perf_counter()
        vel = self._rec_velocity(velocity)                      # 13d2
        dur = 0 if duration_ms is None else max(0, int(duration_ms))
        track = self._cur_track
        time_val = self._pattern._bar_step_to_time(bar_idx, step_idx)
        new_ev = TapeEvent(ETYPE_PATCH, dur=dur, channel=channel,
                            payload={"note": midi_note, "vel": vel},
                            time=time_val)
        with self._pattern._lock:
            self._pattern._ensure_track_count(track + 1)
            self._pattern._chase_bend(track, time_val, bend, channel)
            # overdub comme Sonar : ajoutée (13b1, § 13a V5) ; doublon remplacé
            # si « Enlever les doublons » d'Alt+Shift+Q est cochée (13d2)
            if self._rec_dedupe():
                self._drop_same_note(track, ETYPE_PATCH, midi_note, channel, time_val)
            self._pattern._tape[track].append(new_ev)
        if duration_ms is None:
            # Suivi par id (pas par index) : robuste si d'autres événements de
            # cette piste sont insérés/supprimés d'ici le note_off. Choix fait
            # aussi pour un futur portage C/C++ (id = clé simple, portable ;
            # pas d'équivalent direct à l'identité d'objet Python).
            self._pending_patch[midi_note] = (track, new_ev.id, now)
        else:
            self._pending_patch.pop(midi_note, None)
        bend_log(f"REC note_on  note={midi_note} vel={vel} dur={dur} bend={bend} "
                  f"→ bar={bar_idx} step={step_idx} track={self._cur_track}")
        return bar_idx, step_idx

    def _drop_same_note(self, track, etype, note, channel, time_val):
        """Retire de la piste les notes etype de même hauteur, même canal et
        même temps (doublons à l'enregistrement, 13d2) ; verrou déjà pris."""
        events = self._pattern._tape[track]
        events[:] = [ev for ev in events
                     if not (ev.etype == etype and ev.time == time_val
                             and ev.channel == channel and ev.payload.get("note") == note)]

    def record_patch_note_off(self, midi_note):
        """Finalise la durée d'une note patch dans _tape après le note_off MIDI."""
        pending = self._pending_patch.pop(midi_note, None)
        if pending is None:
            return
        track, target_id, t_start = pending
        with self._pattern._lock:
            events = self._pattern._tape[track]
            for i, ev in enumerate(events):
                if ev.id == target_id:
                    duration_ms = max(1, int((time.perf_counter() - t_start) * 1000))
                    events[i] = TapeEvent(ETYPE_PATCH, dur=duration_ms, channel=ev.channel,
                                           payload=ev.payload, time=ev.time)
                    break
            else:
                return
        bend_log(f"REC note_off note={midi_note} dur_finale={duration_ms}ms")

    #--------------------------------------------------------------------------

    def record_bend(self, bend_value, channel=0):
        """Enregistre un point d'automation Pitch Bend dans _tape (etype=ETYPE_BEND).

        Position flottante brute, comme record_cc (contrôleur continu, voir
        _compute_float_offset). Pas de dédoublonnage. Remplace _bend_tape
        depuis la Phase 7 étape 6b1 (docs/DESIGN.md § 6a1)."""
        time_val = self._compute_float_offset()
        bar_idx, step_idx = self._pattern._time_to_bar_step(time_val)
        track = self._cur_track
        with self._pattern._lock:
            self._pattern._ensure_track_count(track + 1)
            self._pattern._tape[track].append(
                TapeEvent(ETYPE_BEND, channel=channel,
                          payload={"value": bend_value}, time=time_val)
            )
        return bar_idx, step_idx

    #--------------------------------------------------------------------------

    # record_mod supprimé en Phase 7 étape 5h : CC#1 (Mod Wheel) est déjà
    # capturé dans _tape via record_cc (appelé pour tout CC depuis 4f).

    #--------------------------------------------------------------------------

    def record_kit_note(self, midi_note, velocity=100, channel=0):
        """Enregistre une note MIDI brute dans _tape (etype=ETYPE_KIT) sans passer par la grille.
        Overdub comme Sonar (Phase 8 étape 13b1, § 13a V5) : toujours ajoutée,
        même si la même note est déjà au même temps (avant : ignorée, la
        nouvelle vélocité était perdue) ; la quantisation enlève les doublons."""
        _, bar_idx, step_idx = self._compute_record_offset()
        vel = self._rec_velocity(velocity)                      # 13d2
        track = self._cur_track
        time_val = self._pattern._bar_step_to_time(bar_idx, step_idx)
        with self._pattern._lock:
            self._pattern._ensure_track_count(track + 1)
            if self._rec_dedupe():                               # 13d2
                self._drop_same_note(track, ETYPE_KIT, midi_note, channel, time_val)
            self._pattern._tape[track].append(
                TapeEvent(ETYPE_KIT, channel=channel,
                          payload={"note": midi_note, "vel": vel}, time=time_val))
        return bar_idx, step_idx

    #--------------------------------------------------------------------------

    def record_cc(self, cc_num, value, channel=0):
        """Enregistre un Control Change générique dans _tape (etype=ETYPE_CC).

        Pas de dédoublonnage (comme toutes les notes depuis la Phase 8 étape
        13b1) : deux CC de même valeur au même tick sont des données valides.

        Position flottante brute, ni arrondie au pas ni quantifiée (comme
        record_bend) : un CC est un contrôleur continu, un balayage de
        molette tassé sur le pas serait rejoué en escalier (Phase 7 étape
        5b, docs/DESIGN.md § 5a décision 1)."""
        time_val = self._compute_float_offset()
        bar_idx, step_idx = self._pattern._time_to_bar_step(time_val)
        track = self._cur_track
        with self._pattern._lock:
            self._pattern._ensure_track_count(track + 1)
            self._pattern._tape[track].append(
                TapeEvent(ETYPE_CC, channel=channel,
                          payload={"cc_num": cc_num, "value": value}, time=time_val)
            )
        return bar_idx, step_idx

    def record_program_change(self, program, channel=0):
        """Enregistre un Program Change dans _tape (etype=ETYPE_PGM)."""
        _, bar_idx, step_idx = self._compute_record_offset()
        track = self._cur_track
        time_val = self._pattern._bar_step_to_time(bar_idx, step_idx)
        with self._pattern._lock:
            self._pattern._ensure_track_count(track + 1)
            self._pattern._tape[track].append(
                TapeEvent(ETYPE_PGM, channel=channel,
                          payload={"program": program}, time=time_val)
            )
        return bar_idx, step_idx
