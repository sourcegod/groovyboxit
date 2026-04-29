import os
import wx
from sound_manager import SoundManager
from drum_player import DrumPlayer


def _build_pattern_01():
    p = [[False] * 16 for _ in range(16)]
    p[0][0] = p[0][4] = p[0][8] = p[0][12] = True
    p[4][2] = p[4][6] = p[4][10] = True
    p[5][1:4] = [True] * 3
    p[5][5:8] = [True] * 3
    p[5][9:12] = [True] * 3
    p[5][13:16] = [True] * 3
    p[7][15] = True
    p[8][14] = True
    p[9][13] = True
    p[10][0] = True
    return p


class MainWindow(wx.Frame):
    ROWS = 16
    COLS = 16
    _QUANT = ["1/1", "1/2", "1/4", "1/8", "1/16"]
    _QUANT_STEP = {"1/1": 16, "1/2": 8, "1/4": 4, "1/8": 2, "1/16": 1}

    def __init__(self):
        super().__init__(None, title="GroovyboxIt")
        self._cur_row = 0
        self._cur_col = 0
        self._cells = []
        self._shift_pad = 0   # 0 → pads 1-8 (indices 0-7), 8 → pads 9-16 (indices 8-15)
        self._last_pad = None
        self._autoplay = True
        self._init_sound()
        self._build_ui()
        # EVT_CHAR_HOOK remonte la hiérarchie depuis n'importe quel widget natif
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Centre()

    def _init_sound(self):
        ui_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.dirname(os.path.dirname(ui_dir))
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

        self._bpm_ctrl = wx.TextCtrl(
            panel,
            style=wx.TE_READONLY | wx.TE_CENTER | wx.BORDER_SIMPLE,
            size=(80, -1),
        )

        vol_label = wx.StaticText(panel, label="Vol:")
        self._volume_ctrl = wx.SpinCtrl(panel, min=0, max=100, initial=self._player.volume, size=(70, -1))
        self._volume_ctrl.Bind(wx.EVT_SPINCTRL, self._on_volume_spin)

        quant_label = wx.StaticText(panel, label="Quant:")
        self._quant_list = wx.ListBox(
            panel,
            choices=self._QUANT,
            style=wx.LB_SINGLE,
        )
        self._quant_list.SetSelection(len(self._QUANT) - 1)  # défaut: 1/16
        self._quant_list.Bind(wx.EVT_LISTBOX, self._on_quant_select)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(self._status_ctrl, 1, wx.EXPAND | wx.RIGHT, 4)
        hbox.Add(self._bpm_ctrl, 0, wx.EXPAND | wx.RIGHT, 8)
        hbox.Add(vol_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox.Add(self._volume_ctrl, 0, wx.EXPAND | wx.RIGHT, 8)
        hbox.Add(quant_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        hbox.Add(self._quant_list, 0, wx.EXPAND)

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

        self._update_bpm_display()
        self.Fit()
        self._cells[0][0].SetFocus()

    def _set_cursor(self, row, col):
        self._cur_row = row
        self._cur_col = col

    def _set_cell(self, row, col, value):
        self._cells[row][col].SetValue(value)
        self._player.pattern[row][col] = value

    def _on_checkbox(self, row, col):
        self._player.pattern[row][col] = self._cells[row][col].GetValue()

    def _refresh_grid(self):
        for r in range(self.ROWS):
            for c in range(self.COLS):
                self._cells[r][c].SetValue(self._player.pattern[r][c])

    def _on_quant_select(self, event):
        self._apply_quant()

    def _apply_quant(self):
        quant = self._QUANT[self._quant_list.GetSelection()]
        step = self._QUANT_STEP[quant]
        for c in range(self.COLS):
            self._set_cell(self._cur_row, c, False)
        for c in range(0, self.COLS, step):
            self._set_cell(self._cur_row, c, True)
        self._show_status(f"Ligne {self._cur_row + 1}: {quant} coché")

    def _on_volume_spin(self, event):
        vol = self._volume_ctrl.GetValue()
        self._player.set_volume(vol)
        self._show_status(f"Volume: {vol}")

    def _update_bpm_display(self):
        self._bpm_ctrl.SetValue(f"BPM: {self._player.bpm}")

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

    def _on_char_hook(self, event):
        key  = event.GetKeyCode()
        ukey = event.GetUnicodeKey()   # caractère traduit (layout-aware)
        ctrl  = event.ControlDown()
        shift = event.ShiftDown()
        on_list   = (wx.Window.FindFocus() == self._quant_list)
        on_bpm    = (wx.Window.FindFocus() == self._bpm_ctrl)
        on_volume = (wx.Window.FindFocus() == self._volume_ctrl)

        # --- Raccourcis Ctrl ---
        if ctrl and key == ord('D'):
            self._player.load_pattern([[False] * self.COLS for _ in range(self.ROWS)])
            self._refresh_grid()
            self._show_status("Pattern réinitialisé")
        elif ctrl and key == ord('P'):
            self._player.load_pattern(_build_pattern_01())
            self._refresh_grid()
            self._show_status("Pattern initial chargé")
        elif ctrl and key == ord('E'):
            self._apply_quant()

        # --- Shift+E : décocher toute la ligne ---
        elif shift and not ctrl and key == ord('E'):
            for c in range(self.COLS):
                self._set_cell(self._cur_row, c, False)
            self._show_status(f"Ligne {self._cur_row + 1}: tout décoché")

        # --- Flèches : navigation grille ou liste selon le focus ---
        elif key in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_LEFT, wx.WXK_RIGHT):
            if on_list:
                event.Skip()   # laisser la ListBox gérer sa propre navigation
            elif on_volume and key in (wx.WXK_UP, wx.WXK_DOWN):
                event.Skip()   # SpinCtrl gère nativement → EVT_SPINCTRL suit
            elif on_bpm and key in (wx.WXK_UP, wx.WXK_DOWN):
                delta = 1 if key == wx.WXK_UP else -1
                self._player.set_bpm(self._player.bpm + delta)
                self._update_bpm_display()
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
            if on_list:
                self._apply_quant()
            else:
                r, c = self._cur_row, self._cur_col
                new_val = False if shift else not self._cells[r][c].GetValue()
                self._set_cell(r, c, new_val)

        # --- NumPad ---
        elif wx.WXK_NUMPAD1 <= key <= wx.WXK_NUMPAD8:
            self._play((key - wx.WXK_NUMPAD1) + self._shift_pad)
        elif key == wx.WXK_NUMPAD9:
            if self._last_pad is not None:
                self._play(self._last_pad)
        elif key == wx.WXK_NUMPAD0:
            self._player.stop_all()
        elif key == wx.WXK_NUMPAD_ADD:
            self._shift_pad = min(8, self._shift_pad + 8)
            self._show_status(f"ShiftPad: {self._shift_pad + 1}/{self._shift_pad + 8}")
        elif key == wx.WXK_NUMPAD_SUBTRACT:
            self._shift_pad = max(0, self._shift_pad - 8)
            self._show_status(f"ShiftPad: {self._shift_pad + 1}/{self._shift_pad + 8}")

        # --- Raccourcis caractères (ukey = caractère traduit, indépendant du layout) ---
        elif ukey == ord('c'):
            if self._player.clicking:
                self._player.stop_click()
                self._show_status("Click: Off")
            else:
                self._player.play_click()
                self._show_status("Click: On")
        elif ukey in (ord(' '), ord('p')):
            if self._player.playing:
                self._player.stop_pattern()
                self._show_status("Pattern: Stop")
            else:
                self._player.play_pattern()
                self._show_status("Pattern: Play")
        elif ukey == ord('v'):
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
