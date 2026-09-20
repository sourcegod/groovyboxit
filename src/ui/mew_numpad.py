class NumpadMixin:
    """MidiEditorWindow — édition numpad de l'événement/groupe sélectionné (étape 7d)."""

    _SNAP_NOTE_NAMES = {
        1: "Ronde", 2: "Blanche", 3: "Blanche (triolet)", 4: "Noire",
        6: "Noire (triolet)", 8: "Croche", 12: "Croche (triolet)",
        16: "Double croche", 24: "Double croche (triolet)", 32: "Triple croche",
        48: "Triple croche (triolet)", 64: "Quadruple croche",
        96: "Quadruple croche (triolet)", 128: "128e",
    }

    def _grid_value_steps(self):
        """Taille de la grille courante, en steps (float)."""
        from pattern import Pattern
        p = self._parent._player
        return Pattern.grid_step_size(p._grid_idx, p._pattern._num_steps)

    def _grid_value_ms(self):
        """Taille de la grille courante convertie en ms, via le BPM du pattern."""
        pat            = self._parent._player._pattern
        steps_per_beat = max(1, pat._num_steps // pat._num_beats)
        ms_per_step    = (60000.0 / max(1, pat._bpm)) / steps_per_beat
        return self._grid_value_steps() * ms_per_step

    def _numpad_targets(self):
        """Indices ciblés par une commande numpad : le groupe (accord) si
        `_group_entry`, sinon l'événement courant seul. Triés par event_idx
        décroissant pour rester valides pendant des édits successifs qui
        partagent la même clé _tape (accord sur une même piste)."""
        if not self._events:
            return []
        cur = self._midi_editor._cur_idx
        idxs = (self._midi_editor.group_indices(self._events, cur)
                if self._group_entry else [cur])
        return sorted(idxs, key=lambda i: self._events[i].get("event_idx", 0), reverse=True)

    def _apply_numpad_edit(self, title, fn):
        """Applique fn(pattern, ev) -> new_ev|None à la cible numpad courante.

        Ajoute un undo seulement si au moins une édition a réussi. Retourne
        la liste des new_ev produits (vide si rien n'a changé)."""
        targets = self._numpad_targets()
        if not targets:
            return []
        pat = self._parent._player._pattern
        self._add_undo(title)
        results = []
        for i in targets:
            ev = self._events[i]
            if ev.get("type") != "note":
                continue
            new_ev = fn(pat, ev)
            if new_ev is not None:
                results.append(new_ev)
        if not results:
            self._parent._pop_last_undo()
            return []
        self._parent._player._compute_offsets()
        if self._parent._player.playing:
            self._parent._player._wakeup.set()
        self._refresh()
        return results

    def _find_event_index(self, new_ev):
        for i, e in enumerate(self._events):
            if (e.get("etype") == new_ev.get("etype") and
                    e["track"] == new_ev["track"] and
                    e["bar"]   == new_ev["bar"] and
                    e["step"]  == new_ev["step"] and
                    e["pad"]   == new_ev["pad"]):
                return i
        return None

    def _navigate_and_play_after_edit(self, new_ev):
        """Retrouve l'événement édité dans la liste rafraîchie, s'y positionne
        et joue le résultat (groupe si `_group_entry`, sinon seul)."""
        found = self._find_event_index(new_ev)
        if found is None:
            return
        self._navigate_to(found)
        if self._group_entry:
            self._play_group_at(found)
        else:
            self._play_single_at(found)

    def _numpad_shorten(self):
        delta   = self._grid_value_ms()
        results = self._apply_numpad_edit(
            "Raccourcir durée", lambda pat, ev: self._midi_editor.change_duration(pat, ev, -delta))
        if results:
            self._navigate_and_play_after_edit(results[-1])
            self._set_status(f"Durée: {results[-1]['dur']}ms")
        else:
            self._set_status("Raccourcir: durée déjà minimale")

    def _numpad_lengthen(self):
        delta   = self._grid_value_ms()
        results = self._apply_numpad_edit(
            "Rallonger durée", lambda pat, ev: self._midi_editor.change_duration(pat, ev, delta))
        if results:
            self._navigate_and_play_after_edit(results[-1])
            self._set_status(f"Durée: {results[-1]['dur']}ms")
        else:
            self._set_status("Rallonger: aucun changement")

    def _numpad_move(self, direction):
        delta   = direction * self._grid_value_steps()
        title   = "Avancer" if direction > 0 else "Reculer"
        results = self._apply_numpad_edit(
            f"{title} (grille)", lambda pat, ev: self._midi_editor.move_event(pat, ev, delta))
        if results:
            self._navigate_and_play_after_edit(results[-1])
            bbt = self._bbt_str(results[-1]["bar"], results[-1]["step"])
            self._set_status(f"Position: {bbt}")
        else:
            self._set_status("Déplacement: déjà au début du pattern")

    def _numpad_velocity(self, delta):
        results = self._apply_numpad_edit(
            "Vélocité -1" if delta < 0 else "Vélocité +1",
            lambda pat, ev: self._midi_editor.change_velocity(pat, ev, delta))
        if results:
            self._navigate_and_play_after_edit(results[-1])
            self._set_status(f"Vélocité: {results[-1]['vel']}")
        else:
            self._set_status("Vélocité: déjà à la borne (1..127)")

    def _numpad_pitch(self, delta):
        title   = f"{'Octave' if abs(delta) == 12 else 'Demi-ton'} {'+' if delta > 0 else '-'}"
        results = self._apply_numpad_edit(
            title, lambda pat, ev: self._midi_editor.shift_pitch(pat, ev, delta))
        if results:
            self._navigate_and_play_after_edit(results[-1])
            name = self._event_note_name(results[-1])
            self._set_status(f"({name})")
        else:
            self._set_status("Décalage: déjà à la borne")

    def _show_cursor_position(self):
        if not self._events:
            return
        ev  = self._events[self._midi_editor._cur_idx]
        bbt = self._bbt_str(ev["bar"], ev["step"])
        self._set_status(f"Position: {bbt}")

    def _show_grid_value(self):
        from pattern import Pattern
        p = self._parent._player
        label, kind, val = Pattern.GRID_RESOLUTIONS[p._grid_idx]
        if kind == "bars":
            name = f"{val} mesure{'s' if val > 1 else ''}"
        else:
            name = self._SNAP_NOTE_NAMES.get(val, "")
        self._set_status(f"Grille: {label}" + (f", {name}" if name else ""))

    def _change_grid_idx(self, delta):
        from pattern import Pattern
        p       = self._parent._player
        old_idx = p._grid_idx
        new_idx = max(0, min(len(Pattern.GRID_RESOLUTIONS) - 1, old_idx + delta))
        if new_idx == old_idx:
            self._set_status("Grille: déjà à la borne")
            return
        self._add_undo(
            f"Grille : {Pattern.GRID_LABELS[old_idx]} → {Pattern.GRID_LABELS[new_idx]}"
        )
        p._grid_idx = new_idx
        self._set_status(f"Grille : {Pattern.GRID_LABELS[new_idx]}")
