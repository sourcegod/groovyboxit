#python3
"""
    File: src/track_editor.py
    Éditeur de pistes — sélection multi-pistes, copier/couper/coller/effacer.
    Le presse-papier survit aux changements de pattern (cross-pattern).
    Date: Mon, 15/06/2026
    Author: Coolbrother
"""
import copy
from pattern import TapeEvent


class _ClipboardData:
    """Données copiées depuis une sélection de pistes."""
    def __init__(self, num_tracks, num_bars, num_steps, grid, tape):
        self.num_tracks = num_tracks   # nombre de pistes copiées
        self.num_bars   = num_bars     # mesures dans la source
        self.num_steps  = num_steps    # pas par mesure dans la source
        self.grid       = grid         # [rel_track][pad][bar][step]
        self.tape       = tape         # {(rel_track, bar, step): [TapeEvent]}


class _EventClipboard:
    """Presse-papier d'événements MIDI individuels (multi-pistes, multi-offsets).

    Chaque entrée conserve rel_track (relatif à la piste la plus basse copiée)
    et rel_offset (relatif à l'offset minimum copié), ce qui permet de recoller
    les événements sur n'importe quelle piste cible et à n'importe quelle position.
    Ce clipboard est indépendant du _ClipboardData piste-niveau et survit aux
    changements de pattern.
    """
    def __init__(self, events):
        self.events = events   # liste de dicts avec rel_track, rel_offset + données note


class TrackEditor:
    """Gestion de la sélection multi-pistes et des opérations presse-papier.

    La sélection est un ensemble d'indices de pistes (_sel_tracks).  Quand
    elle est vide, les opérations portent sur la seule piste courante.
    """

    def __init__(self):
        self._sel_tracks      = set()       # indices des pistes sélectionnées
        self._clipboard       = None        # _ClipboardData (niveau piste) ou None
        self._event_clipboard = None        # _EventClipboard (niveau note) ou None
        self._lim_left        = None        # limiteur gauche (step 0-based, ou None)
        self._lim_right       = None        # limiteur droit  (step 0-based, ou None)

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
    # Limiteurs temporels (in/out points)
    # ------------------------------------------------------------------

    def set_lim_left(self, step):
        """Pose le limiteur gauche au step donné (0-based)."""
        self._lim_left = step

    def set_lim_right(self, step):
        """Pose le limiteur droit au step donné (0-based)."""
        self._lim_right = step

    def set_full_range(self, total_steps):
        """Étend les limiteurs à la plage complète du pattern."""
        self._lim_left  = 0
        self._lim_right = max(0, total_steps - 1)

    def reset_lims(self):
        """Réinitialise les deux limiteurs (état non défini)."""
        self._lim_left  = None
        self._lim_right = None

    @staticmethod
    def fmt_bbt(step, num_steps, steps_per_beat, total_steps):
        """Formate un step 0-based en 'bar:beat:tick' 1-based.

        Pas de borne supérieure : un step au-delà de total_steps s'affiche
        normalement (ex. step 64 dans un pattern de 64 → '5:1:1').
        """
        step = max(0, step)
        bar  = step // num_steps
        rem  = step % num_steps
        beat = rem // steps_per_beat
        tick = rem % steps_per_beat
        return f"{bar + 1}:{beat + 1}:{tick + 1}"

    # ------------------------------------------------------------------
    # Opérations presse-papier
    # ------------------------------------------------------------------

    def copy(self, pattern, cur_track):
        """Copie les pistes sélectionnées dans le presse-papier.

        Si des limiteurs sont posés, copie uniquement la plage limitée.
        Sans limiteurs, copie toutes les mesures du pattern.
        """
        tracks = self.get_effective_tracks(cur_track)
        self._clipboard = self._extract(pattern, tracks, self._lim_left, self._lim_right)
        return True

    def cut(self, pattern, cur_track):
        """Copie puis efface les pistes sélectionnées."""
        tracks = self.get_effective_tracks(cur_track)
        self._clipboard = self._extract(pattern, tracks)
        self._erase_tracks(pattern, tracks)
        return True

    def paste(self, pattern, cur_track, dest_bar=0, merge=False):
        """Colle le presse-papier à partir de cur_track et dest_bar.

        merge=False (défaut) : remplace les données existantes.
        merge=True  (Shift+V): mélange — max() sur la grille, union sur la tape.
        Étend le pattern si la zone de collage dépasse sa longueur actuelle.
        Retourne False si le presse-papier est vide.
        """
        if self._clipboard is None:
            return False
        cb = self._clipboard
        n_paste   = min(cb.num_tracks, pattern._num_tracks - cur_track)
        num_steps = min(cb.num_steps, pattern._num_steps)

        needed_bars = dest_bar + cb.num_bars
        if needed_bars > pattern._num_bars:
            pattern.resize(needed_bars, pattern._num_steps)

        for rel in range(n_paste):
            abs_t = cur_track + rel
            for pad in range(min(pattern._num_pads, len(cb.grid[rel]))):
                for rel_bar in range(min(cb.num_bars, len(cb.grid[rel][pad]))):
                    dst_bar = dest_bar + rel_bar
                    if dst_bar >= pattern._num_bars:
                        break
                    src = cb.grid[rel][pad][rel_bar]
                    dst = pattern._curpattern[abs_t][pad][dst_bar]
                    n = min(num_steps, len(src), len(dst))
                    if merge:
                        for step in range(n):
                            dst[step] = max(dst[step], src[step])
                    else:
                        for step in range(n):
                            dst[step] = src[step]

        with pattern._lock:
            for (rel_t, rel_bar, step), events in cb.tape.items():
                if rel_t >= n_paste:
                    continue
                dst_bar = dest_bar + rel_bar
                if dst_bar >= pattern._num_bars or step >= pattern._num_steps:
                    continue
                abs_t = cur_track + rel_t
                key = (abs_t, dst_bar, step)
                if merge and key in pattern._tape:
                    pattern._tape[key] = pattern._tape[key] + list(events)
                else:
                    pattern._tape[key] = list(events)

        return True

    def erase_grid(self, pattern, cur_track):
        """Copie dans le presse-papier, puis efface la grille et (si limiteurs) la tape.

        Sans limiteurs : efface toute la grille, tape préservée (comportement d'origine).
        Avec limiteurs : efface grille + _tape + _bend_tape + _mod_tape dans la plage.
        Le clipboard ne contient que la plage limitée (barres relatives à l'origine).
        Raccourci DAW : Ctrl+X (Erase).
        """
        tracks = self.get_effective_tracks(cur_track)
        lim_l = self._lim_left
        lim_r = self._lim_right
        self._clipboard = self._extract(pattern, tracks, lim_l, lim_r)
        for t in tracks:
            for pad in pattern._curpattern[t]:
                for bar_idx, bar in enumerate(pad):
                    if lim_l is None or lim_r is None:
                        bar[:] = [0] * len(bar)
                    else:
                        for step_idx in range(len(bar)):
                            g = bar_idx * pattern._num_steps + step_idx
                            if lim_l <= g <= lim_r:
                                bar[step_idx] = 0
            if lim_l is not None and lim_r is not None:
                self._erase_tape_range(pattern, t, lim_l, lim_r)
        return True

    def erase(self, pattern, cur_track):
        """Efface la sélection (grille + tape) sans toucher au presse-papier.

        Raccourci DAW : Ctrl+Suppr.
        """
        self._erase_tracks(pattern, self.get_effective_tracks(cur_track))
        return True

    def has_clipboard(self):
        return self._clipboard is not None

    # ------------------------------------------------------------------
    # Presse-papier événements (niveau note, multi-pistes)
    # ------------------------------------------------------------------

    def copy_events(self, events):
        """Copie une liste d'événements dans le presse-papier d'événements.

        Conserve rel_track (delta par rapport à la piste la plus basse) et
        rel_offset (delta par rapport à l'offset le plus petit). Retourne le
        nombre d'événements copiés.
        """
        notes = [e for e in events if e.get("type") == "note"]
        if not notes:
            return 0
        anchor_track  = min(e["track"]  for e in notes)
        anchor_offset = min(e["offset"] for e in notes)
        self._event_clipboard = _EventClipboard([
            {**e,
             "rel_track":  e["track"]  - anchor_track,
             "rel_offset": e["offset"] - anchor_offset}
            for e in notes
        ])
        return len(notes)

    def paste_events(self, pattern, target_track, target_offset):
        """Colle le presse-papier d'événements à partir de (target_track, target_offset).

        Chaque note est replacée sur target_track + rel_track, à l'offset
        target_offset + rel_offset. Les événements hors des limites du pattern
        sont ignorés. Retourne le nombre d'événements collés.
        """
        if self._event_clipboard is None:
            return 0
        ns     = pattern._num_steps
        pasted = 0
        for ev in self._event_clipboard.events:
            abs_track  = target_track  + ev["rel_track"]
            abs_offset = target_offset + ev["rel_offset"]
            bar, step  = divmod(abs_offset, ns)
            if abs_track >= pattern._num_tracks:
                continue
            if bar >= pattern._num_bars or step >= ns:
                continue
            if ev["etype"] == "G":
                pad = ev["pad"]
                if pad < len(pattern._curpattern[abs_track]):
                    pattern._curpattern[abs_track][pad][bar][step] = ev["vel"]
                    pasted += 1
            elif ev["etype"] in ("K", "P"):
                te  = TapeEvent(ev["etype"], ev["pad"], ev["vel"],
                                ev["dur"], ev.get("bend", 0))
                key = (abs_track, bar, step)
                with pattern._lock:
                    pattern._tape.setdefault(key, []).append(te)
                pasted += 1
        return pasted

    def has_event_clipboard(self):
        return self._event_clipboard is not None

    # ------------------------------------------------------------------
    # Privé
    # ------------------------------------------------------------------

    def _extract(self, pattern, tracks, lim_l=None, lim_r=None):
        """Extrait les pistes dans le clipboard.

        Sans limiteurs : copie tout le pattern (barres absolues).
        Avec limiteurs : copie seulement la plage [lim_l, lim_r]; les indices
        de barre dans le clipboard sont relatifs au début de la plage (0-based).
        """
        ns = pattern._num_steps
        if lim_l is not None and lim_r is not None:
            start_bar = lim_l // ns
            end_bar   = min(lim_r // ns, pattern._num_bars - 1)
            num_bars  = max(1, end_bar - start_bar + 1)
            grid = []
            for t in tracks:
                track_grid = []
                for pad_data in pattern._curpattern[t]:
                    pad_bars = []
                    for rel_bar in range(num_bars):
                        src_bar = start_bar + rel_bar
                        if src_bar < len(pad_data):
                            pad_bars.append(list(pad_data[src_bar]))
                        else:
                            pad_bars.append([0] * ns)
                    track_grid.append(pad_bars)
                grid.append(track_grid)
            tape = {}
            with pattern._lock:
                for (t, bar, step), events in pattern._tape.items():
                    if t in tracks and start_bar <= bar <= end_bar:
                        rel = tracks.index(t)
                        tape[(rel, bar - start_bar, step)] = list(events)
        else:
            grid = [copy.deepcopy(pattern._curpattern[t]) for t in tracks]
            num_bars = pattern._num_bars
            tape = {}
            with pattern._lock:
                for (t, bar, step), events in pattern._tape.items():
                    if t in tracks:
                        rel = tracks.index(t)
                        tape[(rel, bar, step)] = list(events)
        return _ClipboardData(
            num_tracks = len(tracks),
            num_bars   = num_bars,
            num_steps  = ns,
            grid       = grid,
            tape       = tape,
        )

    def _erase_tracks(self, pattern, tracks):
        lim_l = self._lim_left
        lim_r = self._lim_right
        if lim_l is None or lim_r is None:
            for t in tracks:
                pattern.clear_track(t)
        else:
            for t in tracks:
                for pad in pattern._curpattern[t]:
                    for bar_idx, bar in enumerate(pad):
                        for step_idx in range(len(bar)):
                            g = bar_idx * pattern._num_steps + step_idx
                            if lim_l <= g <= lim_r:
                                bar[step_idx] = 0
                self._erase_tape_range(pattern, t, lim_l, lim_r)

    def _erase_tape_range(self, pattern, track, lim_l, lim_r):
        """Efface _tape, _bend_tape, _mod_tape pour `track` dans [lim_l, lim_r]."""
        with pattern._lock:
            to_del = [
                k for k in pattern._tape
                if k[0] == track
                and lim_l <= k[1] * pattern._num_steps + k[2] <= lim_r
            ]
            for k in to_del:
                del pattern._tape[k]
        if track < len(pattern._bend_tape):
            pattern._bend_tape[track] = [
                (off, b) for off, b in pattern._bend_tape[track]
                if not (lim_l <= off <= lim_r)
            ]
        if track < len(pattern._mod_tape):
            pattern._mod_tape[track] = [
                (off, m) for off, m in pattern._mod_tape[track]
                if not (lim_l <= off <= lim_r)
            ]
