#python3
"""
    File: src/metronome.py
    Métronome : état, génération d'événements et logique enregistrement.
    Date: Sun, 14/06/2026
    Author: Coolbrother
"""
import time as _time


class Metronome:
    """Encapsule l'état et la logique du métronome (click).

    DrumPlayer possède une instance (_metro) et délègue :
    - la génération d'événements (build_events) dans _run_thread
    - la sauvegarde/restauration de l'état click autour de l'enregistrement

    Attributs publics configurables (future boîte de dialogue) :
        active            -- click en cours
        click_in_recording -- activer le click automatiquement lors d'un Rec
        volume            -- volume du click (0..100), non encore utilisé
        sound_idx         -- index du son de click, non encore utilisé
    """

    METRO_EVENT     = -1   # marqueur interne pour les événements click dans _run_thread
    TAP_MIN_TAPS    = 4   # frappes minimales avant d'émettre un BPM (1 mesure à 4/4)
    TAP_MAX_TAPS    = 8   # nombre maximum de frappes conservées pour la moyenne
    TAP_RESET_DELAY = 2.0 # délai (s) sans frappe au-delà duquel on repart de zéro
    BPM_MIN         = 20
    BPM_MAX         = 300

    def __init__(self):
        self.active             = False
        self.click_in_recording = True
        self.volume             = 100   # réservé future dialog
        self.sound_idx          = 0     # réservé future dialog
        self._before_rec        = False  # état active sauvegardé avant Rec
        self._tap_times         = []     # timestamps des frappes (monotonic)

    # ------------------------------------------------------------------

    def build_events(self, loop_bars, num_steps, num_beats, step_duration, elapsed):
        """Construit la liste d'événements métronome pour la mesure courante.

        Retourne une liste de tuples (t_sec, METRO_EVENT, beat, 0) prêts à
        être insérés dans la liste d'événements de _run_thread.
        """
        if not self.active:
            return []
        events = []
        steps_per_beat = num_steps // num_beats
        for bar_idx in range(loop_bars):
            for beat in range(num_beats):
                t_sec = (bar_idx * num_steps + beat * steps_per_beat) * step_duration
                if t_sec > elapsed - 0.002:
                    events.append((t_sec, self.METRO_EVENT, beat, 0))
        return events

    # ------------------------------------------------------------------

    def tap(self, t=None):
        """Enregistre une frappe et retourne le nouveau BPM, ou None si insuffisant.

        t : timestamp (float, monotonic). Si None, utilise time.monotonic().

        Logique :
        - Si la dernière frappe date de plus de TAP_RESET_DELAY secondes, on repart
          de zéro (la frappe courante devient la première d'une nouvelle séquence).
        - BPM calculé en moyennant les intervalles entre les TAP_MAX_TAPS dernières
          frappes consécutives.
        - Retourne None tant qu'il n'y a pas au moins TAP_MIN_TAPS frappes
          (= une mesure à 4/4 → 3 intervalles mesurés, estimation stable).
        - Le BPM retourné est clampé entre BPM_MIN et BPM_MAX.
        """
        now = t if t is not None else _time.monotonic()

        if self._tap_times and (now - self._tap_times[-1]) > self.TAP_RESET_DELAY:
            self._tap_times = []

        self._tap_times.append(now)

        # Limiter à TAP_MAX_TAPS + 1 timestamps (= TAP_MAX_TAPS intervalles)
        if len(self._tap_times) > self.TAP_MAX_TAPS + 1:
            self._tap_times = self._tap_times[-(self.TAP_MAX_TAPS + 1):]

        if len(self._tap_times) < self.TAP_MIN_TAPS:
            return None

        intervals = [self._tap_times[i] - self._tap_times[i - 1]
                     for i in range(1, len(self._tap_times))]
        avg_interval = sum(intervals) / len(intervals)
        bpm = 60.0 / avg_interval
        return max(self.BPM_MIN, min(self.BPM_MAX, round(bpm)))

    def is_fresh_sequence(self, t=None):
        """Vrai si la prochaine frappe démarrerait une nouvelle séquence.

        Permet à l'appelant de sauvegarder un état undo avant la première
        frappe d'une nouvelle séquence, sans en créer une par tap.
        """
        if not self._tap_times:
            return True
        now = t if t is not None else _time.monotonic()
        return (now - self._tap_times[-1]) > self.TAP_RESET_DELAY

    def reset_tap(self):
        """Réinitialise la séquence de frappes Tap Tempo."""
        self._tap_times = []

    # ------------------------------------------------------------------

    def save_rec_state(self):
        """Mémorise l'état actif avant d'entrer en enregistrement."""
        self._before_rec = self.active

    def should_stop_after_rec(self):
        """Vrai si le click doit être arrêté à la fin d'un enregistrement.

        Arrête uniquement si click_in_recording l'avait démarré automatiquement
        (i.e. le click n'était pas actif avant le début de l'enregistrement).
        """
        return self.click_in_recording and not self._before_rec
