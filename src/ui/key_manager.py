#python3
"""
    File: src/ui/key_manager.py
    Gestion centralisée des raccourcis clavier de MainWindow.
    Date: Thu, 21/05/2026
    Author: Coolbrother
"""
import types
import threading
import wx
from drum_player import DrumPlayer
from pattern import Pattern
from synth_engine import midi_to_note_name, SCALE_NAMES
from rack import InstrumentType


class KeyManager:
    """Dispatche les événements clavier reçus par MainWindow._on_char_hook."""

    def __init__(self, win):
        self._win = win

    # ------------------------------------------------------------------
    # Point d'entrée unique
    # ------------------------------------------------------------------

    def handle(self, event):
        win     = self._win
        key     = event.GetKeyCode()
        ukey    = event.GetUnicodeKey()
        ctrl    = event.ControlDown()
        shift   = event.ShiftDown()
        alt     = event.AltDown()
        focused = wx.Window.FindFocus()

        ctx = types.SimpleNamespace(
            key   = key,   ukey  = ukey,
            ctrl  = ctrl,  shift = shift, alt = alt,
            on_quant_list   = focused == win._quant_list,
            on_pattern_list = focused == win._pattern_listbox,
            on_bpm          = focused == win._bpm_ctrl,
            on_volume       = focused == win._volume_ctrl,
            on_pan          = focused == win._pan_ctrl,
            on_voice_spin   = focused in win._vol_ctrls or focused in win._pan_ctrls,
            on_mode_choice  = focused == win._mode_choice,
            on_scale_choice = focused == win._scale_choice,
            on_slot_choice  = focused == win._slot_choice,
            on_track_list   = focused == win._track_list,
            on_pad_list          = focused == win._pad_list,
            on_vel_list          = focused == win._vel_list,
            on_midi_port_list    = focused == win._midi_port_list,
        )

        if key == wx.WXK_F1:
            win._show_keyboard_help()
            return
        if ctx.alt and self._handle_alt(event, ctx):
            return
        if ctx.ctrl and self._handle_ctrl(event, ctx):
            return
        if self._handle_navigation(event, ctx):
            return
        if self._handle_numpad(event, ctx):
            return
        if self._handle_chars(event, ctx):
            return

        print(f"DEBUG key={key} ukey={ukey} shift={shift} ctrl={ctrl} "
              f"char={chr(ukey) if ukey > 31 else '?'}")
        event.Skip()

    # ------------------------------------------------------------------
    # Groupe Alt+…
    # ------------------------------------------------------------------

    def _handle_alt(self, event, ctx):
        win   = self._win
        key   = ctx.key
        ukey  = ctx.ukey
        ctrl  = ctx.ctrl
        shift = ctx.shift
        on_track_list = ctx.on_track_list
        on_pad_list   = ctx.on_pad_list

        if not ctrl and shift and key == ord('W'):
            win._save_preset_as()
            return True
        if not ctrl and not shift and key == ord('W'):
            win._save_preset()
            return True
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
        if not ctrl and shift and (ukey in (ord('m'), ord('M')) or key == ord('M')):
            win._midi_handler.refresh_ports()
            win._show_status("MIDI: liste des ports actualisée")
            return True
        if not ctrl and not shift and (ukey in (ord('m'), ord('M')) or key == ord('M')):
            win._midi_handler.toggle()
            return True
        return False

    # ------------------------------------------------------------------
    # Groupe Ctrl+…
    # ------------------------------------------------------------------

    def _handle_ctrl(self, event, ctx):
        win   = self._win
        key   = ctx.key
        shift = ctx.shift
        alt   = ctx.alt

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
        if key == ord('D'):
            win._player._pattern.reset_pattern()
            win._refresh_grid()
            win._show_status("Pattern réinitialisé")
            return True
        if key == ord('P'):
            win._player._pattern.build_pattern_01()
            win._refresh_grid()
            win._show_status("Pattern initial chargé")
            return True
        if not shift and key == ord('F'):
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
        return False

    # ------------------------------------------------------------------
    # Navigation : Tab, flèches, Entrée
    # ------------------------------------------------------------------

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

        if key in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_LEFT, wx.WXK_RIGHT):
            if on_track_list and key in (wx.WXK_UP, wx.WXK_DOWN):
                cur = win._track_list.GetSelection()
                n   = win._track_list.GetCount()
                at_limit = (key == wx.WXK_UP  and cur <= 0) or \
                           (key == wx.WXK_DOWN and cur >= n - 1)
                if at_limit:
                    wx.Bell()
                else:
                    event.Skip()
                    wx.CallAfter(win._on_track_select, None)
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

        return False

    # ------------------------------------------------------------------
    # Pavé numérique
    # ------------------------------------------------------------------

    def _handle_numpad(self, event, ctx):
        win   = self._win
        key   = ctx.key
        ctrl  = ctx.ctrl
        shift = ctx.shift
        alt   = ctx.alt

        if wx.WXK_NUMPAD1 <= key <= wx.WXK_NUMPAD8:
            if win._input_mode == "keyboard":
                note_idx = key - wx.WXK_NUMPAD1
                cur_slot = win._rack.get_slot(win._cur_slot)
                if note_idx < len(win._router.kb_notes_input) \
                        and cur_slot.type == InstrumentType.SYNTH:
                    midi = win._router.kb_notes_input[note_idx]
                    if win._player.erasing:
                        win._player._erase_active_midi_notes.add(midi)
                        result = win._player.erase_patch_tape_note(
                            win._player._cur_track, midi
                        )
                        # patch_tape n'est pas dans la grille UI → pas de SetValue
                    elif win._router.synth_ready():
                        vm = win._player.voice_manager
                        v  = vm.get_voice(note_idx)
                        win._router.synth.play(midi, v.volume / 100.0, v.pan, v.duration_ms)
                        win._router.kb_last_midi = midi
                        if win._player.recording:
                            win._player.record_patch_note(midi, 100, v.duration_ms)
                    else:
                        win._show_status("Keyboard: patch en cours de chargement…")
                elif note_idx < len(win._router.kb_notes_input):
                    win._play_kit_pitched(note_idx)
            elif win._player.erasing:
                pad_idx = (key - wx.WXK_NUMPAD1) + win._shift_pad
                slot = win._rack.get_slot(win._cur_slot)
                if slot.type == InstrumentType.SYNTH and win._router.synth_ready() \
                        and pad_idx < len(win._router.kb_notes_input):
                    midi = win._router.kb_notes_input[pad_idx]
                    win._router.synth.stop(midi)
                    result = win._player.erase_patch_tape_note(win._player._cur_track, midi)
                else:
                    win._player._erase_active_pads.add(pad_idx)
                    result = win._player.erase_hit(pad_idx)
                if result:
                    bar_idx, step_idx = result
                    if bar_idx == 0 and step_idx < win.COLS:
                        win._cells[pad_idx][step_idx].SetValue(False)
            elif win._note_repeat:
                pad_idx = (key - wx.WXK_NUMPAD1) + win._shift_pad
                if key == win._nr_active_key:
                    win._nr_arm_release()
                elif win._player._note_repeat_active \
                        and win._nr_active_key is None and key == win._nr_prev_key:
                    win._nr_cancel_release()
                    win._nr_prev_key = None
                    win._player.stop_note_repeat()
                    mode = "Ternaire" if win._nr_ternary else "Binaire"
                    win._show_status(
                        f"Note Repeat: ON — {mode} — {Pattern.QUANT_LIST[win._nr_rate_idx]}"
                    )
                else:
                    win._nr_cancel_release()
                    win._nr_active_key = key
                    win._nr_prev_key   = key
                    win._nr_arm_release()
                    win._play(pad_idx)
                    if win._player.recording:
                        bar_idx, step_idx = win._player.record_hit(pad_idx)
                        if bar_idx == 0 and step_idx < win.COLS:
                            win._cells[pad_idx][step_idx].SetValue(True)
                    win._player.start_note_repeat(win._nr_rate_idx, lambda p=pad_idx: p)
                    win._show_status(
                        f"NR: Pad {pad_idx + 1} @ {Pattern.QUANT_LIST[win._nr_rate_idx]}"
                    )
            else:
                pad_idx = (key - wx.WXK_NUMPAD1) + win._shift_pad
                slot = win._rack.get_slot(win._cur_slot)
                if slot.type == InstrumentType.SYNTH and win._router.synth_ready():
                    if pad_idx < len(win._router.kb_notes_input):
                        midi = win._router.kb_notes_input[pad_idx]
                        vm   = win._player.voice_manager
                        v    = vm.get_voice(pad_idx)
                        dur  = max(50, v.duration_ms)
                        win._router.synth.play(midi, v.volume / 100.0, v.pan, dur)
                        threading.Timer(
                            dur / 1000.0, win._router.synth.stop, [midi]
                        ).start()
                        win._router.kb_last_midi = midi
                        win._debug_pad_status(pad_idx, midi)
                        if win._player.recording:
                            win._player.record_patch_note(midi, 100, dur)
                else:
                    win._play(pad_idx)
                    win._debug_pad_status(pad_idx)
                    if win._player.recording:
                        bar_idx, step_idx = win._player.record_hit(pad_idx)
                        if bar_idx == 0 and step_idx < win.COLS:
                            win._cells[pad_idx][step_idx].SetValue(True)
            return True

        if key == wx.WXK_NUMPAD9:
            if win._input_mode == "keyboard":
                if win._router.kb_last_midi is not None:
                    cur_slot = win._rack.get_slot(win._cur_slot)
                    if cur_slot.type == InstrumentType.KIT:
                        if win._router.kit_synth and win._router.kit_synth.is_loaded():
                            win._router.kit_synth.play(win._router.kb_last_midi)
                    elif win._router.synth_ready():
                        win._router.synth.play(win._router.kb_last_midi)
            else:
                last = win._player.last_played_pad
                if last is not None:
                    if win._player.erasing:
                        result = win._player.erase_hit(last)
                        if result:
                            bar_idx, step_idx = result
                            if bar_idx == 0 and step_idx < win.COLS:
                                win._cells[last][step_idx].SetValue(False)
                    else:
                        win._play(last)
                        if win._player.recording:
                            bar_idx, step_idx = win._player.record_hit(last)
                            if bar_idx == 0 and step_idx < win.COLS:
                                win._cells[last][step_idx].SetValue(True)
            return True

        if key == wx.WXK_NUMPAD0:
            win._note_repeat   = False
            win._nr_active_key = None
            win._nr_prev_key   = None
            win._nr_midi_note  = None
            win._nr_cancel_release()
            win._player.stop_all()
            win._router.stop_all_synth_voices()
            return True

        if key == wx.WXK_NUMPAD_ADD:
            if win._input_mode == "keyboard":
                if win._kb_root_midi + 12 > 96:
                    wx.Bell()
                else:
                    win._kb_root_midi += 12
                    win._router.update_input_kb(win._kb_root_midi)
                    win._show_status(f"Keyboard: octave entrée → {midi_to_note_name(win._kb_root_midi)}")
            else:
                win._shift_pad = min(8, win._shift_pad + 8)
                win._show_status(f"Pads {win._shift_pad + 1}–{win._shift_pad + 8}")
            return True

        if key == wx.WXK_NUMPAD_SUBTRACT:
            if win._input_mode == "keyboard":
                if win._kb_root_midi - 12 < 12:
                    wx.Bell()
                else:
                    win._kb_root_midi -= 12
                    win._router.update_input_kb(win._kb_root_midi)
                    win._show_status(f"Keyboard: octave entrée → {midi_to_note_name(win._kb_root_midi)}")
            else:
                win._shift_pad = max(0, win._shift_pad - 8)
                win._show_status(f"Pads {win._shift_pad + 1}–{win._shift_pad + 8}")
            return True

        if win._input_mode == "keyboard" and not ctrl and not shift and not alt:
            if key == wx.WXK_NUMPAD_DIVIDE:
                idx = SCALE_NAMES.index(win._kb_scale)
                if idx == 0:
                    wx.Bell()
                else:
                    idx -= 1
                    win._kb_scale = SCALE_NAMES[idx]
                    win._scale_choice.SetSelection(idx)
                    win._router.update_kb_notes(win._kb_scale, win._kb_play_root)
                    win._router.update_input_kb(win._kb_root_midi)
                    win._show_status(
                        f"Gamme: {win._kb_scale} @ {midi_to_note_name(win._kb_root_midi)}"
                    )
                return True
            if key == wx.WXK_NUMPAD_MULTIPLY:
                idx = SCALE_NAMES.index(win._kb_scale)
                if idx == len(SCALE_NAMES) - 1:
                    wx.Bell()
                else:
                    idx += 1
                    win._kb_scale = SCALE_NAMES[idx]
                    win._scale_choice.SetSelection(idx)
                    win._router.update_kb_notes(win._kb_scale, win._kb_play_root)
                    win._router.update_input_kb(win._kb_root_midi)
                    win._show_status(
                        f"Gamme: {win._kb_scale} @ {midi_to_note_name(win._kb_root_midi)}"
                    )
                return True

        return False

    # ------------------------------------------------------------------
    # Touches caractères (sans modificateurs principaux, ou Shift seul)
    # ------------------------------------------------------------------

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

        # Space / P : play/stop
        if ukey in (ord(' '), ord('p')) or (not ctrl and key in (wx.WXK_SPACE, ord('P'))):
            if win._player.playing:
                was_recording = win._player.recording
                win._player.stop_pattern()
                win._router.stop_all_synth_voices()
                if was_recording:
                    win._refresh_grid()
                    win._refresh_track_list()
                win._show_status("Pattern: Stop")
            else:
                win._player.play_pattern()
                win._show_status("Pattern: Play")
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

        return False
