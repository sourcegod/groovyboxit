#python3
"""
    File: src/midi_editor.py
    MidiEditor — sélection, manipulation et édition des événements MIDI d'un pattern.
    Date: Fri, 26/06/2026
    Author: Coolbrother
"""

from pattern import ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH


class MidiEditor:
    """Logique d'édition des événements MIDI d'un pattern.

    Source unique : _tape[(track, bar, step)] = [TapeEvent], etype
    ETYPE_GRID/ETYPE_KIT/ETYPE_PATCH.
    Mode étendu (VIEW_ALL) : _tape (idem) + _bend_tape + _mod_tape.
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
        """Retourne toutes les notes (GRID/KIT/PATCH) d'une piste, depuis _tape."""
        events = []

        for (t, b, s), tape_list in sorted(pattern._tape.items()):
            if t != track_idx:
                continue
            offset = b * pattern._num_steps + s
            if lim_left  is not None and offset < lim_left:
                continue
            if lim_right is not None and offset > lim_right:
                continue
            for i, ev in enumerate(tape_list):
                if ev.etype == ETYPE_GRID:
                    dur = (pattern._voices[ev.note]["duration_ms"]
                           if ev.note < len(pattern._voices) else 500)
                    events.append({
                        "type":      "note",
                        "etype":     ETYPE_GRID,
                        "track":     t,
                        "pad":       ev.note,
                        "bar":       b,
                        "step":      s,
                        "offset":    offset,
                        "vel":       ev.vel,
                        "dur":       dur,
                        "event_idx": i,
                    })
                else:
                    events.append({
                        "type":      "note",
                        "etype":     ev.etype,
                        "track":     t,
                        "bar":       b,
                        "step":      s,
                        "offset":    offset,
                        "pad":       ev.note,   # KIT: index pad kit ; PATCH: note MIDI brute
                        "vel":       ev.vel,
                        "dur":       ev.dur,
                        "bend":      ev.bend,
                        "event_idx": i,
                    })

        events.sort(key=lambda e: (e["offset"], e["pad"]))
        return events

    def get_all_events(self, pattern, sel_tracks, lim_left=None, lim_right=None):
        """Retourne tous les événements MIDI des pistes sélectionnées.

        Inclut : notes (GRID/KIT/PATCH via get_note_events), bend_tape, mod_tape.
        """
        sel_set = set(sel_tracks)
        events  = []

        # Notes (GRID/KIT/PATCH, via _tape)
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
        if ev.get("etype") == ETYPE_GRID:
            return self._delete_grid_event(pattern, ev)
        return self._delete_tape_event(pattern, ev)

    def _delete_grid_event(self, pattern, ev):
        t, pad, b, s = ev["track"], ev["pad"], ev["bar"], ev["step"]
        if not (0 <= t < pattern._num_tracks):
            return False
        if not (0 <= pad < pattern._num_pads):
            return False
        if not (0 <= b < pattern._num_bars):
            return False
        if not (0 <= s < pattern._num_steps):
            return False
        pattern.set_cell(t, pad, b, s, 0)
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
        """Modifie un événement tape (etype KIT ou PATCH). Retourne le nouvel event_info ou None."""
        from pattern import TapeEvent
        etype = ev.get("etype")
        if etype not in (ETYPE_KIT, ETYPE_PATCH):
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
        """Modifie un événement grille (etype GRID). Retourne le nouvel event_info ou None."""
        if ev.get("etype") != ETYPE_GRID:
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

        if not (0 <= t < pattern._num_tracks):
            return None
        if not (0 <= n_pad < pattern._num_pads):
            return None
        if not (0 <= n_bar < pattern._num_bars):
            return None
        if not (0 <= n_step < pattern._num_steps):
            return None

        n_vel = max(1, min(127, n_vel))
        pattern.set_cell(t, old_pad, old_bar, old_step, 0)
        pattern.set_cell(t, n_pad, n_bar, n_step, n_vel)

        dur = (pattern._voices[n_pad]["duration_ms"]
               if n_pad < len(pattern._voices) else 500)
        return {
            "type":   "note",
            "etype":  ETYPE_GRID,
            "track":  t,
            "pad":    n_pad,
            "bar":    n_bar,
            "step":   n_step,
            "offset": n_bar * pattern._num_steps + n_step,
            "vel":    n_vel,
            "dur":    dur,
        }

    # ------------------------------------------------------------------
    # Édition numpad (étape 7d)
    # ------------------------------------------------------------------

    def move_event(self, pattern, ev, delta_steps):
        """Déplace un événement de ±delta_steps (grille courante).

        Étend le pattern (resize) si la nouvelle position dépasse sa longueur
        actuelle. Retourne None si le déplacement franchirait le début du
        pattern (offset < 0)."""
        ns         = pattern._num_steps
        old_offset = ev["bar"] * ns + ev["step"]
        new_offset = round(old_offset + delta_steps)
        if new_offset < 0:
            return None
        new_bar, new_step = divmod(new_offset, ns)
        if new_bar >= pattern._num_bars:
            pattern.resize(new_bar + 1, ns)
        if ev["etype"] == ETYPE_GRID:
            return self.edit_grid_note(pattern, ev, new_bar=new_bar, new_step=new_step)
        return self.edit_tape_note(pattern, ev, new_bar=new_bar, new_step=new_step)

    def change_duration(self, pattern, ev, delta_ms):
        """Raccourcit/rallonge un événement tape (KIT/PATCH). GRID n'a pas de
        durée propre (dérivée de la voix) : retourne toujours None."""
        if ev.get("etype") not in (ETYPE_KIT, ETYPE_PATCH):
            return None
        new_dur = max(10, ev.get("dur", 500) + delta_ms)
        if new_dur == ev.get("dur", 500):
            return None
        return self.edit_tape_note(pattern, ev, new_dur=new_dur)

    def change_velocity(self, pattern, ev, delta):
        """Modifie la vélocité de ±delta (bornée 1..127)."""
        new_vel = max(1, min(127, ev["vel"] + delta))
        if new_vel == ev["vel"]:
            return None
        if ev["etype"] == ETYPE_GRID:
            return self.edit_grid_note(pattern, ev, new_vel=new_vel)
        return self.edit_tape_note(pattern, ev, new_vel=new_vel)

    def shift_pitch(self, pattern, ev, delta):
        """Décale le champ pad/note de ±delta (demi-ton=±1, octave=±12).

        Borné 0..127 pour PATCH et KIT (notes MIDI brutes, voir
        TrackRouter.on_kit_tape), 0..num_pads-1 pour GRID (index de pad,
        limite structurelle des banques de sons — voir chantier futur
        128 pads)."""
        etype   = ev["etype"]
        hi      = pattern._num_pads - 1 if etype == ETYPE_GRID else 127
        new_pad = max(0, min(hi, ev["pad"] + delta))
        if new_pad == ev["pad"]:
            return None
        if etype == ETYPE_GRID:
            return self.edit_grid_note(pattern, ev, new_pad=new_pad)
        return self.edit_tape_note(pattern, ev, new_note=new_pad)

    # ------------------------------------------------------------------
    # Duplication / Insertion (étape 7i)
    # ------------------------------------------------------------------

    def duplicate_event(self, pattern, ev):
        """Duplique un événement à la même position (accord empilé).

        KIT/PATCH : ajoute une copie identique dans _tape à la même clé
        (plusieurs notes identiques peuvent coexister). GRID : dupliquer sur
        le même pad au même pas serait un no-op (Pattern.set_cell n'autorise
        qu'un seul événement par pad et par pas) — la copie va donc sur le
        pad adjacent (+1, ou -1 si déjà au dernier pad).
        Retourne le nouvel event_info, ou None si impossible (GRID pad 0
        seul disponible)."""
        etype = ev.get("etype")
        if etype == ETYPE_GRID:
            pad = ev["pad"]
            hi  = pattern._num_pads - 1
            new_pad = pad + 1 if pad < hi else pad - 1
            if new_pad < 0:
                return None
            vel = ev["vel"]
            pattern.set_cell(ev["track"], new_pad, ev["bar"], ev["step"], vel)
            dur = (pattern._voices[new_pad]["duration_ms"]
                   if new_pad < len(pattern._voices) else 500)
            return {
                "type":   "note",
                "etype":  ETYPE_GRID,
                "track":  ev["track"],
                "pad":    new_pad,
                "bar":    ev["bar"],
                "step":   ev["step"],
                "offset": ev["offset"],
                "vel":    vel,
                "dur":    dur,
            }
        if etype in (ETYPE_KIT, ETYPE_PATCH):
            from pattern import TapeEvent
            key = (ev["track"], ev["bar"], ev["step"])
            with pattern._lock:
                pattern._tape.setdefault(key, []).append(
                    TapeEvent(etype, ev["pad"], ev["vel"],
                              ev.get("dur", 500), ev.get("bend", 0))
                )
                new_idx = len(pattern._tape[key]) - 1
            return {
                "type":      "note",
                "etype":     etype,
                "track":     ev["track"],
                "bar":       ev["bar"],
                "step":      ev["step"],
                "offset":    ev["offset"],
                "pad":       ev["pad"],
                "vel":       ev["vel"],
                "dur":       ev.get("dur", 500),
                "bend":      ev.get("bend", 0),
                "event_idx": new_idx,
            }
        return None

    def insert_note(self, pattern, etype, track, bar, step, pad, vel=100, dur=500, bend=0):
        """Insère une nouvelle note à (track, bar, step).

        etype GRID : `pad` est un index de pad (borné 0..num_pads-1).
        etype KIT/PATCH : `pad` est une note MIDI brute (bornée 0..127).
        Retourne le nouvel event_info, ou None si (track, bar, step) est
        hors des dimensions actuelles du pattern."""
        if not (0 <= track < pattern._num_tracks):
            return None
        if not (0 <= bar < pattern._num_bars):
            return None
        if not (0 <= step < pattern._num_steps):
            return None
        vel = max(1, min(127, vel))
        if etype == ETYPE_GRID:
            pad = max(0, min(pattern._num_pads - 1, pad))
            pattern.set_cell(track, pad, bar, step, vel)
            dur_v = (pattern._voices[pad]["duration_ms"]
                     if pad < len(pattern._voices) else 500)
            return {
                "type":   "note",
                "etype":  ETYPE_GRID,
                "track":  track,
                "pad":    pad,
                "bar":    bar,
                "step":   step,
                "offset": bar * pattern._num_steps + step,
                "vel":    vel,
                "dur":    dur_v,
            }
        from pattern import TapeEvent
        pad = max(0, min(127, pad))
        dur = max(10, dur)
        key = (track, bar, step)
        with pattern._lock:
            pattern._tape.setdefault(key, []).append(TapeEvent(etype, pad, vel, dur, bend))
            new_idx = len(pattern._tape[key]) - 1
        return {
            "type":      "note",
            "etype":     etype,
            "track":     track,
            "bar":       bar,
            "step":      step,
            "offset":    bar * pattern._num_steps + step,
            "pad":       pad,
            "vel":       vel,
            "dur":       dur,
            "bend":      bend,
            "event_idx": new_idx,
        }
