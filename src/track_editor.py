#python3
"""
    File: src/track_editor.py
    Éditeur de pistes — sélection multi-pistes, copier/couper/coller/effacer.
    Le presse-papier survit aux changements de pattern (cross-pattern).
    Date: Mon, 15/06/2026
    Author: Coolbrother
"""
import copy


class _ClipboardData:
    """Données copiées depuis une sélection de pistes."""
    def __init__(self, num_tracks, num_bars, num_steps, grid, tape):
        self.num_tracks = num_tracks   # nombre de pistes copiées
        self.num_bars   = num_bars     # mesures dans la source
        self.num_steps  = num_steps    # pas par mesure dans la source
        self.grid       = grid         # [rel_track][pad][bar][step]
        self.tape       = tape         # {(rel_track, bar, step): [TapeEvent]}


class TrackEditor:
    """Gestion de la sélection multi-pistes et des opérations presse-papier.

    La sélection est un ensemble d'indices de pistes (_sel_tracks).  Quand
    elle est vide, les opérations portent sur la seule piste courante.
    """

    def __init__(self):
        self._sel_tracks = set()            # indices des pistes sélectionnées
        self._clipboard  = None             # _ClipboardData ou None

    # ------------------------------------------------------------------
    # Sélection de pistes
    # ------------------------------------------------------------------

    def select_one(self, track_idx):
        """Réinitialise la sélection sur une seule piste."""
        self._sel_tracks = {track_idx}

    def select_all(self, num_tracks):
        """Sélectionne toutes les pistes (0..num_tracks-1)."""
        self._sel_tracks = set(range(num_tracks))

    def clear_selection(self):
        """Efface la sélection multi-pistes."""
        self._sel_tracks.clear()

    def toggle_track(self, track_idx):
        """Ajoute ou retire une piste de la sélection."""
        if track_idx in self._sel_tracks:
            self._sel_tracks.discard(track_idx)
        else:
            self._sel_tracks.add(track_idx)

    def extend_up(self, cur_track):
        """Shift+↑ : étend la sélection vers la piste du dessus.

        Initialise la sélection sur cur_track si elle était vide.
        Retourne le nouvel indice focus, ou cur_track si déjà en haut.
        """
        if cur_track <= 0:
            return cur_track
        if not self._sel_tracks:
            self._sel_tracks.add(cur_track)
        new_track = cur_track - 1
        self._sel_tracks.add(new_track)
        return new_track

    def extend_down(self, cur_track, num_tracks):
        """Shift+↓ : étend la sélection vers la piste du dessous.

        Retourne le nouvel indice focus, ou cur_track si déjà en bas.
        """
        if cur_track >= num_tracks - 1:
            return cur_track
        if not self._sel_tracks:
            self._sel_tracks.add(cur_track)
        new_track = cur_track + 1
        self._sel_tracks.add(new_track)
        return new_track

    def has_multi_selection(self):
        return len(self._sel_tracks) > 1

    def is_selected(self, track_idx):
        return track_idx in self._sel_tracks

    def get_effective_tracks(self, cur_track):
        """Pistes actives pour les opérations (triées).

        Si aucune sélection explicite, retourne [cur_track].
        """
        if self._sel_tracks:
            return sorted(self._sel_tracks)
        return [cur_track]

    # ------------------------------------------------------------------
    # Opérations presse-papier
    # ------------------------------------------------------------------

    def copy(self, pattern, cur_track):
        """Copie les pistes sélectionnées dans le presse-papier.

        Copie toutes les mesures du pattern.
        """
        tracks = self.get_effective_tracks(cur_track)
        self._clipboard = self._extract(pattern, tracks)
        return True

    def cut(self, pattern, cur_track):
        """Copie puis efface les pistes sélectionnées."""
        tracks = self.get_effective_tracks(cur_track)
        self._clipboard = self._extract(pattern, tracks)
        self._erase_tracks(pattern, tracks)
        return True

    def paste(self, pattern, cur_track):
        """Colle le presse-papier à partir de cur_track (toutes mesures).

        Ajuste silencieusement si le clipboard est plus grand que le pattern
        de destination.  Retourne False si le presse-papier est vide.
        """
        if self._clipboard is None:
            return False
        cb = self._clipboard
        n_paste   = min(cb.num_tracks, pattern._num_tracks - cur_track)
        num_bars  = min(cb.num_bars,  pattern._num_bars)
        num_steps = min(cb.num_steps, pattern._num_steps)

        for rel in range(n_paste):
            abs_t = cur_track + rel
            for pad in range(min(pattern._num_pads, len(cb.grid[rel]))):
                for bar in range(min(num_bars, len(cb.grid[rel][pad]))):
                    src = cb.grid[rel][pad][bar]
                    dst = pattern._curpattern[abs_t][pad][bar]
                    for step in range(min(num_steps, len(src), len(dst))):
                        dst[step] = src[step]

        with pattern._lock:
            for (rel_t, bar, step), events in cb.tape.items():
                if rel_t >= n_paste:
                    continue
                if bar >= pattern._num_bars or step >= pattern._num_steps:
                    continue
                abs_t = cur_track + rel_t
                pattern._tape[(abs_t, bar, step)] = list(events)

        return True

    def erase(self, pattern, cur_track):
        """Efface la sélection sans toucher au presse-papier."""
        self._erase_tracks(pattern, self.get_effective_tracks(cur_track))
        return True

    def has_clipboard(self):
        return self._clipboard is not None

    # ------------------------------------------------------------------
    # Privé
    # ------------------------------------------------------------------

    def _extract(self, pattern, tracks):
        grid = [copy.deepcopy(pattern._curpattern[t]) for t in tracks]
        tape = {}
        with pattern._lock:
            for (t, bar, step), events in pattern._tape.items():
                if t in tracks:
                    rel = tracks.index(t)
                    tape[(rel, bar, step)] = list(events)
        return _ClipboardData(
            num_tracks = len(tracks),
            num_bars   = pattern._num_bars,
            num_steps  = pattern._num_steps,
            grid       = grid,
            tape       = tape,
        )

    def _erase_tracks(self, pattern, tracks):
        for t in tracks:
            pattern.clear_track(t)
