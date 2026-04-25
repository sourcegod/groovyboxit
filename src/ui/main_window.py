import os
import wx
from sound_manager import SoundManager


class MainWindow(wx.Frame):
    ROWS = 16
    COLS = 16

    def __init__(self):
        super().__init__(None, title="GrooveboxIt")
        self._cur_row = 0
        self._cur_col = 0
        self._cells = []
        self._shift_pad = 0   # 0 → pads 1-8 (indices 0-7), 8 → pads 9-16 (indices 8-15)
        self._last_pad = None
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

    def _build_ui(self):
        panel = wx.Panel(self)
        grid = wx.GridSizer(self.ROWS, self.COLS, 2, 2)

        for r in range(self.ROWS):
            row = []
            for c in range(self.COLS):
                cb = wx.CheckBox(panel, label=f"Pad{r + 1}/{c + 1}")
                cb.Bind(wx.EVT_KEY_DOWN, self._on_key)
                cb.Bind(wx.EVT_SET_FOCUS, lambda e, r=r, c=c: self._set_cursor(r, c))
                grid.Add(cb, 0, wx.EXPAND)
                row.append(cb)
            self._cells.append(row)

        panel.SetSizer(grid)
        self.Fit()
        self._cells[0][0].SetFocus()

    def _set_cursor(self, row, col):
        self._cur_row = row
        self._cur_col = col

    def _move(self, dr, dc):
        r = max(0, min(self.ROWS - 1, self._cur_row + dr))
        c = max(0, min(self.COLS - 1, self._cur_col + dc))
        if r == self._cur_row and c == self._cur_col:
            wx.Bell()
        self._cells[r][c].SetFocus()

    def _play(self, idx):
        self._snd.play_sound(idx)
        self._last_pad = idx

    def _on_key(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_UP:
            self._move(-1, 0)
        elif key == wx.WXK_DOWN:
            self._move(1, 0)
        elif key == wx.WXK_LEFT:
            self._move(0, -1)
        elif key == wx.WXK_RIGHT:
            self._move(0, 1)
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            cb = self._cells[self._cur_row][self._cur_col]
            if event.ShiftDown():
                cb.SetValue(False)
            else:
                cb.SetValue(not cb.GetValue())
        elif wx.WXK_NUMPAD1 <= key <= wx.WXK_NUMPAD8:
            self._play((key - wx.WXK_NUMPAD1) + self._shift_pad)
        elif key == wx.WXK_NUMPAD9:
            if self._last_pad is not None:
                self._play(self._last_pad)
        elif key == wx.WXK_NUMPAD_ADD:
            self._shift_pad = min(8, self._shift_pad + 8)
        elif key == wx.WXK_NUMPAD_SUBTRACT:
            self._shift_pad = max(0, self._shift_pad - 8)
        else:
            event.Skip()
