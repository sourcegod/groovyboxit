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


@pytest.fixture(scope="session", autouse=True)
def isolated_preferences(tmp_path_factory):
    """Préférences de l'utilisateur hors de ~/.config pendant les tests
    (Phase 8 étape 10b1) : un fichier absent, dans un dossier temporaire."""
    path = tmp_path_factory.mktemp("prefs") / "preferences.json"
    old = os.environ.get("GROOVYBOXIT_PREFS")
    os.environ["GROOVYBOXIT_PREFS"] = str(path)
    yield path
    if old is None:
        os.environ.pop("GROOVYBOXIT_PREFS", None)
    else:
        os.environ["GROOVYBOXIT_PREFS"] = old
