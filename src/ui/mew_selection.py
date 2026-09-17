import wx


class SelectionMixin:
    """MidiEditorWindow — sélection multiple d'événements."""

    def _sync_lims_from_selection(self):
        """Synchronise lim_left/right sur l'étendue des événements sélectionnés.
        Réinitialise les limiteurs si la sélection est vide."""
        te = self._parent._track_editor
        if not self._selected_indices:
            te.reset_lims()
            return
        offsets = [self._events[i]["offset"]
                   for i in self._selected_indices if i < len(self._events)]
        if offsets:
            te.set_lim_left(min(offsets))
            te.set_lim_right(max(offsets))

    def _toggle_group_selection(self, idx):
        """Toggle la sélection de tous les indices du groupe à idx."""
        group = self._midi_editor.group_indices(self._events, idx)
        if all(i in self._selected_indices for i in group):
            for i in group:
                self._selected_indices.discard(i)
        else:
            for i in group:
                self._selected_indices.add(i)
        for i in group:
            self._update_label(i)
        self._sync_lims_from_selection()

    def _toggle_note_selection(self, idx):
        """Toggle la sélection d'une seule note."""
        if idx in self._selected_indices:
            self._selected_indices.discard(idx)
        else:
            self._selected_indices.add(idx)
        self._update_label(idx)
        self._sync_lims_from_selection()

    def _select_all(self):
        self._selected_indices = set(range(len(self._events)))
        self._refresh_labels()
        self._sync_lims_from_selection()
        self._set_status(f"{len(self._selected_indices)} événement(s) sélectionné(s)")

    def _deselect_all(self):
        self._selected_indices.clear()
        self._refresh_labels()
        self._sync_lims_from_selection()   # reset_lims() implicite
        self._set_status("Sélection effacée")

    def _clear_selection(self):
        """Vide la sélection et synchronise les limiteurs sans message."""
        self._selected_indices.clear()
        self._sync_lims_from_selection()

    def _sel_status_suffix(self):
        n = len(self._selected_indices)
        return f"  [{n} sél.]" if n else ""

    def _select_move_right(self):
        """Shift+→ : groupe suivant + toggle sélection du groupe + joue."""
        if not self._events:
            return
        cur = self._midi_editor._cur_idx
        nxt = self._midi_editor.first_of_next_group(self._events, cur)
        if nxt >= 0:
            self._navigate_to(nxt)
            self._toggle_group_selection(nxt)
            self._play_group_at(nxt)
            group = self._midi_editor.group_indices(self._events, nxt)
            self._group_entry = len(group) > 1
            wx.CallAfter(self._announce_group, nxt)
        else:
            self._set_status("Dernier groupe")

    def _select_move_left(self):
        """Shift+← : groupe précédent + toggle sélection du groupe + joue."""
        if not self._events:
            return
        cur = self._midi_editor._cur_idx
        prv = self._midi_editor.first_of_prev_group(self._events, cur)
        if prv >= 0:
            self._navigate_to(prv)
            self._toggle_group_selection(prv)
            self._play_group_at(prv)
            group = self._midi_editor.group_indices(self._events, prv)
            self._group_entry = len(group) > 1
            wx.CallAfter(self._announce_group, prv)
        else:
            self._set_status("Premier groupe")

    def _select_move_down(self):
        """Shift+↓ : note suivante dans le groupe + toggle sélection."""
        if not self._events:
            return
        cur   = self._midi_editor._cur_idx
        group = self._midi_editor.group_indices(self._events, cur)
        if not group:
            return
        if self._group_entry:
            target = group[0]
            self._group_entry = False
        else:
            pos = group.index(cur) if cur in group else 0
            target = group[pos + 1] if pos < len(group) - 1 else group[-1]
            if target != cur:
                self._navigate_to(target)
        self._toggle_note_selection(target)
        self._play_single_at(target)
        wx.CallAfter(self._announce_note, target)

    def _select_move_up(self):
        """Shift+↑ : note précédente dans le groupe + toggle sélection."""
        if not self._events:
            return
        cur   = self._midi_editor._cur_idx
        group = self._midi_editor.group_indices(self._events, cur)
        if not group:
            return
        if self._group_entry:
            target = group[0]
            self._group_entry = False
        else:
            pos = group.index(cur) if cur in group else 0
            target = group[pos - 1] if pos > 0 else group[0]
            if target != cur:
                self._navigate_to(target)
        self._toggle_note_selection(target)
        self._play_single_at(target)
        wx.CallAfter(self._announce_note, target)

    def _announce_event_selected(self, idx):
        """Annonce Shift+↑/↓ en liste plate (MODE_ALL) : nom/valeur + position
        + nombre d'événements sélectionnés — équivalent flat de _announce_note."""
        if not self._events or idx >= len(self._events):
            return
        e   = self._events[idx]
        bbt = self._bbt_str(e["bar"], e["step"])
        suf = self._sel_status_suffix()
        if e["type"] == "note":
            name = self._event_note_name(e)
            self._set_status(f"({name})  {bbt}{suf}")
        else:
            self._set_status(f"{e['type'].capitalize()}:{e['value']}  {bbt}{suf}")

    def _select_move_up_flat(self):
        """Shift+↑ en liste plate (MODE_ALL) : événement précédent + toggle
        sélection — un événement à la fois, sans regroupement par offset
        (contrairement à _select_move_up, dédiée au piano roll MODE_NOTES).

        Si l'événement courant n'est pas encore sélectionné (première
        pression, ou retour à la position de départ après navigation libre),
        on le sélectionne d'abord SANS bouger — sinon le point de départ
        n'est jamais inclus dans la sélection (bug signalé : le tout premier
        événement, index 1, restait toujours désélectionné)."""
        if not self._events:
            return
        cur = self._midi_editor._cur_idx
        if cur not in self._selected_indices:
            self._toggle_note_selection(cur)
            self._play_single_at(cur)
            wx.CallAfter(self._announce_event_selected, cur)
            return
        target = max(cur - 1, 0)
        if target != cur:
            self._navigate_to(target)
        self._toggle_note_selection(target)
        self._play_single_at(target)
        wx.CallAfter(self._announce_event_selected, target)

    def _select_move_down_flat(self):
        """Shift+↓ en liste plate (MODE_ALL) : événement suivant + toggle
        sélection — un événement à la fois, sans regroupement par offset
        (contrairement à _select_move_down, dédiée au piano roll MODE_NOTES).

        Même ancrage que _select_move_up_flat : sélectionne d'abord
        l'événement courant sans bouger s'il n'est pas déjà sélectionné."""
        if not self._events:
            return
        cur = self._midi_editor._cur_idx
        if cur not in self._selected_indices:
            self._toggle_note_selection(cur)
            self._play_single_at(cur)
            wx.CallAfter(self._announce_event_selected, cur)
            return
        target = min(cur + 1, len(self._events) - 1)
        if target != cur:
            self._navigate_to(target)
        self._toggle_note_selection(target)
        self._play_single_at(target)
        wx.CallAfter(self._announce_event_selected, target)
