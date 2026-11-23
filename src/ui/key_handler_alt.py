import wx


class AltHandler:
    """Mixin KeyManager — groupe Alt+…"""

    def track_volume_step(self, delta):
        """Volume de la piste courante ± delta, avec Undo (Alt+Haut / Alt+Bas
        sur la liste des pistes ; Mixer > Volume, Phase 9 étape 3b1)."""
        win  = self._win
        tidx = win._player._cur_track
        vol  = win._set_track_volume_undo(tidx, win._router.get_track_volume(tidx) + delta)
        win._show_status(f"Piste {tidx + 1}: Volume {vol}")

    def track_pan_step(self, delta):
        """Pan de la piste courante ± delta, avec Undo (Alt+Gauche / Alt+Droite
        sur la liste des pistes ; Mixer > Pan, Phase 9 étape 3b1)."""
        win  = self._win
        tidx = win._player._cur_track
        pan  = win._set_track_pan_undo(tidx, win._router.get_track_pan(tidx) + delta)
        win._show_status(f"Piste {tidx + 1}: Pan {pan}")

    def _handle_alt(self, event, ctx):
        win   = self._win
        key   = ctx.key
        ukey  = ctx.ukey
        ctrl  = ctx.ctrl
        shift = ctx.shift
        on_track_list = ctx.on_track_list
        on_pad_list   = ctx.on_pad_list

        if not ctrl and not shift and key == wx.WXK_UP:
            if on_track_list:
                self.track_volume_step(5)
            else:
                vm = win._player.voice_manager
                win._set_pad_volume_undo(win._cur_row, vm.get_voice(win._cur_row).volume + 5)
                win._refresh_voice_display(win._cur_row)
                win._show_status(f"Pad {win._cur_row + 1}: Volume {vm.get_voice(win._cur_row).volume}")
                if on_pad_list:
                    win._play(win._cur_row)
            return True
        if not ctrl and not shift and key == wx.WXK_DOWN:
            if on_track_list:
                self.track_volume_step(-5)
            else:
                vm = win._player.voice_manager
                win._set_pad_volume_undo(win._cur_row, vm.get_voice(win._cur_row).volume - 5)
                win._refresh_voice_display(win._cur_row)
                win._show_status(f"Pad {win._cur_row + 1}: Volume {vm.get_voice(win._cur_row).volume}")
                if on_pad_list:
                    win._play(win._cur_row)
            return True
        if not ctrl and not shift and key == wx.WXK_LEFT:
            if on_track_list:
                self.track_pan_step(-10)
            else:
                vm = win._player.voice_manager
                win._set_pad_pan_undo(win._cur_row, vm.get_pan(win._cur_row) - 10)
                win._refresh_voice_display(win._cur_row)
                win._show_status(f"Pad {win._cur_row + 1}: Pan {vm.get_pan(win._cur_row)}")
                if on_pad_list:
                    win._play(win._cur_row)
            return True
        if not ctrl and not shift and key == wx.WXK_RIGHT:
            if on_track_list:
                self.track_pan_step(10)
            else:
                vm = win._player.voice_manager
                win._set_pad_pan_undo(win._cur_row, vm.get_pan(win._cur_row) + 10)
                win._refresh_voice_display(win._cur_row)
                win._show_status(f"Pad {win._cur_row + 1}: Pan {vm.get_pan(win._cur_row)}")
                if on_pad_list:
                    win._play(win._cur_row)
            return True
        if not ctrl and not shift and (ukey in (ord('x'), ord('X')) or key == ord('X')):
            win._open_explorer()
            return True
        if not ctrl and shift and (ukey in (ord('p'), ord('P')) or key == ord('P')):
            win._open_preferences()     # Alt+Shift+P : Préférences (Phase 8 étape 10d1)
            return True
        if not ctrl and shift and (ukey in (ord('e'), ord('E')) or key == ord('E')):
            win._export_midi_choose()   # Alt+Shift+E : pattern ou song en MIDI (Phase 8 étape 4b1)
            return True
        if not ctrl and shift and (ukey in (ord('w'), ord('W')) or key == ord('W')):
            win._export_audio_choose()  # Alt+Shift+W : export audio, toutes les sources (15b1)
            return True
        if not ctrl and shift and (ukey in (ord('i'), ord('I')) or key == ord('I')):
            win._import_midi()          # Alt+Shift+I : import MIDI (Phase 7 étape 18d1)
            return True
        if not ctrl and shift and (ukey in (ord('q'), ord('Q')) or key == ord('Q')):
            win._record_quantize_dialog()   # Alt+Shift+Q : à l'enregistrement (13d2)
            return True
        if not ctrl and shift and (ukey in (ord('t'), ord('T')) or key == ord('T')):
            win._tempo_dialog()         # Alt+Shift+T : tempos (Phase 7 étape 19f1)
            return True
        if not ctrl and not shift and (ukey == ord('4') or key == ord('4')):
            win._open_midi_editor_window()
            return True
        if not ctrl and not shift and (ukey == ord('5') or key == ord('5')):
            win._open_song_window()
            return True
        if not ctrl and not shift and key == ord('L'):   # Alt+L : réinitialiser loop points
            p   = win._player
            pat = p._pattern
            if pat._loop_start is not None or pat._loop_end is not None:
                win._add_undo("Réinitialiser la boucle")  # Phase 7 étape 15f1 (D5)
            pat._loop_start = None
            pat._loop_end   = None
            saved = win._pattern_list[win._cur_pattern_idx]
            saved._loop_start = None
            saved._loop_end   = None
            if p.playing or p.clicking or p._note_repeat_active:
                p._wakeup.set()
            win._show_status("Points de boucle réinitialisés")
            return True
        return False
