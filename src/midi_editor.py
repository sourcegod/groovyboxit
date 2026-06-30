#python3
"""
    File: src/midi_editor.py
    MidiEditor — sélection, manipulation et édition des événements MIDI d'un pattern.
    Date: Fri, 26/06/2026
    Author: Coolbrother
"""


class MidiEditor:
    """Logique d'édition des événements MIDI d'un pattern.

    Source principale : _curpattern[track][pad][bar][step] (grille séquenceur).
    Mode étendu (VIEW_ALL) : grille + _tape (K/P) + _bend_tape + _mod_tape.
    """

    VIEW_NOTES = 0   # notes de la grille de la piste courante
    VIEW_ALL   = 1   # tous les événements MIDI des pistes sélectionnées

    def __init__(self):
        self._view_mode = self.VIEW_NOTES
        self._cur_idx   = 0   # index courant dans la liste d'affichage

    # ------------------------------------------------------------------
    # Collecte d'événements
    # ------------------------------------------------------------------

    def get_note_events(self, pattern, track_idx, lim_left=None, lim_right=None):
        """Retourne toutes les notes (grille + tape K/P) d'une piste.

        - _curpattern[track_idx][pad][bar][step] → etype 'G'
        - _tape[(track_idx, bar, step)] etype K/P → inclus tel quel

        Les deux sources sont fusionnées ici car _tape peut contenir des notes
        enregistrées live (clavier MIDI) absentes de la grille.
        Refactorisation future prévue pour unifier les deux structures.
        """
        events = []

        # --- Grille séquenceur ---
        if track_idx < len(pattern._curpattern):
            for pad_idx, pad_data in enumerate(pattern._curpattern[track_idx]):
                for bar_idx, bar_data in enumerate(pad_data):
                    for step_idx, vel in enumerate(bar_data):
                        if vel <= 0:
                            continue
                        offset = bar_idx * pattern._num_steps + step_idx
                        if lim_left  is not None and offset < lim_left:
                            continue
                        if lim_right is not None and offset > lim_right:
                            continue
                        dur = (pattern._voices[pad_idx]["duration_ms"]
                               if pad_idx < len(pattern._voices) else 500)
                        events.append({
                            "type":   "note",
                            "etype":  "G",
                            "track":  track_idx,
                            "pad":    pad_idx,
                            "bar":    bar_idx,
                            "step":   step_idx,
                            "offset": offset,
                            "vel":    vel,
                            "dur":    dur,
                        })

        # --- Tape enregistrée (K/P) ---
        for (t, b, s), tape_list in sorted(pattern._tape.items()):
            if t != track_idx:
                continue
            offset = b * pattern._num_steps + s
            if lim_left  is not None and offset < lim_left:
                continue
            if lim_right is not None and offset > lim_right:
                continue
            for i, ev in enumerate(tape_list):
                if ev.etype not in ("K", "P"):
                    continue
                events.append({
                    "type":      "note",
                    "etype":     ev.etype,
                    "track":     t,
                    "bar":       b,
                    "step":      s,
                    "offset":    offset,
                    "pad":       ev.note,   # K: index pad kit ; P: note MIDI brute
                    "vel":       ev.vel,
                    "dur":       ev.dur,
                    "bend":      ev.bend,
                    "event_idx": i,
                })

        events.sort(key=lambda e: (e["offset"], e["pad"]))
        return events

    def get_all_events(self, pattern, sel_tracks, lim_left=None, lim_right=None):
        """Retourne tous les événements MIDI des pistes sélectionnées.

        Inclut : notes (grille G + tape K/P via get_note_events), bend_tape, mod_tape.
        La tape K/P n'est PAS relue ici : get_note_events() l'inclut déjà.
        """
        sel_set = set(sel_tracks)
        events  = []

        # Notes (grille + tape K/P)
        for t in sorted(sel_set):
            evs = self.get_note_events(pattern, t, lim_left, lim_right)
            events.extend(evs)

        # Automation pitch bend
        for t in sorted(sel_set):
            if t < len(pattern._bend_tape):
                for off, val in sorted(pattern._bend_tape[t]):
                    if lim_left  is not None and off < lim_left:
                        continue
                    if lim_right is not None and off > lim_right:
                        continue
                    b, s = divmod(int(off), pattern._num_steps)
                    events.append({
                        "type":   "bend",
                        "track":  t,
                        "bar":    b,
                        "step":   s,
                        "offset": off,
                        "value":  val,
                    })

        # Automation mod wheel
        for t in sorted(sel_set):
            if t < len(pattern._mod_tape):
                for off, val in sorted(pattern._mod_tape[t]):
                    if lim_left  is not None and off < lim_left:
                        continue
                    if lim_right is not None and off > lim_right:
                        continue
                    b, s = divmod(int(off), pattern._num_steps)
                    events.append({
                        "type":   "mod",
                        "track":  t,
                        "bar":    b,
                        "step":   s,
                        "offset": off,
                        "value":  val,
                    })

        events.sort(key=lambda e: (e["offset"], e["track"]))
        return events

    # ------------------------------------------------------------------
    # Opérations d'édition
    # ------------------------------------------------------------------

    def delete_event(self, pattern, ev):
        """Supprime un événement. Retourne True si supprimé."""
        if ev.get("type") != "note":
            return False
        if ev.get("etype") == "G":
            return self._delete_grid_event(pattern, ev)
        return self._delete_tape_event(pattern, ev)

    def _delete_grid_event(self, pattern, ev):
        t, pad, b, s = ev["track"], ev["pad"], ev["bar"], ev["step"]
        if t >= len(pattern._curpattern):
            return False
        if pad >= len(pattern._curpattern[t]):
            return False
        if b >= len(pattern._curpattern[t][pad]):
            return False
        if s >= len(pattern._curpattern[t][pad][b]):
            return False
        pattern._curpattern[t][pad][b][s] = 0
        return True

    def _delete_tape_event(self, pattern, ev):
        key = (ev["track"], ev["bar"], ev["step"])
        with pattern._lock:
            lst = pattern._tape.get(key)
            if lst is None:
                return False
            idx = ev.get("event_idx", -1)
            if idx < 0 or idx >= len(lst):
                return False
            del lst[idx]
            if not lst:
                del pattern._tape[key]
        return True

    # ------------------------------------------------------------------
    # Navigation par groupes (accord = plusieurs notes au même offset)
    # ------------------------------------------------------------------

    def group_indices(self, events, idx):
        """Retourne les indices des événements au même offset que events[idx]."""
        if not events or idx >= len(events):
            return []
        offset = events[idx]["offset"]
        return [i for i, e in enumerate(events) if e["offset"] == offset]

    def first_of_next_group(self, events, idx):
        """Retourne l'index du premier événement du groupe suivant, ou -1."""
        if not events or idx >= len(events):
            return -1
        cur_offset = events[idx]["offset"]
        for i in range(idx + 1, len(events)):
            if events[i]["offset"] > cur_offset:
                return i
        return -1

    def first_of_prev_group(self, events, idx):
        """Retourne l'index du premier événement du groupe précédent, ou -1."""
        if not events or idx >= len(events):
            return -1
        cur_offset = events[idx]["offset"]
        prev_any = -1
        for i in range(idx - 1, -1, -1):
            if events[i]["offset"] < cur_offset:
                prev_any = i
                break
        if prev_any < 0:
            return -1
        target_offset = events[prev_any]["offset"]
        for i in range(len(events)):
            if events[i]["offset"] == target_offset:
                return i
        return -1

    # ------------------------------------------------------------------

    def edit_tape_note(self, pattern, ev, new_note=None, new_vel=None,
                       new_bar=None, new_step=None, new_dur=None):
        """Modifie un événement tape (etype K ou P). Retourne le nouvel event_info ou None."""
        from pattern import TapeEvent
        etype = ev.get("etype")
        if etype not in ("K", "P"):
            return None
        old_key = (ev["track"], ev["bar"], ev["step"])
        old_idx = ev.get("event_idx", -1)
        t       = ev["track"]
        n_note  = new_note if new_note is not None else ev["pad"]
        n_vel   = max(1, min(127, new_vel  if new_vel  is not None else ev["vel"]))
        n_bar   = new_bar  if new_bar  is not None else ev["bar"]
        n_step  = new_step if new_step is not None else ev["step"]
        n_dur   = max(10,  new_dur  if new_dur  is not None else ev.get("dur", 500))
        n_bend  = ev.get("bend", 0)
        if n_bar < 0 or n_bar >= pattern._num_bars:
            return None
        if n_step < 0 or n_step >= pattern._num_steps:
            return None
        with pattern._lock:
            lst = pattern._tape.get(old_key)
            if lst is None or old_idx < 0 or old_idx >= len(lst):
                return None
            del lst[old_idx]
            if not lst:
                del pattern._tape[old_key]
            new_key = (t, n_bar, n_step)
            pattern._tape.setdefault(new_key, []).append(
                TapeEvent(etype, n_note, n_vel, n_dur, n_bend)
            )
            new_idx = len(pattern._tape[new_key]) - 1
        return {
            "type":      "note",
            "etype":     etype,
            "track":     t,
            "bar":       n_bar,
            "step":      n_step,
            "offset":    n_bar * pattern._num_steps + n_step,
            "pad":       n_note,
            "vel":       n_vel,
            "dur":       n_dur,
            "bend":      n_bend,
            "event_idx": new_idx,
        }

    def edit_grid_note(self, pattern, ev, new_pad=None, new_vel=None,
                       new_bar=None, new_step=None):
        """Modifie un événement grille (etype G). Retourne le nouvel event_info ou None."""
        if ev.get("etype") != "G":
            return None
        t        = ev["track"]
        old_pad  = ev["pad"]
        old_bar  = ev["bar"]
        old_step = ev["step"]
        old_vel  = ev["vel"]
        n_pad    = new_pad  if new_pad  is not None else old_pad
        n_vel    = new_vel  if new_vel  is not None else old_vel
        n_bar    = new_bar  if new_bar  is not None else old_bar
        n_step   = new_step if new_step is not None else old_step

        grid = pattern._curpattern
        if t >= len(grid):
            return None

        # Effacer l'ancienne cellule
        if (old_pad < len(grid[t]) and
                old_bar  < len(grid[t][old_pad]) and
                old_step < len(grid[t][old_pad][old_bar])):
            grid[t][old_pad][old_bar][old_step] = 0

        # Écrire à la nouvelle position
        if (n_pad < len(grid[t]) and
                n_bar  < len(grid[t][n_pad]) and
                n_step < len(grid[t][n_pad][n_bar])):
            grid[t][n_pad][n_bar][n_step] = max(1, min(127, n_vel))
        else:
            return None

        dur = (pattern._voices[n_pad]["duration_ms"]
               if n_pad < len(pattern._voices) else 500)
        return {
            "type":   "note",
            "etype":  "G",
            "track":  t,
            "pad":    n_pad,
            "bar":    n_bar,
            "step":   n_step,
            "offset": n_bar * pattern._num_steps + n_step,
            "vel":    n_vel,
            "dur":    dur,
        }
