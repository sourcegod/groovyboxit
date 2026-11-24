#python3
"""
    File: tests/test_menu_bar.py
    Barre de menus (Phase 9 étape 1c1, docs/DESIGN.md § Phase 9 étape 1a) :
    - description MENUS : titres, lettres, lettres d'éléments uniques,
      actions existantes, raccourcis présents dans docs/shortcuts.md ;
    - raccourci rejoué (key_event, run) ; raccourci sans effet annoncé ;
    - KeyManager : commandes Alt+lettre avant les menus (K3), F10 ;
    - barre GTK (gui) : raccourcis affichés sans être enregistrés (T1),
      éléments grisés (K5), alternance des lettres partagées, aussi menu
      ouvert (K2), Alt+W et Alt+G, Échap dans un sous-menu ;
    - vraie fenêtre principale (gui) : sa barre, un élément par le vrai chemin
      du clavier, F10.
    Les touches ne passent jamais par le vrai clavier : elles sont envoyées
    aux menus GTK par gtk_widget_event.
    Date: Sun, 22/11/2026
    Author: Coolbrother
"""
import ctypes
import os
import re
import time

import pytest
import wx
from conftest import main_thread_call_after

from menukeys import gtk_menu
from ui import menu_bar
from ui.key_manager import KeyManager
from ui.menu_bar import Item, MENUS, SEP, Submenu

DOC = os.path.join(os.path.dirname(__file__), "..", "docs", "shortcuts.md")

TITLES = ["Fichier", "Edition", "Transport", "Aller à", "Insertion", "Piste", "Pattern",
          "Affichage", "Traitement", "Effets", "Mixer", "Outils", "Options", "Fenêtres",
          "Aide"]                       # Pattern et Mixer : Phase 9 étape 3b1


def _all_items(items):
    for it in items:
        if isinstance(it, Submenu):
            yield from _all_items(it.items)
        elif it is not SEP:
            yield it


def _find(text):
    for _t, _l, items in MENUS:
        for it in _all_items(items):
            if it.text() == text:
                return it
    raise KeyError(text)


# ----------------------------------------------------------------------
# Description
# ----------------------------------------------------------------------

def test_menus_in_order_with_their_letter():
    assert [t for t, _l, _i in MENUS] == TITLES
    letters = {t: l for t, l, _i in MENUS}
    assert letters == {"Fichier": "F", "Edition": "E", "Transport": "T", "Aller à": "G",
                       "Insertion": "I", "Piste": "T", "Pattern": "P", "Affichage": "A",
                       "Traitement": "R", "Effets": "F", "Mixer": "M", "Outils": "O",
                       "Options": "N",
                       "Fenêtres": "W", "Aide": "A"}


def test_shared_letters_are_the_wanted_ones():
    count = {}
    for _t, letter, _i in MENUS:
        count[letter] = count.get(letter, 0) + 1
    assert {l for l, n in count.items() if n > 1} == {"F", "T", "A"}


def _check_menu_letters(items, where):
    letters = []
    for it in items:
        if it is SEP:
            continue
        assert it.label.count("&") == 1, f"{where} : {it.label}"
        letters.append(it.label[it.label.index("&") + 1].lower())
        if isinstance(it, Submenu):
            _check_menu_letters(it.items, f"{where} > {it.text()}")
    assert len(letters) == len(set(letters)), f"{where} : lettres en double {letters}"


def test_item_letters_unique_in_each_menu_and_submenu():
    for title, _l, items in MENUS:
        _check_menu_letters(items, title)


def test_no_menu_starts_or_ends_with_a_separator_nor_doubles_one():
    for title, _l, items in MENUS:
        assert items and items[0] is not SEP and items[-1] is not SEP, title
        assert all(not (a is SEP and b is SEP) for a, b in zip(items, items[1:])), title


def test_every_item_has_an_action():
    for _t, _l, items in MENUS:
        for it in _all_items(items):
            assert it.call or it.accel, it.label


def test_called_methods_exist_on_the_main_window():
    from ui.main_window import MainWindow
    for _t, _l, items in MENUS:
        for it in _all_items(items):
            if it.call and menu_bar.MAIN in it.windows:
                assert callable(getattr(MainWindow, it.call, None)), it.call


def test_windows_are_known():
    for _t, _l, items in MENUS:
        for it in _all_items(items):
            assert it.windows and set(it.windows) <= set(menu_bar.ALL), it.label


def test_submenu_active_where_one_of_its_items_is():
    sub = Submenu("&X", [Item("&a", "F1", windows=(menu_bar.MIDI,)), SEP,
                         Item("&b", "F2", windows=(menu_bar.MAIN,))])
    assert set(sub.windows) == {menu_bar.MAIN, menu_bar.MIDI}
    assert sub.text() == "X"


def test_treatment_has_audio_and_midi_submenus():
    items = dict((t, i) for t, _l, i in MENUS)["Traitement"]
    assert [s.text() for s in items] == ["Audio", "Midi"]
    assert all(isinstance(s, Submenu) for s in items)
    assert {it.accel for it in items[1].items} == {"Ctrl+Q", "Shift+Q", "Ctrl+Shift+Q",
                                                   "Alt+Shift+Q"}


def test_requests_of_the_trial():
    """Essai de 1b1 : Alt+F4, Panic dans Options, Fenêtres numérotées."""
    menus = {t: i for t, _l, i in MENUS}
    assert _find("Quitter").accel == "Alt+F4"
    assert _find("Panic") in menus["Options"]
    assert all(it is SEP or it.text() != "Panic" for it in menus["Transport"])
    assert [it.text() for it in menus["Fenêtres"]] == [
        "1 - Fenêtre principale", "2 - Éditeur MIDI", "3 - Songs"]
    assert _find("Au début").accel == "G" and _find("Mesure suivante").accel == "PageDown"


# L'aide écrit les flèches « ↑ », les menus « Haut » (Phase 9 étape 3c1)
_ARROWS = {"Haut": "↑", "Bas": "↓", "Gauche": "←", "Droite": "→"}


def _help_spellings(accel):
    *mods, key = accel.split("+")
    names = [accel, accel.lower()]
    if key in _ARROWS:
        names.append("+".join(mods + [_ARROWS[key]]))
    return names


def test_every_shortcut_shown_is_in_the_keyboard_help():
    with open(DOC, encoding="utf-8") as f:
        doc = f.read()
    for _t, _l, items in MENUS:
        for it in _all_items(items):
            if not it.accel:
                continue
            found = any(re.search(r"(?<![\w+])" + re.escape(a) + r"(?![\w+])", doc)
                        for a in _help_spellings(it.accel))
            assert found, f"{it.accel} ({it.text()}) absent de shortcuts.md"


def test_help_mentions_f10_and_menu_letters():
    with open(DOC, encoding="utf-8") as f:
        doc = f.read()
    assert "F10" in doc and "G Aller à" in doc and "W Fenêtres" in doc


# ----------------------------------------------------------------------
# Lettres des titres (K3)
# ----------------------------------------------------------------------

def test_title_label_marks_the_letter():
    assert menu_bar.title_label("Fichier", "F", menu_bar.MAIN) == "&Fichier"
    assert menu_bar.title_label("Piste", "T", menu_bar.MAIN) == "Pis&te"
    assert menu_bar.title_label("Options", "N", menu_bar.MAIN) == "Optio&ns"
    assert menu_bar.title_label("Traitement", "R", menu_bar.MAIN) == "T&raitement"


def test_title_without_its_letter_stays_plain():
    assert menu_bar.title_label("Fenêtres", "W", menu_bar.MAIN) == "Fenêtres"
    assert menu_bar.title_label("Aller à", "G", menu_bar.MAIN) == "Aller à"


def test_letter_taken_by_a_command_is_not_given_to_the_menu():
    assert menu_bar.title_label("Insertion", "I", menu_bar.MIDI) == "Insertion"
    assert "I" not in menu_bar.menu_letters(menu_bar.MIDI)
    assert "I" in menu_bar.menu_letters(menu_bar.MAIN)


def test_main_window_letters_do_not_collide_with_its_alt_commands():
    assert not menu_bar.menu_letters(menu_bar.MAIN) & menu_bar.TAKEN[menu_bar.MAIN]


# ----------------------------------------------------------------------
# Raccourci rejoué
# ----------------------------------------------------------------------

@pytest.mark.parametrize("accel, code, uni, ctrl, shift, alt", [
    ("Ctrl+Shift+S", ord("S"), ord("S"), True, True, False),
    ("Ctrl+N", ord("N"), ord("n"), True, False, False),
    ("G", ord("G"), ord("g"), False, False, False),
    ("Shift+G", ord("G"), ord("G"), False, True, False),
    ("Espace", wx.WXK_SPACE, ord(" "), False, False, False),
    ("Ctrl+Espace", wx.WXK_SPACE, ord(" "), True, False, False),
    ("PageDown", wx.WXK_PAGEDOWN, 0, False, False, False),
    ("Shift+PageUp", wx.WXK_PAGEUP, 0, False, True, False),
    ("F2", wx.WXK_F2, 0, False, False, False),
    ("Ctrl+Shift+F12", wx.WXK_F12, 0, True, True, False),
    ("Alt+Shift+P", ord("P"), ord("P"), False, True, True),
    ("Alt+4", ord("4"), ord("4"), False, False, True),
    ("Alt+F4", wx.WXK_F4, 0, False, False, True),
])
def test_key_event_like_the_keyboard(accel, code, uni, ctrl, shift, alt):
    evt = menu_bar.key_event(accel)
    assert evt.GetEventType() == wx.wxEVT_CHAR_HOOK
    assert (evt.GetKeyCode(), evt.GetUnicodeKey()) == (code, uni)
    assert (evt.ControlDown(), evt.ShiftDown(), evt.AltDown()) == (ctrl, shift, alt)


@pytest.mark.parametrize("accel, gtk", [
    ("Ctrl+Shift+S", "<Control><Shift>s"), ("G", "g"), ("Espace", "space"),
    ("PageDown", "Page_Down"), ("Ctrl+PageUp", "<Control>Page_Up"), ("F10", "F10"),
    ("Alt+F4", "<Alt>F4"), ("Alt+Shift+I", "<Alt><Shift>i"), ("Alt+4", "<Alt>4"),
])
def test_gtk_accel_syntax(accel, gtk):
    assert gtk_menu.gtk_accel(accel) == gtk


class _Win(wx.EvtHandler):
    """Fenêtre factice : clavier et barre d'état enregistrés."""

    def __init__(self, skip=False):
        super().__init__()
        self.keys, self.status, self.calls, self.skip = [], [], [], skip

    def __bool__(self):
        return True

    def _on_char_hook(self, evt):
        self.keys.append((evt.GetKeyCode(), evt.GetUnicodeKey(), evt.ControlDown(),
                          evt.ShiftDown(), evt.AltDown()))
        if self.skip:
            evt.Skip()

    def _show_status(self, msg):
        self.status.append(msg)

    def _rename_track(self):
        self.calls.append("_rename_track")


def test_run_replays_the_shortcut_through_the_window_keyboard():
    win = _Win()
    menu_bar.run(win, _find("Dupliquer le pattern…"))      # pas un élément Item.main (1e1)
    assert win.keys == [(ord("W"), ord("W"), True, True, False)]
    assert win.status == []


def test_run_calls_the_method_of_a_focus_dependent_item():
    win = _Win()
    menu_bar.run(win, _find("Renommer la piste…"))
    assert win.calls == ["_rename_track"] and win.keys == []


def test_shortcut_without_effect_is_announced():
    win = _Win(skip=True)
    menu_bar.run(win, _find("Grille…"))
    assert win.status == ["Grille… : sans effet ici"]


def test_run_ignores_a_window_being_deleted():
    win = _Win()
    win.IsBeingDeleted = lambda: True
    menu_bar.run(win, _find("Grille…"))
    assert win.keys == []


def test_menu_event_runs_after_the_menu_closes(monkeypatch):
    """Essai de 3b1 : l'action attend MENU_DELAY_MS, le temps qu'Orca lise
    le retour du focus."""
    later = []
    monkeypatch.setattr(wx, "CallLater", lambda ms, fn, *a: later.append((ms, fn, a)))
    win = _Win()
    item = _find("Grille…")
    win._menu_items = {123: item}

    class _Evt:
        def GetId(self):
            return 123
    menu_bar._on_menu(win, _Evt())
    assert later == [(menu_bar.MENU_DELAY_MS, menu_bar.run, (win, item))] and win.keys == []
    assert 100 <= menu_bar.MENU_DELAY_MS <= 300


def test_mixin_actions():
    class _M(menu_bar.MenuBarMixin):
        def __init__(self):
            self.status, self.closed, self.raised = [], 0, 0

        def _show_status(self, msg):
            self.status.append(msg)

        def Close(self):
            self.closed += 1

        def Raise(self):
            self.raised += 1

        def SetFocus(self):             # « Fenêtre principale » rend le focus (1d1)
            pass
    m = _M()
    m._menu_quit()
    m._menu_no_effect()
    m._menu_no_audio_process()
    m._menu_main_window()
    assert m.closed == 1 and m.raised == 1
    assert m.status == ["Aucun effet pour l'instant", "Aucun traitement audio pour l'instant",
                        "Fenêtre principale"]


# ----------------------------------------------------------------------
# KeyManager : commandes avant les menus (K3), F10 (K1)
# ----------------------------------------------------------------------

def _km(monkeypatch):
    from test_key_manager import FakeWindow
    win = FakeWindow()
    seen = []
    monkeypatch.setattr(menu_bar, "open_menu", lambda w, l: seen.append(("menu", l)) or True)
    monkeypatch.setattr(menu_bar, "open_first", lambda w: seen.append(("first",)) or True)
    return KeyManager(win), win, seen


def _hook(key, ukey=None, ctrl=False, shift=False, alt=False):
    evt = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    evt.SetKeyCode(key)
    evt.SetUnicodeKey(key if ukey is None else ukey)
    evt.SetControlDown(ctrl)
    evt.SetRawControlDown(ctrl)
    evt.SetShiftDown(shift)
    evt.SetAltDown(alt)
    return evt


def test_alt_letter_of_a_menu_opens_it(monkeypatch):
    km, _win, seen = _km(monkeypatch)
    km.handle(_hook(ord("F"), ord("f"), alt=True))
    assert seen == [("menu", "f")]


def test_alt_command_keeps_priority_over_menus(monkeypatch):
    km, win, seen = _km(monkeypatch)
    km.handle(_hook(ord("X"), ord("x"), alt=True))
    assert seen == [] and "_open_explorer" in win.calls


def test_alt_shift_letter_is_not_a_menu(monkeypatch):
    km, win, seen = _km(monkeypatch)
    win._open_preferences = lambda: win.calls.append("_open_preferences")
    km.handle(_hook(ord("P"), ord("P"), shift=True, alt=True))
    assert seen == [] and "_open_preferences" in win.calls


def test_f10_opens_the_bar(monkeypatch):
    km, _win, seen = _km(monkeypatch)
    km.handle(_hook(wx.WXK_F10, 0))
    assert seen == [("first",)]


def test_without_a_bar_alt_letter_goes_on(monkeypatch):
    """Fenêtre sans barre (_menu_kind absent) : open_menu rend False."""
    from test_key_manager import FakeWindow
    assert menu_bar.open_menu(FakeWindow(), "f") is False
    assert menu_bar.open_first(FakeWindow()) is False


# ----------------------------------------------------------------------
# Barre GTK (fenêtre affichée)
# ----------------------------------------------------------------------

class _Frame(menu_bar.MenuBarMixin, wx.Frame):
    def __init__(self):
        super().__init__(None, title="menus")
        self.keys, self.status = [], []

    def _on_char_hook(self, evt):
        self.keys.append(evt.GetKeyCode())

    def _show_status(self, msg):
        self.status.append(msg)


def _yield(n=10, sleep=0.0):
    for _ in range(n):
        if sleep:
            time.sleep(sleep)
        wx.SafeYield()


@pytest.fixture(scope="module")
def shown():
    if not gtk_menu.available():
        pytest.skip("GTK seulement")
    frame = _Frame()
    bar = menu_bar.install(frame, menu_bar.MAIN)
    frame.Show()
    _yield(20)
    yield frame, bar
    gtk_menu.close(bar)
    frame.Destroy()
    _yield(5)


@pytest.fixture
def bar(shown):
    frame, bar = shown
    gtk_menu.close(bar)
    _yield(5)
    yield frame, bar
    gtk_menu.close(bar)
    _yield(5)


def _lib():
    g, _gl = gtk_menu._lib()
    V = ctypes.c_void_p
    g.gtk_widget_get_window.restype = V
    g.gtk_widget_get_window.argtypes = [V]
    g.gtk_widget_event.restype = ctypes.c_int
    g.gtk_widget_event.argtypes = [V, V]
    g.gtk_menu_shell_select_item.argtypes = [V, V]
    g.gtk_menu_shell_select_first.argtypes = [V, ctypes.c_int]
    g.gtk_widget_is_sensitive.restype = ctypes.c_int
    g.gtk_widget_is_sensitive.argtypes = [V]
    return g


def _send_key(widget, keyval, state=0):
    """Touche envoyée au menu GTK widget, sans passer par le clavier."""
    g = _lib()
    gdk = ctypes.CDLL("libgdk-3.so.0")
    gdk.gdk_event_new.restype = ctypes.c_void_p
    gdk.gdk_event_new.argtypes = [ctypes.c_int]
    gdk.gdk_event_free.argtypes = [ctypes.c_void_p]
    gobj = ctypes.CDLL("libgobject-2.0.so.0")
    gobj.g_object_ref.restype = ctypes.c_void_p
    gobj.g_object_ref.argtypes = [ctypes.c_void_p]
    event = gdk.gdk_event_new(8)                      # GDK_KEY_PRESS
    ev = ctypes.cast(event, ctypes.POINTER(gtk_menu._GdkEventKey)).contents
    ev.keyval, ev.state = keyval, state
    ev.window = gobj.g_object_ref(g.gtk_widget_get_window(widget))
    try:
        return g.gtk_widget_event(widget, event)
    finally:
        gdk.gdk_event_free(event)                     # rend aussi la fenêtre


def _submenu(item):
    return _lib().gtk_menu_item_get_submenu(item)


@pytest.mark.gui
def test_gtk_bar_has_the_menus_and_submenus(bar):
    _frame, mb = bar
    items = gtk_menu.bar_items(mb)
    assert [gtk_menu.label(i) for i in items] == TITLES
    treatment = gtk_menu.menu_items(items[TITLES.index("Traitement")])
    assert [gtk_menu.label(i) for i in treatment] == ["Audio", "Midi"]
    midi = gtk_menu.menu_items(treatment[1])
    assert gtk_menu.label(midi[0]) == "Quantiser"


@pytest.mark.gui
def test_shortcuts_shown_but_not_registered(bar):
    """T1 : le raccourci est affiché (et lu par Orca), mais GTK ne le
    déclenche pas (le clavier de la fenêtre reste seul)."""
    frame, mb = bar
    items = gtk_menu.bar_items(mb)
    fichier = gtk_menu.menu_items(items[0])
    labels = [gtk_menu.label(i) for i in fichier]
    save_as = fichier[labels.index("Enregistrer sous…")]
    assert gtk_menu.accel_text(save_as) == (ord("s"), (1 << 2) | (1 << 0))
    quit_ = fichier[labels.index("Quitter")]
    assert gtk_menu.accel_text(quit_)[1] == gtk_menu.GDK_MOD1_MASK
    g = _lib()
    g.gtk_accel_groups_activate.restype = ctypes.c_int
    g.gtk_accel_groups_activate.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int]
    top = gtk_menu._toplevel(mb)
    frame.keys.clear()
    assert not g.gtk_accel_groups_activate(top, ord("s"), (1 << 2) | (1 << 0))
    assert not g.gtk_accel_groups_activate(top, ord("r"), 0)
    _yield()
    assert frame.keys == []


@pytest.mark.gui
def test_items_without_object_are_greyed(bar):
    frame, mb = bar
    ids = {it.text(): i for i, it in frame._menu_items.items()}
    assert not mb.FindItemById(ids["Notes"]).IsEnabled()            # éditeur MIDI
    assert mb.FindItemById(ids["Grille…"]).IsEnabled()
    assert mb.FindItemById(ids["Aucun traitement audio pour l'instant"]).IsEnabled()


@pytest.mark.gui
def test_menu_event_runs_the_item(bar, monkeypatch):
    monkeypatch.setattr(wx, "CallLater", lambda ms, fn, *a: fn(*a))     # 3b1 : différé
    frame, mb = bar
    ids = {it.text(): i for i, it in frame._menu_items.items()}
    frame.keys.clear()
    evt = wx.CommandEvent(wx.wxEVT_MENU, ids["Stop"])
    evt.SetEventObject(frame)
    frame.ProcessEvent(evt)
    assert frame.keys == [ord("V")]


@pytest.mark.gui
def test_shared_letter_alternates(bar):
    frame, mb = bar
    seq = []
    for letter in "aaa":
        assert menu_bar.open_menu(frame, letter)
        _yield()
        seq.append(gtk_menu.open_menus(mb))
    assert seq == [[TITLES.index("Affichage")], [TITLES.index("Aide")],
                   [TITLES.index("Affichage")]]


@pytest.mark.gui
def test_letters_absent_from_titles_open_their_menu(bar):
    frame, mb = bar
    assert menu_bar.open_menu(frame, "w")
    _yield()
    assert gtk_menu.open_menus(mb) == [TITLES.index("Fenêtres")]
    gtk_menu.close(mb)
    _yield()
    assert menu_bar.open_menu(frame, "g")
    _yield()
    assert gtk_menu.open_menus(mb) == [TITLES.index("Aller à")]


@pytest.mark.gui
def test_f10_opens_the_first_menu(bar):
    frame, mb = bar
    assert menu_bar.open_first(frame)
    _yield()
    assert gtk_menu.open_menus(mb) == [0]


@pytest.mark.gui
def test_letter_of_no_menu_does_nothing(bar):
    frame, mb = bar
    assert not menu_bar.open_menu(frame, "x")
    _yield()
    assert gtk_menu.open_menus(mb) == []


@pytest.mark.gui
def test_alt_letter_in_an_open_menu_alternates_at_once(bar):
    """Essai de 1b1 : sans refermer le menu, Alt+F passe de Fichier à
    Effets, puis revient ; Alt+N ouvre Options."""
    frame, mb = bar
    items = gtk_menu.bar_items(mb)
    menu_bar.open_menu(frame, "f")
    _yield()
    seq = []
    for letter in "ffn":
        cur = gtk_menu.open_menus(mb)[0]
        assert _send_key(_submenu(items[cur]), ord(letter), gtk_menu.GDK_MOD1_MASK)
        _yield()
        seq.append(gtk_menu.open_menus(mb))
    assert seq == [[TITLES.index("Effets")], [0], [TITLES.index("Options")]]


def _open_midi_submenu(frame, mb):
    items = gtk_menu.bar_items(mb)
    treat = items[TITLES.index("Traitement")]
    midi_item = gtk_menu.menu_items(treat)[1]
    menu_bar.open_menu(frame, "r")
    _yield()
    _lib().gtk_menu_shell_select_item(_submenu(treat), midi_item)
    t0 = time.time()
    midi = _submenu(midi_item)
    while not _lib().gtk_widget_get_mapped(midi) and time.time() - t0 < 2:
        _yield(1, 0.01)
    assert _lib().gtk_widget_get_mapped(midi)
    return treat, midi


@pytest.fixture
def emitted(monkeypatch):
    calls = []
    lib = gtk_menu._gobject()
    monkeypatch.setattr(lib, "g_signal_emit_by_name",
                        lambda obj, name, arg: calls.append((obj, name, arg)))
    return calls


@pytest.mark.gui
def test_escape_in_an_entered_submenu_goes_up(bar, emitted):
    frame, mb = bar
    _treat, midi = _open_midi_submenu(frame, mb)
    _lib().gtk_menu_shell_select_first(midi, 0)       # entré dans Midi
    assert _send_key(midi, gtk_menu.GDK_KEY_ESCAPE)
    assert emitted == [(midi, b"move-current", gtk_menu.GTK_MENU_DIR_PARENT)]


@pytest.mark.gui
def test_escape_in_a_submenu_not_entered_is_left_to_gtk(bar, emitted):
    """GTK ouvre de lui-même le sous-menu de l'élément sélectionné, sans y
    entrer : Échap doit fermer la barre, pas remonter (essais de 1b1)."""
    frame, mb = bar
    _treat, midi = _open_midi_submenu(frame, mb)
    _send_key(midi, gtk_menu.GDK_KEY_ESCAPE)
    assert emitted == []


@pytest.mark.gui
def test_escape_in_a_menu_of_the_bar_is_left_to_gtk(bar, emitted):
    frame, mb = bar
    menu_bar.open_menu(frame, "e")
    _yield()
    _send_key(_submenu(gtk_menu.bar_items(mb)[1]), gtk_menu.GDK_KEY_ESCAPE)
    assert emitted == []




# ----------------------------------------------------------------------
# Éditeur MIDI et Songs (Phase 9 étape 1e1, tests de 1d1)
# ----------------------------------------------------------------------

def test_file_items_reach_every_window():
    """Essai de 1d1 : Nouveau, Ouvrir, Enregistrer, Enregistrer sous et
    Quitter accessibles de partout ; les quatre premiers joués par la
    fenêtre principale (Item.main)."""
    for text in ("Nouveau projet", "Ouvrir un projet…", "Enregistrer sous…"):
        it = _find(text)
        assert it.main and set(it.windows) == set(menu_bar.ALL), text
    fichier = dict((t, i) for t, _l, i in MENUS)["Fichier"]
    save = [it for it in fichier if it is not SEP and it.text() == "Enregistrer"][0]
    assert save.main and save.accel == "Ctrl+S"
    quit_ = _find("Quitter")
    assert set(quit_.windows) == set(menu_bar.ALL) and not quit_.main


def test_main_items_are_the_file_shortcuts():
    assert set(menu_bar._main_items()) == {"Ctrl+N", "Ctrl+O", "Ctrl+S", "Ctrl+Shift+S"}


def test_song_items_only_in_songs():
    for text in ("Enregistrer le song", "Dupliquer le song…", "Renommer le song…"):
        assert _find(text).windows == (menu_bar.SONGS,), text
    assert _find("Enregistrer le pattern").windows == (menu_bar.MAIN,)


def test_windows_and_help_items_everywhere():
    for text in ("1 - Fenêtre principale", "2 - Éditeur MIDI", "3 - Songs", "Aide clavier"):
        it = _find(text)
        assert it.call and set(it.windows) == set(menu_bar.ALL), text
    assert _find("2 - Éditeur MIDI").accel == "Alt+4"
    assert _find("Aide clavier").accel == "F1"


@pytest.mark.parametrize("kind, cls", [
    (menu_bar.MIDI, "ui.midi_editor_window.MidiEditorWindow"),
    (menu_bar.SONGS, "ui.song_window.SongWindow"),
])
def test_called_methods_exist_on_each_window(kind, cls):
    import importlib
    mod, name = cls.rsplit(".", 1)
    klass = getattr(importlib.import_module(mod), name)
    for _t, _l, items in MENUS:
        for it in _all_items(items):
            if it.call and kind in it.windows:
                assert callable(getattr(klass, it.call, None)), (kind, it.call)


@pytest.mark.parametrize("accel", ["Ctrl+S", "Ctrl+Shift+S", "Alt+F4", "F10", "Shift+G",
                                   "Ctrl+Alt+X", "4"])
def test_accel_of_is_the_inverse_of_key_event(accel):
    assert menu_bar.accel_of(menu_bar.key_event(accel)) == accel


def test_accel_of_named_keys_and_others():
    """Phase 9 étape 3b1 : les touches nommées ont leur nom ; Tab, non."""
    assert menu_bar.accel_of(menu_bar.key_event("Espace")) == "Espace"
    assert menu_bar.accel_of(menu_bar.key_event("Shift+PageDown")) == "Shift+PageDown"
    evt = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    evt.SetKeyCode(wx.WXK_TAB)
    assert menu_bar.accel_of(evt) is None


# --- Clavier de l'éditeur et de Songs : handle_key --------------------

class _Child(_Win):
    """Fenêtre secondaire factice (éditeur MIDI, Songs) et sa principale."""

    def __init__(self, kind, main=None):
        super().__init__()
        self._menu_kind = kind
        self._parent = main
        self.raised, self.deleting = 0, False

    def _menu_main(self):
        return menu_bar.MenuBarMixin._menu_main(self)

    def _on_key(self, evt):
        self._on_char_hook(evt)

    def Raise(self):
        self.raised += 1

    def IsBeingDeleted(self):
        return self.deleting


class _Main(_Child):
    def __init__(self):
        super().__init__(menu_bar.MAIN)
        self.main_keys = []

    def _on_menu_key(self, evt):
        self.main_keys.append(menu_bar.accel_of(evt))


@pytest.fixture
def now(monkeypatch):
    """wx.CallLater synchrone : le retour différé du focus tout de suite."""
    delays = []
    monkeypatch.setattr(wx, "CallLater",
                        lambda ms, fn, *a: (delays.append(ms), fn(*a)))
    return delays


def test_handle_key_alt_letter_and_f10(monkeypatch):
    seen = []
    monkeypatch.setattr(menu_bar, "open_menu", lambda w, l: seen.append(l) or True)
    monkeypatch.setattr(menu_bar, "open_first", lambda w: seen.append("F10") or True)
    win = _Child(menu_bar.MIDI, _Main())
    assert menu_bar.handle_key(win, menu_bar.key_event("Alt+T"))
    assert menu_bar.handle_key(win, menu_bar.key_event("F10"))
    assert seen == ["t", "F10"]


def test_handle_key_leaves_alt_i_to_the_midi_editor():
    """K3 : Alt+I reste « insérer sans avancer » ; la vraie open_menu le
    refuse sans toucher à GTK."""
    win = _Child(menu_bar.MIDI, _Main())
    assert not menu_bar.handle_key(win, menu_bar.key_event("Alt+I"))
    assert not menu_bar.open_menu(win, "i")


def test_handle_key_leaves_other_keys():
    win = _Child(menu_bar.SONGS, _Main())
    for accel in ("Ctrl+W", "Ctrl+Shift+W", "G", "Alt+Shift+P", "F2", "Espace"):
        assert not menu_bar.handle_key(win, menu_bar.key_event(accel)), accel
    assert win._parent.main_keys == []


@pytest.mark.parametrize("kind", [menu_bar.MIDI, menu_bar.SONGS])
def test_file_shortcuts_typed_in_a_child_go_to_the_main_window(kind, now):
    main = _Main()
    win = _Child(kind, main)
    for accel in ("Ctrl+N", "Ctrl+O", "Ctrl+S", "Ctrl+Shift+S"):
        assert menu_bar.handle_key(win, menu_bar.key_event(accel))
    assert main.main_keys == ["Ctrl+N", "Ctrl+O", "Ctrl+S", "Ctrl+Shift+S"]
    assert win.keys == [] and win.raised == 4


def test_file_shortcuts_in_the_main_window_stay_its_own():
    main = _Main()
    assert not menu_bar.handle_key(main, menu_bar.key_event("Ctrl+S"))
    assert main.main_keys == []


def test_file_item_chosen_in_a_child_runs_on_the_main_window(now):
    main = _Main()
    win = _Child(menu_bar.MIDI, main)
    menu_bar.run(win, _find("Ouvrir un projet…"))
    assert main.main_keys == ["Ctrl+O"] and win.keys == []
    assert win.raised == 1 and now == [menu_bar.BACK_DELAY_MS]


def test_file_item_in_the_main_window_uses_its_own_keyboard(now):
    main = _Main()
    menu_bar.run(main, _find("Ouvrir un projet…"))
    assert main.keys == [(ord("O"), ord("o"), True, False, False)]
    assert main.main_keys == [] and now == []


def test_focus_comes_back_late_not_at_once(monkeypatch):
    """Essai de 1d1 : un Raise immédiat était défait par la réactivation de
    la fenêtre principale après sa boîte → différé."""
    later = []
    monkeypatch.setattr(wx, "CallLater", lambda ms, fn, *a: later.append((ms, fn)))
    main = _Main()
    win = _Child(menu_bar.SONGS, main)
    menu_bar.run_on_main(win, menu_bar.key_event("Ctrl+O"))
    assert win.raised == 0 and len(later) == 1
    assert later[0][0] == menu_bar.BACK_DELAY_MS >= 100
    later[0][1]()
    assert win.raised == 1


@pytest.mark.parametrize("who", ["main", "win"])
def test_no_focus_back_when_a_window_closes(who, now):
    main = _Main()
    win = _Child(menu_bar.MIDI, main)
    (main if who == "main" else win).deleting = True
    menu_bar.run_on_main(win, menu_bar.key_event("Ctrl+N"))
    assert win.raised == 0 and main.main_keys == ["Ctrl+N"]


def test_quit_from_a_child_closes_the_main_window(now):
    class _QMain(_Main):
        closed = 0

        def Close(self):
            self.closed += 1

    class _QChild(menu_bar.MenuBarMixin, _Child):
        pass
    main = _QMain()
    win = _QChild(menu_bar.SONGS, main)
    win._menu_quit()                                   # Annuler : la principale reste
    assert main.closed == 1 and win.raised == 1
    main.deleting = True                               # quitter pour de bon
    win._menu_quit()
    assert main.closed == 2 and win.raised == 1


def test_menu_main_of_each_window():
    main = _Main()

    class _C(menu_bar.MenuBarMixin):
        pass
    child = _C()
    child._menu_kind, child._parent = menu_bar.MIDI, main
    assert child._menu_main() is main
    child._menu_kind = menu_bar.MAIN
    assert child._menu_main() is child


def test_window_items_delegate_to_the_main_window(monkeypatch):
    calls = []

    class _M:
        def _open_midi_editor_window(self):
            calls.append("midi")

        def _open_song_window(self):
            calls.append("songs")

    class _C(menu_bar.MenuBarMixin):
        _menu_kind = menu_bar.SONGS
        _parent = _M()
    _C()._menu_midi_editor()
    _C()._menu_songs()
    assert calls == ["midi", "songs"]


def test_help_item_opens_the_keyboard_help_on_the_window(monkeypatch):
    import ui.dialogs as dialogs
    shown = []

    class _Dlg:
        def __init__(self, parent):
            shown.append(parent)

        def ShowModal(self):
            shown.append("modal")

        def Destroy(self):
            shown.append("destroy")
    monkeypatch.setattr(dialogs, "KeyboardHelpDialog", _Dlg)

    class _C(menu_bar.MenuBarMixin):
        pass
    c = _C()
    c._menu_help()
    assert shown == [c, "modal", "destroy"]


def test_nothing_here_is_announced_in_the_status_bar():
    class _C(menu_bar.MenuBarMixin):
        def __init__(self):
            self.msgs = []

        def _set_status(self, msg):                    # éditeur MIDI, Songs
            self.msgs.append(msg)
    c = _C()
    c._menu_nothing_here()
    c._menu_no_effect()
    assert c.msgs == ["Aucune commande de ce menu dans cette fenêtre",
                      "Aucun effet pour l'instant"]


def test_skipped_shortcut_announced_in_a_child_status_bar():
    class _S(_Child):
        _on_char_hook = None                           # Songs : _on_key seul

        def _on_key(self, evt):
            evt.Skip()
    win = _S(menu_bar.SONGS, _Main())
    win._set_status = win.status.append
    win._show_status = None                          # Songs : _set_status seul
    menu_bar.run(win, _find("Grille…"))
    assert win.status == ["Grille… : sans effet ici"]


# --- Barres construites pour chaque fenêtre ---------------------------

def _built(kind):
    frame = _Frame()
    bar = menu_bar.install(frame, kind)
    return frame, bar


def _enabled_texts(bar, title):
    menu = bar.GetMenu(TITLES.index(title))
    return [it.GetItemLabelText() for it in menu.GetMenuItems()
            if not it.IsSeparator() and it.IsEnabled()]


def _greyed(frame, bar):
    return {it.text() for i, it in frame._menu_items.items()
            if not bar.FindItemById(i).IsEnabled()}


@pytest.mark.parametrize("kind, filled", [
    (menu_bar.MAIN, set()),
    (menu_bar.MIDI, {"Piste", "Pattern", "Mixer", "Outils"}),
    (menu_bar.SONGS, {"Insertion", "Piste", "Pattern", "Mixer", "Outils"}),
])
def test_menu_without_active_item_gets_one(kind, filled):
    """Essai de 1d1 : GTK ne prenait pas le clavier dans un menu tout grisé
    (flèches et Échap retombaient sur l'éditeur)."""
    frame, bar = _built(kind)
    try:
        nothing = menu_bar.NOTHING_HERE.replace("&", "")
        got = set()
        for title in TITLES:
            enabled = _enabled_texts(bar, title)
            assert enabled, (kind, title)                       # jamais tout grisé
            if nothing in enabled:
                got.add(title)
                assert enabled == [nothing]
        assert got == filled
    finally:
        frame.Destroy()


def test_greyed_items_of_each_window():
    expected = {
        menu_bar.MAIN: {"Enregistrer le song", "Dupliquer le song…", "Renommer le song…",
                        "Notes", "Liste des événements"},
    }
    frames = []
    try:
        greyed = {}
        for kind in menu_bar.ALL:
            frame, bar = _built(kind)
            frames.append(frame)
            greyed[kind] = _greyed(frame, bar)
        assert greyed[menu_bar.MAIN] == expected[menu_bar.MAIN]
        # 20 / 29 en 1e1 ; + 42 / 48 éléments de la fenêtre principale (3b1-3b5),
        # + 7 dialogues (3d1)
        assert len(greyed[menu_bar.MIDI]) == 69 and len(greyed[menu_bar.SONGS]) == 84
        # Fichier, Fenêtres, Aide jamais grisés
        for kind in menu_bar.ALL:
            for text in ("Nouveau projet", "Ouvrir un projet…", "Enregistrer sous…",
                         "Quitter", "1 - Fenêtre principale", "Aide clavier"):
                assert text not in greyed[kind], (kind, text)
        assert {"Notes", "Liste des événements", "Quantiser"} <= greyed[menu_bar.SONGS]
        assert not {"Notes", "Quantiser", "Tempos…", "Importer un fichier MIDI…"} \
            & greyed[menu_bar.MIDI]
        assert {"Enregistrer", "Propriétés de la piste…", "Explorateur…"} <= \
            greyed[menu_bar.MIDI]
    finally:
        for f in frames:
            f.Destroy()


def test_midi_submenu_greyed_in_songs_audio_kept():
    frame, bar = _built(menu_bar.SONGS)
    try:
        menu = bar.GetMenu(TITLES.index("Traitement"))
        state = {it.GetItemLabelText(): it.IsEnabled() for it in menu.GetMenuItems()}
        assert state == {"Audio": True, "Midi": False}
    finally:
        frame.Destroy()


def test_insertion_title_has_no_letter_in_the_midi_editor():
    frame, bar = _built(menu_bar.MIDI)
    try:
        assert bar.GetMenuLabel(TITLES.index("Insertion")) == "Insertion"
        assert bar.GetMenuLabel(TITLES.index("Fichier")) == "&Fichier"
    finally:
        frame.Destroy()


# ----------------------------------------------------------------------
# Vraies fenêtres : principale, éditeur MIDI, Songs (une seule principale
# pour le module)
# ----------------------------------------------------------------------

@pytest.fixture(scope="module")
def real():
    from ui.main_window import MainWindow
    win = MainWindow()
    win._open_midi_editor_window()
    win._open_song_window()
    yield win
    for child in (win._song_window, win._midi_editor_window):
        if child:
            child.Destroy()
    win._router.wait_loaded()
    win._close_midi_devices()
    win._audio_driver.close()
    win.Destroy()


@pytest.mark.gui
def test_main_window_bar_and_real_keyboard_path(real, monkeypatch):
    # synchrone dans le fil principal seulement (conftest, 1e2)
    monkeypatch.setattr(wx, "CallAfter", main_thread_call_after())
    win = real
    mb = win.GetMenuBar()
    assert mb is not None and mb.GetMenuCount() == len(TITLES)
    assert win._menu_kind == menu_bar.MAIN
    status = []
    monkeypatch.setattr(win, "_show_status", status.append)
    # focus dans la principale (l'éditeur et Songs du module l'ont pris)
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: None))
    menu_bar.run(win, _find("État et position"))              # U
    assert status and "Pos" in status[-1]
    if gtk_menu.available():
        win.Show()
        _yield(10)
        win._key_manager.handle(_hook(wx.WXK_F10, 0))
        _yield()
        assert gtk_menu.open_menus(mb) == [0]
        gtk_menu.close(mb)
        _yield()


@pytest.mark.gui
def test_child_windows_have_the_same_bar(real):
    for child, kind in ((real._midi_editor_window, menu_bar.MIDI),
                        (real._song_window, menu_bar.SONGS)):
        assert child._menu_kind == kind
        assert child.GetMenuBar().GetMenuCount() == len(TITLES)
        assert child._menu_main() is real


@pytest.mark.gui
def test_midi_editor_keyboard_with_the_bar(real, monkeypatch, now):
    ed = real._midi_editor_window
    inserted, main_keys, menus = [], [], []
    monkeypatch.setattr(ed, "_quick_insert", inserted.append)
    monkeypatch.setattr(real, "_on_menu_key",
                        lambda evt: main_keys.append(menu_bar.accel_of(evt)))
    monkeypatch.setattr(menu_bar, "open_menu",       # décision de la vraie, sans GTK
                        lambda w, l: l.upper() in menu_bar.menu_letters(w._menu_kind)
                        and not menus.append(l))
    ed._on_key(menu_bar.key_event("Alt+I"))           # « insérer sans avancer »
    ed._on_key(menu_bar.key_event("Ctrl+S"))          # Fichier : la principale
    ed._on_key(menu_bar.key_event("Alt+R"))           # Traitement, pas « rafraîchir »
    assert inserted == [False] and main_keys == ["Ctrl+S"] and menus == ["r"]


@pytest.mark.gui
def test_midi_editor_items_by_its_keyboard(real, monkeypatch):
    ed = real._midi_editor_window
    status = []
    monkeypatch.setattr(ed, "_set_status", status.append)
    menu_bar.run(ed, _find("Liste des événements"))
    assert ed._view_mode == ed.MODE_ALL
    menu_bar.run(ed, _find("Notes"))
    assert ed._view_mode == ed.MODE_NOTES
    assert status == ["Mode : Tous les événements MIDI", "Mode : Notes de la piste courante"]


@pytest.mark.gui
def test_songs_items_by_its_keyboard(real, monkeypatch, now):
    sw = real._song_window
    calls, main_keys = [], []
    monkeypatch.setattr(sw, "_rename_song", lambda: calls.append("rename"))
    monkeypatch.setattr(real, "_save_song", lambda: calls.append("save song"))
    monkeypatch.setattr(real, "_on_menu_key",
                        lambda evt: main_keys.append(menu_bar.accel_of(evt)))
    menu_bar.run(sw, _find("Renommer le song…"))
    menu_bar.run(sw, _find("Enregistrer le song"))            # Ctrl+W de Songs
    sw._on_key(menu_bar.key_event("Ctrl+O"))                  # Fichier : la principale
    assert calls == ["rename", "save song"] and main_keys == ["Ctrl+O"]
