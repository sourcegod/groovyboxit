#python3
"""
    File: src/metronome.py
    Métronome : état, génération d'événements et logique enregistrement.
    Date: Sun, 14/06/2026
    Author: Coolbrother
"""


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

    METRO_EVENT = -1   # marqueur interne pour les événements click dans _run_thread

    def __init__(self):
        self.active             = False
        self.click_in_recording = True
        self.volume             = 100   # réservé future dialog
        self.sound_idx          = 0     # réservé future dialog
        self._before_rec        = False  # état active sauvegardé avant Rec

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

    def save_rec_state(self):
        """Mémorise l'état actif avant d'entrer en enregistrement."""
        self._before_rec = self.active

    def should_stop_after_rec(self):
        """Vrai si le click doit être arrêté à la fin d'un enregistrement.

        Arrête uniquement si click_in_recording l'avait démarré automatiquement
        (i.e. le click n'était pas actif avant le début de l'enregistrement).
        """
        return self.click_in_recording and not self._before_rec
