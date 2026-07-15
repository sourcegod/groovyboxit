import wx
from pattern import Pattern
from .dialogs import (
    GenRowDialog,
    GridDialog,
    GotoDialog,
    QuantizeDialog,
    SavePatternDialog,
    TrackSelectDialog,
    PatternPropertiesDialog,
    LoopSelectDialog,
    KeyboardHelpDialog,
)


class PatternMixin:
    """Méthodes MainWindow relatives aux patterns : grille, sauvegarde, dialogs."""

    def _refresh_grid(self):
        for r in range(self.ROWS):
            for c in range(self.COLS):
                self._cells[r][c].SetValue(
                    self._player._pattern._curpattern[self._player._cur_track][r][0][c]
                )
        self._player._compute_offsets()

    def _on_pattern_select(self, event):
        self._switch_pattern(self._pattern_listbox.GetSelection())

    def _rename_pattern(self):
        """F2 : renomme le pattern courant via un TextEntryDialog."""
        idx = self._cur_pattern_idx
        old = self._pattern_list[idx]._name
        self._add_undo(f"Renommer pattern {idx + 1:02d}")
        dlg = wx.TextEntryDialog(self, f"Nom du pattern {idx + 1:02d}:", "Renommer", old)
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name == old:
                self._pop_last_undo()
            else:
                self._pattern_list[idx]._name = name
                self._player._pattern._name   = name
                self._refresh_pattern_listbox()
                self._show_status(f"Pattern {idx + 1:02d}: {name or '(sans nom)'}")
        else:
            self._pop_last_undo()
        dlg.Destroy()

    def _pattern_label(self, idx):
        pat = self._pattern_list[idx]
        if pat._name:
            return f"Pat_{idx + 1:02d} - {pat._name}"
        if pat.is_empty():
            return f"Pat_{idx + 1:02d} (Unused)"
        return f"Pat_{idx + 1:02d}"

    def _refresh_pattern_listbox(self):
        sel = self._pattern_listbox.GetSelection()
        self._pattern_listbox.Set([self._pattern_label(i) for i in range(99)])
        self._pattern_listbox.SetSelection(sel if sel != wx.NOT_FOUND else 0)

    def _flush_pattern_to_store(self, pat):
        """Copie l'état courant du player + router dans l'objet Pattern du store."""
        live = self._player._pattern
        pat.load_pattern(live._curpattern)
        pat._bpm           = self._player.bpm
        pat._track_slots   = self._router._track_slots[:]
        pat._track_mutes   = self._router._track_mutes[:]
        pat._track_solos   = self._router._track_solos[:]
        pat._track_volumes = self._router._track_volumes[:]
        pat._track_pans    = self._router._track_pans[:]
        pat._tape      = dict(live._tape)
        pat._bend_tape = [list(t) for t in live._bend_tape]
        pat._mod_tape  = [list(t) for t in live._mod_tape]

    def _apply_pattern_from_store(self, new):
        """Charge un Pattern du store dans le player et le router."""
        live = self._player._pattern
        live.load_pattern(new._curpattern)
        self._player.set_bpm(new._bpm)
        self._bpm_ctrl.SetValue(int(new._bpm))
        live._looping  = new._looping
        live._tape     = dict(new._tape)
        live._bend_tape = [list(t) for t in new._bend_tape]
        live._mod_tape  = [list(t) for t in new._mod_tape]
        self._player.voice_manager.from_list(new._voices)
        self._router._track_slots[:]   = new._track_slots
        self._router._track_mutes[:]   = new._track_mutes
        self._router._track_solos[:]   = new._track_solos
        self._router._track_volumes[:] = new._track_volumes
        self._router._track_pans[:]    = new._track_pans
        self._router.set_playback_kb(new._kb_scale, new._kb_root_midi)

    def _play_toggle(self):
        """Bascule lecture / arrêt (utilisé comme callback par les dialogs de propriétés)."""
        if self._player.playing:
            self._player.stop_pattern()
        else:
            self._player.play_pattern()

    def _switch_pattern(self, idx):
        cur = self._pattern_list[self._cur_pattern_idx]
        cur._voices = self._player.voice_manager.to_list()
        self._flush_pattern_to_store(cur)
        self._pattern_cache_dirty.add(self._cur_pattern_idx)  # ancien courant flushé
        self._cur_pattern_idx = idx
        new = self._pattern_list[idx]
        self._apply_pattern_from_store(new)
        self._player._compute_offsets()
        self._refresh_grid()
        self._refresh_all_voice_display()
        self._refresh_track_list()
        self._refresh_pad_list()
        self._show_status(f"Pattern {idx + 1:02d}")

    def _save_pattern(self):
        self._add_undo(f"Sauvegarder pattern {self._cur_pattern_idx + 1:02d}")
        pat = self._pattern_list[self._cur_pattern_idx]
        pat.load_pattern(self._player._pattern._curpattern)
        self._flush_pattern_to_store(pat)
        self._refresh_pattern_listbox()
        self._mark_modified()
        self._show_status(f"Pattern {self._cur_pattern_idx + 1:02d} sauvegardé")

    def _save_pattern_as(self):
        cur_name = self._pattern_list[self._cur_pattern_idx]._name
        dlg = SavePatternDialog(self, self._cur_pattern_idx, cur_name)
        if dlg.ShowModal() == wx.ID_OK:
            idx  = dlg.get_selection()
            name = dlg.get_name()
            self._add_undo(f"Dupliquer pattern → {idx + 1:02d}")
            pat  = self._pattern_list[idx]
            pat.load_pattern(self._player._pattern._curpattern)
            pat._name = name
            self._flush_pattern_to_store(pat)
            self._pattern_cache_dirty.add(idx)   # slot cible modifié hors du courant
            self._refresh_pattern_listbox()
            self._mark_modified()
            self._show_status(f"Pattern {idx + 1:02d} dupliqué")
        dlg.Destroy()

    def _on_quant_select(self, event):
        self._player.quant_idx = self._quant_list.GetSelection()
        self._apply_quant()

    def _apply_quant(self):
        row       = self._cur_row
        quant_idx = self._quant_list.GetSelection()
        self._player.quant_idx = quant_idx
        self._add_undo(f"Quant ligne {row + 1}")
        self._player.apply_quant_row(quant_idx, row)
        pad = self._player._pattern._curpattern[self._player._cur_track][row][0]
        for c in range(self.COLS):
            self._cells[row][c].SetValue(bool(pad[c]))
        self._show_status(f"Ligne {row + 1}: {Pattern.QUANT_LIST[quant_idx]} coché")

    def _quantize_pattern(self):
        self._add_undo("Quantiser pattern")
        self._player.apply_quant_to_pattern()
        self._refresh_grid()
        self._show_status(f"Pattern quantisé: {Pattern.QUANT_LIST[self._player.quant_idx]}")

    def _quantize_from_grid(self):
        p = self._player
        _, kind, val = Pattern.GRID_RESOLUTIONS[p._grid_idx]
        res = Pattern.QUANT_STEPS.index(val) if kind == "snaps" and val in Pattern.QUANT_STEPS else -1
        if res < 0:
            self._show_status("Ctrl+Q : résolution de grille incompatible")
            return
        self._add_undo("Quantiser pattern (grille)")
        p.apply_quant_to_pattern(
            res,
            force_idx      = p._quant_force_idx,
            swing_idx      = p._quant_swing_idx,
            window_idx     = p._quant_window_idx,
            quant_starts   = p._quant_starts,
            quant_durations= p._quant_durations,
        )
        p._compute_offsets()
        self._refresh_grid()
        self._show_status(f"Pattern quantisé (grille) : {Pattern.QUANT_LIST[res]}")

    def _quantize_with_last_params(self):
        p = self._player
        res = p._quant_res_idx
        if res == -2:
            _, kind, val = Pattern.GRID_RESOLUTIONS[p._grid_idx]
            res = Pattern.QUANT_STEPS.index(val) if kind == "snaps" and val in Pattern.QUANT_STEPS else -1
        if res < 0:
            self._show_status("Shift+Q : aucune résolution de quantisation mémorisée")
            return
        self._add_undo("Quantiser pattern (derniers params)")
        p.apply_quant_to_pattern(
            res,
            force_idx      = p._quant_force_idx,
            swing_idx      = p._quant_swing_idx,
            window_idx     = p._quant_window_idx,
            quant_starts   = p._quant_starts,
            quant_durations= p._quant_durations,
        )
        p._compute_offsets()
        self._refresh_grid()
        self._show_status(f"Pattern quantisé : {Pattern.QUANT_LIST[res]}")

    def _gen_row_dialog(self):
        dlg    = GenRowDialog(self, self._cur_row, self._player.quant_idx, self.ROWS)
        result = dlg.ShowModal()
        if result in (wx.ID_OK, wx.ID_APPLY):
            row       = dlg.get_row()
            quant_idx = dlg.get_quant_idx()
            self._player.quant_idx = quant_idx
            self._quant_list.SetSelection(quant_idx)
            if result == wx.ID_APPLY:
                self._add_undo(f"Générer ligne {row + 1}")
                self._player.apply_quant_row(quant_idx, row)
                pad = self._player._pattern._curpattern[self._player._cur_track][row][0]
                for c in range(self.COLS):
                    self._cells[row][c].SetValue(bool(pad[c]))
                self._show_status(
                    f"Ligne {row + 1}: {Pattern.QUANT_LIST[quant_idx]} généré"
                )
            else:
                self._show_status(
                    f"Défaut: ligne {row + 1}, quant {Pattern.QUANT_LIST[quant_idx]}"
                )
        dlg.Destroy()

    def _goto_dialog(self):
        p   = self._player
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
        dlg.Destroy()

    def _loop_select_dialog(self):
        p   = self._player
        pat = p._pattern
        te  = self._track_editor
        dlg = LoopSelectDialog(
            self,
            num_bars       = pat._num_bars,
            num_beats      = pat._num_beats,
            num_steps      = pat._num_steps,
            cur_step       = int(p._current_offset()),
            loop_start     = pat._loop_start,
            loop_end       = pat._loop_end,
            loop_count     = pat._loop_count,
            looping        = pat._looping,
            lim_left       = te._lim_left,
            lim_right      = te._lim_right,
            on_play_toggle = self._play_toggle,
        )
        if dlg.ShowModal() == wx.ID_OK:
            ls      = dlg.get_loop_start()
            le      = dlg.get_loop_end()
            lc      = dlg.get_loop_count()
            looping = dlg.get_looping()
            pat._loop_start = ls
            pat._loop_end   = le
            pat._loop_count = lc
            pat._looping    = looping
            p._loop_remaining = lc
            saved = self._pattern_list[self._cur_pattern_idx]
            saved._loop_start = ls
            saved._loop_end   = le
            saved._loop_count = lc
            saved._looping    = looping
            if p.playing or p.clicking or p._note_repeat_active:
                p._wakeup.set()
            total = pat._num_bars * pat._num_steps
            start_str = dlg._fmt_bbt(ls if ls is not None else 0)
            end_str   = dlg._fmt_bbt(le if le is not None else total - 1)
            rep_str   = f"{lc} fois" if lc else "infini"
            loop_str  = "On" if looping else "Off"
            self._show_status(
                f"Boucle [{loop_str}]: {start_str} → {end_str} | {rep_str}"
            )
        dlg.Destroy()

    def _track_select_dialog(self):
        p   = self._player
        pat = p._pattern
        track_labels = [
            f"Track {i + 1:02d} — {self._router.slot_name(i)}"
            for i in range(pat._num_tracks)
        ]
        te  = self._track_editor
        dlg = TrackSelectDialog(
            self,
            num_tracks   = pat._num_tracks,
            sel_tracks   = te._sel_tracks,
            track_labels = track_labels,
            num_bars     = pat._num_bars,
            num_beats    = pat._num_beats,
            num_steps    = pat._num_steps,
            cur_step     = int(p._current_offset()),
            lim_left     = te._lim_left,
            lim_right    = te._lim_right,
        )
        if dlg.ShowModal() == wx.ID_OK:
            new_sel = dlg.get_sel_tracks()
            te._sel_tracks = new_sel
            self._refresh_track_list()
            start = dlg.get_start_step()
            end   = dlg.get_end_step()
            if start > end:
                start, end = end, start
            te._lim_left  = start
            te._lim_right = end
            sel = sorted(new_sel)
            msg_tracks = (
                f"Piste{'s' if len(sel) > 1 else ''} {', '.join(str(i+1) for i in sel)}"
                if sel else "Aucune piste"
            )
            self._show_status(
                f"Sélection : {msg_tracks} | {dlg._fmt_bbt(start)} → {dlg._fmt_bbt(end)}"
            )
        dlg.Destroy()

    def _show_keyboard_help(self):
        dlg = KeyboardHelpDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def _grid_dialog(self):
        old_idx = self._player._grid_idx
        dlg = GridDialog(self, old_idx)
        if dlg.ShowModal() == wx.ID_OK:
            new_idx = dlg.get_grid_idx()
            if new_idx != old_idx:
                self._add_undo(f"Grille : {Pattern.GRID_LABELS[old_idx]} → {Pattern.GRID_LABELS[new_idx]}")
                self._player._grid_idx = new_idx
            label = Pattern.GRID_LABELS[self._player._grid_idx]
            self._show_status(f"Grille : {label}")
        dlg.Destroy()

    def _quantize_pattern_dialog(self):
        p        = self._player
        old_snap = (p._quant_res_idx, p._quant_force_idx, p._quant_swing_idx,
                    p._quant_window_idx, p._quant_starts, p._quant_durations)
        dlg = QuantizeDialog(self,
                             res_idx        = p._quant_res_idx,
                             force_idx      = p._quant_force_idx,
                             swing_idx      = p._quant_swing_idx,
                             window_idx     = p._quant_window_idx,
                             quant_starts   = p._quant_starts,
                             quant_durations= p._quant_durations)
        result = dlg.ShowModal()
        if result in (wx.ID_OK, wx.ID_APPLY):
            p._quant_res_idx    = dlg.get_resolution()
            p._quant_force_idx  = dlg.get_force_idx()
            p._quant_swing_idx  = dlg.get_swing_idx()
            p._quant_window_idx = dlg.get_window_idx()
            p._quant_starts     = dlg.get_quant_starts()
            p._quant_durations  = dlg.get_quant_durations()
            new_snap = (p._quant_res_idx, p._quant_force_idx, p._quant_swing_idx,
                        p._quant_window_idx, p._quant_starts, p._quant_durations)
            # Résoudre la résolution effective (Grille courante → QUANT_STEPS)
            res = p._quant_res_idx
            if res == -2:   # Grille courante
                _, kind, val = Pattern.GRID_RESOLUTIONS[p._grid_idx]
                res = Pattern.QUANT_STEPS.index(val) if kind == "snaps" and val in Pattern.QUANT_STEPS else -1
            if result == wx.ID_APPLY and res >= 0:
                self._add_undo("Quantiser pattern")
            elif result == wx.ID_OK and new_snap != old_snap:
                self._add_undo("Paramètres quantisation modifiés")
                self._player.apply_quant_to_pattern(
                    res,
                    force_idx      = p._quant_force_idx,
                    swing_idx      = p._quant_swing_idx,
                    window_idx     = p._quant_window_idx,
                    quant_starts   = p._quant_starts,
                    quant_durations= p._quant_durations,
                )
                self._player._compute_offsets()
                self._refresh_grid()
                self._show_status(f"Pattern quantisé : {Pattern.QUANT_LIST[res]}")
            elif res >= 0:
                self._show_status(f"Quantisation mémorisée : {Pattern.QUANT_LIST[res]}")
            else:
                self._show_status("Quantisation : aucune résolution sélectionnée")
        dlg.Destroy()

    def _pattern_properties_dialog(self):
        pat  = self._pattern_list[self._cur_pattern_idx]
        live = self._player._pattern
        dlg  = PatternPropertiesDialog(
            self,
            self._cur_pattern_idx,
            pat._name,
            pat._start_bar,
            live._num_bars,
            live._num_steps,
            pat._looping,
            Pattern.MAX_BARS,
            Pattern.VALID_NUM_STEPS,
            on_play_toggle=self._play_toggle,
        )
        result = dlg.ShowModal()
        if result == wx.ID_OK:
            name      = dlg.get_name()
            start_bar = dlg.get_start_bar()
            num_bars  = dlg.get_num_bars()
            num_steps = dlg.get_num_steps()
            looping   = dlg.get_looping()
            action    = dlg.get_action()
            pat._name      = name
            pat._start_bar = start_bar
            pat._looping   = looping
            live._looping  = looping
            if action == "Nouveau":
                self._add_undo(f"Nouveau pattern {self._cur_pattern_idx + 1:02d}")
                pat.new_pattern(num_bars, num_steps)
                live.new_pattern(num_bars, num_steps)
                self._player._compute_offsets()
                self._refresh_grid()
                self._show_status(f"Pattern {self._cur_pattern_idx + 1:02d}: nouveau")
            elif action == "Doubler":
                self._add_undo(f"Doubler pattern {self._cur_pattern_idx + 1:02d}")
                if self._player.double_pattern():
                    pat.load_pattern(live._curpattern)
                    self._refresh_grid()
                    self._show_status(
                        f"Pattern {self._cur_pattern_idx + 1:02d}: doublé — {live._num_bars} mesures"
                    )
                else:
                    self._show_status("Impossible de doubler (limite atteinte)")
            elif action == "Diviser par 2":
                self._add_undo(f"Diviser pattern {self._cur_pattern_idx + 1:02d}")
                if self._player.halve_pattern():
                    pat.load_pattern(live._curpattern)
                    self._refresh_grid()
                    self._show_status(
                        f"Pattern {self._cur_pattern_idx + 1:02d}: divisé — {live._num_bars} mesures"
                    )
                else:
                    self._show_status("Impossible de diviser (1 mesure minimum)")
            else:
                self._add_undo(f"Redimensionner pattern {self._cur_pattern_idx + 1:02d}")
                self._resize_live_pattern(num_bars, num_steps)
                self._refresh_grid()
                self._show_status(f"Pattern {self._cur_pattern_idx + 1:02d}: mis à jour")
            self._refresh_pattern_listbox()
        dlg.Destroy()

    def _resize_live_pattern(self, num_bars, num_steps):
        live = self._player._pattern
        live.resize(num_bars, num_steps)
        self._pattern_list[self._cur_pattern_idx].load_pattern(live._curpattern)
        self._player._compute_offsets()
