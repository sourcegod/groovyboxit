#python3
"""
    File: tests/test_menukeys.py
    Paquet autonome menukeys (Phase 9 étape 2c1, docs/DESIGN.md § Phase 9
    étape 2a, avenant 2b2) :
    - autonomie (aucun import de l'appli) ; title_letter ; keys ;
    - AltState : Alt seul, autre touche, AltGr, Ctrl+Alt, relâchement sans
      appui, perte du focus (Alt+Tab), Alt droit, répétition ;
    - MenuKeys sans GTK : lettres (titres, letters, taken), handle_key,
      Alt seul selon la fenêtre (active, inactive, détruite) ;
    - fenêtre de démonstration affichée (gui, sous Xvfb) : raccourcis
      affichés mais non déclenchés par GTK, Alt seul ouvre et referme,
      Alt+F4, AltGr, Alt+Tab, fenêtre inactive : rien ; Alt+lettre et
      alternance menu ouvert, Alt+W, lettre prise, F10, Échap de sous-menu,
      clavier et menus de la démonstration.
    Les touches ne passent jamais par le vrai clavier : envoyées aux
    fenêtres et menus GTK par gtk_widget_event.
    Date: Sun, 22/11/2026
    Author: Coolbrother
"""
import ast
import ctypes
import os
import time

import pytest
import wx

import menukeys
from menukeys import gtk_menu, keys
from menukeys.gtk_menu import (AltState, GDK_FOCUS_CHANGE, GDK_KEY_PRESS,
                               GDK_KEY_RELEASE, GDK_MOD1_MASK, GDK_CONTROL_MASK)

PKG = os.path.join(os.path.dirname(__file__), "..", "src", "menukeys")
ALT_L, ALT_R, ALTGR, F4, ESC = 0xffe9, 0xffea, 0xfe03, 0xffc1, 0xff1b


# ----------------------------------------------------------------------
# Autonomie, lettres des titres, raccourcis écrits
# ----------------------------------------------------------------------

def test_package_imports_nothing_from_the_app():
    allowed = {"wx", "ctypes"}
    for name in sorted(os.listdir(PKG)):
        if not name.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(PKG, name), encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root in allowed | {"menukeys"}, (name, alias.name)
            elif isinstance(node, ast.ImportFrom):
                assert node.level > 0 or node.module.split(".")[0] in allowed | {"menukeys"}, \
                    (name, node.module)


def test_package_exports():
    for name in ("enable", "MenuKeys", "key_event", "accel_of", "gtk_accel", "title_letter"):
        assert hasattr(menukeys, name), name


@pytest.mark.parametrize("label, letter", [
    ("&Fichier", "F"), ("Pis&te", "T"), ("Optio&ns", "N"), ("Fenêtres", None),
    ("R&&D", None), ("R&&&D", "D"), ("Fin&", None), ("&aide", "A"), ("", None),
])
def test_title_letter(label, letter):
    assert menukeys.title_letter(label) == letter


@pytest.mark.parametrize("accel", ["Ctrl+S", "Ctrl+Shift+S", "Alt+F4", "F10", "G", "Alt+4"])
def test_keys_round_trip(accel):
    assert keys.accel_of(keys.key_event(accel)) == accel


def test_keys_gtk_syntax():
    assert keys.gtk_accel("Ctrl+Shift+S") == "<Control><Shift>s"
    assert keys.gtk_accel("PageDown") == "Page_Down"
    assert keys.gtk_accel("Espace") == "space"
    assert gtk_menu.gtk_accel is keys.gtk_accel                 # même fonction


# --- Touches nommées (GroovyboxIt, Phase 9 étapes 3b1 et 3b3) ------------

@pytest.mark.parametrize("accel, code, uni, gtk", [
    ("Haut", wx.WXK_UP, 0, "Up"), ("Ctrl+Bas", wx.WXK_DOWN, 0, "<Control>Down"),
    ("Alt+Gauche", wx.WXK_LEFT, 0, "<Alt>Left"), ("Droite", wx.WXK_RIGHT, 0, "Right"),
    ("Suppr", wx.WXK_DELETE, 127, "Delete"), ("Shift+Suppr", wx.WXK_DELETE, 127, "<Shift>Delete"),
    ("Début", wx.WXK_HOME, 0, "Home"), ("Alt+Fin", wx.WXK_END, 0, "<Alt>End"),
    ("Ctrl+Retour arrière", wx.WXK_BACK, 8, "<Control>BackSpace"),
    ("Num 0", wx.WXK_NUMPAD0, 0, "KP_0"), ("Ctrl+Num 8", wx.WXK_NUMPAD8, 0, "<Control>KP_8"),
    ("(", ord("("), ord("("), "parenleft"), (")", ord(")"), ord(")"), "parenright"),
])
def test_named_keys(accel, code, uni, gtk):
    evt = keys.key_event(accel)
    assert (evt.GetKeyCode(), evt.GetUnicodeKey()) == (code, uni)
    assert keys.gtk_accel(accel) == gtk
    if accel not in ("(", ")"):                    # accel_of : lettres, chiffres, nommées
        assert keys.accel_of(evt) == accel


def test_gtk_parses_every_named_key():
    """Chaque nom donne un raccourci que GTK sait afficher (keyval non nul)."""
    if not gtk_menu.available():
        pytest.skip("GTK seulement")
    g, _gl = gtk_menu._lib()
    g.gtk_accelerator_parse.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint),
                                        ctypes.POINTER(ctypes.c_int)]
    for name in list(keys._GTK_KEYS) + ["Ctrl+S", "F10"]:
        key, mods = ctypes.c_uint(), ctypes.c_int()
        g.gtk_accelerator_parse(keys.gtk_accel(name).encode(), ctypes.byref(key),
                                ctypes.byref(mods))
        assert key.value, name


# ----------------------------------------------------------------------
# AltState : Alt seul (A1-A4)
# ----------------------------------------------------------------------

def _feed(state, *events):
    """Événements (type, touche, modificateurs) ; rend les déclenchements."""
    return [state.feed(*e) for e in events]


def test_alt_alone_fires_on_release():
    st = AltState()
    assert _feed(st, (GDK_KEY_PRESS, ALT_L, 0), (GDK_KEY_RELEASE, ALT_L, GDK_MOD1_MASK)) \
        == [False, True]
    assert not st.armed


def test_right_alt_too():
    assert _feed(AltState(), (GDK_KEY_PRESS, ALT_R, 0), (GDK_KEY_RELEASE, ALT_R, 0))[-1]


def test_autorepeat_of_alt_stays_armed():
    st = AltState()
    assert _feed(st, (GDK_KEY_PRESS, ALT_L, 0), (GDK_KEY_PRESS, ALT_L, GDK_MOD1_MASK),
                 (GDK_KEY_RELEASE, ALT_L, GDK_MOD1_MASK))[-1]


def test_other_key_while_alt_held_disarms():
    st = AltState()
    out = _feed(st, (GDK_KEY_PRESS, ALT_L, 0), (GDK_KEY_PRESS, ord("x"), GDK_MOD1_MASK),
                (GDK_KEY_RELEASE, ord("x"), GDK_MOD1_MASK),
                (GDK_KEY_RELEASE, ALT_L, GDK_MOD1_MASK))
    assert out == [False] * 4


def test_altgr_is_not_alt():
    assert _feed(AltState(), (GDK_KEY_PRESS, ALTGR, 0), (GDK_KEY_RELEASE, ALTGR, 0)) \
        == [False, False]


def test_ctrl_alt_does_not_arm():
    assert not _feed(AltState(), (GDK_KEY_PRESS, ALT_L, GDK_CONTROL_MASK),
                     (GDK_KEY_RELEASE, ALT_L, GDK_CONTROL_MASK | GDK_MOD1_MASK))[-1]


def test_release_without_press_does_nothing():
    """Retour par Alt+Tab : le relâchement arrive sans l'appui (A4)."""
    assert not AltState().feed(GDK_KEY_RELEASE, ALT_L, GDK_MOD1_MASK)


def test_focus_lost_while_alt_held_disarms():
    """Alt+Tab : Tab va au gestionnaire de fenêtres, la fenêtre perd le
    focus ; au retour, le relâchement d'Alt ne doit rien ouvrir (A4)."""
    st = AltState()
    out = _feed(st, (GDK_KEY_PRESS, ALT_L, 0), (GDK_FOCUS_CHANGE,),
                (GDK_KEY_RELEASE, ALT_L, GDK_MOD1_MASK))
    assert out == [False, False, False]


def test_new_alt_after_a_disarm_arms_again():
    st = AltState()
    _feed(st, (GDK_KEY_PRESS, ALT_L, 0), (GDK_KEY_PRESS, ord("x"), GDK_MOD1_MASK),
          (GDK_KEY_RELEASE, ALT_L, GDK_MOD1_MASK))
    assert _feed(st, (GDK_KEY_PRESS, ALT_L, 0), (GDK_KEY_RELEASE, ALT_L, GDK_MOD1_MASK))[-1]


# ----------------------------------------------------------------------
# MenuKeys sans GTK : lettres, handle_key, Alt seul selon la fenêtre
# ----------------------------------------------------------------------

class _Bar:
    def __init__(self, labels):
        self.labels = labels

    def GetMenuCount(self):
        return len(self.labels)

    def GetMenuLabel(self, i):
        return self.labels[i]


class _Frame:
    def __init__(self, labels=("&Fichier", "&Edition", "&Affichage", "Fenêtre", "&Aide")):
        self.bar = _Bar(list(labels))
        self.active, self.deleting = True, False

    def GetMenuBar(self):
        return self.bar

    def IsActive(self):
        return self.active

    def IsBeingDeleted(self):
        return self.deleting

    def __bool__(self):
        return True


@pytest.fixture
def no_gtk(monkeypatch):
    monkeypatch.setattr(gtk_menu, "available", lambda: False)


def test_letters_from_titles_extra_and_taken(no_gtk):
    frame = _Frame()
    mk = menukeys.enable(frame, letters={3: "w"}, taken="e")
    assert frame._menukeys is mk
    assert mk.letters == {"F", "A", "W"}                       # E prise, W ajoutée


def test_extra_letter_can_be_taken(no_gtk):
    mk = menukeys.enable(_Frame(), letters={3: "W"}, taken=("W",))
    assert "W" not in mk.letters


def test_open_menu_alternates_itself(no_gtk, monkeypatch):
    """Essai de GroovyboxIt 3b1 : l'alternance est calculée par le paquet
    (menu suivant de celui qui est ouvert) et chaque menu ouvert comme par
    F10 (open_item), jamais par l'alternance de GTK."""
    frame = _Frame(("&Fichier", "&Affichage", "E&ffets", "&Aide", "Fenêtre"))
    mk = menukeys.enable(frame, letters={4: "A"})
    opened, now = [], []
    monkeypatch.setattr(gtk_menu, "open_item", lambda bar, i: opened.append(i) or True)
    monkeypatch.setattr(gtk_menu, "activate_mnemonic", lambda *a: pytest.fail("GTK"))
    monkeypatch.setattr(mk, "open_menus", lambda: now)
    for expected in ([], [1], [3], [4], [2]):
        now[:] = expected
        assert mk.open_menu("a")
    assert opened == [1, 3, 4, 1, 1]          # fermée → 1 ; 1 → 3 ; 3 → 4 ; 4 → 1 ; autre → 1
    opened.clear()
    now[:] = [0]
    assert mk.open_menu("F") and opened == [2]           # Fichier ouvert : Effets


def test_open_menu_refuses_other_letters(no_gtk):
    mk = menukeys.enable(_Frame(), taken="E")
    assert mk.open_menu("x") is False and mk.open_menu("e") is False
    assert mk.open_menu("") is False


@pytest.fixture
def spied(no_gtk, monkeypatch):
    mk = menukeys.enable(_Frame(), letters={3: "W"})
    seen = []
    monkeypatch.setattr(mk, "open_menu", lambda l: seen.append(l) or True)
    monkeypatch.setattr(mk, "open_first", lambda: seen.append("first") or True)
    monkeypatch.setattr(mk, "close", lambda: seen.append("close"))
    return mk, seen


def test_handle_key_alt_letter_and_f10(spied):
    mk, seen = spied
    assert mk.handle_key(keys.key_event("Alt+A"))
    assert mk.handle_key(keys.key_event("F10"))
    assert seen == ["a", "first"]


@pytest.mark.parametrize("accel", ["Ctrl+Alt+F", "Alt+Shift+F", "Alt+4", "Ctrl+F10",
                                   "Shift+F10", "F", "Ctrl+S", "Espace"])
def test_handle_key_leaves_other_keys(spied, accel):
    mk, seen = spied
    assert not mk.handle_key(keys.key_event(accel))
    assert seen == []


def test_alt_alone_opens_only_an_active_window(spied):
    mk, seen = spied
    mk._alt_alone()
    mk.frame.active = False
    mk._alt_alone()
    mk.frame.active, mk.frame.deleting = True, True
    mk._alt_alone()
    assert seen == ["first"]


def test_alt_alone_in_a_menu_closes(spied):
    mk, seen = spied
    mk._alt_alone_in_menu()
    mk.frame.deleting = True
    mk._alt_alone_in_menu()
    assert seen == ["close"]


def test_without_gtk_nothing_breaks(no_gtk):
    mk = menukeys.enable(_Frame())
    assert mk.open_menus() == []
    assert mk.open_menu("f") is False                         # GTK absent


# ----------------------------------------------------------------------
# Fenêtre de démonstration affichée (GTK, Xvfb)
# ----------------------------------------------------------------------

def _pump(n=10):
    """Vide d'abord les CallAfter (une barre ne s'ouvre pas pendant un
    wx.SafeYield, qui désactive les fenêtres), puis les événements GTK."""
    wx.GetApp().ProcessPendingEvents()
    for _ in range(n):
        wx.SafeYield()


def _lib():
    g, _gl = gtk_menu._lib()
    V = ctypes.c_void_p
    g.gtk_widget_get_window.restype = V
    g.gtk_widget_get_window.argtypes = [V]
    g.gtk_widget_event.restype = ctypes.c_int
    g.gtk_widget_event.argtypes = [V, V]
    g.gtk_menu_shell_select_item.argtypes = [V, V]
    g.gtk_menu_shell_select_first.argtypes = [V, ctypes.c_int]
    g.gtk_widget_get_mapped.restype = ctypes.c_int
    g.gtk_accel_groups_activate.restype = ctypes.c_int
    g.gtk_accel_groups_activate.argtypes = [V, ctypes.c_uint, ctypes.c_int]
    return g


def _send(widget, etype, keyval=0, state=0):
    """Événement GDK (appui, relâchement, focus) envoyé au widget GTK."""
    g = _lib()
    gdk = ctypes.CDLL("libgdk-3.so.0")
    gdk.gdk_event_new.restype = ctypes.c_void_p
    gdk.gdk_event_new.argtypes = [ctypes.c_int]
    gdk.gdk_event_free.argtypes = [ctypes.c_void_p]
    gobj = ctypes.CDLL("libgobject-2.0.so.0")
    gobj.g_object_ref.restype = ctypes.c_void_p
    gobj.g_object_ref.argtypes = [ctypes.c_void_p]
    event = gdk.gdk_event_new(etype)
    ev = ctypes.cast(event, ctypes.POINTER(gtk_menu._GdkEventKey)).contents
    if etype in (GDK_KEY_PRESS, GDK_KEY_RELEASE):
        ev.keyval, ev.state = keyval, state
    ev.window = gobj.g_object_ref(g.gtk_widget_get_window(widget))
    try:
        return g.gtk_widget_event(widget, event)
    finally:
        gdk.gdk_event_free(event)


def _alt_alone(widget):
    _send(widget, GDK_KEY_PRESS, ALT_L)
    _send(widget, GDK_KEY_RELEASE, ALT_L, GDK_MOD1_MASK)
    _pump()


@pytest.fixture(scope="module")
def demo_frame():
    if not gtk_menu.available():
        pytest.skip("GTK seulement")
    from menukeys.__main__ import DemoFrame
    frame = DemoFrame()
    frame.Show()
    _pump(20)
    yield frame
    frame.keys.close()
    frame.Destroy()
    _pump(5)


@pytest.fixture
def demo(demo_frame, monkeypatch):
    """La démonstration, barre fermée, tenue pour active (Xvfb n'a pas de
    gestionnaire de fenêtres)."""
    monkeypatch.setattr(demo_frame, "IsActive", lambda: True)
    demo_frame.keys.close()
    demo_frame.keys.alt_state.armed = False
    _pump(5)
    yield demo_frame
    demo_frame.keys.close()
    _pump(5)


def _menu_of(frame, index):
    return gtk_menu.submenu(gtk_menu.bar_items(frame.GetMenuBar())[index])


TITLES = ["Fichier", "Edition", "Affichage", "Outils", "Fenêtre", "Aide"]


def _open_reglages(frame):
    """Outils, puis son sous-menu Réglages ouvert (GTK l'ouvre après un
    court délai) ; rend le GtkMenu de Réglages."""
    frame.keys.open_menu("o")
    _pump()
    outils = gtk_menu.bar_items(frame.GetMenuBar())[TITLES.index("Outils")]
    reglages = gtk_menu.menu_items(outils)[0]
    _lib().gtk_menu_shell_select_item(gtk_menu.submenu(outils), reglages)
    sub = gtk_menu.submenu(reglages)
    t0 = time.time()
    while not _lib().gtk_widget_get_mapped(sub) and time.time() - t0 < 2:
        time.sleep(0.01)
        _pump(1)
    assert _lib().gtk_widget_get_mapped(sub)
    return sub


@pytest.mark.gui
def test_demo_bar_and_letters(demo):
    bar = demo.GetMenuBar()
    assert [gtk_menu.label(i) for i in gtk_menu.bar_items(bar)] == TITLES
    assert demo.keys.letters == {"F", "E", "A", "O", "W"}
    assert demo._menukeys is demo.keys


@pytest.mark.gui
def test_demo_shortcuts_shown_not_triggered_by_gtk(demo):
    items = gtk_menu.menu_items(gtk_menu.bar_items(demo.GetMenuBar())[0])
    labels = [gtk_menu.label(i) for i in items]
    save = items[labels.index("Enregistrer")]
    assert gtk_menu.accel_text(save) == (ord("s"), GDK_CONTROL_MASK)
    top = gtk_menu.toplevel(demo.GetMenuBar())
    demo.SetStatusText("")
    assert not _lib().gtk_accel_groups_activate(top, ord("s"), GDK_CONTROL_MASK)
    _pump()
    assert demo.GetStatusBar().GetStatusText() == ""


@pytest.mark.gui
def test_alt_alone_opens_then_closes(demo):
    top = gtk_menu.toplevel(demo.GetMenuBar())
    _alt_alone(top)
    assert demo.keys.open_menus() == [0]
    _alt_alone(_menu_of(demo, 0))                            # menu ouvert : referme
    assert demo.keys.open_menus() == []


@pytest.mark.gui
def test_alt_alone_closes_from_a_submenu_too(demo):
    _alt_alone(_open_reglages(demo))
    assert demo.keys.open_menus() == []


@pytest.mark.gui
@pytest.mark.parametrize("keyval", [F4, ord("4")])
def test_alt_with_another_key_opens_nothing(demo, keyval):
    top = gtk_menu.toplevel(demo.GetMenuBar())
    _send(top, GDK_KEY_PRESS, ALT_L)
    _send(top, GDK_KEY_PRESS, keyval, GDK_MOD1_MASK)
    _send(top, GDK_KEY_RELEASE, keyval, GDK_MOD1_MASK)
    _send(top, GDK_KEY_RELEASE, ALT_L, GDK_MOD1_MASK)
    _pump()
    assert demo.keys.open_menus() == []


@pytest.mark.gui
def test_altgr_opens_nothing(demo):
    top = gtk_menu.toplevel(demo.GetMenuBar())
    _send(top, GDK_KEY_PRESS, ALTGR)
    _send(top, GDK_KEY_RELEASE, ALTGR)
    _pump()
    assert demo.keys.open_menus() == []


@pytest.mark.gui
def test_back_by_alt_tab_opens_nothing(demo):
    top = gtk_menu.toplevel(demo.GetMenuBar())
    _send(top, GDK_KEY_PRESS, ALT_L)
    _send(top, GDK_FOCUS_CHANGE)                              # Alt+Tab : focus perdu
    _send(top, GDK_KEY_RELEASE, ALT_L, GDK_MOD1_MASK)        # au retour
    _pump()
    assert demo.keys.open_menus() == []
    _send(top, GDK_KEY_RELEASE, ALT_L, GDK_MOD1_MASK)        # relâchement seul
    _pump()
    assert demo.keys.open_menus() == []


@pytest.mark.gui
def test_inactive_window_opens_nothing(demo, monkeypatch):
    monkeypatch.setattr(demo, "IsActive", lambda: False)
    _alt_alone(gtk_menu.toplevel(demo.GetMenuBar()))
    assert demo.keys.open_menus() == []


@pytest.mark.gui
def test_alt_letter_alternates_in_an_open_menu(demo):
    demo.keys.open_menu("a")
    _pump()
    seq = [demo.keys.open_menus()]
    for _ in range(2):
        cur = demo.keys.open_menus()[0]
        assert _send(_menu_of(demo, cur), GDK_KEY_PRESS, ord("a"), GDK_MOD1_MASK)
        _pump()
        seq.append(demo.keys.open_menus())
    assert seq == [[2], [5], [2]]                             # Affichage, Aide, Affichage


def _selected_and_grab(frame, index):
    g = _lib()
    V = ctypes.c_void_p
    g.gtk_menu_shell_get_selected_item.restype = V
    g.gtk_menu_shell_get_selected_item.argtypes = [V]
    g.gtk_grab_get_current.restype = V
    sub = _menu_of(frame, index)
    item = g.gtk_menu_shell_get_selected_item(sub)
    return (gtk_menu.label(item) if item else None), g.gtk_grab_get_current() == sub


@pytest.mark.gui
def test_alternating_menu_has_its_first_item_and_the_keyboard(demo):
    """Essai de GroovyboxIt 3b1 : l'alternance de GTK, menu ouvert,
    sélectionnait le titre suivant sans entrer dans son menu (Orca « Piste
    menu », Bas partait dans la fenêtre) ; chaque menu doit avoir son premier
    élément sélectionné et prendre le clavier (grab)."""
    demo.keys.open_menu("a")
    _pump()
    seen = [_selected_and_grab(demo, 2)]
    for index in (5, 2, 5):
        cur = demo.keys.open_menus()[0]
        _send(_menu_of(demo, cur), GDK_KEY_PRESS, ord("a"), GDK_MOD1_MASK)
        _pump()
        assert demo.keys.open_menus() == [index]
        seen.append(_selected_and_grab(demo, index))
    assert seen == [("Grille", True), ("À propos", True), ("Grille", True), ("À propos", True)]


@pytest.mark.gui
def test_letter_absent_from_title_and_f10(demo):
    assert demo.keys.handle_key(keys.key_event("Alt+W"))
    _pump()
    assert demo.keys.open_menus() == [TITLES.index("Fenêtre")]
    demo.keys.close()
    _pump()
    assert demo.keys.handle_key(keys.key_event("F10"))
    _pump()
    assert demo.keys.open_menus() == [0]


@pytest.mark.gui
def test_taken_letter_is_not_a_menu():
    if not gtk_menu.available():
        pytest.skip("GTK seulement")
    frame = wx.Frame(None)
    bar = wx.MenuBar()
    for title in ("&Fichier", "&Edition"):
        m = wx.Menu()
        m.Append(wx.ID_ANY, "x")
        bar.Append(m, title)
    frame.SetMenuBar(bar)
    try:
        mk = menukeys.enable(frame, taken="E")
        assert mk.letters == {"F"}
        assert not mk.handle_key(keys.key_event("Alt+E"))
    finally:
        frame.Destroy()


@pytest.fixture
def emitted(monkeypatch):
    calls = []
    monkeypatch.setattr(gtk_menu._gobject(), "g_signal_emit_by_name",
                        lambda obj, name, arg: calls.append((obj, name, arg)))
    return calls


@pytest.mark.gui
def test_escape_goes_up_only_from_an_entered_submenu(demo, emitted):
    sub = _open_reglages(demo)
    _send(sub, GDK_KEY_PRESS, ESC)                            # pas entré : laissé à GTK
    assert emitted == []
    demo.keys.close()
    _pump()
    sub = _open_reglages(demo)
    _lib().gtk_menu_shell_select_first(sub, 0)               # entré
    assert _send(sub, GDK_KEY_PRESS, ESC)
    assert emitted == [(sub, b"move-current", gtk_menu.GTK_MENU_DIR_PARENT)]


@pytest.mark.gui
def test_demo_keyboard_and_menu_commands(demo, monkeypatch):
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    demo.on_key(keys.key_event("Ctrl+S"))
    assert demo.GetStatusBar().GetStatusText() == "Enregistrer (clavier)"
    ids = {demo.GetMenuBar().FindItemById(i).GetItemLabelText(): i
           for i in [it.GetId() for m, _t in demo.GetMenuBar().GetMenus()
                     for it in m.GetMenuItems() if not it.IsSeparator()]}
    evt = wx.CommandEvent(wx.wxEVT_MENU, ids["Enregistrer"])
    evt.SetEventObject(demo)
    demo.ProcessEvent(evt)
    assert demo.GetStatusBar().GetStatusText() == "Enregistrer"
