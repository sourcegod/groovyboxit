from pattern import Pattern, TapeEvent


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
        """Reconstruit _all_offsets et les entrées "G" du tape depuis _curpattern."""
        p = self._p
        pattern    = p._pattern
        num_tracks = pattern._num_tracks
        all_offsets = []
        new_grid = {}   # (track, bar, step) -> [TapeEvent("G", ...)]
        for track_idx in range(num_tracks):
            track_offsets = []
            for pad_idx, pad in enumerate(pattern._curpattern[track_idx]):
                offsets = []
                base = 0
                for bar_idx, bar in enumerate(pad):
                    for step_idx, active in enumerate(bar):
                        if active:
                            offsets.append(float(base + step_idx))
                            vel = 100 if isinstance(active, bool) else int(active)
                            key = (track_idx, bar_idx, step_idx)
                            new_grid.setdefault(key, []).append(
                                TapeEvent(etype="G", note=pad_idx, vel=vel, dur=0, bend=0)
                            )
                    base += len(bar)
                track_offsets.append(offsets)
            all_offsets.append(track_offsets)
        p._all_offsets = all_offsets   # assignation atomique
        with pattern._lock:
            for key in list(pattern._tape.keys()):
                pattern._tape[key] = [ev for ev in pattern._tape[key]
                                      if ev.etype != "G"]
                if not pattern._tape[key]:
                    del pattern._tape[key]
            for key, evs in new_grid.items():
                pattern._tape.setdefault(key, []).extend(evs)
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
        pad       = p._pattern._curpattern[p._cur_track][row]
        for c in range(num_steps):
            pad[0][c] = False
        for fp in grid:
            c = min(num_steps - 1, round(fp))
            pad[0][c] = True
        p.float_offsets[row] = sorted(grid)

    def apply_quant_to_pattern(self, quant_idx=None):
        p = self._p
        if quant_idx is None:
            quant_idx = p.quant_idx
        if quant_idx < 0:
            return
        denom     = Pattern.QUANT_STEPS[quant_idx]
        num_steps = p._pattern._num_steps
        grid_per_bar = [i * num_steps / denom for i in range(denom)]
        full_grid = [
            bar_idx * num_steps + gp
            for bar_idx in range(p._pattern._num_bars)
            for gp in grid_per_bar
        ]
        for pad_idx in range(p._pattern._num_pads):
            pad    = p._pattern._curpattern[p._cur_track][pad_idx]
            active = p.float_offsets[pad_idx]
            for bar in pad:
                bar[:] = [False] * len(bar)
            if not active:
                continue
            snapped = set()
            for pos in active:
                nearest = min(full_grid, key=lambda pt: abs(pt - pos))
                snapped.add(nearest)
            for fp in snapped:
                bar_idx  = int(fp // num_steps)
                step_idx = round(fp % num_steps) % num_steps
                if bar_idx < p._pattern._num_bars:
                    pad[bar_idx][step_idx] = True
            p.float_offsets[pad_idx] = sorted(snapped)

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
