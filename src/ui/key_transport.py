import wx


class TransportHandler:
    """Mixin KeyManager — transport partagé (appelé depuis SongWindow et futures fenêtres)."""

    def handle_transport(self, event):
        """Sous-ensemble transport : Play/Pause, Stop, navigation, boucle, position.
        Retourne True si l'événement a été consommé."""
        win   = self._win
        key   = event.GetKeyCode()
        ukey  = event.GetUnicodeKey()
        ctrl  = event.ControlDown()
        shift = event.ShiftDown()

        # Ctrl+G / Ctrl+Shift+G : Aller à / Grille — désormais interceptés en
        # amont par chaque fenêtre appelante (MainWindow via CtrlHandler,
        # MidiEditorWindow/SongWindow via leur propre _goto_dialog/_grid_dialog),
        # pour que le dialog reste modal à la bonne fenêtre (focus au retour).

        # Ctrl+F12 : Panic
        if ctrl and not shift and key == wx.WXK_F12:
            win._player.stop_all()
            win._router.panic()
            win._show_status("Panic: All Sounds Off + Reset All Controllers")
            return True

        # PageUp / PageDown : navigation bar / beat / tick
        if key in (wx.WXK_PAGEUP, wx.WXK_PAGEDOWN):
            direction = -1 if key == wx.WXK_PAGEUP else 1
            if ctrl:
                win._player.move_by_beats(direction)
            elif shift:
                win._player.move_by_ticks(direction)
            else:
                win._player.navigate_bar(direction)
            win._show_status(f"Mesure: {win._player.position_str()}")
            return True

        # Ctrl+Space : jouer depuis le début
        if ctrl and not shift and key in (wx.WXK_SPACE,):
            win._player.goto_start()
            win._player.play_pattern()
            win._show_status(f"Play depuis début: {win._player.position_str()}")
            return True

        if ctrl:
            return False

        # Space / P : play / pause
        if ukey in (ord(' '), ord('p')) or key in (wx.WXK_SPACE, ord('P')):
            if win._player.playing:
                win._player.pause_pattern()
                win._router.stop_all_synth_voices()
                win._show_status(f"Pause: {win._player.position_str()}")
            else:
                win._player.play_pattern()
                win._show_status(f"Play: {win._player.position_str()}")
            return True

        # V : stop all
        if ukey == ord('v') or key == ord('V'):
            win._player.stop_all()
            win._router.stop_all_synth_voices()
            win._show_status("Stop All")
            return True

        # g : GotoStart  /  Shift+G : GotoEnd
        if not shift and (ukey == ord('g') or key == ord('G')):
            win._player.goto_start()
            win._show_status(f"Début: {win._player.position_str()}")
            return True
        if shift and (ukey == ord('g') or key == ord('G')):
            win._player.goto_end()
            win._show_status(f"Fin: {win._player.position_str()}")
            return True

        # b : −1 s  /  w : +1 s
        if ukey == ord('b') or key == ord('B'):
            win._player.move_by_seconds(-1)
            win._show_status(f"Temps: {win._player.time_str()}")
            return True
        if ukey == ord('w') or key == ord('W'):
            win._player.move_by_seconds(+1)
            win._show_status(f"Temps: {win._player.time_str()}")
            return True

        # l : toggle boucle  /  Shift+L : boucle fin
        if ukey == ord('l') or key == ord('L'):
            p   = win._player
            pat = p._pattern
            if shift:
                step  = int(p._current_offset())
                total = pat._num_bars * pat._num_steps
                pat._loop_end = None if step == total - 1 else step
                win._show_status(f"Boucle fin: {p.position_str()}")
            else:
                pat._looping = not pat._looping
                win._show_status(f"Boucle: {'On' if pat._looping else 'Off'}")
            return True

        return False
