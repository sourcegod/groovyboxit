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


_APPS = []        # wx.App recréées : gardées (sans référence, elles seraient libérées)


@pytest.fixture(autouse=True)
def wx_app_alive():
    """Une wx.App avant chaque test (Phase 8 étape 17b1) : certains fichiers
    détruisent celle de la session (make_km / teardown, export MIDI) ; les
    tests à vraie fenêtre en recréaient une au passage, si bien qu'en les
    écartant (niveau Intermédiaire) les suivants échouaient (PyNoAppError).
    Chaque test trouve désormais une wx.App, quel que soit l'ordre."""
    import wx
    if wx.GetApp() is None:
        _APPS.append(wx.App(False))
    yield


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


# ---------------------------------------------------------------------------
# Garde-fou des tests lents non marqués (Phase 8 étape 17b1, § 17a T7) :
# --slow-guard (niveau Avancé) signale en fin de suite tout test sans marque
# slow / audio / gui qui a pris au moins SLOW_GUARD_SECS (préparation +
# exécution) — il ralentirait le niveau Intermédiaire sans qu'on le voie.
# ---------------------------------------------------------------------------

SLOW_GUARD_SECS = 0.3
LEVEL_MARKS = ("slow", "audio", "gui")


def pytest_addoption(parser):
    parser.addoption("--slow-guard", action="store_true", default=False,
                     help="signaler les tests non marqués slow / audio / gui de plus de "
                          f"{SLOW_GUARD_SECS} s")


def pytest_configure(config):
    config._slow_guard = {} if config.getoption("--slow-guard") else None
    config._level_marked = set()


def pytest_collection_modifyitems(config, items):
    for item in items:
        if any(item.get_closest_marker(m) for m in LEVEL_MARKS):
            config._level_marked.add(item.nodeid)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    guard = item.config._slow_guard
    if guard is not None and call.when in ("setup", "call") \
            and item.nodeid not in item.config._level_marked:
        guard[item.nodeid] = guard.get(item.nodeid, 0.0) + call.duration


def pytest_terminal_summary(terminalreporter, config):
    guard = getattr(config, "_slow_guard", None)
    if not guard:
        return
    slow = sorted(((secs, nid) for nid, secs in guard.items() if secs >= SLOW_GUARD_SECS),
                  reverse=True)
    if not slow:
        return
    terminalreporter.section("Tests lents non marqués (slow / audio / gui)")
    for secs, nid in slow:
        terminalreporter.write_line(f"{secs:5.2f} s  {nid}")
    terminalreporter.write_line(
        f"{len(slow)} test(s) de plus de {SLOW_GUARD_SECS} s sans marque : les marquer, "
        "ou les accélérer (docs/SPECS.md, Tests).")
