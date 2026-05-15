import json
import os
import wx
from sound_manager import SoundManager
from drum_player import DrumPlayer
from pattern import Pattern
from ui.dialogs import (
    KeyboardHelpDialog,
    GenRowDialog,
    QuantizeDialog,
    SavePatternDialog,
)


class MainWindow(wx.Frame):
    ROWS = 16
    COLS = 16
    # Indices dans QUANT_LIST pour les touches 1-8 (binaire) et 1-6 (ternaire)
    NR_BINARY  = [0, 1, 3, 5, 7, 9, 11, 13]   # 1/1,1/2,1/4,1/8,1/16,1/32,1/64,1/128
    NR_TERNARY = [2, 4, 6,  8, 10, 12]          # 1/3,1/6,1/12,1/24,1/48,1/96

    def __init__(self):
        super().__init__(None, title="GroovyboxIt")
        self._cur_row = 0
        self._cur_col = 0
        self._cells = []
        self._shift_pad = 0   # 0 → pads 1-8 (indices 0-7), 8 → pads 9-16 (indices 8-15)
        self._autoplay  = True
        self._note_repeat      = False
        self._nr_active_key    = None   # touche NumPad tenue (effacée par timer)
        self._nr_prev_key      = None   # dernière touche NumPad ayant démarré le NR
        self._nr_release_timer = None
        self._nr_rate_idx      = 7      # indice QUANT_LIST courant (défaut 1/16)
        self._nr_ternary       = False  # False=binaire, True=ternaire
        self._init_sound()
        self._pattern_list = [Pattern() for _ in range(99)]
        self._cur_pattern_idx = 0
        self._preset_path = os.path.join(self._base_dir, "data", "presets", "preset_01.json")
        self._build_ui()
        self._load_preset()
        # EVT_CHAR_HOOK remonte la hiérarchie depuis n'importe quel widget natif
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Centre()

    def _init_sound(self):
        ui_dir = os.path.dirname(os.path.abspath(__file__))
        self._base_dir = os.path.dirname(os.path.dirname(ui_dir))
        base_dir = self._base_dir
        media_dir = os.path.join(base_dir, "media")
        media_lst = [os.path.join(media_dir, f"{i}.wav") for i in range(1, 17)]
        click1 = os.path.join(media_dir, "hi_wood_block_mono.wav")
        click2 = os.path.join(media_dir, "low_wood_block_mono.wav")
        self._snd = SoundManager(media_lst, click1, click2)
        self._snd.load_sounds()
        self._player = DrumPlayer(self._snd)
        self._player._on_recorded_cb = lambda pad, bar, step: wx.CallAfter(
            self._on_nr_recorded, pad, bar, step
        )
        self._player._on_replaced_cb = lambda pad, bar, step: wx.CallAfter(
            self._on_note_replaced, pad, bar, step
        )
        self._player._on_count_in_done_cb = lambda: wx.CallAfter(self._on_count_in_done)

    def _build_ui(self):
        panel = wx.Panel(self)

        self._status_ctrl = wx.TextCtrl(
            panel,
            style=wx.TE_READONLY | wx.TE_LEFT | wx.BORDER_SIMPLE,
        )
        self._status_ctrl.SetValue("ShiftPad: 1/8")

        bpm_label = wx.StaticText(panel, label="BPM:")
        self._bpm_ctrl = wx.SpinCtrl(panel, min=5, max=600, initial=self._player.bpm, size=(80, -1))
        self._bpm_ctrl.Bind(wx.EVT_SPINCTRL, self._on_bpm_spin)

        vol_label = wx.StaticText(panel, label="Vol:")
        self._volume_ctrl = wx.SpinCtrl(panel, min=0, max=100, initial=self._player.volume, size=(70, -1))
        self._volume_ctrl.Bind(wx.EVT_SPINCTRL, self._on_volume_spin)

        quant_label = wx.StaticText(panel, label="Quant:")
        self._quant_list = wx.ListBox(
            panel,
            choices=DrumPlayer.QUANT_LIST,
            style=wx.LB_SINGLE,
        )
        self._quant_list.SetSelection(self._player.quant_idx)
        self._quant_list.Bind(wx.EVT_LISTBOX, self._on_quant_select)

        pattern_label = wx.StaticText(panel, label="Pat:")
        self._pattern_listbox = wx.ListBox(
            panel,
            choices=[self._pattern_label(i) for i in range(99)],
            style=wx.LB_SINGLE,
        )
        self._pattern_listbox.SetSelection(0)
        self._pattern_listbox.Bind(wx.EVT_LISTBOX, self._on_pattern_select)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(self._status_ctrl, 1, wx.EXPAND | wx.RIGHT, 4)
        hbox.Add(bpm_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox.Add(self._bpm_ctrl, 0, wx.EXPAND | wx.RIGHT, 8)
        hbox.Add(vol_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox.Add(self._volume_ctrl, 0, wx.EXPAND | wx.RIGHT, 8)
        hbox.Add(quant_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox.Add(self._quant_list, 0, wx.EXPAND | wx.RIGHT, 8)
        hbox.Add(pattern_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox.Add(self._pattern_listbox, 0, wx.EXPAND)

        # Panneau voix : M / S / SpinVol / SpinPan par ligne
        self._mute_btns = []
        self._solo_btns = []
        self._vol_ctrls = []
        self._pan_ctrls = []
        voice_grid = wx.FlexGridSizer(self.ROWS, 4, 2, 2)
        for r in range(self.ROWS):
            m_btn   = wx.ToggleButton(panel, label="M", size=(26, -1))
            s_btn   = wx.ToggleButton(panel, label="S", size=(26, -1))
            vol_sp  = wx.SpinCtrl(panel, min=0,    max=100,  initial=100, size=(60, -1))
            pan_sp  = wx.SpinCtrl(panel, min=-100, max=100,  initial=0,   size=(68, -1))
            m_btn.Bind(wx.EVT_TOGGLEBUTTON, lambda e, r=r: self._on_mute_btn(r))
            s_btn.Bind(wx.EVT_TOGGLEBUTTON, lambda e, r=r: self._on_solo_btn(r))
            vol_sp.Bind(wx.EVT_SPINCTRL, lambda e, r=r: self._on_vol_spin(r))
            pan_sp.Bind(wx.EVT_SPINCTRL, lambda e, r=r: self._on_pan_spin(r))
            voice_grid.Add(m_btn,  0, wx.EXPAND)
            voice_grid.Add(s_btn,  0, wx.EXPAND)
            voice_grid.Add(vol_sp, 0, wx.EXPAND)
            voice_grid.Add(pan_sp, 0, wx.EXPAND)
            self._mute_btns.append(m_btn)
            self._solo_btns.append(s_btn)
            self._vol_ctrls.append(vol_sp)
            self._pan_ctrls.append(pan_sp)

        grid = wx.GridSizer(self.ROWS, self.COLS, 2, 2)
        for r in range(self.ROWS):
            row = []
            for c in range(self.COLS):
                cb = wx.CheckBox(panel, label=f"Pad{r + 1}/{c + 1}")
                cb.Bind(wx.EVT_CHECKBOX, lambda e, r=r, c=c: self._on_checkbox(r, c))
                cb.Bind(wx.EVT_SET_FOCUS, lambda e, r=r, c=c: self._set_cursor(r, c))
                grid.Add(cb, 0, wx.EXPAND)
                row.append(cb)
            self._cells.append(row)

        content_hbox = wx.BoxSizer(wx.HORIZONTAL)
        content_hbox.Add(voice_grid, 0, wx.EXPAND | wx.RIGHT, 4)
        content_hbox.Add(grid,       1, wx.EXPAND)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(hbox,         0, wx.EXPAND | wx.ALL, 4)
        vbox.Add(content_hbox, 1, wx.EXPAND)
        panel.SetSizer(vbox)

        self.Fit()
        self._cells[0][0].SetFocus()

    def _set_cursor(self, row, col):
        self._cur_row = row
        self._cur_col = col

    def _set_cell(self, row, col, value):
        self._cells[row][col].SetValue(value)
        self._player._pattern._curpattern[self._player._cur_track][row][0][col] = value
        self._player.float_offsets[row] = [
            float(c) for c in range(self.COLS) if self._player._pattern._curpattern[self._player._cur_track][row][0][c]
        ]

    def _on_checkbox(self, row, col):
        self._player._pattern._curpattern[self._player._cur_track][row][0][col] = self._cells[row][col].GetValue()
        self._player.float_offsets[row] = [
            float(c) for c in range(self.COLS) if self._player._pattern._curpattern[self._player._cur_track][row][0][c]
        ]

    def _refresh_grid(self):
        for r in range(self.ROWS):
            for c in range(self.COLS):
                self._cells[r][c].SetValue(self._player._pattern._curpattern[self._player._cur_track][r][0][c])
        self._player._compute_offsets()

    def _on_pattern_select(self, event):
        self._switch_pattern(self._pattern_listbox.GetSelection())

    def _is_pattern_empty(self, pat):
        return not any(
            step
            for track in pat._curpattern
            for pad in track
            for bar in pad
            for step in bar
        )

    def _pattern_label(self, idx):
        pat = self._pattern_list[idx]
        if pat._name:
            return f"{idx + 1:02d} - {pat._name}"
        if self._is_pattern_empty(pat):
            return f"{idx + 1:02d} (Unused)"
        return f"{idx + 1:02d}"

    def _refresh_pattern_listbox(self):
        sel = self._pattern_listbox.GetSelection()
        self._pattern_listbox.Set([self._pattern_label(i) for i in range(99)])
        self._pattern_listbox.SetSelection(sel if sel != wx.NOT_FOUND else 0)

    def _switch_pattern(self, idx):
        # Sauvegarder l'état des voix dans le pattern courant avant de changer
        self._pattern_list[self._cur_pattern_idx]._voices = \
            self._player.voice_manager.to_list()
        self._cur_pattern_idx = idx
        self._player._pattern.load_pattern(self._pattern_list[idx]._curpattern)
        self._player.voice_manager.from_list(self._pattern_list[idx]._voices)
        self._player._compute_offsets()
        self._refresh_grid()
        self._refresh_all_voice_display()
        self._show_status(f"Pattern {idx + 1:02d}")

    def _save_pattern(self):
        self._pattern_list[self._cur_pattern_idx].load_pattern(self._player._pattern._curpattern)
        self._refresh_pattern_listbox()
        self._show_status(f"Pattern {self._cur_pattern_idx + 1:02d} sauvegardé")

    def _save_pattern_as(self):
        cur_name = self._pattern_list[self._cur_pattern_idx]._name
        dlg = SavePatternDialog(self, self._cur_pattern_idx, cur_name)
        if dlg.ShowModal() == wx.ID_OK:
            idx  = dlg.get_selection()
            name = dlg.get_name()
            self._pattern_list[idx].load_pattern(self._player._pattern._curpattern)
            self._pattern_list[idx]._name = name
            self._refresh_pattern_listbox()
            self._show_status(f"Pattern {idx + 1:02d} sauvegardé")
        dlg.Destroy()

    def _save_preset(self):
        # Synchroniser l'état courant des voix avant sauvegarde
        self._pattern_list[self._cur_pattern_idx]._voices = \
            self._player.voice_manager.to_list()
        os.makedirs(os.path.dirname(self._preset_path), exist_ok=True)
        data = {
            "version": 1,
            "patterns": [
                {
                    "name":       pat._name,
                    "bpm":        pat._bpm,
                    "num_bars":   pat._num_bars,
                    "num_steps":  pat._num_steps,
                    "curpattern": pat._curpattern,
                    "voices":     pat._voices,
                }
                for pat in self._pattern_list
            ],
        }
        with open(self._preset_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self._show_status(f"Preset sauvegardé : {os.path.basename(self._preset_path)}")

    def _save_preset_as(self):
        presets_dir = os.path.dirname(self._preset_path)
        os.makedirs(presets_dir, exist_ok=True)
        dlg = wx.FileDialog(
            self,
            message="Enregistrer le preset sous…",
            defaultDir=presets_dir,
            defaultFile=os.path.basename(self._preset_path),
            wildcard="Preset JSON (*.json)|*.json",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self._preset_path = dlg.GetPath()
            self._save_preset()
        dlg.Destroy()

    def _load_preset(self):
        if not os.path.exists(self._preset_path):
            return
        with open(self._preset_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for i, p in enumerate(data.get("patterns", [])):
            if i >= len(self._pattern_list):
                break
            pat = self._pattern_list[i]
            pat._name      = p.get("name", "")
            pat._bpm       = p.get("bpm", 100)
            pat._num_bars  = p.get("num_bars", 1)
            pat._num_steps = p.get("num_steps", 16)
            pat.load_pattern(p["curpattern"])
            if "voices" in p:
                pat._voices = p["voices"]
        self._refresh_pattern_listbox()
        self._switch_pattern(0)

    def _on_quant_select(self, event):
        self._player.quant_idx = self._quant_list.GetSelection()
        self._apply_quant()

    def _apply_quant(self):
        row       = self._cur_row
        quant_idx = self._quant_list.GetSelection()
        self._player.quant_idx = quant_idx
        self._player.apply_quant_row(quant_idx, row)
        pad = self._player._pattern._curpattern[self._player._cur_track][row][0]
        for c in range(self.COLS):
            self._cells[row][c].SetValue(bool(pad[c]))
        self._show_status(f"Ligne {row + 1}: {DrumPlayer.QUANT_LIST[quant_idx]} coché")

    def _quantize_pattern(self):
        self._player.apply_quant_to_pattern()
        self._refresh_grid()
        self._show_status(f"Pattern quantisé: {DrumPlayer.QUANT_LIST[self._player.quant_idx]}")

    def _gen_row_dialog(self):
        dlg    = GenRowDialog(self, self._cur_row, self._player.quant_idx, self.ROWS)
        result = dlg.ShowModal()
        if result in (wx.ID_OK, wx.ID_APPLY):
            row       = dlg.get_row()
            quant_idx = dlg.get_quant_idx()
            self._player.quant_idx    = quant_idx
            self._quant_list.SetSelection(quant_idx)
            if result == wx.ID_APPLY:
                self._player.apply_quant_row(quant_idx, row)
                pad = self._player._pattern._curpattern[self._player._cur_track][row][0]
                for c in range(self.COLS):
                    self._cells[row][c].SetValue(bool(pad[c]))
                self._show_status(
                    f"Ligne {row + 1}: {DrumPlayer.QUANT_LIST[quant_idx]} généré"
                )
            else:
                self._show_status(
                    f"Défaut: ligne {row + 1}, quant {DrumPlayer.QUANT_LIST[quant_idx]}"
                )
        dlg.Destroy()

    def _show_keyboard_help(self):
        dlg = KeyboardHelpDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def _quantize_pattern_dialog(self):
        dlg    = QuantizeDialog(self, self._player.quant_idx)
        result = dlg.ShowModal()
        if result in (wx.ID_OK, wx.ID_APPLY):
            idx = dlg.get_selection()
            self._player.quant_idx = idx
            self._quant_list.SetSelection(idx)
            if result == wx.ID_APPLY:
                self._player.apply_quant_to_pattern()
                self._refresh_grid()
                self._show_status(f"Pattern quantisé: {DrumPlayer.QUANT_LIST[idx]}")
            else:
                self._show_status(f"Quant par défaut: {DrumPlayer.QUANT_LIST[idx]}")
        dlg.Destroy()

    def _on_bpm_spin(self, event):
        bpm = self._bpm_ctrl.GetValue()
        self._player.set_bpm(bpm)
        self._show_status(f"BPM: {bpm}")

    def _on_volume_spin(self, event):
        vol = self._volume_ctrl.GetValue()
        self._player.set_volume(vol)
        self._show_status(f"Volume: {vol}")

    def _update_bpm_display(self):
        self._bpm_ctrl.SetValue(self._player.bpm)

    def _on_nr_recorded(self, pad_idx, bar_idx, step_idx):
        if bar_idx == 0 and step_idx < self.COLS:
            self._cells[pad_idx][step_idx].SetValue(True)

    def _on_note_replaced(self, pad_idx, bar_idx, step_idx):
        if bar_idx == 0 and step_idx < self.COLS:
            self._cells[pad_idx][step_idx].SetValue(False)

    def _on_count_in_done(self):
        self._show_status("Rec: On")

    def _refresh_voice_display(self, pad_idx):
        vm = self._player.voice_manager
        v  = vm.get_voice(pad_idx)
        self._mute_btns[pad_idx].SetValue(v.mute)
        self._solo_btns[pad_idx].SetValue(v.solo)
        self._vol_ctrls[pad_idx].SetValue(v.volume)
        self._pan_ctrls[pad_idx].SetValue(v.pan)

    def _on_vol_spin(self, pad_idx):
        val = self._vol_ctrls[pad_idx].GetValue()
        self._player.voice_manager.set_volume(pad_idx, val)
        self._show_status(f"Pad {pad_idx + 1}: Volume {val}")

    def _on_pan_spin(self, pad_idx):
        val = self._pan_ctrls[pad_idx].GetValue()
        self._player.voice_manager.set_pan(pad_idx, val)
        self._show_status(f"Pad {pad_idx + 1}: Pan {val}")

    def _refresh_all_voice_display(self):
        for r in range(self.ROWS):
            self._refresh_voice_display(r)

    def _on_mute_btn(self, pad_idx):
        muted = self._player.voice_manager.toggle_mute(pad_idx)
        self._mute_btns[pad_idx].SetValue(muted)
        self._show_status(f"Pad {pad_idx + 1}: Mute {'On' if muted else 'Off'}")

    def _on_solo_btn(self, pad_idx):
        soloed = self._player.voice_manager.toggle_solo(pad_idx)
        self._solo_btns[pad_idx].SetValue(soloed)
        self._show_status(f"Pad {pad_idx + 1}: Solo {'On' if soloed else 'Off'}")

    def _show_status(self, msg):
        focused = wx.Window.FindFocus()
        self._status_ctrl.SetValue(msg)
        if focused:
            wx.CallAfter(focused.SetFocus)

    def _move(self, dr, dc):
        r = max(0, min(self.ROWS - 1, self._cur_row + dr))
        c = max(0, min(self.COLS - 1, self._cur_col + dc))
        if r == self._cur_row and c == self._cur_col:
            wx.Bell()
        else:
            if dr != 0 and self._autoplay:
                self._play(r)
        self._cells[r][c].SetFocus()

    def _play(self, idx):
        self._player.play_sound(idx)

    def _nr_arm_release(self):
        if self._nr_release_timer:
            self._nr_release_timer.cancel()
        import threading as _t
        self._nr_release_timer = _t.Timer(
            0.050, lambda: wx.CallAfter(setattr, self, '_nr_active_key', None)
        )
        self._nr_release_timer.start()

    def _nr_cancel_release(self):
        if self._nr_release_timer:
            self._nr_release_timer.cancel()
            self._nr_release_timer = None

    def _on_char_hook(self, event):
        key  = event.GetKeyCode()
        ukey = event.GetUnicodeKey()   # caractère traduit (layout-aware)
        ctrl  = event.ControlDown()
        shift = event.ShiftDown()
        alt   = event.AltDown()
        focused       = wx.Window.FindFocus()
        on_quant_list   = (focused == self._quant_list)
        on_pattern_list = (focused == self._pattern_listbox)
        on_bpm          = (focused == self._bpm_ctrl)
        on_volume       = (focused == self._volume_ctrl)
        on_voice_spin   = (focused in self._vol_ctrls or focused in self._pan_ctrls)

        # --- F1 : Aide clavier ---
        if key == wx.WXK_F1:
            self._show_keyboard_help()

        # --- Raccourcis Alt ---
        # --- Alt+Shift+W : Enregistrer Sous le fichier de preset  ---
        elif alt and not ctrl and shift and key == ord('W'):
            self._save_preset_as()
        # --- Alt+W : Enregistrer le fichier de preset ---
        elif alt and not ctrl and not shift and key == ord('W'):
            self._save_preset()

        # --- Alt+↑/↓ : volume pad courant ±5 ---
        elif alt and not ctrl and not shift and key == wx.WXK_UP:
            vm = self._player.voice_manager
            vm.set_volume(self._cur_row, vm.get_voice(self._cur_row).volume + 5)
            self._refresh_voice_display(self._cur_row)
            self._show_status(f"Pad {self._cur_row + 1}: Volume {vm.get_voice(self._cur_row).volume}")
        elif alt and not ctrl and not shift and key == wx.WXK_DOWN:
            vm = self._player.voice_manager
            vm.set_volume(self._cur_row, vm.get_voice(self._cur_row).volume - 5)
            self._refresh_voice_display(self._cur_row)
            self._show_status(f"Pad {self._cur_row + 1}: Volume {vm.get_voice(self._cur_row).volume}")

        # --- Alt+←/→ : pan pad courant ±10 ; Alt+0 : reset centre ---
        elif alt and not ctrl and not shift and key == wx.WXK_LEFT:
            vm = self._player.voice_manager
            vm.set_pan(self._cur_row, vm.get_pan(self._cur_row) - 10)
            self._refresh_voice_display(self._cur_row)
            self._show_status(f"Pad {self._cur_row + 1}: Pan {vm.get_pan(self._cur_row)}")
        elif alt and not ctrl and not shift and key == wx.WXK_RIGHT:
            vm = self._player.voice_manager
            vm.set_pan(self._cur_row, vm.get_pan(self._cur_row) + 10)
            self._refresh_voice_display(self._cur_row)
            self._show_status(f"Pad {self._cur_row + 1}: Pan {vm.get_pan(self._cur_row)}")
        elif alt and not ctrl and not shift and (ukey == ord('0') or key == ord('0')):
            self._player.voice_manager.set_pan(self._cur_row, 0)
            self._refresh_voice_display(self._cur_row)
            self._show_status(f"Pad {self._cur_row + 1}: Pan 0 (centre)")

        # --- Raccourcis Ctrl ---
        elif ctrl and shift and key == ord('W'):
            self._save_pattern_as()
        elif ctrl and key == ord('W'):
            self._save_pattern()
        elif ctrl and key == ord('D'):
            self._player._pattern.reset_pattern()
            self._refresh_grid()
            self._show_status("Pattern réinitialisé")
        elif ctrl and key == ord('P'):
            self._player._pattern.build_pattern_01()
            self._refresh_grid()
            self._show_status("Pattern initial chargé")
        elif ctrl and not shift and key == ord('F'):
            if self._player.double_pattern():
                self._refresh_grid()
                self._show_status(f"Pattern doublé: {self._player._pattern._num_bars} mesures")
            else:
                self._show_status("Impossible de doubler (limite atteinte)")
        elif not ctrl and shift and not alt and key == ord('F'):
            if self._player.halve_pattern():
                self._refresh_grid()
                self._show_status(f"Pattern divisé: {self._player._pattern._num_bars} mesures")
            else:
                self._show_status("Impossible de diviser (1 mesure minimum)")
        # --- Ctrl+Shift+E : choisir ligne + quant et générer le motif ---
        elif ctrl and shift and key == ord('E'):
            self._gen_row_dialog()
        # --- Ctrl+E : appliquer la quant à la ligne courante ---
        elif ctrl and not shift and key == ord('E'):
            self._apply_quant()
        # --- Ctrl+Shift+Q : choisir la valeur de quantize et appliquer au pattern ---
        elif ctrl and shift and key == ord('Q'):
            self._quantize_pattern_dialog()

        # --- Shift+Q : quantiser le pattern courant (valeur par défaut) ---
        elif shift and not ctrl and key == ord('Q'):
            self._quantize_pattern()

        # --- Q : activer / désactiver le mode Note Repeat ---
        elif not ctrl and not shift and not alt and (ukey == ord('q') or key == ord('Q')):
            self._note_repeat = not self._note_repeat
            if self._note_repeat:
                mode = "Ternaire" if self._nr_ternary else "Binaire"
                self._show_status(
                    f"Note Repeat: ON — {mode} — {DrumPlayer.QUANT_LIST[self._nr_rate_idx]}"
                )
            else:
                self._nr_cancel_release()
                self._nr_active_key = None
                self._nr_prev_key   = None
                self._player.stop_note_repeat()
                self._show_status("Note Repeat: OFF")

        # --- Shift+E : décocher toute la ligne ---
        elif shift and not ctrl and key == ord('E'):
            for c in range(self.COLS):
                self._set_cell(self._cur_row, c, False)
            self._show_status(f"Ligne {self._cur_row + 1}: tout décoché")

        # --- E : bascule mode Erase ---
        elif not ctrl and not shift and not alt and (ukey == ord('e') or key == ord('E')):
            now_erasing = self._player.toggle_erase()
            if now_erasing:
                self._show_status("Erase: On")
            elif self._player.replace_recording:
                self._show_status("Erase: Off — Replace Rec: On")
            elif self._player.recording:
                self._show_status("Erase: Off — Rec: On")
            else:
                self._show_status("Erase: Off")

        # --- X / Shift+X : mute pad courant / démuter tous ---
        elif not ctrl and not shift and not alt and (ukey == ord('x') or key == ord('X')):
            muted = self._player.voice_manager.toggle_mute(self._cur_row)
            self._refresh_voice_display(self._cur_row)
            self._show_status(f"Pad {self._cur_row + 1}: Mute {'On' if muted else 'Off'}")
        elif not ctrl and shift and not alt and (ukey == ord('x') or key == ord('X')):
            self._player.voice_manager.set_mute_all(False)
            self._refresh_all_voice_display()
            self._show_status("Tous les Pads: Démutés")

        # --- S / Shift+S : solo pad courant / désolo tous ---
        elif not ctrl and not shift and not alt and (ukey == ord('s') or key == ord('S')):
            soloed = self._player.voice_manager.toggle_solo(self._cur_row)
            self._refresh_voice_display(self._cur_row)
            self._show_status(f"Pad {self._cur_row + 1}: Solo {'On' if soloed else 'Off'}")
        elif not ctrl and shift and not alt and (ukey == ord('s') or key == ord('S')):
            self._player.voice_manager.set_solo_all(False)
            self._refresh_all_voice_display()
            self._show_status("Tous les Pads: Désolés")

        # --- Tab / Shift+Tab : navigation entre widgets principaux ---
        # Les CheckBoxes étant dans l'ordre de tabulation par défaut, Tab navigue
        # cellule par cellule. On l'intercepte pour sauter entre les widgets clés.
        # Ordre : BPM → Volume → Quant → Grille → BPM (et inverse pour Shift+Tab).
        elif key == wx.WXK_TAB:
            order = [self._bpm_ctrl, self._volume_ctrl, self._quant_list, self._pattern_listbox]
            if focused in order:
                idx = order.index(focused)
                if shift:
                    target = self._cells[self._cur_row][self._cur_col] if idx == 0 else order[idx - 1]
                else:
                    target = self._cells[self._cur_row][self._cur_col] if idx == len(order) - 1 else order[idx + 1]
            else:
                target = self._bpm_ctrl if not shift else self._pattern_listbox
            target.SetFocus()

        # --- Flèches : navigation grille ou liste selon le focus ---
        elif key in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_LEFT, wx.WXK_RIGHT):
            if on_quant_list or on_pattern_list:
                event.Skip()   # laisser la ListBox gérer sa propre navigation
            elif on_volume and key in (wx.WXK_UP, wx.WXK_DOWN):
                event.Skip()   # SpinCtrl gère nativement → EVT_SPINCTRL suit
            elif on_bpm and key in (wx.WXK_UP, wx.WXK_DOWN):
                event.Skip()   # SpinCtrl gère nativement → EVT_SPINCTRL suit
            elif on_voice_spin and key in (wx.WXK_UP, wx.WXK_DOWN):
                event.Skip()
            elif key == wx.WXK_UP:
                self._move(-1, 0)
            elif key == wx.WXK_DOWN:
                self._move(1, 0)
            elif key == wx.WXK_LEFT:
                self._move(0, -1)
            else:
                self._move(0, 1)

        # --- Entrée : appliquer quant (ListBox) ou basculer cellule (grille) ---
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if on_quant_list:
                self._apply_quant()
            elif on_pattern_list:
                pass  # la sélection est déjà appliquée via EVT_LISTBOX
            else:
                r, c = self._cur_row, self._cur_col
                new_val = False if shift else not self._cells[r][c].GetValue()
                self._set_cell(r, c, new_val)

        # --- NumPad ---
        elif wx.WXK_NUMPAD1 <= key <= wx.WXK_NUMPAD8:
            if self._note_repeat:
                pad_idx = (key - wx.WXK_NUMPAD1) + self._shift_pad
                if key == self._nr_active_key:
                    # Autorepeat GTK → reset timer uniquement
                    self._nr_arm_release()
                elif self._player._note_repeat_active \
                        and self._nr_active_key is None and key == self._nr_prev_key:
                    # Même pad re-pressé après relâche → stopper NR
                    self._nr_cancel_release()
                    self._nr_prev_key = None
                    self._player.stop_note_repeat()
                    mode = "Ternaire" if self._nr_ternary else "Binaire"
                    self._show_status(
                        f"Note Repeat: ON — {mode} — {DrumPlayer.QUANT_LIST[self._nr_rate_idx]}"
                    )
                else:
                    # Nouveau pad ou NR inactif → jouer + démarrer/switcher NR
                    self._nr_cancel_release()
                    self._nr_active_key = key
                    self._nr_prev_key   = key
                    self._nr_arm_release()
                    self._play(pad_idx)
                    if self._player.recording:
                        bar_idx, step_idx = self._player.record_hit(pad_idx)
                        if bar_idx == 0 and step_idx < self.COLS:
                            self._cells[pad_idx][step_idx].SetValue(True)
                    self._player.start_note_repeat(self._nr_rate_idx, lambda p=pad_idx: p)
                    self._show_status(
                        f"NR: Pad {pad_idx + 1} @ {DrumPlayer.QUANT_LIST[self._nr_rate_idx]}"
                    )
            elif self._player.erasing:
                pad_idx = (key - wx.WXK_NUMPAD1) + self._shift_pad
                result = self._player.erase_hit(pad_idx)
                if result:
                    bar_idx, step_idx = result
                    if bar_idx == 0 and step_idx < self.COLS:
                        self._cells[pad_idx][step_idx].SetValue(False)
            else:
                pad_idx = (key - wx.WXK_NUMPAD1) + self._shift_pad
                self._play(pad_idx)
                if self._player.recording:
                    bar_idx, step_idx = self._player.record_hit(pad_idx)
                    if bar_idx == 0 and step_idx < self.COLS:
                        self._cells[pad_idx][step_idx].SetValue(True)
        elif key == wx.WXK_NUMPAD9:
            last = self._player.last_played_pad
            if last is not None:
                if self._player.erasing:
                    result = self._player.erase_hit(last)
                    if result:
                        bar_idx, step_idx = result
                        if bar_idx == 0 and step_idx < self.COLS:
                            self._cells[last][step_idx].SetValue(False)
                else:
                    self._play(last)
                    if self._player.recording:
                        bar_idx, step_idx = self._player.record_hit(last)
                        if bar_idx == 0 and step_idx < self.COLS:
                            self._cells[last][step_idx].SetValue(True)
        elif key == wx.WXK_NUMPAD0:
            self._note_repeat   = False
            self._nr_active_key = None
            self._nr_prev_key   = None
            self._nr_cancel_release()
            self._player.stop_all()
        elif key == wx.WXK_NUMPAD_ADD:
            self._shift_pad = min(8, self._shift_pad + 8)
            self._show_status(f"ShiftPad: {self._shift_pad + 1}/{self._shift_pad + 8}")
        elif key == wx.WXK_NUMPAD_SUBTRACT:
            self._shift_pad = max(0, self._shift_pad - 8)
            self._show_status(f"ShiftPad: {self._shift_pad + 1}/{self._shift_pad + 8}")

        # --- Raccourcis caractères ---
        # ukey (GetUnicodeKey) est fiable uniquement dans EVT_CHAR, pas dans EVT_CHAR_HOOK
        # (retourne WXK_NONE=0 sur certains GTK). Fallback sur key (GetKeyCode) qui renvoie
        # le code ASCII majuscule de la touche physique, indépendamment du layout pour a-z.
        elif ukey == ord('c') or (not ctrl and not shift and key == ord('C')):
            if self._player.clicking:
                self._player.stop_click()
                self._show_status("Click: Off")
            else:
                self._player.play_click()
                self._show_status("Click: On")
        elif shift and not ctrl and (ukey == ord('p') or key == ord('P')):
            self._player._pattern.gen_pattern(self._player._cur_track)
            self._player._compute_offsets()
            self._refresh_grid()
            self._show_status("Pattern aléatoire généré")
        elif ukey in (ord(' '), ord('p')) or (not ctrl and key in (wx.WXK_SPACE, ord('P'))):
            if self._player.playing:
                self._player.stop_pattern()
                self._show_status("Pattern: Stop")
            else:
                self._player.play_pattern()
                self._show_status("Pattern: Play")
        elif ukey == ord('v') or (not ctrl and not shift and key == ord('V')):
            self._note_repeat   = False
            self._nr_active_key = None
            self._nr_prev_key   = None
            self._nr_cancel_release()
            self._player.stop_all()
            self._show_status("Stop All")
        elif ctrl and not shift and not alt and key == ord('R'):
            self._player.record_pattern_with_count_in()
            n = self._player.count_in_bars
            self._show_status(f"Count-In: {n} mesure{'s' if n > 1 else ''}..." if n else "Rec: On")
        elif not ctrl and shift and not alt and (ukey == ord('r') or key == ord('R')):
            if self._player.replace_recording:
                self._player.stop_record()
                self._show_status("Replace Rec: Off")
            else:
                self._player.start_replace_recording()
                self._show_status("Replace Rec: On")
        elif ukey == ord('r') or (not ctrl and not shift and not alt and key == ord('R')):
            if self._player.recording or self._player._count_in > 0:
                self._player.stop_record()
                self._show_status("Rec: Off")
            else:
                self._player.record_pattern()
                self._show_status("Rec: On")
        # --- Touches 1-9 clavier standard en mode Note Repeat ---
        # GetKeyCode() renvoie le code de position US → fonctionne sur AZERTY sans Shift.
        elif self._note_repeat and not ctrl and not shift and not alt \
                and not on_bpm and not on_volume and not on_voice_spin \
                and not on_quant_list and not on_pattern_list \
                and ord('1') <= key <= ord('9'):
            digit = key - ord('0')   # 1..9
            if digit == 9:
                self._nr_ternary = not self._nr_ternary
                mode = "Ternaire" if self._nr_ternary else "Binaire"
                self._show_status(f"Note Repeat: mode {mode}")
            elif self._nr_ternary and 1 <= digit <= 6:
                self._nr_rate_idx = self.NR_TERNARY[digit - 1]
                self._player.update_nr_rate(self._nr_rate_idx)
                self._show_status(f"NR: {DrumPlayer.QUANT_LIST[self._nr_rate_idx]}")
            elif not self._nr_ternary and 1 <= digit <= 8:
                self._nr_rate_idx = self.NR_BINARY[digit - 1]
                self._player.update_nr_rate(self._nr_rate_idx)
                self._show_status(f"NR: {DrumPlayer.QUANT_LIST[self._nr_rate_idx]}")

        ### Note: Sur GTK+AZERTY, GetKeyCode() renvoie le code US de la position physique
        ### (touche '(' → key=53 comme '5') au lieu du caractère produit (key=40).
        ### GetUnicodeKey() ne corrige pas ce problème. On ajoute key==ord('5') sans
        ### modificateur comme repli AZERTY. La touche ')' échappe à ce bug par hasard.
        elif ukey == ord('(') or key == ord('(') or (not shift and not ctrl and key == ord('5')):
            self._player.set_bpm(self._player.bpm + 5)
            self._update_bpm_display()
        elif ukey == ord(')') or key == ord(')'):
            self._player.set_bpm(self._player.bpm - 5)
            self._update_bpm_display()
        elif ukey == ord('+') or key == ord('+'):
            self._player.set_volume(self._player.volume + 1)
            self._volume_ctrl.SetValue(self._player.volume)
            self._show_status(f"Volume: {self._player.volume}")
        ### Note: même bug AZERTY que '(' → '-' est key=54 ('6') au lieu de key=45.
        ### Les touches non-shiftées aux positions de chiffres renvoient le code US du chiffre.
        ### Les touches shiftées (+, ), ...) fonctionnent via ukey (GetUnicodeKey traduit).
        elif ukey == ord('-') or key == ord('-') or (not shift and not ctrl and key == ord('6')):
            self._player.set_volume(self._player.volume - 1)
            self._volume_ctrl.SetValue(self._player.volume)
            self._show_status(f"Volume: {self._player.volume}")

        else:
            print(f"DEBUG key={key} ukey={ukey} shift={shift} ctrl={ctrl} char={chr(ukey) if ukey > 31 else '?'}")
            event.Skip()
