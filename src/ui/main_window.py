import wx


class MainWindow(wx.Frame):
    ROWS = 16
    COLS = 16

    def __init__(self):
        super().__init__(None, title="GrooveboxIt")
        self._cur_row = 0
        self._cur_col = 0
        self._cells = []
        self._build_ui()
        self.Centre()

    def _build_ui(self):
        panel = wx.Panel(self)
        grid = wx.GridSizer(self.ROWS, self.COLS, 2, 2)

        for r in range(self.ROWS):
            row = []
            for c in range(self.COLS):
                cb = wx.CheckBox(panel, label=f"{r + 1}/{c + 1}")
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
        self._cells[r][c].SetFocus()

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
        else:
            event.Skip()
