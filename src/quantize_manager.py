from pattern import Pattern, TapeEvent, ETYPE_KIT, ETYPE_PATCH


class QuantizeManager:
    """Opérations géométriques et de quantisation sur un Pattern.

    Reçoit le DrumPlayer comme propriétaire (owner) pour accéder à
    _pattern, _all_offsets, _cur_track, quant_idx, _wakeup, etc.
    sans dupliquer d'état.
    """

    def __init__(self, owner):
        self._p = owner   # DrumPlayer

    # ------------------------------------------------------------------
    # Offsets
    # ------------------------------------------------------------------

    def compute_offsets(self):
        """Reconstruit _all_offsets (cache float par piste/pad) depuis les notes GRID de _tape."""
        p = self._p
        pattern    = p._pattern
        num_tracks = pattern._num_tracks
        all_offsets = [
            [[] for _ in range(pattern._num_pads)]
            for _ in range(num_tracks)
        ]
        for track_idx, pad_idx, bar_idx, step_idx, vel in pattern.iter_grid():
            if track_idx < num_tracks:
                all_offsets[track_idx][pad_idx].append(
                    float(bar_idx * pattern._num_steps + step_idx)
                )
        for track_offsets in all_offsets:
            for offsets in track_offsets:
                offsets.sort()
        p._all_offsets = all_offsets   # assignation atomique
        if p.playing or p.clicking or p._note_repeat_active:
            p._wakeup.set()

    # ------------------------------------------------------------------
    # Quantisation
    # ------------------------------------------------------------------

    def apply_quant_row(self, quant_idx, row):
        p = self._p
        denom     = Pattern.QUANT_STEPS[quant_idx]
        num_steps = p._pattern._num_steps
        grid      = [i * num_steps / denom for i in range(denom)]
        row_vals  = [0] * num_steps
        for fp in grid:
            c = min(num_steps - 1, round(fp))
            row_vals[c] = 100
        p._pattern.set_grid_row(p._cur_track, row, 0, row_vals)
        p.float_offsets[row] = sorted(grid)

    def apply_quant_to_pattern(self, quant_idx=None, force_idx=4, swing_idx=0,
                               window_idx=4, quant_starts=True, quant_durations=False,
                               direction_idx=0):
        """Quantise grille (GRID) et tape (KIT/PATCH) avec force, swing, fenêtre et direction.

        force_idx     : 0..4 → 0/25/50/75/100 % d'attraction vers la grille
        swing_idx     : 0..4 → 0/25/50/75/100 % de décalage des temps impairs
        window_idx    : 0..4 → 0/25/50/75/100 % de la demi-division : zone de capture
        quant_starts  : aligner les débuts de notes
        quant_durations: aligner les durées (KIT/PATCH uniquement)
        direction_idx : 0=Proche, 1=Précédente, 2=Suivante
        """
        p = self._p
        if quant_idx is None:
            quant_idx = p.quant_idx
        if quant_idx < 0:
            return

        _PCT       = [0, 25, 50, 75, 100]
        force_pct  = _PCT[min(force_idx,  4)]
        swing_pct  = _PCT[min(swing_idx,  4)]
        window_pct = _PCT[min(window_idx, 4)]

        denom     = Pattern.QUANT_STEPS[quant_idx]
        num_steps = p._pattern._num_steps
        num_bars  = p._pattern._num_bars
        step_size = num_steps / denom
        half_step = step_size / 2.0

        # Grille avec swing : temps impairs (i % 2 == 1) décalés
        swing_shift = swing_pct / 100.0 * step_size / 2.0
        full_grid = [
            bar * num_steps + i * step_size + (swing_shift if i % 2 == 1 else 0.0)
            for bar in range(num_bars)
            for i in range(denom)
        ]

        def _find_target(pos, grid):
            if direction_idx == 1:   # Précédente : plus grand point ≤ pos
                cands = [g for g in grid if g <= pos]
                return cands[-1] if cands else grid[0]
            elif direction_idx == 2: # Suivante : plus petit point ≥ pos
                cands = [g for g in grid if g >= pos]
                return cands[0] if cands else grid[-1]
            else:                    # Proche (défaut)
                return min(grid, key=lambda g: abs(g - pos))

        def _in_window(pos, ng):
            if window_pct >= 100:
                return True
            return abs(pos - ng) <= window_pct / 100.0 * half_step

        def _snap(pos, ng):
            if force_pct >= 100:
                return ng
            return pos + (ng - pos) * force_pct / 100.0

        # --- Notes grille (GRID) ---
        if quant_starts:
            for pad_idx in range(p._pattern._num_pads):
                active = p.float_offsets[pad_idx]
                p._pattern.clear_grid_pad(p._cur_track, pad_idx)
                if not active:
                    continue
                snapped = []
                for pos in active:
                    ng = _find_target(pos, full_grid)
                    new_pos = _snap(pos, ng) if _in_window(pos, ng) else pos
                    rounded = round(new_pos)
                    snapped.append(float(rounded))
                for fp in snapped:
                    bar_idx  = int(fp) // num_steps
                    step_idx = int(fp) % num_steps
                    if 0 <= bar_idx < num_bars and 0 <= step_idx < num_steps:
                        p._pattern.set_cell(p._cur_track, pad_idx, bar_idx, step_idx, 100)
                p.float_offsets[pad_idx] = sorted(snapped)

        # --- Notes tape KIT/PATCH ---
        if not quant_starts and not quant_durations:
            return
        pattern        = p._pattern
        steps_per_beat = max(1, num_steps // pattern._num_beats)
        ms_per_step    = 60000.0 / max(1, p.bpm) / steps_per_beat
        dur_grid       = [max(1.0, i * step_size)
                          for i in range(1, num_bars * denom + 2)]
        new_tape = {}
        with pattern._lock:
            for (t, b, s), evs in list(pattern._tape.items()):
                if t != p._cur_track:
                    new_tape[(t, b, s)] = evs
                    continue
                for ev in evs:
                    if ev.etype not in (ETYPE_KIT, ETYPE_PATCH):
                        new_tape.setdefault((t, b, s), []).append(ev)
                        continue
                    n_bar, n_step = b, s
                    if quant_starts:
                        pos = b * num_steps + float(s)
                        ng  = _find_target(pos, full_grid)
                        if _in_window(pos, ng):
                            new_pos = _snap(pos, ng)
                            n_bar   = max(0, min(int(new_pos // num_steps), num_bars - 1))
                            n_step  = max(0, min(int(round(new_pos % num_steps)), num_steps - 1))
                    n_dur = ev.dur
                    if quant_durations and ev.dur > 0:
                        dur_steps = ev.dur / ms_per_step
                        ng_dur    = _find_target(dur_steps, dur_grid)
                        if _in_window(dur_steps, ng_dur):
                            n_dur = max(10, round(_snap(dur_steps, ng_dur) * ms_per_step))
                    new_tape.setdefault((t, n_bar, n_step), []).append(
                        TapeEvent(ev.etype, ev.note, ev.vel, n_dur, ev.bend)
                    )
            # Nettoyer les clés vides et mettre à jour
            pattern._tape.clear()
            pattern._tape.update({k: v for k, v in new_tape.items() if v})

    # ------------------------------------------------------------------
    # Géométrie du pattern
    # ------------------------------------------------------------------

    def double_pattern(self):
        """Double les mesures. Retourne False si impossible."""
        p = self._p
        half_steps = p._pattern._num_bars * p._pattern._num_steps
        if not p._pattern.double_bars():
            return False
        for track_offsets in p._all_offsets:
            for pad_idx in range(len(track_offsets)):
                orig    = track_offsets[pad_idx]
                shifted = [f + half_steps for f in orig]
                track_offsets[pad_idx] = sorted(orig + shifted)
        p._wakeup.set()
        return True

    def halve_pattern(self):
        """Divise par deux les mesures. Retourne False si impossible."""
        p = self._p
        if p._pattern._num_bars < 2:
            return False
        half_steps = (p._pattern._num_bars // 2) * p._pattern._num_steps
        p._pattern.halve_bars()
        for track_offsets in p._all_offsets:
            for pad_idx in range(len(track_offsets)):
                track_offsets[pad_idx] = [
                    f for f in track_offsets[pad_idx] if f < half_steps
                ]
        p._wakeup.set()
        return True
