import wx


class NavigationHandler:
    """Mixin KeyManager — navigation : Tab, flèches, Entrée, Home/End."""

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
        on_midi_port_list    = ctx.on_midi_port_list

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
                    or on_pad_list or on_vel_list or on_midi_port_list:
                event.Skip()
            elif on_volume and key in (wx.WXK_UP, wx.WXK_DOWN):
                event.Skip()
            elif on_pan and key in (wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_UP, wx.WXK_DOWN):
                if key in (wx.WXK_UP, wx.WXK_RIGHT):
                    pan = min(100, win._player.pan + 1)
                else:
                    pan = max(-100, win._player.pan - 1)
                win._player.set_pan(pan)
                win._pan_ctrl.SetValue(pan)
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
                    or on_mode_choice or on_slot_choice or on_midi_port_list:
                pass  # GTK transforme Enter en DCLICK sur les ListBox
            else:
                r, c = win._cur_row, win._cur_col
                new_val = False if shift else not win._cells[r][c].GetValue()
                win._set_cell(r, c, new_val)
                win._play(r)
            return True

        if shift and key == wx.WXK_DELETE:
            win._player._pattern.reset_pattern()
            win._refresh_grid()
            win._show_status("Pattern réinitialisé")
            return True

        if key == wx.WXK_DELETE and on_track_list:
            te  = win._track_editor
            cur = win._player._cur_track
            tracks = te.get_effective_tracks(cur)
            te.erase(win._player._pattern, cur)
            win._refresh_grid()
            win._show_status(
                f"Effacé: Piste{'s' if len(tracks) > 1 else ''} "
                f"{', '.join(str(i + 1) for i in tracks)}"
            )
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
            if lim is not None:
                win._player._go_to_offset(float(lim))
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
