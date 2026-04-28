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

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(self._status_ctrl, 1, wx.EXPAND | wx.RIGHT, 4)
        hbox.Add(self._bpm_ctrl, 0, wx.EXPAND)

        grid = wx.GridSizer(self.ROWS, self.COLS, 2, 2)
        for r in range(self.ROWS):
            row = []
            for c in range(self.COLS):
                cb = wx.CheckBox(panel, label=f"Pad{r + 1}/{c + 1}")
                cb.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
                cb.Bind(wx.EVT_CHAR, self._on_char)
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

    def _update_bpm_display(self):
        self._bpm_ctrl.SetValue(f"BPM: {self._player.bpm}")

    def _show_status(self, msg):
        self._status_ctrl.SetValue(msg)
        self._status_ctrl.SetFocus()
        wx.CallAfter(self._cells[self._cur_row][self._cur_col].SetFocus)

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

    def _on_key_down(self, event):
        # Note: Use event.GetKeyCode() function to filtering events, instead the constants event.keycode.
        key = event.GetKeyCode()
        controlDown = event.ControlDown()
        shiftDown = event.ShiftDown()
        altDown = event.AltDown()
        print(f"on_key_down, Keycode: {key}")
        # print("\a")
        """
        # DEBUG
        if controlDown or shiftDown or altDown:
            print("\a")
        """

        """
        # Note: (wx.WXK_CONTROL, wx.WXK_SHIFT, wx.WXK_ALT)
        # Do not work on Linux
        # Use instead: event.ControlDown(), event.ShiftDown(), event.AltDown() functions.
        print("a")
        """

        # if controlDown:    
        if controlDown and key == ord('D'): # Ctrl+D
            self._player.load_pattern([[False] * self.COLS for _ in range(self.ROWS)])
            self._refresh_grid()
            self._show_status("Pattern réinitialisé")

        elif controlDown and key == ord('P'): # Ctrl+P
            self._player.load_pattern(_build_pattern_01())
            self._refresh_grid()
            self._show_status("Pattern initial chargé")

        elif controlDown and key == ord('E'): # Ctrl+E
            for c in range(self.COLS):
                self._set_cell(self._cur_row, c, True)
            self._show_status(f"Ligne {self._cur_row + 1}: tout coché")
        elif shiftDown and key == ord('E'): # Shift+E
            for c in range(self.COLS):
                self._set_cell(self._cur_row, c, False)
            self._show_status(f"Ligne {self._cur_row + 1}: tout décoché")

        elif key == wx.WXK_UP:
            self._move(-1, 0)
        elif key == wx.WXK_DOWN:
            self._move(1, 0)
        elif key == wx.WXK_LEFT:
            self._move(0, -1)
        elif key == wx.WXK_RIGHT:
            self._move(0, 1)
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            r, c = self._cur_row, self._cur_col
            new_val = False if event.ShiftDown() else not self._cells[r][c].GetValue()
            self._set_cell(r, c, new_val)
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
        else:
            event.Skip()

    def _on_char(self, event):
        key = event.GetKeyCode()
        # DEBUG
        print(f"On_char, Keycode: {key}")
        # print("\a")
        
        if key == ord('c'):
            if self._player.clicking:
                self._player.stop_click()
                self._show_status("Click: Off")
            else:
                self._player.play_click()
                self._show_status("Click: On")
        elif key == ord(' ') or key == ord('p'): # space, p
            if self._player.playing:
                self._player.stop_pattern()
                self._show_status("Pattern: Stop")
            else:
                self._player.play_pattern()
                self._show_status("Pattern: Play")

        elif key == ord('v'):
            self._player.stop_all()
            self._show_status("Stop All")
        elif key == ord('('):
            self._player.set_bpm(self._player.bpm + 5)
            self._update_bpm_display()
        elif key == ord(')'):
            self._player.set_bpm(self._player.bpm - 5)
            self._update_bpm_display()
        else:
            event.Skip()

