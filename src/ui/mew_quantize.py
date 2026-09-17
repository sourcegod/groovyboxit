import wx


class QuantizeMixin:
    """MidiEditorWindow — dialogues quantisation, Goto, Grille, Filtre."""

    def _quantize_dialog(self):
        """Ouvre le dialog de quantisation depuis l'éditeur MIDI.

        Le dialog est créé avec self comme parent wxPython afin que ESC/Annuler
        redonne le focus à l'éditeur et non à la fenêtre principale.
        """
        from ui.dialogs_simple import QuantizeDialog
        from pattern import Pattern
        p        = self._parent._player
        old_snap = (p._quant_res_idx, p._quant_force_idx, p._quant_swing_idx,
                    p._quant_window_idx, p._quant_starts, p._quant_durations,
                    p._quant_direction_idx)
        dlg = QuantizeDialog(self,
                             res_idx        = p._quant_res_idx,
                             force_idx      = p._quant_force_idx,
                             swing_idx      = p._quant_swing_idx,
                             window_idx     = p._quant_window_idx,
                             quant_starts   = p._quant_starts,
                             quant_durations= p._quant_durations,
                             direction_idx  = p._quant_direction_idx)
        result = dlg.ShowModal()
        if result in (wx.ID_OK, wx.ID_APPLY):
            p._quant_res_idx       = dlg.get_resolution()
            p._quant_force_idx     = dlg.get_force_idx()
            p._quant_swing_idx     = dlg.get_swing_idx()
            p._quant_window_idx    = dlg.get_window_idx()
            p._quant_starts        = dlg.get_quant_starts()
            p._quant_durations     = dlg.get_quant_durations()
            p._quant_direction_idx = dlg.get_direction_idx()
            new_snap = (p._quant_res_idx, p._quant_force_idx, p._quant_swing_idx,
                        p._quant_window_idx, p._quant_starts, p._quant_durations,
                        p._quant_direction_idx)
            res = p._quant_res_idx
            if res == -2:
                _, kind, val = Pattern.GRID_RESOLUTIONS[p._grid_idx]
                res = (Pattern.QUANT_STEPS.index(val)
                       if kind == "snaps" and val in Pattern.QUANT_STEPS else -1)
            if result == wx.ID_APPLY and res >= 0:
                self._parent._add_undo("Quantiser pattern (éditeur MIDI)")
            elif result == wx.ID_OK and new_snap != old_snap:
                self._parent._add_undo("Paramètres quantisation modifiés")
                p.apply_quant_to_pattern(
                    res,
                    force_idx      = p._quant_force_idx,
                    swing_idx      = p._quant_swing_idx,
                    window_idx     = p._quant_window_idx,
                    quant_starts   = p._quant_starts,
                    quant_durations= p._quant_durations,
                    direction_idx  = p._quant_direction_idx,
                )
                p._compute_offsets()
                self._parent._refresh_grid()
                self._refresh()
                self._set_status(f"Pattern quantisé : {Pattern.QUANT_LIST[res]}")
            elif res >= 0:
                self._set_status(f"Quantisation mémorisée : {Pattern.QUANT_LIST[res]}")
            else:
                self._set_status("Quantisation : aucune résolution sélectionnée")
        dlg.Destroy()
        self._event_lb.SetFocus()

    def _goto_dialog(self):
        """Ctrl+G depuis l'éditeur MIDI (voir _quantize_dialog : le dialog
        est créé avec self comme parent wxPython afin que ESC/Annuler
        redonne le focus à l'éditeur et non à la fenêtre principale)."""
        from ui.dialogs_temporal import GotoDialog
        p   = self._parent._player
        pat = p._pattern
        dlg = GotoDialog(
            self,
            step_idx      = int(p._current_offset()),
            num_bars      = pat._num_bars,
            num_beats     = pat._num_beats,
            num_steps     = pat._num_steps,
            step_duration = p.step_duration,
        )
        if dlg.ShowModal() == wx.ID_OK:
            p._go_to_offset(dlg.get_offset())
            self._refresh()
            self._set_status(f"Position: {self._bbt_str(*divmod(int(p._current_offset()), pat._num_steps))}")
        dlg.Destroy()
        self._event_lb.SetFocus()

    def _grid_dialog(self):
        """Ctrl+Shift+G depuis l'éditeur MIDI (voir _goto_dialog)."""
        from ui.dialogs_simple import GridDialog
        from pattern import Pattern
        p       = self._parent._player
        old_idx = p._grid_idx
        dlg = GridDialog(self, old_idx)
        if dlg.ShowModal() == wx.ID_OK:
            new_idx = dlg.get_grid_idx()
            if new_idx != old_idx:
                self._parent._add_undo(
                    f"Grille : {Pattern.GRID_LABELS[old_idx]} → {Pattern.GRID_LABELS[new_idx]}"
                )
                p._grid_idx = new_idx
            self._set_status(f"Grille : {Pattern.GRID_LABELS[p._grid_idx]}")
        dlg.Destroy()
        self._event_lb.SetFocus()

    def _filter_dialog(self):
        """Ctrl+Shift+F depuis l'éditeur MIDI (voir _goto_dialog : le dialog
        est créé avec self comme parent wxPython afin que ESC/Annuler
        redonne le focus à l'éditeur et non à la fenêtre principale)."""
        from ui.dialogs_temporal import EventFilterDialog
        p   = self._parent._player
        pat = p._pattern
        te  = self._parent._track_editor
        dlg = EventFilterDialog(
            self,
            events     = self._events,
            num_bars   = pat._num_bars,
            num_beats  = pat._num_beats,
            num_steps  = pat._num_steps,
            lim_left   = te._lim_left,
            lim_right  = te._lim_right,
            view_mode  = self._view_mode,
            state      = p._event_filter_state,
            on_action  = self._apply_filter_result,
        )
        dlg.ShowModal()
        dlg.Destroy()
        self._event_lb.SetFocus()

    def _apply_filter_result(self, action, matched, criteria=None):
        """Callback EventFilterDialog : applique le résultat du filtre à la
        sélection courante et mémorise l'état en session (persistance
        Ctrl+Shift+F, voir DrumPlayer._event_filter_state)."""
        if action == "apply":
            self._selected_indices = set(matched)
        elif action == "add":
            self._selected_indices |= matched
        elif action == "remove":
            self._selected_indices -= matched
        elif action == "reset_sel":
            self._selected_indices = set()

        if action in ("apply", "add", "remove") and criteria is not None:
            self._parent._player._event_filter_state = criteria

        self._refresh_labels()
        self._sync_lims_from_selection()
        self._set_status(f"Filtre: {len(self._selected_indices)} événement(s) sélectionné(s)")

    def _quantize_from_grid(self):
        from pattern import Pattern
        p = self._parent._player
        _, kind, val = Pattern.GRID_RESOLUTIONS[p._grid_idx]
        res = Pattern.QUANT_STEPS.index(val) if kind == "snaps" and val in Pattern.QUANT_STEPS else -1
        if res < 0:
            self._set_status("Ctrl+Q : résolution de grille incompatible")
            return
        self._parent._add_undo("Quantiser pattern (grille, éditeur MIDI)")
        p.apply_quant_to_pattern(
            res,
            force_idx      = p._quant_force_idx,
            swing_idx      = p._quant_swing_idx,
            window_idx     = p._quant_window_idx,
            quant_starts   = p._quant_starts,
            quant_durations= p._quant_durations,
            direction_idx  = p._quant_direction_idx,
        )
        p._compute_offsets()
        self._parent._refresh_grid()
        self._refresh()
        self._set_status(f"Pattern quantisé (grille) : {Pattern.QUANT_LIST[res]}")

    def _quantize_with_last_params(self):
        from pattern import Pattern
        p = self._parent._player
        res = p._quant_res_idx
        if res == -2:
            _, kind, val = Pattern.GRID_RESOLUTIONS[p._grid_idx]
            res = Pattern.QUANT_STEPS.index(val) if kind == "snaps" and val in Pattern.QUANT_STEPS else -1
        if res < 0:
            self._set_status("Shift+Q : aucune résolution de quantisation mémorisée")
            return
        self._parent._add_undo("Quantiser pattern (derniers params, éditeur MIDI)")
        p.apply_quant_to_pattern(
            res,
            force_idx      = p._quant_force_idx,
            swing_idx      = p._quant_swing_idx,
            window_idx     = p._quant_window_idx,
            quant_starts   = p._quant_starts,
            quant_durations= p._quant_durations,
            direction_idx  = p._quant_direction_idx,
        )
        p._compute_offsets()
        self._parent._refresh_grid()
        self._refresh()
        self._set_status(f"Pattern quantisé : {Pattern.QUANT_LIST[res]}")
