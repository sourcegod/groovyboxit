import wx
from .dialogs import TrackPropertiesDialog


class TrackMixin:
    """Méthodes MainWindow relatives aux pistes (tracks), slots et sélection."""

    def _assign_track_slot(self):
        track_idx = self._player._cur_track
        slot_idx  = self._cur_slot
        self._router.assign_slot(track_idx, slot_idx)
        self._refresh_track_list()
        slot = self._rack.get_slot(slot_idx)
        self._show_status(
            f"Piste {track_idx + 1} → Slot_{slot_idx + 1:02d} ({slot.name})"
        )

    def _track_properties_dialog(self):
        tidx = self._player._cur_track
        orig = dict(
            slot   = self._router.slot_for_track(tidx),
            volume = self._router.get_track_volume(tidx),
            pan    = self._router.get_track_pan(tidx),
            mute   = self._router._track_mutes[tidx],
            solo   = self._router._track_solos[tidx],
        )

        def apply(slot, vol, pan, mute, solo):
            if slot != self._router.slot_for_track(tidx):
                self._router.assign_slot(tidx, slot)
                self._cur_slot = slot
                self._slot_choice.SetSelection(slot)
            self._router.set_track_volume(tidx, vol)
            self._router.set_track_pan(tidx, pan)
            self._router._track_mutes[tidx] = mute
            self._router._track_solos[tidx] = solo
            self._refresh_track_list()

        dlg    = TrackPropertiesDialog(
            self, tidx, self._rack,
            orig['slot'], orig['volume'], orig['pan'], orig['mute'], orig['solo'],
            on_change=apply, on_play_toggle=self._play_toggle,
        )
        result = dlg.ShowModal()
        if result == wx.ID_OK:
            apply(dlg.get_slot_idx(), dlg.get_volume(), dlg.get_pan(),
                  dlg.get_mute(), dlg.get_solo())
            self._show_status(f"Piste {tidx + 1}: propriétés mises à jour")
        else:
            apply(orig['slot'], orig['volume'], orig['pan'], orig['mute'], orig['solo'])
            self._show_status(f"Piste {tidx + 1}: modifications annulées")
        dlg.Destroy()

    def _rename_track(self):
        """F2 : renomme la piste courante via un TextEntryDialog."""
        idx = self._player._cur_track
        old = self._player.voice_manager.get_name(idx)
        self._add_undo(f"Renommer piste {idx + 1}")
        dlg = wx.TextEntryDialog(self, f"Nom de la piste {idx + 1}:", "Renommer", old)
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name == old:
                self._pop_last_undo()
            else:
                self._player.voice_manager.set_name(idx, name)
                cur = self._pattern_list[self._cur_pattern_idx]
                cur._voices[idx]["name"] = name
                self._refresh_track_list()
                self._show_status(f"Piste {idx + 1}: {name or '(sans nom)'}")
        else:
            self._pop_last_undo()
        dlg.Destroy()

    def _track_label(self, idx):
        slot_idx  = self._router.slot_for_track(idx)
        slot_name = self._router.slot_name(idx)
        prefix    = "* " if self._track_editor.is_selected(idx) else "  "
        track_name = self._player.voice_manager.get_name(idx)
        if track_name:
            label = f"{prefix}Track_{idx + 1:02d} ({track_name}) - Slot_{slot_idx + 1:02d} - {slot_name}"
        else:
            label = f"{prefix}Track_{idx + 1:02d} - Slot_{slot_idx + 1:02d} - {slot_name}"
        if self._player._cur_track == idx and self._player.recording:
            label += " [REC]"
        if self._router._track_mutes[idx]:
            label += " [M]"
        if self._router._track_solos[idx]:
            label += " [S]"
        return label

    def _refresh_track_list(self):
        for i in range(self._track_list.GetCount()):
            self._track_list.SetString(i, self._track_label(i))

    def _on_track_list_activate(self, event):
        if wx.GetKeyState(wx.WXK_RETURN) and wx.GetKeyState(wx.WXK_CONTROL):
            self._track_select_dialog()
        elif wx.GetKeyState(wx.WXK_RETURN) and wx.GetKeyState(wx.WXK_ALT):
            self._track_properties_dialog()
        elif wx.GetKeyState(wx.WXK_RETURN):
            self._assign_track_slot()
        else:
            self._play(self._cur_row)

    def _on_pattern_list_activate(self, event):
        if wx.GetKeyState(wx.WXK_ALT):
            self._pattern_properties_dialog()
        else:
            self._play(self._cur_row)

    def _on_listbox_play_activate(self, event):
        self._play(self._cur_row)

    def _on_slot_list_activate(self, event):
        self._assign_track_slot()

    def _on_midi_port_activate(self, event):
        self._midi_handler.connect()

    def _on_track_select(self, event):
        idx = self._track_list.GetSelection()
        if idx < 0:
            return
        if self._skip_next_track_select:
            self._skip_next_track_select = False
            return
        if self._player.recording or self._player._count_in > 0:
            self._track_list.SetSelection(self._player._cur_track)
            self._show_status("Changement de piste interdit pendant l'enregistrement")
            return
        self._track_editor.clear_selection()
        self._refresh_track_list()
        self._go_to_track(idx)

    def _go_to_track(self, idx):
        from rack import InstrumentType
        if self._player.recording or self._player._count_in > 0:
            self._track_list.SetSelection(self._player._cur_track)
            self._show_status("Changement de piste interdit pendant l'enregistrement")
            return
        self._player._cur_track = idx
        self._cur_slot = self._router.slot_for_track(idx)
        self._slot_choice.SetSelection(self._cur_slot)
        self._router.reset_kit_pad()
        self._refresh_grid()
        slot = self._rack.get_slot(self._cur_slot)
        self._show_status(f"Piste {idx + 1} — {slot.name}")
        if slot.type == InstrumentType.SYNTH:
            self._router.load_slot_preview(self._cur_slot)
        elif slot.type == InstrumentType.KIT:
            self._load_kit_slot(self._cur_slot)
        if self._midi_editor_window is not None:
            self._midi_editor_window.refresh()

    def _on_slot_choice(self, event):
        from rack import InstrumentType
        self._cur_slot = self._slot_choice.GetSelection()
        slot = self._rack.get_slot(self._cur_slot)
        if slot.is_empty:
            self._show_status(f"Slot {self._cur_slot + 1:02d}: vide — Alt+X pour charger")
        else:
            self._show_status(
                f"Slot {self._cur_slot + 1:02d}: {slot.name} (Ctrl+T pour assigner)"
            )
            if slot.type == InstrumentType.SYNTH:
                self._router.load_slot_preview(self._cur_slot)
            elif slot.type == InstrumentType.KIT:
                self._load_kit_slot(self._cur_slot)

    def _update_slot_list(self):
        self._slot_choice.Set(self._rack.labels())
        self._slot_choice.SetSelection(self._cur_slot)
