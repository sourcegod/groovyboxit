import json
import os
import wx
from sound_manager import SoundManager
from drum_player import DrumPlayer
from pattern import Pattern


def _load_keyboard_help():
    path = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "shortcuts.md")
    )
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return f"(Fichier d'aide introuvable : {path})"

_KEYBOARD_HELP = _load_keyboard_help()


class KeyboardHelpDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Aide clavier")

        text = wx.TextCtrl(
            self,
            value=_KEYBOARD_HELP,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_LEFT | wx.HSCROLL,
            size=(420, 460),
        )
        text.SetFont(wx.Font(
            10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL
        ))

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(self, wx.ID_OK, "Fermer")
        ok_btn.SetDefault()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.Realize()

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(text,      1, wx.EXPAND | wx.ALL, 6)
        vbox.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        ok_btn.SetFocus()


class GenRowDialog(wx.Dialog):
    def __init__(self, parent, cur_row, cur_quant_idx, num_rows=16):
        super().__init__(parent, title="Générer un motif sur une ligne")

        row_label = wx.StaticText(self, label="Ligne :")
        self._row_ctrl = wx.SpinCtrl(self, min=1, max=num_rows, size=(70, -1))

        quant_label = wx.StaticText(self, label="Valeur de quantisation :")
        self._quant_list = wx.ListBox(
            self,
            choices=DrumPlayer.QUANT_LIST,
            style=wx.LB_SINGLE,
        )
        self._quant_list.SetSelection(cur_quant_idx)

        ok_btn     = wx.Button(self, wx.ID_OK,     "Ok")
        apply_btn  = wx.Button(self, wx.ID_APPLY,  "Appliquer")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        ok_btn.SetDefault()
        apply_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_APPLY))

        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(apply_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()

        row_box = wx.BoxSizer(wx.HORIZONTAL)
        row_box.Add(row_label,      0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row_box.Add(self._row_ctrl, 0)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(row_box,          0, wx.ALL, 6)
        vbox.Add(quant_label,      0, wx.LEFT | wx.RIGHT, 6)
        vbox.Add(self._quant_list, 1, wx.EXPAND | wx.ALL, 6)
        vbox.Add(btn_sizer,        0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._row_ctrl.SetValue(cur_row + 1)  # après Fit() : GTK réinitialise la valeur au layout
        self._row_ctrl.SetFocus()

    def get_row(self):
        return self._row_ctrl.GetValue() - 1  # 0-based

    def get_quant_idx(self):
        sel = self._quant_list.GetSelection()
        return sel if sel != wx.NOT_FOUND else 7


class QuantizeDialog(wx.Dialog):
    def __init__(self, parent, cur_idx):
        super().__init__(parent, title="Quantisation du pattern")

        list_label = wx.StaticText(self, label="Valeur de quantisation :")
        self._list = wx.ListBox(
            self,
            choices=DrumPlayer.QUANT_LIST,
            style=wx.LB_SINGLE,
        )
        self._list.SetSelection(cur_idx)

        ok_btn     = wx.Button(self, wx.ID_OK,     "Ok")
        apply_btn  = wx.Button(self, wx.ID_APPLY,  "Appliquer")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        ok_btn.SetDefault()
        apply_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_APPLY))

        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(apply_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(list_label,  0, wx.ALL, 6)
        vbox.Add(self._list,  1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(btn_sizer,   0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._list.SetFocus()

    def get_selection(self):
        return self._list.GetSelection()


class SavePatternDialog(wx.Dialog):
    def __init__(self, parent, cur_idx, cur_name=""):
        super().__init__(parent, title="Enregistrer le pattern")

        list_label = wx.StaticText(self, label="Numéro de pattern :")
        self._list = wx.ListBox(
            self,
            choices=[f"{i:02d}" for i in range(1, 100)],
            style=wx.LB_SINGLE,
        )
        self._list.SetSelection(cur_idx)

        name_label = wx.StaticText(self, label="Nom (optionnel) :")
        self._name_ctrl = wx.TextCtrl(self, value=cur_name)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(self, wx.ID_OK, "Ok")
        ok_btn.SetDefault()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL, "Annuler"))
        btn_sizer.Realize()

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(list_label,      0, wx.ALL, 6)
        vbox.Add(self._list,      1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(name_label,      0, wx.LEFT | wx.RIGHT, 6)
        vbox.Add(self._name_ctrl, 0, wx.EXPAND | wx.ALL, 6)
        vbox.Add(btn_sizer,       0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._list.SetFocus()

    def get_selection(self):
        return self._list.GetSelection()

    def get_name(self):
        return self._name_ctrl.GetValue().strip()


class MainWindow(wx.Frame):
    ROWS = 16
    COLS = 16

    def __init__(self):
        super().__init__(None, title="GroovyboxIt")
        self._cur_row = 0
        self._cur_col = 0
        self._cells = []
        self._shift_pad     = 0   # 0 → pads 1-8 (indices 0-7), 8 → pads 9-16 (indices 8-15)
        self._last_pad      = None
        self._autoplay      = True
        self._note_repeat      = False
        self._nr_active_key    = None   # touche courante "tenue" (effacée par timer)
        self._nr_prev_key      = None   # touche qui a démarré le repeat en cours
        self._nr_release_timer = None
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

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(hbox, 0, wx.EXPAND | wx.ALL, 4)
        vbox.Add(grid, 1, wx.EXPAND)
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
            self._player.float_offsets[r] = [
                float(c) for c in range(self.COLS) if self._player._pattern._curpattern[self._player._cur_track][r][0][c]
            ]

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
        self._cur_pattern_idx = idx
        self._player._pattern.load_pattern(self._pattern_list[idx]._curpattern)
        self._player._compute_offsets()
        self._refresh_grid()
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
        self._last_pad = idx

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
                self._show_status("Note Repeat: ON")
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
                nr_idx = (key - wx.WXK_NUMPAD1) + (8 if self._shift_pad else 0)
                if nr_idx >= len(DrumPlayer.QUANT_LIST):
                    pass   # hors plage (1/128+), ignorer
                elif key == self._nr_active_key:
                    # Même touche encore tenue → autorepeat GTK → reset timer, ignorer
                    self._nr_arm_release()
                elif self._player._note_repeat_active \
                        and self._nr_active_key is None and key == self._nr_prev_key:
                    # Touche relâchée (timer a vidé active_key) + même touche re-pressée → toggle off
                    self._nr_cancel_release()
                    self._nr_prev_key = None
                    self._player.stop_note_repeat()
                    self._show_status("Note Repeat: ON")
                else:
                    # Nouvelle touche ou pas de repeat actif → démarrer / changer le rythme
                    self._nr_cancel_release()
                    self._nr_active_key = key
                    self._nr_prev_key   = key
                    self._nr_arm_release()
                    self._player.start_note_repeat(nr_idx, lambda: self._cur_row)
                    self._show_status(f"Note Repeat: {DrumPlayer.QUANT_LIST[nr_idx]}")
            else:
                self._play((key - wx.WXK_NUMPAD1) + self._shift_pad)
        elif key == wx.WXK_NUMPAD9:
            if self._last_pad is not None:
                self._play(self._last_pad)
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
