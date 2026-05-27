#python3
"""
    File: src/ui/midi_handler.py
    Gestion des événements MIDI entrants (note_on, note_off, vélocité, connexion).
    Date: Wed, 27/05/2026
    Author: Coolbrother
"""
import wx
from drum_player import DrumPlayer
from rack import InstrumentType
from synth_engine import midi_to_note_name


class MidiHandler:
    """Traite les événements MIDI entrants pour MainWindow."""

    def __init__(self, win):
        self._win        = win
        self._erase_held = set()   # notes MIDI tenues en mode Erase

    # ------------------------------------------------------------------
    # Connexion MIDI
    # ------------------------------------------------------------------

    def connect(self):
        """Connecte le port MIDI sélectionné dans la liste."""
        win   = self._win
        ports = win._midi.list_ports()
        if not ports:
            win._show_status("MIDI: aucun port disponible")
            return
        idx = win._midi_port_list.GetSelection()
        if idx == wx.NOT_FOUND:
            idx = 0
        win._midi.open(idx)

    def disconnect(self):
        self._win._midi.close()

    def toggle(self):
        """Connecte si déconnecté, déconnecte sinon."""
        if self._win._midi.is_open():
            self.disconnect()
        else:
            self.connect()

    def refresh_ports(self):
        """Recharge la liste des ports MIDI disponibles."""
        win   = self._win
        ports = win._midi.list_ports()
        sel   = win._midi_port_list.GetSelection()
        win._midi_port_list.Set(ports if ports else ["(aucun port)"])
        if ports:
            win._midi_port_list.SetSelection(
                min(sel, len(ports) - 1) if sel != wx.NOT_FOUND else 0
            )

    def toggle_erase(self):
        """Bascule le mode Erase et vide les notes MIDI tenues."""
        self._erase_held.clear()
        return self._win._player.toggle_erase()

    # ------------------------------------------------------------------
    # Vélocité
    # ------------------------------------------------------------------

    def on_vel_level_select(self, event):
        win          = self._win
        win._vel_level = win._vel_list.GetSelection()
        win._show_status(f"MIDI Vel: {win.VEL_LEVEL_LABELS[win._vel_level]}")

    def _apply_vel_level(self, velocity):
        """Quantifie velocity selon le niveau courant (0-127 → 1-127)."""
        win = self._win
        if win._vel_level == 0:
            return 127
        step = win._VEL_STEPS[win._vel_level]
        if step is None:
            return velocity
        return min(127, ((velocity - 1) // step + 1) * step)

    # ------------------------------------------------------------------
    # Helpers internes
    # ------------------------------------------------------------------

    def _midi_to_pad(self, note):
        """Mappe note MIDI → index pad (0-ROWS-1) chromatiquement depuis la note racine."""
        win = self._win
        return (note - win._kb_root_midi) % win.ROWS

    def _kb_play_idx(self, transposed_note):
        """Indice lecture dans kb_notes pour un pitch transposé.
        Si hors gamme, cherche l'équivalent octave le plus proche."""
        kb = self._win._router.kb_notes
        if transposed_note in kb:
            return kb.index(transposed_note)
        for step in (-12, 12, -24, 24, -36, 36):
            equiv = transposed_note + step
            if 0 <= equiv <= 127 and equiv in kb:
                return kb.index(equiv)
        return -1

    def _update_erase_range(self):
        """Recalcule _erase_active_pads selon les notes MIDI tenues (plage min→max)."""
        win = self._win
        if not self._erase_held:
            win._player._erase_active_pads.clear()
            return
        pads = [self._midi_to_pad(n) for n in self._erase_held]
        win._player._erase_active_pads = set(range(min(pads), max(pads) + 1))

    # ------------------------------------------------------------------
    # Note On
    # ------------------------------------------------------------------

    def on_note_on(self, note, velocity, channel):
        """Note On MIDI reçue — jouée et enregistrée/effacée si mode Rec/Erase actif."""
        win      = self._win
        velocity = self._apply_vel_level(velocity)
        slot     = win._rack.get_slot(win._cur_slot)
        if win._input_mode == "keyboard" and slot.type == InstrumentType.SYNTH \
                and win._router.synth_ready():
            self._handle_keyboard_note_on(note, velocity)
        else:
            pad_idx = self._midi_to_pad(note)
            self._handle_pad_note_on(note, velocity, slot, pad_idx)

    def _handle_keyboard_note_on(self, note, velocity):
        win        = self._win
        offset     = win._kb_root_midi - win._kb_play_root
        transposed = max(0, min(127, note + offset))
        play_idx   = self._kb_play_idx(transposed)
        if win._player.erasing:
            if play_idx >= 0:
                result = win._player.erase_hit(play_idx)
                if result:
                    bar_idx, step_idx = result
                    if bar_idx == 0 and step_idx < win.COLS:
                        win._cells[play_idx][step_idx].SetValue(False)
        elif win._note_repeat:
            vol_factor = velocity / 127.0
            v   = win._player.voice_manager.get_voice(win._cur_row)
            pan = win._player._mix_pan(v.pan)
            win._router.synth.play(transposed, vol_factor, pan, 0)
            win._router.kb_last_midi = transposed
            if win._player.recording and 0 <= play_idx < win.ROWS:
                bar_idx, step_idx = win._player.record_hit(play_idx, velocity)
                if bar_idx == 0 and step_idx < win.COLS:
                    win._cells[play_idx][step_idx].SetValue(True)
            win._nr_cancel_release()
            win._nr_active_key = None
            win._nr_midi_note  = note
            safe_idx = max(0, play_idx)
            _t, _vf, _p = transposed, vol_factor, pan
            router = win._router
            def _nr_kb_play(_pad, t=_t, vf=_vf, p=_p):
                router.synth.play(t, vf, p, 0)
            win._player.start_note_repeat(
                win._nr_rate_idx, lambda s=safe_idx: s, play_cb=_nr_kb_play
            )
            win._show_status(
                f"NR Keyboard: {midi_to_note_name(transposed)}"
                f" @ {DrumPlayer.QUANT_LIST[win._nr_rate_idx]}"
            )
        else:
            vol_factor = velocity / 127.0
            v   = win._player.voice_manager.get_voice(win._cur_row)
            pan = win._player._mix_pan(v.pan)
            win._router.synth.play(transposed, vol_factor, pan, 0)
            win._router.kb_last_midi = transposed
            if win._player.recording:
                win._player.record_patch_note(transposed, velocity)

    def _handle_pad_note_on(self, note, velocity, slot, pad_idx):
        win = self._win
        if win._player.erasing:
            prev_range = set(win._player._erase_active_pads)
            self._erase_held.add(note)
            self._update_erase_range()
            for p in sorted(win._player._erase_active_pads - prev_range):
                result = win._player.erase_hit(p)
                if result:
                    bar_idx, step_idx = result
                    if bar_idx == 0 and step_idx < win.COLS:
                        win._cells[p][step_idx].SetValue(False)
        elif win._note_repeat:
            if slot.type == InstrumentType.SYNTH and win._router.synth_ready() \
                    and pad_idx < len(win._router.kb_notes_input):
                vm     = win._player.voice_manager
                v      = vm.get_voice(pad_idx)
                vol    = min(1.0, vm.get_volume_factor(pad_idx) * velocity / 100.0)
                pan    = win._player._mix_pan(v.pan)
                midi_n = win._router.kb_notes_input[pad_idx]
                win._router.synth.play(midi_n, vol, pan, 0)
                win._router.kb_last_midi    = midi_n
                win._player.last_played_pad = pad_idx
                if win._player.recording:
                    bar_idx, step_idx = win._player.record_hit(pad_idx, velocity)
                    if bar_idx == 0 and step_idx < win.COLS:
                        win._cells[pad_idx][step_idx].SetValue(True)
                win._nr_cancel_release()
                win._nr_active_key = None
                win._nr_midi_note  = note
                _mn, _vol, _pan = midi_n, vol, pan
                router = win._router
                def _nr_pad_play(_pad, m=_mn, vv=_vol, p=_pan):
                    router.synth.play(m, vv, p, 0)
                win._player.start_note_repeat(
                    win._nr_rate_idx, lambda pi=pad_idx: pi, play_cb=_nr_pad_play
                )
            else:
                win._player.play_sound(pad_idx, velocity)
                win._player.last_played_pad = pad_idx
                if win._player.recording:
                    bar_idx, step_idx = win._player.record_hit(pad_idx, velocity)
                    if bar_idx == 0 and step_idx < win.COLS:
                        win._cells[pad_idx][step_idx].SetValue(True)
                win._nr_cancel_release()
                win._nr_active_key = None
                win._nr_midi_note  = note
                win._player.start_note_repeat(win._nr_rate_idx, lambda pi=pad_idx: pi)
            win._show_status(
                f"NR: Pad {pad_idx + 1} @ {DrumPlayer.QUANT_LIST[win._nr_rate_idx]}"
            )
        elif slot.type == InstrumentType.SYNTH and win._router.synth_ready() \
                and pad_idx < len(win._router.kb_notes_input):
            vm  = win._player.voice_manager
            v   = vm.get_voice(pad_idx)
            vol = min(1.0, vm.get_volume_factor(pad_idx) * velocity / 100.0)
            pan = win._player._mix_pan(v.pan)
            win._router.synth.play(win._router.kb_notes_input[pad_idx], vol, pan, 0)
            win._router.kb_last_midi    = win._router.kb_notes_input[pad_idx]
            win._player.last_played_pad = pad_idx
            win._debug_pad_status(pad_idx, note)
            if win._player.recording:
                bar_idx, step_idx = win._player.record_hit(pad_idx, velocity)
                if bar_idx == 0 and step_idx < win.COLS:
                    win._cells[pad_idx][step_idx].SetValue(True)
        elif slot.type == InstrumentType.KIT and win._snd.note_map:
            win._snd.play_note(note, velocity / 127.0)
            kit_pad = note - (win._snd.kit_base + win._snd.kit_offset)
            pad_idx = max(0, min(win.ROWS - 1, kit_pad))
            win._debug_pad_status(pad_idx, note)
            if win._player.recording:
                win._player.record_kit_note(note, velocity)
        else:
            win._player.play_sound(pad_idx, velocity)
            win._debug_pad_status(pad_idx, note)
            if win._player.recording:
                bar_idx, step_idx = win._player.record_hit(pad_idx, velocity)
                if bar_idx == 0 and step_idx < win.COLS:
                    win._cells[pad_idx][step_idx].SetValue(True)

    # ------------------------------------------------------------------
    # Note Off
    # ------------------------------------------------------------------

    def on_note_off(self, note, channel):
        """Note Off MIDI — coupe la note tenue (Synth) ou arrête l'effacement (Erase)."""
        win = self._win
        if win._note_repeat and win._nr_midi_note == note:
            win._player.stop_note_repeat()
            win._nr_midi_note = None
            mode = "Ternaire" if win._nr_ternary else "Binaire"
            win._show_status(
                f"Note Repeat: ON — {mode} — {DrumPlayer.QUANT_LIST[win._nr_rate_idx]}"
            )
        slot = win._rack.get_slot(win._cur_slot)
        if win._router.synth_ready() and slot.type == InstrumentType.SYNTH:
            if win._input_mode == "keyboard":
                offset     = win._kb_root_midi - win._kb_play_root
                transposed = max(0, min(127, note + offset))
                win._router.synth.stop(transposed)
                if win._player.recording:
                    win._player.record_patch_note_off(transposed)
            else:
                pad_idx = self._midi_to_pad(note)
                if pad_idx < len(win._router.kb_notes_input):
                    win._router.synth.stop(win._router.kb_notes_input[pad_idx])
        self._erase_held.discard(note)
        self._update_erase_range()
