import wx


class AltHandler:
    """Mixin KeyManager — groupe Alt+…"""

    def _handle_alt(self, event, ctx):
        win   = self._win
        key   = ctx.key
        ukey  = ctx.ukey
        ctrl  = ctx.ctrl
        shift = ctx.shift
        on_track_list = ctx.on_track_list
        on_pad_list   = ctx.on_pad_list

        if not ctrl and not shift and key == wx.WXK_UP:
            tidx = win._player._cur_track
            if on_track_list:
                win._router.set_track_volume(tidx, win._router.get_track_volume(tidx) + 5)
                win._show_status(f"Piste {tidx + 1}: Volume {win._router.get_track_volume(tidx)}")
            else:
                vm = win._player.voice_manager
                vm.set_volume(win._cur_row, vm.get_voice(win._cur_row).volume + 5)
                win._refresh_voice_display(win._cur_row)
                win._show_status(f"Pad {win._cur_row + 1}: Volume {vm.get_voice(win._cur_row).volume}")
                if on_pad_list:
                    win._play(win._cur_row)
            return True
        if not ctrl and not shift and key == wx.WXK_DOWN:
            tidx = win._player._cur_track
            if on_track_list:
                win._router.set_track_volume(tidx, win._router.get_track_volume(tidx) - 5)
                win._show_status(f"Piste {tidx + 1}: Volume {win._router.get_track_volume(tidx)}")
            else:
                vm = win._player.voice_manager
                vm.set_volume(win._cur_row, vm.get_voice(win._cur_row).volume - 5)
                win._refresh_voice_display(win._cur_row)
                win._show_status(f"Pad {win._cur_row + 1}: Volume {vm.get_voice(win._cur_row).volume}")
                if on_pad_list:
                    win._play(win._cur_row)
            return True
        if not ctrl and not shift and key == wx.WXK_LEFT:
            tidx = win._player._cur_track
            if on_track_list:
                win._router.set_track_pan(tidx, win._router.get_track_pan(tidx) - 10)
                win._show_status(f"Piste {tidx + 1}: Pan {win._router.get_track_pan(tidx)}")
            else:
                vm = win._player.voice_manager
                vm.set_pan(win._cur_row, vm.get_pan(win._cur_row) - 10)
                win._refresh_voice_display(win._cur_row)
                win._show_status(f"Pad {win._cur_row + 1}: Pan {vm.get_pan(win._cur_row)}")
                if on_pad_list:
                    win._play(win._cur_row)
            return True
        if not ctrl and not shift and key == wx.WXK_RIGHT:
            tidx = win._player._cur_track
            if on_track_list:
                win._router.set_track_pan(tidx, win._router.get_track_pan(tidx) + 10)
                win._show_status(f"Piste {tidx + 1}: Pan {win._router.get_track_pan(tidx)}")
            else:
                vm = win._player.voice_manager
                vm.set_pan(win._cur_row, vm.get_pan(win._cur_row) + 10)
                win._refresh_voice_display(win._cur_row)
                win._show_status(f"Pad {win._cur_row + 1}: Pan {vm.get_pan(win._cur_row)}")
                if on_pad_list:
                    win._play(win._cur_row)
            return True
        if not ctrl and not shift and (ukey == ord('0') or key == ord('0')):
            tidx = win._player._cur_track
            if on_track_list:
                win._router.set_track_pan(tidx, 0)
                win._show_status(f"Piste {tidx + 1}: Pan 0 (centre)")
            else:
                win._player.voice_manager.set_pan(win._cur_row, 0)
                win._refresh_voice_display(win._cur_row)
                win._show_status(f"Pad {win._cur_row + 1}: Pan 0 (centre)")
                if on_pad_list:
                    win._play(win._cur_row)
            return True
        if not ctrl and not shift and (ukey in (ord('x'), ord('X')) or key == ord('X')):
            win._open_explorer()
            return True
        if not ctrl and not shift and (ukey == ord('5') or key == ord('5')):
            win._open_song_window()
            return True
        if not ctrl and shift and (ukey in (ord('m'), ord('M')) or key == ord('M')):
            win._midi_handler.refresh_ports()
            win._show_status("MIDI: liste des ports actualisée")
            return True
        if not ctrl and not shift and (ukey in (ord('m'), ord('M')) or key == ord('M')):
            win._midi_handler.toggle()
            return True
        if not ctrl and not shift and key == ord('L'):   # Alt+L : réinitialiser loop points
            p   = win._player
            pat = p._pattern
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
