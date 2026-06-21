import wx
from pattern import Pattern


class CharHandler:
    """Mixin KeyManager — touches caractères (sans modificateurs principaux, ou Shift seul)."""

    def _handle_chars(self, event, ctx):
        win   = self._win
        key   = ctx.key
        ukey  = ctx.ukey
        ctrl  = ctx.ctrl
        shift = ctx.shift
        alt   = ctx.alt
        on_bpm          = ctx.on_bpm
        on_volume       = ctx.on_volume
        on_pan          = ctx.on_pan
        on_voice_spin   = ctx.on_voice_spin
        on_quant_list   = ctx.on_quant_list
        on_pattern_list = ctx.on_pattern_list
        on_track_list   = ctx.on_track_list

        # Shift+V : coller en mélangeant (merge) à partir de la position courante
        if not ctrl and shift and not alt and key == ord('V'):
            te  = win._track_editor
            cur = win._player._cur_track
            pat = win._player._pattern
            dest_bar = int(win._player._current_offset()) // pat._num_steps
            if te.paste(pat, cur, dest_bar=dest_bar, merge=True):
                win._refresh_grid()
                win._show_status(
                    f"Mélangé à partir de la Piste {cur + 1}, Mesure {dest_bar + 1}"
                )
            else:
                win._show_status("Presse-papier vide")
            return True

        # Shift+D : effacer la piste courante
        if not ctrl and shift and not alt and key == ord('D'):
            tidx = win._player._cur_track
            win._player._pattern.clear_track(tidx)
            win._refresh_grid()
            win._show_status(f"Piste {tidx + 1}: effacée")
            return True

        # Shift+F : diviser le pattern
        if not ctrl and shift and not alt and key == ord('F'):
            if win._player.halve_pattern():
                win._refresh_grid()
                win._show_status(f"Pattern divisé: {win._player._pattern._num_bars} mesures")
            else:
                win._show_status("Impossible de diviser (1 mesure minimum)")
            return True

        # Shift+Q : quantiser le pattern
        if shift and not ctrl and key == ord('Q'):
            win._quantize_pattern()
            return True

        # Q : toggle Note Repeat
        if not ctrl and not shift and not alt and (ukey == ord('q') or key == ord('Q')):
            win._note_repeat = not win._note_repeat
            if win._note_repeat:
                mode = "Ternaire" if win._nr_ternary else "Binaire"
                win._show_status(
                    f"Note Repeat: ON — {mode} — {Pattern.QUANT_LIST[win._nr_rate_idx]}"
                )
            else:
                win._nr_cancel_release()
                win._nr_active_key = None
                win._nr_prev_key   = None
                win._nr_midi_note  = None
                win._player.stop_note_repeat()
                win._show_status("Note Repeat: OFF")
            return True

        # Shift+E : décocher toute la ligne
        if shift and not ctrl and key == ord('E'):
            for c in range(win.COLS):
                win._set_cell(win._cur_row, c, False)
            win._show_status(f"Ligne {win._cur_row + 1}: tout décoché")
            return True

        # E : bascule mode Erase
        if not ctrl and not shift and not alt and (ukey == ord('e') or key == ord('E')):
            now_erasing = win._midi_handler.toggle_erase()
            if now_erasing:
                win._show_status("Erase: On")
            elif win._player.replace_recording:
                win._show_status("Erase: Off — Replace Rec: On")
            elif win._player.recording:
                win._show_status("Erase: Off — Rec: On")
            else:
                win._show_status("Erase: Off")
            return True

        # X : mute pad ou piste
        if not ctrl and not shift and not alt and (ukey == ord('x') or key == ord('X')):
            if on_track_list:
                tidx  = win._player._cur_track
                muted = win._router.toggle_track_mute(tidx)
                win._refresh_track_list()
                win._show_status(f"Piste {tidx + 1}: Mute {'On' if muted else 'Off'}")
            else:
                muted = win._player.voice_manager.toggle_mute(win._cur_row)
                win._refresh_voice_display(win._cur_row)
                win._show_status(f"Pad {win._cur_row + 1}: Mute {'On' if muted else 'Off'}")
            return True

        # Shift+X : démuter tous
        if not ctrl and shift and not alt and (ukey == ord('x') or key == ord('X')):
            if on_track_list:
                win._router.unmute_all_tracks()
                win._refresh_track_list()
                win._show_status("Toutes les Pistes: Démutées")
            else:
                win._player.voice_manager.set_mute_all(False)
                win._refresh_all_voice_display()
                win._show_status("Tous les Pads: Démutés")
            return True

        # S : solo pad ou piste
        if not ctrl and not shift and not alt and (ukey == ord('s') or key == ord('S')):
            if on_track_list:
                tidx   = win._player._cur_track
                soloed = win._router.toggle_track_solo(tidx)
                win._refresh_track_list()
                win._show_status(f"Piste {tidx + 1}: Solo {'On' if soloed else 'Off'}")
            else:
                soloed = win._player.voice_manager.toggle_solo(win._cur_row)
                win._refresh_voice_display(win._cur_row)
                win._show_status(f"Pad {win._cur_row + 1}: Solo {'On' if soloed else 'Off'}")
            return True

        # Shift+S : désolo tous
        if not ctrl and shift and not alt and (ukey == ord('s') or key == ord('S')):
            if on_track_list:
                win._router.unsolo_all_tracks()
                win._refresh_track_list()
                win._show_status("Toutes les Pistes: Désolées")
            else:
                win._player.voice_manager.set_solo_all(False)
                win._refresh_all_voice_display()
                win._show_status("Tous les Pads: Désolés")
            return True

        # C : toggle click
        if ukey == ord('c') or (not ctrl and not shift and key == ord('C')):
            if win._player.clicking:
                win._player.stop_click()
                win._show_status("Click: Off")
            else:
                win._player.play_click()
                win._show_status("Click: On")
            return True

        # Shift+P : générer un pattern aléatoire
        if shift and not ctrl and (ukey == ord('p') or key == ord('P')):
            win._player._pattern.gen_pattern(win._player._cur_track)
            win._player._compute_offsets()
            win._refresh_grid()
            win._show_status("Pattern aléatoire généré")
            return True

        # Space / P : play/pause
        if ukey in (ord(' '), ord('p')) or (not ctrl and key in (wx.WXK_SPACE, ord('P'))):
            if win._player.playing:
                win._player.pause_pattern()
                win._router.stop_all_synth_voices()
                win._show_status(f"Pause: {win._player.position_str()}")
            else:
                win._player.play_pattern()
                win._show_status(f"Play: {win._player.position_str()}")
            return True

        # V : stop all
        if ukey == ord('v') or (not ctrl and not shift and key == ord('V')):
            win._note_repeat   = False
            win._nr_active_key = None
            win._nr_prev_key   = None
            win._nr_midi_note  = None
            win._nr_cancel_release()
            win._player.stop_all()
            win._router.stop_all_synth_voices()
            win._show_status("Stop All")
            return True

        # Shift+R : remplacement
        if not ctrl and shift and not alt and (ukey == ord('r') or key == ord('R')):
            if win._player.replace_recording:
                win._player.stop_record()
                win._refresh_track_list()
                win._show_status("Replace Rec: Off")
            else:
                win._player.start_replace_recording()
                win._refresh_track_list()
                track_idx = win._player._cur_track
                win._show_status(
                    f"Replace Rec: Piste {track_idx + 1} — {win._router.slot_name(track_idx)}"
                )
            return True

        # R : enregistrement
        if ukey == ord('r') or (not ctrl and not shift and not alt and key == ord('R')):
            if win._player.recording or win._player._count_in > 0:
                win._player.stop_record()
                win._refresh_grid()
                win._refresh_track_list()
                win._show_status("Rec: Off")
            else:
                win._player.record_pattern()
                win._refresh_track_list()
                track_idx = win._player._cur_track
                win._show_status(
                    f"Rec: Piste {track_idx + 1} — {win._router.slot_name(track_idx)}"
                )
            return True

        # Touches 1-9 en mode Note Repeat
        if win._note_repeat and not ctrl and not shift and not alt \
                and not on_bpm and not on_volume and not on_pan and not on_voice_spin \
                and not on_quant_list and not on_pattern_list \
                and ord('1') <= key <= ord('9'):
            digit = key - ord('0')
            if digit == 9:
                win._nr_ternary = not win._nr_ternary
                mode = "Ternaire" if win._nr_ternary else "Binaire"
                win._show_status(f"Note Repeat: mode {mode}")
            elif win._nr_ternary and 1 <= digit <= 6:
                win._nr_rate_idx = win.NR_TERNARY[digit - 1]
                win._player.update_nr_rate(win._nr_rate_idx)
                win._show_status(f"NR: {Pattern.QUANT_LIST[win._nr_rate_idx]}")
            elif not win._nr_ternary and 1 <= digit <= 8:
                win._nr_rate_idx = win.NR_BINARY[digit - 1]
                win._player.update_nr_rate(win._nr_rate_idx)
                win._show_status(f"NR: {Pattern.QUANT_LIST[win._nr_rate_idx]}")
            return True

        # b / w : ±1 seconde
        if not ctrl and not shift and not alt \
                and not on_bpm and not on_volume and not on_pan and not on_voice_spin \
                and (ukey == ord('b') or key == ord('B')):
            win._player.move_by_seconds(-1)
            win._show_status(f"Temps: {win._player.time_str()}")
            return True
        if not ctrl and not shift and not alt \
                and not on_bpm and not on_volume and not on_pan and not on_voice_spin \
                and (ukey == ord('w') or key == ord('W')):
            win._player.move_by_seconds(+1)
            win._show_status(f"Temps: {win._player.time_str()}")
            return True

        # Shift+L : poser loop end à la position courante
        if not ctrl and shift and not alt \
                and not on_bpm and not on_volume and not on_pan and not on_voice_spin \
                and (ukey == ord('l') or key == ord('L')):
            p    = win._player
            pat  = p._pattern
            step = int(p._current_offset())
            total = pat._num_bars * pat._num_steps
            pat._loop_end = None if step == total - 1 else step
            win._pattern_list[win._cur_pattern_idx]._loop_end = pat._loop_end
            if p.playing or p.clicking or p._note_repeat_active:
                p._wakeup.set()
            win._show_status(f"Boucle fin: {p.position_str()}")
            return True

        # l : toggle boucle
        if not ctrl and not shift and not alt \
                and not on_bpm and not on_volume and not on_pan and not on_voice_spin \
                and (ukey == ord('l') or key == ord('L')):
            pat = win._player._pattern
            pat._looping = not pat._looping
            win._show_status(f"Boucle: {'On' if pat._looping else 'Off'}")
            return True

        # g : GotoStart — G : GotoEnd
        if not ctrl and not shift and not alt \
                and not on_bpm and not on_volume and not on_pan and not on_voice_spin \
                and (ukey == ord('g') or key == ord('G')):
            win._player.goto_start()
            win._show_status(f"Début: {win._player.position_str()}")
            return True
        if not ctrl and shift and not alt \
                and not on_bpm and not on_volume and not on_pan and not on_voice_spin \
                and (ukey == ord('g') or key == ord('G')):
            win._player.goto_end()
            win._show_status(f"Fin: {win._player.position_str()}")
            return True

        # BPM / Volume
        if ukey == ord('(') or key == ord('(') or (not shift and not ctrl and key == ord('5')):
            win._player.set_bpm(win._player.bpm + 5)
            win._update_bpm_display()
            return True
        if ukey == ord(')') or key == ord(')'):
            win._player.set_bpm(win._player.bpm - 5)
            win._update_bpm_display()
            return True
        if ukey == ord('+') or key == ord('+'):
            win._player.set_volume(win._player.volume + 1)
            win._volume_ctrl.SetValue(win._player.volume)
            win._show_status(f"Volume: {win._player.volume}")
            return True
        if ukey == ord('-') or key == ord('-') or (not shift and not ctrl and key == ord('6')):
            win._player.set_volume(win._player.volume - 1)
            win._volume_ctrl.SetValue(win._player.volume)
            win._show_status(f"Volume: {win._player.volume}")
            return True

        # Shift+I : poser le limiteur gauche (In) au début du pattern
        if not ctrl and not alt and shift and key == ord('I'):
            pat         = win._player._pattern
            total_steps = pat._num_bars * pat._num_steps
            win._track_editor.set_lim_left(0)
            bbt = win._track_editor.fmt_bbt(0, pat._num_steps,
                      max(1, pat._num_steps // pat._num_beats), total_steps)
            win._show_status(f"Limiteur Gauche: {bbt}")
            return True

        # Shift+O : poser le limiteur droit (Out) à la fin du pattern
        if not ctrl and not alt and shift and key == ord('O'):
            pat         = win._player._pattern
            total_steps = pat._num_bars * pat._num_steps
            step        = total_steps - 1
            win._track_editor.set_lim_right(step)
            bbt = win._track_editor.fmt_bbt(step, pat._num_steps,
                      max(1, pat._num_steps // pat._num_beats), total_steps)
            win._show_status(f"Limiteur Droit: {bbt}")
            return True

        # i : poser le limiteur gauche (In) à la position courante du playhead
        if not ctrl and not alt and not shift \
                and (ukey in (ord('i'), ord('I')) or key == ord('I')):
            pat  = win._player._pattern
            step = int(win._player._current_offset())
            win._track_editor.set_lim_left(step)
            bbt  = win._track_editor.fmt_bbt(step, pat._num_steps,
                       max(1, pat._num_steps // pat._num_beats),
                       pat._num_bars * pat._num_steps)
            win._show_status(f"Limiteur Gauche: {bbt}")
            return True

        # o : poser le limiteur droit (Out) à la position courante du playhead
        if not ctrl and not alt and not shift \
                and (ukey in (ord('o'), ord('O')) or key == ord('O')):
            pat  = win._player._pattern
            step = int(win._player._current_offset())
            win._track_editor.set_lim_right(step)
            bbt  = win._track_editor.fmt_bbt(step, pat._num_steps,
                       max(1, pat._num_steps // pat._num_beats),
                       pat._num_bars * pat._num_steps)
            win._show_status(f"Limiteur Droit: {bbt}")
            return True

        return False
