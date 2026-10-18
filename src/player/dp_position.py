import math
import time


class PositionMixin:
    """DrumPlayer — position du playhead, chaînes de statut et déplacements."""

    def goto_start(self):
        """Positionne le playhead au début du pattern."""
        self._go_to_offset(None)

    #--------------------------------------------------------------------------

    def goto_end(self):
        """Positionne le playhead à la fin du pattern (dernier pas)."""
        total_steps = self._pattern._num_bars * self._pattern._num_steps
        self._go_to_offset(float(total_steps - 1))

    #--------------------------------------------------------------------------

    def _go_to_offset(self, offset):
        """Déplace le playhead à offset (pas flottants ; None = début).
        Stoppe et redémarre le thread si nécessaire pour garantir la prise en compte."""
        active = self.playing or self.clicking or self._note_repeat_active
        if active:
            self.stop_thread()
        self._resume_offset = offset
        if active:
            self.start_thread()

    #--------------------------------------------------------------------------

    def _current_offset(self):
        """Retourne la position courante du playhead en pas flottants."""
        if not (self.playing or self.clicking or self._note_repeat_active):
            return self._resume_offset or 0.0
        now = time.perf_counter()
        if self._cur_loop_steps > 0:
            measure_secs = self._cur_loop_steps * self.step_duration
        else:
            measure_secs = self._pattern._num_bars * self._pattern._num_steps * self.step_duration
        ref = self._measure_start if self._measure_start is not None else now
        return self._cur_lp_start + ((now - ref) % measure_secs) / self.step_duration

    #--------------------------------------------------------------------------

    def position_str(self):
        """Retourne 'bar:beat:tick / Bar:Beat:Tick' (1-based) pour la barre de statut."""
        num_steps      = self._pattern._num_steps
        num_beats      = self._pattern._num_beats
        num_bars       = self._pattern._num_bars
        steps_per_beat = max(1, num_steps // num_beats)
        total_steps    = num_bars * num_steps

        def _fmt(step_idx):
            step_idx = max(0, step_idx)   # pas de borne supérieure : on peut dépasser la fin
            bar  = step_idx // num_steps
            rem  = step_idx % num_steps
            beat = rem // steps_per_beat
            tick = rem % steps_per_beat
            return f"{bar + 1}:{beat + 1}:{tick + 1}"

        cur = int(self._current_offset())
        last = total_steps - 1
        return f"{_fmt(cur)} / {_fmt(last)}"

    def time_str(self):
        """Retourne 'cur.msec / total.msec' pour la barre de statut."""
        def _fmt(t):
            t    = round(max(0.0, t), 3)
            secs = int(t)
            msec = int(round((t - secs) * 1000))
            return f"{secs}.{msec:03d}"

        total_steps = self._pattern._num_bars * self._pattern._num_steps
        cur   = self._current_offset() * self.step_duration
        total = total_steps * self.step_duration
        return f"{_fmt(cur)} / {_fmt(total)}"

    #--------------------------------------------------------------------------

    def move_by_ticks(self, ticks):
        """Déplace le playhead de ±ticks pas (clamp bas à 0, pas de borne supérieure)."""
        new_off = max(0.0, self._current_offset() + ticks)
        self._go_to_offset(new_off)

    def move_by_beats(self, beats):
        """Déplace le playhead de ±beats battements (clamp via move_by_ticks)."""
        steps_per_beat = self._pattern._num_steps // self._pattern._num_beats
        self.move_by_ticks(beats * steps_per_beat)

    def move_by_seconds(self, seconds):
        """Déplace le playhead en se calant sur les frontières entières de secondes.

        W (seconds>0) : floor(position courante) + n secondes.
        B (seconds<0) : ceil(position courante)  - n secondes.
        Garantit un affichage toujours en valeur entière (0.000, 1.000, 2.000…).
        """
        cur_secs = round(self._current_offset() * self.step_duration, 9)
        if seconds >= 0:
            base = math.floor(cur_secs)
        else:
            base = math.ceil(cur_secs)
        new_secs = max(0.0, base + seconds)
        self._go_to_offset(new_secs / self.step_duration)

    def move_by_bars(self, bars):
        """Déplace le playhead de ±bars mesures (wrapping cyclique, usage interne)."""
        total   = self._pattern._num_bars * self._pattern._num_steps
        new_off = (self._current_offset() + bars * self._pattern._num_steps) % total
        self._go_to_offset(new_off)

    def navigate_bar(self, direction):
        """Navigation par mesure style DAW (sans wrap).

        direction = -1 (PageUp) :
          - en cours de mesure → début de la mesure courante
          - au début de mesure → début de la mesure précédente
          - mesure 0           → reste à 0
        direction = +1 (PageDown) :
          - toujours           → début de la mesure suivante
          - dernière mesure    → dernier tick du pattern (total - 1)
        """
        num_steps = self._pattern._num_steps
        num_bars  = self._pattern._num_bars
        total     = num_bars * num_steps
        cur_off   = self._current_offset()
        cur_bar   = int(cur_off) // num_steps
        bar_start = cur_bar * num_steps
        now       = time.perf_counter()

        if direction < 0:
            # Fenêtre 100 ms : si navigate_bar a été appelé récemment, on
            # considère le playhead « au début de la mesure » même s'il a
            # légèrement avancé depuis.
            in_window = (now - self._last_nav_time < 0.1)
            if cur_off - bar_start > 0.01 and not in_window:
                target = float(bar_start)
            elif cur_bar > 0:
                target = float((cur_bar - 1) * num_steps)
            else:
                # Début du pattern : en song mode, passer au pattern précédent
                if (self._song_mode and self._song_pos > 0
                        and self._on_song_cross_nav_cb):
                    self._last_nav_time = now
                    self._on_song_cross_nav_cb(-1)
                    return
                target = 0.0
        else:
            next_bar = cur_bar + 1
            if next_bar >= num_bars:
                # En song mode : passer au pattern suivant s'il existe
                if (self._song_mode
                        and self._song_pos + 1 < len(self._song_sequence)
                        and self._on_song_cross_nav_cb):
                    self._last_nav_time = now
                    self._on_song_cross_nav_cb(+1)
                    return
                # Hors song mode : autoriser le dépassement (ex. 4:4:4 → 5:1:1)
                # afin de permettre un collage après la fin du pattern.
            target = float(next_bar * num_steps)

        self._last_nav_time = now
        self._go_to_offset(target)
