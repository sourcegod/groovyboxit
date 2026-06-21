from dataclasses import dataclass


@dataclass
class LoopWindow:
    """Résultat du calcul de la fenêtre de boucle pour une mesure de lecture."""
    lp_start:      int
    lp_end:        int
    total_steps:   int
    loop_bars:     int
    cur_lp_start:  int   # 0 si pas de fenêtre active
    cur_loop_steps: int  # 0 si pas de fenêtre active


class LoopManager:
    """Gère la fenêtre de boucle et le décompte des répétitions d'un Pattern."""

    def __init__(self):
        self._remaining = 0   # répétitions restantes (0 = infini / inactif)

    def init_from_pattern(self, pattern):
        """Initialise le décompte depuis pattern._loop_count. Appelé à play_pattern()."""
        self._remaining = pattern._loop_count

    def compute_window(self, pattern) -> LoopWindow:
        """Calcule lp_start/lp_end/total_steps/loop_bars depuis les attributs du pattern."""
        num_steps       = pattern._num_steps
        total_pat_steps = pattern._num_bars * num_steps
        use_window = (pattern._looping
                      and (pattern._loop_start is not None
                           or pattern._loop_end is not None))
        if use_window:
            lp_start = pattern._loop_start if pattern._loop_start is not None else 0
            lp_end   = pattern._loop_end   if pattern._loop_end   is not None else total_pat_steps - 1
            lp_start = max(0, min(lp_start, total_pat_steps - 1))
            lp_end   = max(lp_start, min(lp_end, total_pat_steps - 1))
            total_steps = lp_end - lp_start + 1
            loop_bars   = max(1, -(-total_steps // num_steps))  # ceiling division
            return LoopWindow(
                lp_start=lp_start, lp_end=lp_end,
                total_steps=total_steps, loop_bars=loop_bars,
                cur_lp_start=lp_start, cur_loop_steps=total_steps,
            )
        else:
            return LoopWindow(
                lp_start=0, lp_end=total_pat_steps - 1,
                total_steps=total_pat_steps, loop_bars=pattern._num_bars,
                cur_lp_start=0, cur_loop_steps=0,
            )

    def on_measure_end(self) -> bool:
        """Décrémente le compteur si actif. Retourne True si le playback doit stopper."""
        if self._remaining > 0:
            self._remaining -= 1
            return self._remaining == 0
        return False

    @property
    def remaining(self) -> int:
        return self._remaining
