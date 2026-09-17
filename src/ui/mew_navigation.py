import wx


class NavigationMixin:
    """MidiEditorWindow — déplacement du curseur (groupes/notes)."""

    def _on_listbox_select(self, evt):
        idx = self._event_lb.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        self._midi_editor._cur_idx = idx
        if self._skip_listbox_announce:
            self._skip_listbox_announce = False
            return
        if self._view_mode == self.MODE_ALL:
            # Navigation native (Haut/Bas via evt.Skip(), ou clic) : la
            # ListBox est déjà lue par Orca (label = format complet), il
            # reste à synchroniser le playhead et jouer la note le cas
            # échéant (silencieux sur CC/Bend, voir _play_event).
            self._parent._player._go_to_offset(float(self._events[idx]["offset"]))
            self._play_single_at(idx)
        self._announce_event(idx)

    def _navigate_to(self, idx):
        """Déplace la sélection sans déclencher l'annonce EVT_LISTBOX.
        Synchronise aussi le playhead sur l'offset de l'événement cible,
        afin que I/O enregistrent la position courante dans la liste."""
        if not self._events:
            return
        idx = max(0, min(idx, len(self._events) - 1))
        self._midi_editor._cur_idx = idx
        self._skip_listbox_announce = True
        self._event_lb.SetSelection(idx)
        self._parent._player._go_to_offset(float(self._events[idx]["offset"]))

    def _move_right(self):
        """→ : groupe temporel suivant, joue le groupe, annonce position."""
        if not self._events:
            return
        cur = self._midi_editor._cur_idx
        nxt = self._midi_editor.first_of_next_group(self._events, cur)
        if nxt >= 0:
            self._navigate_to(nxt)
            self._play_group_at(nxt)
            group = self._midi_editor.group_indices(self._events, nxt)
            self._group_entry = len(group) > 1
            wx.CallAfter(self._announce_group, nxt)
        else:
            self._set_status("Dernier groupe")

    def _move_left(self):
        """← : groupe temporel précédent, joue le groupe, annonce position."""
        if not self._events:
            return
        cur = self._midi_editor._cur_idx
        prv = self._midi_editor.first_of_prev_group(self._events, cur)
        if prv >= 0:
            self._navigate_to(prv)
            self._play_group_at(prv)
            group = self._midi_editor.group_indices(self._events, prv)
            self._group_entry = len(group) > 1
            wx.CallAfter(self._announce_group, prv)
        else:
            self._set_status("Premier groupe")

    def _move_down_in_group(self):
        """↓ : note suivante dans l'accord courant ; joue et annonce toujours."""
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
            if pos < len(group) - 1:
                target = group[pos + 1]
                self._navigate_to(target)
            else:
                target = group[-1]
        self._play_single_at(target)
        wx.CallAfter(self._announce_note, target)

    def _move_up_in_group(self):
        """↑ : note précédente dans l'accord courant ; joue et annonce toujours."""
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
            if pos > 0:
                target = group[pos - 1]
                self._navigate_to(target)
            else:
                target = group[0]
        self._play_single_at(target)
        wx.CallAfter(self._announce_note, target)
