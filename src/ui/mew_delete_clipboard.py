import wx


class DeleteClipboardMixin:
    """MidiEditorWindow — suppression, limiteurs et presse-papier d'événements."""

    def _delete_event(self):
        if not self._events:
            return
        pat = self._parent._player._pattern
        cur = self._midi_editor._cur_idx

        if self._selected_indices:
            # Supprimer toutes les notes sélectionnées (G uniquement)
            targets = sorted(
                [i for i in self._selected_indices
                 if self._events[i].get("type") == "note"],
                reverse=True
            )
            if not targets:
                self._set_status("Aucune note sélectionnée supprimable")
                return
            self._add_undo(f"Suppr {len(targets)} note(s) sélectionnée(s)")
            deleted = 0
            for idx in targets:
                if self._midi_editor.delete_event(pat, self._events[idx]):
                    deleted += 1
            if deleted:
                self._parent._player._compute_offsets()
                self._clear_selection()
                self._midi_editor._cur_idx = max(0, cur - deleted)
                self._refresh()
                self._set_status(f"{deleted} note(s) supprimée(s)")
            else:
                self._parent._pop_last_undo()
        else:
            # Supprimer le groupe (accord) courant
            group = self._midi_editor.group_indices(self._events, cur)
            targets = [i for i in group if self._events[i].get("type") == "note"]
            if not targets:
                self._set_status("Suppression non disponible pour ce type")
                return
            n = len(targets)
            ev0 = self._events[targets[0]]
            self._add_undo(
                f"Suppr {'accord' if n > 1 else 'note'} "
                f"Tr{ev0['track']+1} B{ev0['bar']+1}:S{ev0['step']+1}"
            )
            deleted = sum(
                1 for idx in sorted(targets, reverse=True)
                if self._midi_editor.delete_event(pat, self._events[idx])
            )
            if deleted:
                self._parent._player._compute_offsets()
                self._midi_editor._cur_idx = max(0, cur - deleted)
                self._refresh()
                self._set_status(
                    f"{'Accord' if n > 1 else 'Note'} supprimé(e) ({deleted} note(s))"
                )
            else:
                self._parent._pop_last_undo()

    # ------------------------------------------------------------------
    # Limiteurs (délégation vers TrackEditor du parent)
    # ------------------------------------------------------------------

    def _lim_bbt(self, step):
        pat   = self._parent._player._pattern
        ns    = pat._num_steps
        spb   = max(1, ns // pat._num_beats)
        total = pat._num_bars * ns
        return self._parent._track_editor.fmt_bbt(step, ns, spb, total)

    def _set_lim_left(self, step):
        self._parent._track_editor.set_lim_left(step)
        self._refresh()
        wx.CallAfter(self._set_status, f"Limiteur Gauche: {self._lim_bbt(step)}")

    def _set_lim_right(self, step):
        self._parent._track_editor.set_lim_right(step)
        self._refresh()
        wx.CallAfter(self._set_status, f"Limiteur Droit: {self._lim_bbt(step)}")

    def _reset_lims(self):
        self._parent._track_editor.reset_lims()
        self._refresh()
        wx.CallAfter(self._set_status, "Limiteurs réinitialisés")

    def _go_first_event(self):
        if self._events:
            self._navigate_to(0)
            wx.CallAfter(self._announce_group, 0)

    def _go_last_event(self):
        if self._events:
            last = len(self._events) - 1
            self._navigate_to(last)
            wx.CallAfter(self._announce_group, last)

    # ------------------------------------------------------------------
    # Presse-papier événements
    # ------------------------------------------------------------------

    def _source_events(self):
        """Retourne les notes source pour copier/couper/supprimer.

        Priorité :
        1. Sélection manuelle (_selected_indices non vide)
        2. Limiteurs actifs → tous les événements dans [lim_left, lim_right]
        3. Groupe courant (accord à la position du curseur)
        """
        if self._selected_indices:
            return [self._events[i] for i in sorted(self._selected_indices)
                    if self._events[i].get("type") == "note"]
        te    = self._parent._track_editor
        lim_l = te._lim_left
        lim_r = te._lim_right
        if lim_l is not None or lim_r is not None:
            lo    = lim_l if lim_l is not None else 0
            hi    = lim_r if lim_r is not None else float("inf")
            notes = [e for e in self._events
                     if e.get("type") == "note" and lo <= e["offset"] <= hi]
            if notes:
                return notes
        if not self._events:
            return []
        cur   = self._midi_editor._cur_idx
        group = self._midi_editor.group_indices(self._events, cur)
        return [self._events[i] for i in group
                if self._events[i].get("type") == "note"]

    def _copy_events(self):
        src = self._source_events()
        n   = self._parent._track_editor.copy_events(src)
        self._set_status(f"{n} note(s) copiée(s)" if n else "Rien à copier")

    def _cut_events(self):
        src = self._source_events()
        if not src:
            self._set_status("Rien à couper")
            return
        self._parent._track_editor.copy_events(src)
        pat  = self._parent._player._pattern
        n    = len(src)
        self._add_undo(f"Couper {n} note(s)")
        deleted = sum(
            1 for ev in src
            if self._midi_editor.delete_event(pat, ev)
        )
        if deleted:
            self._parent._player._compute_offsets()
            self._clear_selection()
            cur = self._midi_editor._cur_idx
            self._midi_editor._cur_idx = max(0, cur - deleted)
            self._refresh()
            self._set_status(f"{deleted} note(s) coupée(s)")
        else:
            self._parent._pop_last_undo()
            self._set_status("Coupe impossible")

    def _paste_events(self):
        te = self._parent._track_editor
        if not te.has_event_clipboard():
            self._set_status("Presse-papier vide")
            return
        pat         = self._parent._player._pattern
        cur_track   = self._parent._player._cur_track
        cur_offset  = (self._events[self._midi_editor._cur_idx]["offset"]
                       if self._events else 0)
        self._add_undo(f"Coller notes Tr{cur_track + 1} @{cur_offset}")
        n = te.paste_events(pat, cur_track, cur_offset)
        if n:
            self._parent._player._compute_offsets()
            self._refresh()
            self._set_status(f"{n} note(s) collée(s)")
        else:
            self._parent._pop_last_undo()
            self._set_status("Coller: hors limites du pattern")
