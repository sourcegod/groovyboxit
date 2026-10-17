#python3
"""
    File: src/midi/midi_editor.py
    MidiEditor — sélection, manipulation et édition des événements MIDI d'un pattern.
    Date: Fri, 26/06/2026
    Author: Coolbrother
"""

from pattern import ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH, ETYPE_CC, ETYPE_PGM, ETYPE_BEND


class MidiEditor:
    """Logique d'édition des événements MIDI d'un pattern.

    Source unique : _tape[track] = [TapeEvent, ...] (liste plate, position =
    TapeEvent.time), etype ETYPE_GRID/ETYPE_KIT/ETYPE_PATCH pour les notes,
    ETYPE_CC/ETYPE_PGM pour CC générique et Program Change (Phase 7 étape 4i),
    ETYPE_BEND pour l'automation Pitch Bend (Phase 7 étape 6d1).
    Mode étendu (VIEW_ALL) : tout _tape (notes + CC/PGM/BEND). Ni CC#1
    (Mod Wheel, étape 5f) ni Pitch Bend (étape 6d1) n'ont plus de source
    séparée : ils vivent dans _tape comme les autres etypes.
    """

    VIEW_NOTES = 0   # notes de la grille de la piste courante
    VIEW_ALL   = 1   # tous les événements MIDI des pistes sélectionnées

    def __init__(self):
        self._view_mode = self.VIEW_NOTES
        self._cur_idx   = 0   # index courant dans la liste d'affichage

    # ------------------------------------------------------------------
    # Collecte d'événements
    # ------------------------------------------------------------------

    def _events_by_time(self, pattern, track_idx, lim_left=None, lim_right=None):
        """Itère _tape[track_idx] groupé par position, dans l'ordre des positions.

        Rend des tuples (offset, bar, step, event_idx, ev) où event_idx est la
        position de ev parmi TOUS les événements de la piste à cette position,
        **tous etypes confondus** — c'est la convention que résolvent
        _delete_tape_event/edit_tape_note via
        `[i for i, e in enumerate(track_list) if e.time == time]`.
        Partagé par get_note_events (notes) et get_cc_pgm_events (CC/PGM) pour
        que les deux produisent des event_idx mutuellement cohérents : un
        compteur local à chaque famille d'etype désignerait le mauvais
        événement à la suppression/édition (Phase 7 étape 4i).
        """
        if track_idx >= len(pattern._tape):
            return
        by_time = {}
        for ev in pattern._tape[track_idx]:
            by_time.setdefault(ev.time, []).append(ev)
        for offset in sorted(by_time):
            if lim_left  is not None and offset < lim_left:
                continue
            # Limiteur droit inclusif sur le PAS entier (Phase 7 étape 6g2) :
            # un CC/bend fractionnaire du pas lim_right (ex. 5.4 pour
            # lim_right=5) est dans la plage.
            if lim_right is not None and offset >= lim_right + 1:
                continue
            b, s = pattern._time_to_bar_step(offset)
            for i, ev in enumerate(by_time[offset]):
                yield offset, b, s, i, ev

    def get_note_events(self, pattern, track_idx, lim_left=None, lim_right=None):
        """Retourne toutes les notes (GRID/KIT/PATCH) d'une piste, depuis _tape.

        event_idx : position de l'événement parmi ceux à la même position
        (time) sur cette piste — voir _events_by_time.
        Les etypes ETYPE_CC/ETYPE_PGM ne sont pas des notes (pas de pad/vel) :
        exclus ici, remontés par get_cc_pgm_events.
        """
        events = []
        for offset, b, s, i, ev in self._events_by_time(pattern, track_idx, lim_left, lim_right):
            if ev.etype == ETYPE_GRID:
                pad = ev.payload.get("pad")
                voice_dur = (pattern._voices[pad]["duration_ms"]
                             if pad < len(pattern._voices) else 500)
                dur = ev.dur if ev.dur > 0 else voice_dur
                events.append({
                    "type":         "note",
                    "etype":        ETYPE_GRID,
                    "track":        track_idx,
                    "pad":          pad,
                    "bar":          b,
                    "step":         s,
                    "offset":       offset,
                    "vel":          ev.payload.get("vel"),
                    "dur":          dur,
                    "dur_override": ev.dur,
                    "channel":      ev.channel,
                    "event_idx":    i,
                })
            elif ev.etype in (ETYPE_KIT, ETYPE_PATCH):
                events.append({
                    "type":      "note",
                    "etype":     ev.etype,
                    "track":     track_idx,
                    "bar":       b,
                    "step":      s,
                    "offset":    offset,
                    "pad":       ev.payload.get("note"),   # KIT: index pad kit ; PATCH: note MIDI brute
                    "vel":       ev.payload.get("vel"),
                    "dur":       ev.dur,
                    "bend":      ev.payload.get("bend", 0),
                    "channel":   ev.channel,
                    "event_idx": i,
                })

        events.sort(key=lambda e: (e["offset"], e["pad"]))
        return events

    def get_cc_pgm_events(self, pattern, track_idx, lim_left=None, lim_right=None):
        """Retourne les CC générique (ETYPE_CC), Program Change (ETYPE_PGM)
        et Pitch Bend (ETYPE_BEND, type "bend", Phase 7 étape 6d1) d'une
        piste, depuis _tape (Phase 7 étape 4i).

        Pas des notes (ni pad ni vélocité) : séparés de get_note_events, donc
        absents du mode Notes (Ctrl+1) et remontés seulement par
        get_all_events (Ctrl+2). event_idx partagé avec les notes de la même
        position (voir _events_by_time).
        """
        events = []
        for offset, b, s, i, ev in self._events_by_time(pattern, track_idx, lim_left, lim_right):
            if ev.etype == ETYPE_CC:
                events.append({
                    "type":      "cc",
                    "etype":     ETYPE_CC,
                    "track":     track_idx,
                    "bar":       b,
                    "step":      s,
                    "offset":    offset,
                    "cc_num":    ev.payload.get("cc_num"),
                    "value":     ev.payload.get("value"),
                    "channel":   ev.channel,
                    "event_idx": i,
                })
            elif ev.etype == ETYPE_PGM:
                events.append({
                    "type":      "pgm",
                    "etype":     ETYPE_PGM,
                    "track":     track_idx,
                    "bar":       b,
                    "step":      s,
                    "offset":    offset,
                    "program":   ev.payload.get("program"),
                    "channel":   ev.channel,
                    "event_idx": i,
                })
            elif ev.etype == ETYPE_BEND:
                events.append({
                    "type":      "bend",
                    "etype":     ETYPE_BEND,
                    "track":     track_idx,
                    "bar":       b,
                    "step":      s,
                    "offset":    offset,
                    "value":     ev.payload.get("value"),
                    "channel":   ev.channel,
                    "event_idx": i,
                })
        return events

    def get_all_events(self, pattern, sel_tracks, lim_left=None, lim_right=None):
        """Retourne tous les événements MIDI des pistes sélectionnées.

        Inclut : notes (GRID/KIT/PATCH via get_note_events), CC générique,
        Program Change et Pitch Bend (ETYPE_CC/ETYPE_PGM/ETYPE_BEND via
        get_cc_pgm_events, dont CC#1/Mod Wheel — plus de type "mod" séparé
        depuis l'étape 5f, ni de lecture de _bend_tape depuis l'étape 6d1).
        """
        sel_set = set(sel_tracks)
        events  = []

        # Notes (GRID/KIT/PATCH, via _tape)
        for t in sorted(sel_set):
            evs = self.get_note_events(pattern, t, lim_left, lim_right)
            events.extend(evs)

        # CC générique / Program Change / Pitch Bend (ETYPE_CC/ETYPE_PGM/
        # ETYPE_BEND, via _tape). CC#1 (Mod Wheel) y est un "cc" ordinaire
        # depuis l'étape 5f ; le Pitch Bend y est lu depuis l'étape 6d1 (plus
        # de bloc séparé sur _bend_tape).
        for t in sorted(sel_set):
            events.extend(self.get_cc_pgm_events(pattern, t, lim_left, lim_right))

        events.sort(key=lambda e: (e["offset"], e["track"]))
        return events

    # ------------------------------------------------------------------
    # Filtre / sélection par critères
    # ------------------------------------------------------------------

    def filter_events(self, events, criteria):
        """Retourne l'ensemble des indices de `events` qui passent `criteria`.

        criteria (dict) :
            active       bool  — interrupteur maître ; False = tout passe
            invert       bool  — inverse le résultat (appliqué en dernier)
            etype_filter str   — "all" | "note" | "bend" | "cc" | "pgm" | "mod"
                                 ("mod" est un alias conservé pour le raccourci
                                 « Mod Wheel (CC1) » du dialog de filtre, Phase 7
                                 étape 5f — traduit en type=="cc" and cc_num==1,
                                 "mod" n'est plus un type d'événement réel)
            note_lo/hi   int   — bornes sur e["pad"], type "note" seulement
            vel_lo/hi    int   — bornes sur e["vel"], type "note" seulement
            bend_lo/hi   int   — bornes sur e["value"], type "bend" seulement
            cc_num_lo/hi int   — bornes sur e["cc_num"], type "cc" seulement
            cc_val_lo/hi int   — bornes sur e["value"],  type "cc" seulement
            pgm_lo/hi    int   — bornes sur e["program"], type "pgm" seulement
            pos_from/to  num   — bornes en pas sur e["offset"], tous types ;
                                 pos_to inclut tout le pas qui le contient
                                 (fraction comprise, Phase 7 étape 6g2)
        """
        if not criteria.get("active", True):
            matched = set(range(len(events)))
            if criteria.get("invert", False):
                matched = set(range(len(events))) - matched
            return matched

        etype_filter = criteria.get("etype_filter", "all")
        pos_from     = criteria.get("pos_from")
        pos_to       = criteria.get("pos_to")
        note_lo      = criteria.get("note_lo", 0)
        note_hi      = criteria.get("note_hi", 127)
        vel_lo       = criteria.get("vel_lo", 0)
        vel_hi       = criteria.get("vel_hi", 127)
        bend_lo      = criteria.get("bend_lo", -8192)
        bend_hi      = criteria.get("bend_hi", 8191)
        cc_num_lo    = criteria.get("cc_num_lo", 0)
        cc_num_hi    = criteria.get("cc_num_hi", 127)
        cc_val_lo    = criteria.get("cc_val_lo", 0)
        cc_val_hi    = criteria.get("cc_val_hi", 127)
        pgm_lo       = criteria.get("pgm_lo", 0)
        pgm_hi       = criteria.get("pgm_hi", 127)

        matched = set()
        for i, e in enumerate(events):
            offset = e["offset"]
            if pos_from is not None and offset < pos_from:
                continue
            if pos_to is not None and offset >= int(pos_to) + 1:   # pas de pos_to inclus (6g2)
                continue

            if etype_filter == "mod":
                if e["type"] != "cc" or e.get("cc_num") != 1:
                    continue
                matched.add(i)
                continue

            if etype_filter != "all" and e["type"] != etype_filter:
                continue

            if e["type"] == "note" and etype_filter == "note":
                if not (note_lo <= e["pad"] <= note_hi):
                    continue
                if not (vel_lo <= e["vel"] <= vel_hi):
                    continue
            elif e["type"] == "bend" and etype_filter == "bend":
                if not (bend_lo <= e["value"] <= bend_hi):
                    continue
            elif e["type"] == "cc" and etype_filter == "cc":
                if not (cc_num_lo <= e["cc_num"] <= cc_num_hi):
                    continue
                if not (cc_val_lo <= e["value"] <= cc_val_hi):
                    continue
            elif e["type"] == "pgm" and etype_filter == "pgm":
                if not (pgm_lo <= e["program"] <= pgm_hi):
                    continue

            matched.add(i)

        if criteria.get("invert", False):
            matched = set(range(len(events))) - matched

        return matched

    # ------------------------------------------------------------------
    # Opérations d'édition
    # ------------------------------------------------------------------

    def delete_event(self, pattern, ev):
        """Supprime un événement. Retourne True si supprimé.

        Notes GRID → via la façade grille ; notes KIT/PATCH, CC/PGM et Pitch
        Bend (dans _tape depuis l'étape 6d1) → via _delete_tape_event (même
        repérage time+event_idx, voir _events_by_time).
        """
        kind = ev.get("type")
        if kind == "note":
            if ev.get("etype") == ETYPE_GRID:
                return self._delete_grid_event(pattern, ev)
            return self._delete_tape_event(pattern, ev)
        if kind in ("cc", "pgm", "bend"):
            return self._delete_tape_event(pattern, ev)
        return False

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

    @staticmethod
    def _event_time(pattern, ev):
        """TapeEvent.time exact visé par l'event dict `ev`.

        Un CC peut vivre à une position fractionnaire (Phase 7 étape 5b) :
        la reconstruire depuis bar/step la tronquerait et ne retrouverait
        plus l'événement. On reprend donc ev["offset"] (égal à ev.time,
        fourni par _events_by_time) tant qu'il est cohérent avec bar/step ;
        sinon (dict construit/modifié à la main) on retombe sur bar/step.
        """
        offset = ev.get("offset")
        if offset is not None and pattern._time_to_bar_step(offset) == (ev["bar"], ev["step"]):
            return offset
        return pattern._bar_step_to_time(ev["bar"], ev["step"])

    def _delete_tape_event(self, pattern, ev):
        t    = ev["track"]
        time = self._event_time(pattern, ev)
        idx  = ev.get("event_idx", -1)
        with pattern._lock:
            if t >= len(pattern._tape):
                return False
            track_list = pattern._tape[t]
            matches = [i for i, e in enumerate(track_list) if e.time == time]
            if idx < 0 or idx >= len(matches):
                return False
            del track_list[matches[idx]]
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
                       new_bar=None, new_step=None, new_dur=None, new_channel=None):
        """Modifie un événement tape (etype KIT ou PATCH). Retourne le nouvel event_info ou None."""
        from pattern import TapeEvent
        etype = ev.get("etype")
        if etype not in (ETYPE_KIT, ETYPE_PATCH):
            return None
        t       = ev["track"]
        old_time = self._event_time(pattern, ev)
        old_idx = ev.get("event_idx", -1)
        n_note  = new_note if new_note is not None else ev["pad"]
        n_vel   = max(1, min(127, new_vel  if new_vel  is not None else ev["vel"]))
        n_bar   = new_bar  if new_bar  is not None else ev["bar"]
        n_step  = new_step if new_step is not None else ev["step"]
        n_dur   = max(10,  new_dur  if new_dur  is not None else ev.get("dur", 500))
        n_bend  = ev.get("bend", 0)
        n_channel = max(0, min(15, new_channel if new_channel is not None else ev.get("channel", 0)))
        if n_bar < 0 or n_bar >= pattern._num_bars:
            return None
        if n_step < 0 or n_step >= pattern._num_steps:
            return None
        new_time = pattern._bar_step_to_time(n_bar, n_step)
        with pattern._lock:
            if t >= len(pattern._tape):
                return None
            track_list = pattern._tape[t]
            matches = [i for i, e in enumerate(track_list) if e.time == old_time]
            if old_idx < 0 or old_idx >= len(matches):
                return None
            del track_list[matches[old_idx]]
            payload = {"note": n_note, "vel": n_vel}
            if etype == ETYPE_PATCH:
                payload["bend"] = n_bend
            track_list.append(TapeEvent(etype, dur=n_dur, channel=n_channel, payload=payload, time=new_time))
            new_idx = sum(1 for e in track_list if e.time == new_time) - 1
        return {
            "type":      "note",
            "etype":     etype,
            "track":     t,
            "bar":       n_bar,
            "step":      n_step,
            "offset":    new_time,
            "pad":       n_note,
            "vel":       n_vel,
            "dur":       n_dur,
            "bend":      n_bend,
            "channel":   n_channel,
            "event_idx": new_idx,
        }

    def edit_grid_note(self, pattern, ev, new_pad=None, new_vel=None,
                       new_bar=None, new_step=None, new_channel=None, new_dur=None):
        """Modifie un événement grille (etype GRID). Retourne le nouvel event_info ou None.

        new_dur : durée propre à cette occurrence (Numpad1/3, Phase 7 étape
        1k) — None préserve l'override existant (ev["dur_override"], 0 si
        aucun) ; sinon devient le nouvel override, qui prime désormais sur
        voice_manager.get_duration_ms(pad) pour cette seule occurrence.
        """
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
        n_channel = max(0, min(15, new_channel if new_channel is not None else ev.get("channel", 0)))
        n_dur_override = max(0, new_dur if new_dur is not None else ev.get("dur_override", 0))

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
        pattern.set_cell(t, n_pad, n_bar, n_step, n_vel, channel=n_channel, dur=n_dur_override)

        voice_dur = (pattern._voices[n_pad]["duration_ms"]
                     if n_pad < len(pattern._voices) else 500)
        dur = n_dur_override if n_dur_override > 0 else voice_dur
        return {
            "type":         "note",
            "etype":        ETYPE_GRID,
            "track":        t,
            "pad":          n_pad,
            "bar":          n_bar,
            "step":         n_step,
            "offset":       n_bar * pattern._num_steps + n_step,
            "vel":          n_vel,
            "dur":          dur,
            "dur_override": n_dur_override,
            "channel":      n_channel,
        }

    def edit_bend_event(self, pattern, ev, new_value=None, new_bar=None, new_step=None):
        """Modifie un point d'automation Pitch Bend de _tape (etype ETYPE_BEND) :
        valeur (-8192..+8191) et/ou position. Retourne le nouvel event_info ou None.

        Via _replace_tape_event depuis la Phase 7 étape 6d1 : position
        inchangée → time fractionnaire d'origine conservé (l'ancienne version
        sur _bend_tape le ramenait toujours au pas entier).
        """
        n_val = new_value if new_value is not None else ev["value"]
        n_val = max(-8192, min(8191, n_val))
        res = self._replace_tape_event(
            pattern, ev, ETYPE_BEND, {"value": n_val}, new_bar, new_step
        )
        if res is None:
            return None
        n_bar, n_step, new_time, new_idx, channel = res
        return {
            "type":      "bend",
            "etype":     ETYPE_BEND,
            "track":     ev["track"],
            "bar":       n_bar,
            "step":      n_step,
            "offset":    new_time,
            "value":     n_val,
            "channel":   channel,
            "event_idx": new_idx,
        }

    # Note (Phase 7 étape 5f) : edit_mod_event a disparu — CC#1 (Mod Wheel)
    # n'a plus de type "mod" séparé, il est édité par edit_cc_event comme
    # n'importe quel CC générique (_mod_tape lui-même supprimé en 5h).

    def _replace_tape_event(self, pattern, ev, etype, payload, new_bar, new_step):
        """Remplace le TapeEvent repéré par (time, event_idx) par un nouveau de
        même etype/canal avec `payload`, éventuellement à une autre position.

        Retourne (bar, step, time, event_idx, channel) du nouvel événement, ou
        None si la position visée est hors pattern / l'index ne résout rien /
        l'etype trouvé ne correspond pas. Factorise la chirurgie commune à
        edit_cc_event, edit_pgm_event (Phase 7 étape 4i) et edit_bend_event
        (étape 6d1).
        """
        from pattern import TapeEvent
        t        = ev["track"]
        old_time = self._event_time(pattern, ev)
        old_idx  = ev.get("event_idx", -1)
        n_bar    = new_bar  if new_bar  is not None else ev["bar"]
        n_step   = new_step if new_step is not None else ev["step"]
        if n_bar < 0 or n_bar >= pattern._num_bars:
            return None
        if n_step < 0 or n_step >= pattern._num_steps:
            return None
        # Position inchangée → time d'origine conservé, fraction comprise
        # (Phase 7 étape 5b) ; déplacée → posée sur le pas entier choisi.
        if (n_bar, n_step) == (ev["bar"], ev["step"]):
            new_time = old_time
        else:
            new_time = pattern._bar_step_to_time(n_bar, n_step)
        with pattern._lock:
            if t >= len(pattern._tape):
                return None
            track_list = pattern._tape[t]
            matches = [i for i, e in enumerate(track_list) if e.time == old_time]
            if old_idx < 0 or old_idx >= len(matches):
                return None
            old_ev = track_list[matches[old_idx]]
            if old_ev.etype != etype:
                return None
            channel = old_ev.channel
            del track_list[matches[old_idx]]
            track_list.append(TapeEvent(etype, channel=channel, payload=payload, time=new_time))
            new_idx = sum(1 for e in track_list if e.time == new_time) - 1
        return n_bar, n_step, new_time, new_idx, channel

    def edit_cc_event(self, pattern, ev, new_value=None, new_bar=None, new_step=None):
        """Modifie un CC générique de _tape (etype ETYPE_CC).

        Seuls la valeur (0..127) et la position sont éditables — cc_num reste
        inchangé dans ce chantier (voir docs/DESIGN.md § Phase 7 étape 4a,
        décision 3). Retourne le nouvel event_info ou None.
        """
        cc_num = ev["cc_num"]
        n_val  = new_value if new_value is not None else ev["value"]
        n_val  = max(0, min(127, n_val))
        res = self._replace_tape_event(
            pattern, ev, ETYPE_CC, {"cc_num": cc_num, "value": n_val}, new_bar, new_step
        )
        if res is None:
            return None
        n_bar, n_step, new_time, new_idx, channel = res
        return {
            "type":      "cc",
            "etype":     ETYPE_CC,
            "track":     ev["track"],
            "bar":       n_bar,
            "step":      n_step,
            "offset":    new_time,
            "cc_num":    cc_num,
            "value":     n_val,
            "channel":   channel,
            "event_idx": new_idx,
        }

    def edit_pgm_event(self, pattern, ev, new_value=None, new_bar=None, new_step=None):
        """Modifie un Program Change de _tape (etype ETYPE_PGM) : numéro de
        program (0..127) et/ou position. Retourne le nouvel event_info ou None.
        """
        n_prog = new_value if new_value is not None else ev["program"]
        n_prog = max(0, min(127, n_prog))
        res = self._replace_tape_event(
            pattern, ev, ETYPE_PGM, {"program": n_prog}, new_bar, new_step
        )
        if res is None:
            return None
        n_bar, n_step, new_time, new_idx, channel = res
        return {
            "type":      "pgm",
            "etype":     ETYPE_PGM,
            "track":     ev["track"],
            "bar":       n_bar,
            "step":      n_step,
            "offset":    new_time,
            "program":   n_prog,
            "channel":   channel,
            "event_idx": new_idx,
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
        """Raccourcit/rallonge un événement (KIT/PATCH, ou GRID depuis la
        Phase 7 étape 1k — la durée devient alors propre à cette occurrence,
        elle prime sur voice_manager.get_duration_ms(pad))."""
        etype = ev.get("etype")
        if etype not in (ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH):
            return None
        new_dur = max(10, ev.get("dur", 500) + delta_ms)
        if new_dur == ev.get("dur", 500):
            return None
        if etype == ETYPE_GRID:
            return self.edit_grid_note(pattern, ev, new_dur=new_dur)
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
            vel          = ev["vel"]
            channel      = ev.get("channel", 0)
            dur_override = ev.get("dur_override", 0)
            pattern.set_cell(ev["track"], new_pad, ev["bar"], ev["step"], vel,
                              channel=channel, dur=dur_override)
            voice_dur = (pattern._voices[new_pad]["duration_ms"]
                         if new_pad < len(pattern._voices) else 500)
            dur = dur_override if dur_override > 0 else voice_dur
            return {
                "type":         "note",
                "etype":        ETYPE_GRID,
                "track":        ev["track"],
                "pad":          new_pad,
                "bar":          ev["bar"],
                "step":         ev["step"],
                "offset":       ev["offset"],
                "vel":          vel,
                "dur":          dur,
                "dur_override": dur_override,
                "channel":      channel,
            }
        if etype in (ETYPE_KIT, ETYPE_PATCH):
            from pattern import TapeEvent
            t       = ev["track"]
            time    = pattern._bar_step_to_time(ev["bar"], ev["step"])
            channel = ev.get("channel", 0)
            payload = {"note": ev["pad"], "vel": ev["vel"]}
            if etype == ETYPE_PATCH:
                payload["bend"] = ev.get("bend", 0)
            with pattern._lock:
                pattern._ensure_track_count(t + 1)
                track_list = pattern._tape[t]
                track_list.append(
                    TapeEvent(etype, dur=ev.get("dur", 500), channel=channel, payload=payload, time=time)
                )
                new_idx = sum(1 for e in track_list if e.time == time) - 1
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
                "channel":   channel,
                "event_idx": new_idx,
            }
        return None

    def insert_between_offset(self, cur_offset, nxt_offset):
        """Calcule le pas (offset entier) médian entre deux offsets, pour
        l'insertion 'entre deux notes' (étape 7n). Retourne None si aucun
        pas n'est disponible entre les deux (offsets adjacents ou égaux)."""
        mid = round((cur_offset + nxt_offset) / 2)
        if cur_offset < mid < nxt_offset:
            return mid
        return None

    def insert_note(self, pattern, etype, track, bar, step, pad, vel=100, dur=500, bend=0, channel=0):
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
        vel     = max(1, min(127, vel))
        channel = max(0, min(15, channel))
        if etype == ETYPE_GRID:
            # Pas d'override de durée à l'insertion : toujours la voix (comme
            # avant l'étape 1k) — seule l'édition d'une note existante
            # (Numpad1/3, change_duration/edit_grid_note) en pose un.
            pad = max(0, min(pattern._num_pads - 1, pad))
            pattern.set_cell(track, pad, bar, step, vel, channel=channel)
            dur_v = (pattern._voices[pad]["duration_ms"]
                     if pad < len(pattern._voices) else 500)
            return {
                "type":         "note",
                "etype":        ETYPE_GRID,
                "track":        track,
                "pad":          pad,
                "bar":          bar,
                "step":         step,
                "offset":       bar * pattern._num_steps + step,
                "vel":          vel,
                "dur":          dur_v,
                "dur_override": 0,
                "channel":      channel,
            }
        from pattern import TapeEvent
        pad     = max(0, min(127, pad))
        dur     = max(10, dur)
        time    = pattern._bar_step_to_time(bar, step)
        payload = {"note": pad, "vel": vel}
        if etype == ETYPE_PATCH:
            payload["bend"] = bend
        with pattern._lock:
            pattern._ensure_track_count(track + 1)
            track_list = pattern._tape[track]
            track_list.append(TapeEvent(etype, dur=dur, channel=channel, payload=payload, time=time))
            new_idx = sum(1 for e in track_list if e.time == time) - 1
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
            "channel":   channel,
            "event_idx": new_idx,
        }
