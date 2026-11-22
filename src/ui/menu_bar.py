#python3
"""
    File: src/ui/menu_bar.py
    Barre de menus (Phase 9 étape 1b1, docs/DESIGN.md § Phase 9 étape 1a).
    - Une seule description (MENUS) pour toutes les fenêtres (K5, T2) : chaque
      fenêtre construit sa copie (un wx.MenuBar n'appartient qu'à une fenêtre),
      les éléments sans objet dans la fenêtre y sont grisés.
    - Raccourcis AFFICHÉS mais jamais enregistrés dans GTK (T1) : le clavier
      de la fenêtre reste seul à les déclencher (gtk_menu.set_accel_text).
    - Un élément refait son raccourci par le vrai chemin du clavier de la
      fenêtre (T3 : jamais une copie du code), ou appelle une méthode quand
      l'action dépend du focus ou n'a pas de raccourci ; lancé par
      wx.CallAfter, menu refermé et focus revenu.
    - F10 ouvre la barre (K1) ; Alt+lettre ouvre un menu, en alternance si la
      lettre est partagée (K2, fait par GTK) ; une lettre déjà prise par une
      commande de la fenêtre n'est pas donnée au menu (K3).
    Date: Sat, 21/11/2026
    Author: Coolbrother
"""
import wx

from . import gtk_menu

MAIN, MIDI, SONGS = "main", "midi", "songs"
ALL = (MAIN, MIDI, SONGS)


class Item:
    """Élément de menu : label (avec « & » devant sa lettre), accel (raccourci
    affiché et rejoué, ou None), call (méthode de la fenêtre, sinon le
    raccourci est rejoué), windows (fenêtres où il est actif)."""

    def __init__(self, label, accel=None, call=None, windows=ALL):
        self.label, self.accel, self.call, self.windows = label, accel, call, tuple(windows)

    def text(self):
        """Libellé sans « & »."""
        return self.label.replace("&", "")


class Submenu:
    """Sous-menu : label (avec « & »), éléments ; actif dans une fenêtre si
    l'un de ses éléments l'est."""

    def __init__(self, label, items):
        self.label, self.items = label, items
        self.windows = tuple(sorted({w for it in items if it is not None
                                     for w in it.windows}))

    def text(self):
        return self.label.replace("&", "")


SEP = None      # séparateur

P, PM = (MAIN,), (MAIN, MIDI)

# Menus : (titre, lettre de Alt+lettre, éléments). Fenêtres (1b1) : seule la
# principale a sa barre ; l'éditeur MIDI et Songs viennent en 1d1.
MENUS = [
    ("Fichier", "F", [
        Item("&Nouveau projet", "Ctrl+N", windows=P),
        Item("&Ouvrir un projet…", "Ctrl+O", windows=P),
        Item("&Enregistrer", "Ctrl+S", windows=P),
        Item("Enregistrer &sous…", "Ctrl+Shift+S", windows=P),
        SEP,
        Item("Enregistrer le &pattern", "Ctrl+W", windows=P),
        Item("&Dupliquer le pattern…", "Ctrl+Shift+W", windows=P),
        SEP,
        Item("&Importer un fichier MIDI…", "Alt+Shift+I", windows=PM),
        Item("Exporter en &MIDI…", "Alt+Shift+E"),
        Item("Exporter en &audio…", "Alt+Shift+W"),
        SEP,
        Item("&Quitter", "Alt+F4", call="_menu_quit", windows=P),
    ]),
    ("Edition", "E", [
        Item("&Annuler", "Ctrl+Z", windows=PM),
        Item("&Refaire", "Shift+Z", windows=PM),
        Item("&Historique des annulations…", "Ctrl+Shift+Z", windows=PM),
        SEP,
        Item("Renommer la &piste…", "F2", call="_rename_track", windows=P),
        Item("Renommer le pa&ttern…", "F2", call="_rename_pattern", windows=P),
    ]),
    ("Transport", "T", [
        Item("&Lecture / Pause", "Espace"),
        Item("Lecture depuis le &début", "Ctrl+Espace"),
        Item("&Stop", "V"),
        SEP,
        Item("&Enregistrer", "R", windows=P),
        Item("Enregistrer en &remplacement", "Shift+R", windows=P),
        Item("Dé&compte puis enregistrer", "Ctrl+R", windows=P),
        SEP,
        Item("É&tat et position", "U", windows=P),
        SEP,
        Item("Bo&ucle On / Off", "L"),
        Item("&Points de boucle…", "Ctrl+Shift+L", windows=P),
    ]),
    # Aller à (essai de 1b1) : Alt+G, lettre absente du titre (comme Alt+W)
    ("Aller à", "G", [
        Item("Au &début", "G"),
        Item("À la &fin", "Shift+G"),
        Item("À une &position…", "Ctrl+G"),
        SEP,
        Item("Mesure s&uivante", "PageDown"),
        Item("Mesure pré&cédente", "PageUp"),
        Item("&Battement suivant", "Ctrl+PageDown"),
        Item("Ba&ttement précédent", "Ctrl+PageUp"),
        Item("Pas &suivant", "Shift+PageDown"),
        Item("Pas p&récédent", "Shift+PageUp"),
        Item("Seconde suiva&nte", "W"),
        Item("Seconde précéd&ente", "B"),
    ]),
    ("Insertion", "I", [
        Item("&Tempos…", "Alt+Shift+T", windows=PM),
    ]),
    ("Piste", "T", [
        Item("&Propriétés de la piste…", "Ctrl+Shift+T", windows=P),
        SEP,
        Item("&Mute exclusif", "F3", windows=P),
        Item("&Solo exclusif", "F4", windows=P),
        Item("&Réinitialiser les Mute et Solo", "F5", windows=P),
    ]),
    ("Affichage", "A", [
        Item("&Grille…", "Ctrl+Shift+G"),
        Item("&Filtre des événements…", "Ctrl+Shift+F", windows=PM),
        SEP,
        Item("&Notes", "Ctrl+1", windows=(MIDI,)),
        Item("&Liste des événements", "Ctrl+2", windows=(MIDI,)),
    ]),
    ("Traitement", "R", [
        Submenu("&Audio", [
            Item("&Aucun traitement audio pour l'instant", call="_menu_no_audio_process"),
        ]),
        Submenu("&Midi", [
            Item("&Quantiser", "Ctrl+Q", windows=PM),
            Item("Quantiser avec les &derniers réglages", "Shift+Q", windows=PM),
            Item("Quantiser &avec dialogue…", "Ctrl+Shift+Q", windows=PM),
            Item("Quantisation à l'&enregistrement…", "Alt+Shift+Q", windows=PM),
        ]),
    ]),
    ("Effets", "F", [
        Item("&Aucun effet pour l'instant", call="_menu_no_effect"),
    ]),
    ("Outils", "O", [
        Item("&Explorateur…", "Alt+X", windows=P),
    ]),
    ("Options", "N", [
        Item("&Préférences…", "Alt+Shift+P"),
        Item("Options de l'&enregistrement…", "Ctrl+Shift+R"),
        Item("&Monitoring de l'entrée On / Off", "F8", windows=P),
        SEP,
        Item("Mode d'entrée P&ads", "Ctrl+1", windows=P),
        Item("Mode d'entrée &Clavier", "Ctrl+2", windows=P),
        SEP,
        Item("Connecter / déconnecter les entrées M&IDI", "Shift+F12"),
        Item("&Réinitialiser les périphériques MIDI", "Ctrl+Shift+F12"),
        Item("Pa&nic", "Ctrl+F12"),
    ]),
    ("Fenêtres", "W", [
        Item("&1 - Fenêtre principale", call="_menu_main_window"),
        Item("&2 - Éditeur MIDI", "Alt+4", windows=P),
        Item("&3 - Songs", "Alt+5", windows=P),
    ]),
    ("Aide", "A", [
        Item("Aide &clavier", "F1", windows=P),
        Item("À &propos de GroovyboxIt", call="_menu_about"),
    ]),
]

# Alt+lettre déjà pris par une commande de la fenêtre (K3) : la lettre n'est
# pas donnée au menu, qui reste accessible par F10 et les flèches
TAKEN = {MAIN: set("XL45"), MIDI: {"I"}, SONGS: set()}


def title_label(title, letter, kind):
    """Titre avec « & » devant la lettre, si le titre la contient et qu'elle
    est libre dans la fenêtre ; sinon le titre seul."""
    if letter in TAKEN.get(kind, ()):
        return title
    i = title.lower().find(letter.lower())
    return title if i < 0 else title[:i] + "&" + title[i:]


def menu_letters(kind):
    """Lettres des menus de la fenêtre (libres, K3)."""
    return {letter for _t, letter, _i in MENUS if letter not in TAKEN.get(kind, ())}


# ----------------------------------------------------------------------
# Construction
# ----------------------------------------------------------------------

def install(win, kind):
    """Construit la barre de la fenêtre win (kind : MAIN, MIDI, SONGS) et la
    pose ; win._menu_items : {id wx: Item}."""
    bar = wx.MenuBar()
    win._menu_kind = kind
    win._menu_items = {}
    for title, letter, items in MENUS:
        bar.Append(_build_menu(win, kind, items), title_label(title, letter, kind))
    win.SetMenuBar(bar)
    win.Bind(wx.EVT_MENU, lambda evt: _on_menu(win, evt))
    _decorate(win, bar, kind)
    return bar


def _build_menu(win, kind, items):
    menu = wx.Menu()
    for item in items:
        if item is SEP:
            menu.AppendSeparator()
            continue
        if isinstance(item, Submenu):
            mi = menu.AppendSubMenu(_build_menu(win, kind, item.items), item.label)
        else:
            mi = menu.Append(wx.ID_ANY, item.label)
            win._menu_items[mi.GetId()] = item
        if kind not in item.windows:
            mi.Enable(False)
    return menu


def _decorate(win, bar, kind):
    """Raccourcis affichés (T1), lettres absentes des titres (Alt+W, Alt+G),
    Alt+lettre dans un menu ouvert (alternance réactive, essai de 1b1)."""
    if not gtk_menu.available():
        return
    gtk_bar = gtk_menu.bar_items(bar)
    for (title, letter, items), bar_item in zip(MENUS, gtk_bar):
        if letter not in TAKEN.get(kind, ()) and letter.lower() not in title.lower():
            gtk_menu.add_mnemonic(bar, letter, bar_item)
        _decorate_menu(win, items, bar_item)


def _decorate_menu(win, items, gtk_parent, nested=False):
    """nested : sous-menu d'un menu (Échap y remonte d'un niveau, essai de
    1b1 : GTK refermait toute la barre)."""
    gtk_menu.on_menu_alt_letter(gtk_parent, lambda letter: open_menu(win, letter),
                                keep=win, escape_to_parent=nested)
    for item, gtk_item in zip(items, gtk_menu.menu_items(gtk_parent)):
        if isinstance(item, Submenu):
            _decorate_menu(win, item.items, gtk_item, nested=True)
        elif item is not SEP and item.accel:
            gtk_menu.set_accel_text(gtk_item, item.accel)


# ----------------------------------------------------------------------
# Actions
# ----------------------------------------------------------------------

def _on_menu(win, evt):
    item = getattr(win, "_menu_items", {}).get(evt.GetId())
    if item is None:
        evt.Skip()
        return
    wx.CallAfter(run, win, item)


def run(win, item):
    """Exécute l'élément : sa méthode, sinon son raccourci rejoué par le
    clavier de la fenêtre ; annonce si le raccourci est sans effet ici."""
    if not win or (hasattr(win, "IsBeingDeleted") and win.IsBeingDeleted()):
        return
    if item.call:
        getattr(win, item.call)()
        return
    evt = key_event(item.accel)
    evt.SetEventObject(win)
    win._on_char_hook(evt)
    if evt.GetSkipped() and hasattr(win, "_show_status"):
        win._show_status(f"{item.text()} : sans effet ici")


_KEYS = {"Espace": (wx.WXK_SPACE, ord(" ")), "Entrée": (wx.WXK_RETURN, 13),
         "Échap": (wx.WXK_ESCAPE, 27), "PageUp": (wx.WXK_PAGEUP, 0),
         "PageDown": (wx.WXK_PAGEDOWN, 0)}


def key_event(accel):
    """wx.KeyEvent (EVT_CHAR_HOOK) du raccourci « Ctrl+Shift+S », tel que le
    clavier le donne : code en majuscule, caractère en minuscule sans Shift."""
    parts = accel.split("+")
    mods, key = set(parts[:-1]), parts[-1]
    evt = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    if key in _KEYS:
        code, uni = _KEYS[key]
    elif key[0] == "F" and key[1:].isdigit():
        code, uni = wx.WXK_F1 + int(key[1:]) - 1, 0
    else:
        code = ord(key.upper())
        uni = ord(key.upper() if "Shift" in mods else key.lower())
    evt.SetKeyCode(code)
    evt.SetUnicodeKey(uni)
    evt.SetControlDown("Ctrl" in mods)
    evt.SetRawControlDown("Ctrl" in mods)
    evt.SetShiftDown("Shift" in mods)
    evt.SetAltDown("Alt" in mods)
    return evt


def open_menu(win, letter):
    """Alt+lettre (K2) : ouvre le menu de la lettre, en alternance si elle est
    partagée ; False si la lettre n'est pas celle d'un menu de la fenêtre."""
    kind = getattr(win, "_menu_kind", None)
    if kind is None or letter.upper() not in menu_letters(kind):
        return False
    return gtk_menu.activate_mnemonic(win.GetMenuBar(), letter)


def open_first(win):
    """F10 (K1) : ouvre le premier menu de la barre (Fichier)."""
    if getattr(win, "_menu_kind", None) is None:
        return False
    return gtk_menu.open_item(win.GetMenuBar(), 0)


class MenuBarMixin:
    """Actions des éléments sans raccourci (fenêtre principale ; 1d1 : les
    autres fenêtres)."""

    def _menu_quit(self):
        self.Close()

    def _menu_no_effect(self):
        self._show_status("Aucun effet pour l'instant")

    def _menu_no_audio_process(self):
        self._show_status("Aucun traitement audio pour l'instant")

    def _menu_main_window(self):
        main = getattr(self, "_main", None) or self
        main.Raise()
        main._show_status("Fenêtre principale")

    def _menu_about(self):
        wx.MessageBox("GroovyboxIt\n\nGroovebox : pads, patterns, songs, MIDI et audio.\n"
                      "Prototype en Python et wxPython.", "À propos de GroovyboxIt",
                      wx.OK | wx.ICON_INFORMATION, self)
