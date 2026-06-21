import threading
import wx
from pattern import Pattern
from synth_engine import midi_to_note_name, SCALE_NAMES
from rack import InstrumentType


class NumpadHandler:
    """Mixin KeyManager — pavé numérique (pads, keyboard, Note Repeat)."""

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
