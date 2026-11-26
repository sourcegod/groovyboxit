import wx


class NavigationHandler:
    """Mixin KeyManager — navigation : Tab, flèches, Entrée, Home/End."""

    def _bbt(self, step):
        pat   = self._win._player._pattern
        total = pat._num_bars * pat._num_steps
        return self._win._track_editor.fmt_bbt(
            step, pat._num_steps, max(1, pat._num_steps // pat._num_beats), total)

    def lims_to_loop(self):
        """Limiteurs → boucle (Alt+Fin ; Transport > Limiteurs, Phase 9 étape
        3b5, § 3b4 B3) : limiteur absent = début / fin du pattern ; écrit
        comme Ctrl+L / Shift+L, un point d'Undo, rien si rien ne change."""
        win   = self._win
        p     = win._player
        pat   = p._pattern
        te    = win._track_editor
        total = pat._num_bars * pat._num_steps
        left  = te._lim_left if te._lim_left is not None else 0
        right = te._lim_right if te._lim_right is not None else total - 1
        if left > right:
            win._show_status("Boucle : limiteur gauche après le limiteur droit")
            return
        start = None if left == 0 else left
        end   = None if right == total - 1 else right + 1   # fin de boucle exclue (4b1)
        if (start, end) != (pat._loop_start, pat._loop_end):
            win._add_undo(f"Boucle : limiteurs {self._bbt(left)} à {self._bbt(right + 1)}")
            pat._loop_start, pat._loop_end = start, end
            saved = win._pattern_list[win._cur_pattern_idx]
            saved._loop_start, saved._loop_end = start, end
            if p.playing or p.clicking or p._note_repeat_active:
                p._wakeup.set()
        win._show_status(f"Boucle : {self._bbt(left)} à {self._bbt(right + 1)}")   # fin exclue

    def loop_to_lims(self):
        """Boucle → limiteurs (Alt+Début ; Transport > Limiteurs, Phase 9
        étape 3b5, § 3b4 B4) : pas de début de boucle = 0, pas de fin = le
        dernier pas ; une entrée d'Undo (3g4, U3)."""
        win   = self._win
        pat   = win._player._pattern
        total = pat._num_bars * pat._num_steps
        left  = pat._loop_start if pat._loop_start is not None else 0
        right = pat._loop_end - 1 if pat._loop_end is not None else total - 1   # 4b1
        win._set_limiters_undo(left, right)                     # Undo (3g4, U3)
        win._show_status(f"Limiteurs : {self._bbt(left)} à {self._bbt(right + 1)}")   # 4d1

    def reset_pattern_undo(self):
        """Vide le pattern, avec Undo (Shift+Suppr ; Pattern > Redimensionner >
        Vider le pattern ; Undo : Phase 9 étape 3b1, § 3a E7)."""
        win = self._win
        win._add_undo("Vider le pattern")
        win._player._pattern.reset_pattern()
        win._refresh_grid()
        win._show_status("Pattern réinitialisé")

    def delete_tracks(self):
        """Efface les pistes sélectionnées (ou la courante) sans presse-papier,
        avec Undo (Suppr sur la liste des pistes ; Edition > Supprimer ;
        Undo : Phase 9 étape 3b1, § 3a E7)."""
        win = self._win
        te  = win._track_editor
        cur = win._player._cur_track
        tracks = te.get_effective_tracks(cur)
        names  = f"{'s' if len(tracks) > 1 else ''} {', '.join(str(i + 1) for i in tracks)}"
        win._add_undo(f"Effacer piste{names}")
        te.erase(win._player._pattern, cur)
        win._refresh_grid()
        win._show_status(f"Effacé: Piste{names}")

    def _handle_navigation(self, event, ctx):
        win   = self._win
        key   = ctx.key
        shift = ctx.shift
        on_quant_list   = ctx.on_quant_list
        on_pattern_list = ctx.on_pattern_list
        on_bpm          = ctx.on_bpm
        on_volume       = ctx.on_volume
        on_pan          = ctx.on_pan
        on_voice_spin   = ctx.on_voice_spin
        on_mode_choice  = ctx.on_mode_choice
        on_scale_choice = ctx.on_scale_choice
        on_slot_choice  = ctx.on_slot_choice
        on_track_list        = ctx.on_track_list
        on_pad_list          = ctx.on_pad_list
        on_vel_list          = ctx.on_vel_list

        if key == wx.WXK_TAB:
            win._on_tab_order(shift)
            return True

        if key in (wx.WXK_PAGEUP, wx.WXK_PAGEDOWN):
            direction = -1 if key == wx.WXK_PAGEUP else 1
            if ctx.ctrl:
                win._player.move_by_beats(direction)
            elif shift:
                win._player.move_by_ticks(direction)
            else:
                win._player.navigate_bar(direction)
            win._show_status(f"Mesure: {win._player.position_str()}")
            return True

        if key in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_LEFT, wx.WXK_RIGHT):
            if ctx.on_status_ctrl:
                return True
            if on_track_list and shift and key in (wx.WXK_UP, wx.WXK_DOWN):
                cur = win._player._cur_track
                n   = win._track_list.GetCount()
                te  = win._track_editor
                if key == wx.WXK_UP:
                    new_track = te.extend_up(cur)
                else:
                    new_track = te.extend_down(cur, n)
                if new_track == cur:
                    wx.Bell()
                else:
                    win._player._cur_track = new_track
                    win._track_list.SetSelection(new_track)
                    win._refresh_track_list()
                    sel = sorted(te._sel_tracks)
                    win._show_status(
                        f"Sélection: Piste{'s' if len(sel) > 1 else ''} "
                        f"{', '.join(str(i + 1) for i in sel)}"
                    )
                return True
            if on_track_list and key in (wx.WXK_UP, wx.WXK_DOWN):
                cur = win._track_list.GetSelection()
                n   = win._track_list.GetCount()
                at_limit = (key == wx.WXK_UP  and cur <= 0) or \
                           (key == wx.WXK_DOWN and cur >= n - 1)
                if at_limit:
                    wx.Bell()
                else:
                    new_idx = cur - 1 if key == wx.WXK_UP else cur + 1
                    win._go_to_track(new_idx)          # mise à jour état + grille
                    win._skip_next_track_select = True  # bloque EVT_LISTBOX GTK
                    event.Skip()                        # lecteur d'écran
            elif on_pad_list and key in (wx.WXK_UP, wx.WXK_DOWN):
                cur = win._pad_list.GetSelection()
                n   = win._pad_list.GetCount()
                at_limit = (key == wx.WXK_UP  and cur <= 0) or \
                           (key == wx.WXK_DOWN and cur >= n - 1)
                if at_limit:
                    wx.Bell()
                else:
                    event.Skip()
                    wx.CallAfter(win._on_pad_list_key_nav, None)
            elif on_quant_list or on_pattern_list or on_mode_choice \
                    or on_scale_choice or on_slot_choice or on_track_list \
                    or on_pad_list or on_vel_list:
                event.Skip()
            elif on_volume and key in (wx.WXK_UP, wx.WXK_DOWN):
                event.Skip()
            elif on_pan and key in (wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_UP, wx.WXK_DOWN):
                step = 1 if key in (wx.WXK_UP, wx.WXK_RIGHT) else -1
                pan  = win._set_master_pan_undo(win._player.pan + step)
                win._show_status(f"Pan Global: {pan}")
            elif on_bpm and key in (wx.WXK_UP, wx.WXK_DOWN):
                event.Skip()
            elif on_voice_spin and key in (wx.WXK_UP, wx.WXK_DOWN):
                event.Skip()
            elif key == wx.WXK_UP:
                win._move(-1, 0)
            elif key == wx.WXK_DOWN:
                win._move(1, 0)
            elif key == wx.WXK_LEFT:
                win._move(0, -1)
            else:
                win._move(0, 1)
            return True

        if key == wx.WXK_NUMPAD_ENTER:
            win._play(win._cur_row)
            return True

        if key == wx.WXK_RETURN:
            if on_quant_list:
                win._apply_quant()
            elif on_pattern_list:
                pass
            elif on_pad_list:
                win._cells[win._cur_row][win._cur_col].SetFocus()
            elif on_track_list or on_vel_list or on_scale_choice \
                    or on_mode_choice or on_slot_choice:
                pass  # GTK transforme Enter en DCLICK sur les ListBox
            else:
                r, c = win._cur_row, win._cur_col
                new_val = False if shift else not win._cells[r][c].GetValue()
                win._set_cell(r, c, new_val)
                win._play(r)
            return True

        if shift and key == wx.WXK_DELETE:
            self.reset_pattern_undo()
            return True

        if key == wx.WXK_DELETE and on_track_list:
            self.delete_tracks()
            return True

        # Alt+Début / Alt+Fin : boucle → limiteurs / limiteurs → boucle
        # (Phase 9 étape 3b5, § 3b4 B2 ; avant, Alt+Début faisait Début)
        if ctx.alt and not ctx.ctrl and not shift and key in (wx.WXK_HOME, wx.WXK_END):
            if key == wx.WXK_HOME:
                self.loop_to_lims()
            else:
                self.lims_to_loop()
            return True

        if not ctx.ctrl and not shift and key == wx.WXK_HOME:
            te  = win._track_editor
            lim = te._lim_left
            if lim is not None:
                win._player._go_to_offset(float(lim))
            else:
                win._player.goto_start()
            win._show_status(f"Mesure: {win._player.position_str()}")
            return True

        if not ctx.ctrl and not shift and key == wx.WXK_END:
            te  = win._track_editor
            lim = te._lim_right
            pat = win._player._pattern
            # limiteur droit exclu (Phase 9 étape 4d1, § 4a L3) : sa position ;
            # à la fin du pattern (ou sans limiteur) : le dernier pas
            if lim is not None and lim + 1 < pat._num_bars * pat._num_steps:
                win._player._go_to_offset(float(lim + 1))
            else:
                win._player.goto_end()
            win._show_status(f"Mesure: {win._player.position_str()}")
            return True

        if not ctx.ctrl and shift and key == wx.WXK_HOME:   # Shift+Début : début de boucle
            p   = win._player
            pat = p._pattern
            step = pat._loop_start if pat._loop_start is not None else 0
            p._go_to_offset(float(step))
            win._show_status(f"Début boucle: {p.position_str()}")
            return True

        if not ctx.ctrl and shift and key == wx.WXK_END:    # Shift+Fin : fin de boucle
            p   = win._player
            pat = p._pattern
            total = pat._num_bars * pat._num_steps
            step = pat._loop_end if pat._loop_end is not None else total - 1
            p._go_to_offset(float(step))
            win._show_status(f"Fin boucle: {p.position_str()}")
            return True

        # Shift+Espace : toggle la piste courante dans/hors sélection (non-adjacent)
        if shift and not ctx.ctrl and key == wx.WXK_SPACE and on_track_list:
            cur = win._player._cur_track
            te  = win._track_editor
            if te.is_selected(cur):
                te.toggle_track(cur)
            else:
                te.toggle_track(cur)
                wx.Bell()
            win._refresh_track_list()
            sel = sorted(te._sel_tracks)
            if sel:
                win._show_status(
                    f"Sélection: Piste{'s' if len(sel) > 1 else ''} "
                    f"{', '.join(str(i + 1) for i in sel)}"
                )
            else:
                win._show_status(f"Piste {cur + 1}: désélectionnée")
            return True

        return False
