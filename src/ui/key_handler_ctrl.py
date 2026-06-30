import wx


class CtrlHandler:
    """Mixin KeyManager — groupe Ctrl+…"""

    def _handle_ctrl(self, event, ctx):
        win   = self._win
        key   = ctx.key
        shift = ctx.shift
        alt   = ctx.alt

        if not alt and key == ord('Z'):
            if shift:
                win._undo_history_dialog()
            else:
                win._undo_action()
            return True

        if not shift and not alt and key == ord('N'):
            win._new_project()
            return True
        if not shift and not alt and key == ord('O'):
            win._open_project()
            return True
        if shift and not alt and key == ord('S'):
            win._save_project_as()
            return True
        if not shift and not alt and key == ord('S'):
            win._save_project()
            return True
        if shift and not alt and key == ord('A'):
            win._track_editor.clear_selection()
            win._track_editor.reset_lims()
            win._refresh_track_list()
            win._show_status("Sélection effacée | Limiteurs réinitialisés")
            return True
        if not shift and not alt and key == ord('A'):
            pat = win._player._pattern
            n   = pat._num_tracks
            win._track_editor.select_all(n)
            win._track_editor.set_full_range(pat._num_bars * pat._num_steps)
            win._refresh_track_list()
            win._show_status(f"Toutes les pistes sélectionnées ({n}) | Plage complète")
            return True
        if not shift and not alt and key == ord('C'):
            te = win._track_editor
            cur = win._player._cur_track
            te.copy(win._player._pattern, cur)
            tracks = te.get_effective_tracks(cur)
            win._show_status(
                f"Copié: Piste{'s' if len(tracks) > 1 else ''} "
                f"{', '.join(str(i + 1) for i in tracks)}"
            )
            return True
        if not shift and not alt and key == ord('X'):
            te = win._track_editor
            cur = win._player._cur_track
            tracks = te.get_effective_tracks(cur)
            win._add_undo(
                f"Effacer grille piste{'s' if len(tracks) > 1 else ''} "
                f"{', '.join(str(i + 1) for i in tracks)}"
            )
            te.erase_grid(win._player._pattern, cur)
            win._refresh_grid()
            win._show_status(
                f"Effacé (grille): Piste{'s' if len(tracks) > 1 else ''} "
                f"{', '.join(str(i + 1) for i in tracks)}"
            )
            return True
        if not shift and not alt and key == ord('V'):
            te         = win._track_editor
            cur        = win._player._cur_track
            pat        = win._player._pattern
            cur_offset = int(win._player._current_offset())
            dest_bar   = cur_offset // pat._num_steps
            if te.has_event_clipboard():
                win._add_undo(f"Coller notes Tr{cur + 1} @{cur_offset}")
                n = te.paste_events(pat, cur, cur_offset)
                if n:
                    win._player._compute_offsets()
                    win._refresh_grid()
                    win._show_status(
                        f"{n} note(s) collée(s) — Piste {cur + 1}, Mesure {dest_bar + 1}"
                    )
                else:
                    win._pop_last_undo()
                    win._show_status("Coller: hors limites du pattern")
            elif te.has_clipboard():
                win._add_undo(f"Coller piste {cur + 1}, mesure {dest_bar + 1}")
                if te.paste(pat, cur, dest_bar=dest_bar):
                    win._refresh_grid()
                    win._show_status(
                        f"Collé à partir de la Piste {cur + 1}, Mesure {dest_bar + 1}"
                    )
                else:
                    win._pop_last_undo()
                    win._show_status("Presse-papier vide")
            else:
                win._show_status("Presse-papier vide")
            return True
        if shift and key == ord('W'):
            win._save_pattern_as()
            return True
        if shift and not alt and key == ord('T'):
            win._track_properties_dialog()
            return True
        if not shift and not alt and key == ord('T'):
            win._assign_track_slot()
            return True
        if key == ord('W'):
            win._save_pattern()
            return True
        if not shift and not alt and key == ord('D'):
            te = win._track_editor
            cur = win._player._cur_track
            tracks = te.get_effective_tracks(cur)
            win._add_undo(
                f"Supprimer piste{'s' if len(tracks) > 1 else ''} "
                f"{', '.join(str(i + 1) for i in tracks)}"
            )
            te.cut(win._player._pattern, cur)
            win._refresh_grid()
            win._show_status(
                f"Supprimé: Piste{'s' if len(tracks) > 1 else ''} "
                f"{', '.join(str(i + 1) for i in tracks)}"
            )
            return True
        if key == ord('P'):
            win._add_undo("Charger pattern initial")
            win._player._pattern.build_pattern_01()
            win._refresh_grid()
            win._show_status("Pattern initial chargé")
            return True
        if not shift and key == ord('F'):
            win._add_undo("Doubler pattern")
            if win._player.double_pattern():
                win._refresh_grid()
                win._show_status(f"Pattern doublé: {win._player._pattern._num_bars} mesures")
            else:
                win._show_status("Impossible de doubler (limite atteinte)")
            return True
        if shift and key == ord('E'):
            win._gen_row_dialog()
            return True
        if not shift and key == ord('E'):
            win._apply_quant()
            return True
        if not shift and not alt and key == ord('1'):
            win._set_input_mode("pad")
            return True
        if not shift and not alt and key == ord('2'):
            win._set_input_mode("keyboard")
            return True
        if shift and key == ord('Q'):
            win._quantize_pattern_dialog()
            return True
        if not shift and not alt and key == ord('R'):
            win._player.record_pattern_with_count_in()
            n = win._player.count_in_bars
            win._refresh_track_list()
            win._show_status(
                f"Count-In: {n} mesure{'s' if n > 1 else ''}..." if n else "Rec: On"
            )
            return True
        if not shift and not alt and key == wx.WXK_UP:
            vol = min(100, win._player.volume + 1)
            win._player.set_volume(vol)
            win._volume_ctrl.SetValue(vol)
            win._show_status(f"Volume Global: {vol}")
            return True
        if not shift and not alt and key == wx.WXK_DOWN:
            vol = max(0, win._player.volume - 1)
            win._player.set_volume(vol)
            win._volume_ctrl.SetValue(vol)
            win._show_status(f"Volume Global: {vol}")
            return True
        if not shift and not alt and key == wx.WXK_RIGHT:
            pan = min(100, win._player.pan + 1)
            win._player.set_pan(pan)
            win._pan_ctrl.SetValue(pan)
            win._show_status(f"Pan Global: {pan}")
            return True
        if not shift and not alt and key == wx.WXK_LEFT:
            pan = max(-100, win._player.pan - 1)
            win._player.set_pan(pan)
            win._pan_ctrl.SetValue(pan)
            win._show_status(f"Pan Global: {pan}")
            return True
        if not shift and not alt and key == ord('0'):
            win._player.set_pan(0)
            win._pan_ctrl.SetValue(0)
            win._show_status("Pan Global: 0 (centré)")
            return True
        if not shift and not alt and key == wx.WXK_F12:   # Ctrl+F12 : Panic
            win._player.stop_all()
            win._router.panic()
            win._show_status("Panic: All Sounds Off + Reset All Controllers")
            return True
        if not shift and not alt and key == wx.WXK_DELETE:
            te = win._track_editor
            cur = win._player._cur_track
            tracks = te.get_effective_tracks(cur)
            win._add_undo(
                f"Effacer piste{'s' if len(tracks) > 1 else ''} "
                f"{', '.join(str(i + 1) for i in tracks)}"
            )
            te.erase(win._player._pattern, cur)
            win._refresh_grid()
            win._show_status(
                f"Supprimé sans copie: Piste{'s' if len(tracks) > 1 else ''} "
                f"{', '.join(str(i + 1) for i in tracks)}"
            )
            return True
        if not shift and not alt and key == wx.WXK_HOME:   # Ctrl+Début : début absolu
            win._player.goto_start()
            win._show_status(f"Début: {win._player.position_str()}")
            return True
        if not shift and not alt and key == wx.WXK_END:    # Ctrl+Fin : fin absolue
            win._player.goto_end()
            win._show_status(f"Fin: {win._player.position_str()}")
            return True
        if shift and not alt and key == ord('G'):          # Ctrl+Shift+G : Grille
            win._grid_dialog()
            return True
        if shift and not alt and key == ord('L'):         # Ctrl+Shift+L : dialog loop points
            win._loop_select_dialog()
            return True
        if not shift and not alt and key == ord('L'):     # Ctrl+L : loop start à la position courante
            p   = win._player
            pat = p._pattern
            step = int(p._current_offset())
            pat._loop_start = None if step == 0 else step
            win._pattern_list[win._cur_pattern_idx]._loop_start = pat._loop_start
            if p.playing or p.clicking or p._note_repeat_active:
                p._wakeup.set()
            win._show_status(f"Boucle début: {win._player.position_str()}")
            return True
        if not shift and not alt and key == ord('G'):     # Ctrl+G : Aller à une position
            win._goto_dialog()
            return True
        if not shift and not alt and key == wx.WXK_SPACE:  # Ctrl+Space : jouer depuis le début
            win._player.goto_start()
            win._player.play_pattern()
            win._show_status(f"Play depuis début: {win._player.position_str()}")
            return True
        return False
