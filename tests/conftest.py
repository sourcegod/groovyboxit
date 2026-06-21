import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture(scope="session", autouse=True)
def wx_app():
    """Une seule wx.App pour toute la session de tests."""
    import wx
    app = wx.App(False)
    yield app
    app.Destroy()
