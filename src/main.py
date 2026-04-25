import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import wx
from ui.main_window import MainWindow


def main():
    app = wx.App(False)
    frame = MainWindow()
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
