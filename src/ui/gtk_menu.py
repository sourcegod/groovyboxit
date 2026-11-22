#python3
"""
    File: src/ui/gtk_menu.py
    Accès GTK de la barre de menus (Phase 9 étape 1b1, docs/DESIGN.md
    § Phase 9 étape 1a, T1, K2) — par ctypes, comme gtk_listbox.py :
    - set_accel_text(item, accel) : raccourci AFFICHÉ dans l'élément de menu
      (GtkAccelLabel) et transmis à Orca (ATK), sans raccourci GTK enregistré :
      le clavier de l'appli reste seul à déclencher les commandes ;
    - add_mnemonic(window, letter, item) : lettre d'un menu dont le titre ne
      la contient pas (Fenêtres → Alt+W) ;
    - activate_mnemonic(window, letter) : ouvre le menu de la lettre comme
      Alt+lettre ; deux menus de même lettre → GTK alterne de lui-même
      (constaté en 1b1 : Alt+A = Affichage, Aide, Affichage…) ;
    - bar_items(menubar), menu_items(bar_item) : éléments GTK, dans l'ordre.
    Hors de GTK, ou si GTK est introuvable : rien (fonctions sans effet).
    Date: Sat, 21/11/2026
    Author: Coolbrother
"""
import ctypes

import wx

_gtk = None          # (libgtk-3, libglib-2.0) chargées, False si indisponibles

GDK_MOD1_MASK = 1 << 3          # Alt


def _lib():
    global _gtk
    if _gtk is None:
        try:
            g = ctypes.CDLL("libgtk-3.so.0")
            gl = ctypes.CDLL("libglib-2.0.so.0")
            V = ctypes.c_void_p
            for name, res, args in (
                    ("gtk_container_get_children", V, [V]),
                    ("gtk_menu_item_get_submenu", V, [V]),
                    ("gtk_menu_item_get_label", ctypes.c_char_p, [V]),
                    ("gtk_bin_get_child", V, [V]),
                    ("gtk_widget_get_name", ctypes.c_char_p, [V]),
                    ("gtk_widget_get_toplevel", V, [V]),
                    ("gtk_accelerator_parse", None,
                     [ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint),
                      ctypes.POINTER(ctypes.c_int)]),
                    ("gtk_accel_label_set_accel", None, [V, ctypes.c_uint, ctypes.c_int]),
                    ("gtk_accel_label_get_accel", None,
                     [V, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_int)]),
                    ("gtk_window_add_mnemonic", None, [V, ctypes.c_uint, V]),
                    ("gtk_window_mnemonic_activate", ctypes.c_int,
                     [V, ctypes.c_uint, ctypes.c_int]),
                    ("gtk_widget_get_mapped", ctypes.c_int, [V]),
                    ("gtk_widget_mnemonic_activate", ctypes.c_int, [V, ctypes.c_int]),
                    ("gtk_menu_shell_deactivate", None, [V]),
                    ("gtk_menu_shell_get_selected_item", V, [V])):
                fn = getattr(g, name)
                fn.restype, fn.argtypes = res, args
            gl.g_list_length.restype = ctypes.c_uint
            gl.g_list_length.argtypes = [V]
            gl.g_list_nth_data.restype = V
            gl.g_list_nth_data.argtypes = [V, ctypes.c_uint]
            gl.g_list_free.argtypes = [V]
            _gtk = (g, gl)
        except (OSError, AttributeError):
            _gtk = False
    return _gtk


def available():
    return "__WXGTK__" in wx.PlatformInfo and bool(_lib())


def _children(container):
    g, gl = _lib()
    lst = g.gtk_container_get_children(container)
    try:
        return [gl.g_list_nth_data(lst, i) for i in range(gl.g_list_length(lst))]
    finally:
        gl.g_list_free(lst)


def bar_items(menubar):
    """GtkMenuItem des menus d'une vraie wx.MenuBar, dans l'ordre ; [] sinon."""
    if not available() or not isinstance(menubar, wx.MenuBar):
        return []
    widget = menubar.GetGtkWidget()
    return _children(int(widget)) if widget else []


def menu_items(bar_item):
    """GtkMenuItem (séparateurs compris) du menu d'un élément de barre."""
    g, _gl = _lib()
    sub = g.gtk_menu_item_get_submenu(bar_item)
    return _children(sub) if sub else []


def label(item):
    """Libellé GTK d'un élément, sans le soulignement de la lettre."""
    g, _gl = _lib()
    text = g.gtk_menu_item_get_label(item)
    return (text or b"").decode("utf-8").replace("_", "")


def gtk_accel(accel):
    """« Ctrl+Shift+S » → « <Control><Shift>s » (syntaxe de GTK)."""
    parts = accel.split("+")
    mods = {"Ctrl": "<Control>", "Shift": "<Shift>", "Alt": "<Alt>"}
    keys = {"Espace": "space", "Entrée": "Return", "Échap": "Escape",
            "PageUp": "Page_Up", "PageDown": "Page_Down"}
    prefix = "".join(mods[p] for p in parts[:-1])
    key = parts[-1]
    return prefix + keys.get(key, key.lower() if len(key) == 1 else key)


def set_accel_text(item, accel):
    """Affiche accel dans l'élément GTK item, sans l'enregistrer ; False si
    GTK ne le comprend pas."""
    g, _gl = _lib()
    child = g.gtk_bin_get_child(item)
    if not child or g.gtk_widget_get_name(child) != b"GtkAccelLabel":
        return False
    key, mods = ctypes.c_uint(), ctypes.c_int()
    g.gtk_accelerator_parse(gtk_accel(accel).encode(), ctypes.byref(key), ctypes.byref(mods))
    if not key.value:
        return False
    g.gtk_accel_label_set_accel(child, key.value, mods.value)
    return True


def accel_text(item):
    """(touche, modificateurs) affichés par l'élément : pour les tests."""
    g, _gl = _lib()
    child = g.gtk_bin_get_child(item)
    if not child or g.gtk_widget_get_name(child) != b"GtkAccelLabel":
        return 0, 0
    key, mods = ctypes.c_uint(), ctypes.c_int()
    g.gtk_accel_label_get_accel(child, ctypes.byref(key), ctypes.byref(mods))
    return key.value, mods.value


def _toplevel(menubar):
    g, _gl = _lib()
    return g.gtk_widget_get_toplevel(int(menubar.GetGtkWidget()))


def add_mnemonic(menubar, letter, item):
    """Alt+letter ouvre aussi le menu item (lettre absente de son titre)."""
    if not available():
        return
    g, _gl = _lib()
    g.gtk_window_add_mnemonic(_toplevel(menubar), ord(letter.lower()), item)


def activate_mnemonic(menubar, letter):
    """Ouvre le menu de Alt+letter (alternance de GTK si la lettre est
    partagée) ; True si un menu l'a prise."""
    if not available() or not isinstance(menubar, wx.MenuBar):
        return False
    g, _gl = _lib()
    return bool(g.gtk_window_mnemonic_activate(_toplevel(menubar),
                                               ord(letter.lower()), GDK_MOD1_MASK))


def open_item(menubar, index):
    """Ouvre le menu n° index de la barre, comme sa lettre (F10 : le premier)."""
    items = bar_items(menubar)
    if not 0 <= index < len(items):
        return False
    g, _gl = _lib()
    return bool(g.gtk_widget_mnemonic_activate(items[index], 0))


# Rappel GTK « key-press-event » : gboolean (*)(GtkWidget*, GdkEventKey*, gpointer)
_KEY_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
GDK_SHIFT_MASK, GDK_CONTROL_MASK = 1 << 0, 1 << 2


class _GdkEventKey(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("window", ctypes.c_void_p),
                ("send_event", ctypes.c_int8), ("time", ctypes.c_uint32),
                ("state", ctypes.c_uint), ("keyval", ctypes.c_uint)]


GDK_KEY_ESCAPE = 0xff1b
GTK_MENU_DIR_PARENT = 0


def on_menu_alt_letter(parent_item, handler, keep, escape_to_parent=False):
    """Dans le menu ouvert de parent_item, Alt+lettre appelle handler(lettre) ;
    s'il rend True, la touche est prise (sinon GTK la traite). Si
    escape_to_parent (sous-menu), Échap remonte au menu du dessus, comme
    Gauche, au lieu de refermer toute la barre. Le rappel est gardé sur keep
    (la fenêtre), sinon Python le libérerait."""
    if not available():
        return
    g, _gl = _lib()
    sub = g.gtk_menu_item_get_submenu(parent_item)
    if not sub:
        return

    def _cb(_widget, event, _data):
        try:
            ev = ctypes.cast(event, ctypes.POINTER(_GdkEventKey)).contents
            # Seulement si l'on est ENTRÉ dans le sous-menu (un élément y est
            # sélectionné) : GTK ouvre de lui-même, sans y entrer, le sous-menu
            # de l'élément sélectionné (Audio, Midi), et lui envoie les touches ;
            # remonter alors le rouvrait aussitôt, Échap ne fermait plus la
            # barre (essais de 1b1) → laissé à GTK, qui ferme la barre
            if escape_to_parent and ev.keyval == GDK_KEY_ESCAPE and not ev.state & (
                    GDK_MOD1_MASK | GDK_CONTROL_MASK | GDK_SHIFT_MASK) \
                    and g.gtk_widget_get_mapped(sub) \
                    and g.gtk_menu_shell_get_selected_item(sub):
                _gobject().g_signal_emit_by_name(sub, b"move-current", GTK_MENU_DIR_PARENT)
                return 1
            if not ev.state & GDK_MOD1_MASK or ev.state & (GDK_CONTROL_MASK | GDK_SHIFT_MASK):
                return 0
            if not 0x61 <= ev.keyval <= 0x7a and not 0x41 <= ev.keyval <= 0x5a:
                return 0
            return 1 if handler(chr(ev.keyval)) else 0
        except Exception:               # jamais d'exception à travers GTK
            return 0

    cb = _KEY_CB(_cb)
    if not hasattr(keep, "_gtk_menu_callbacks"):
        keep._gtk_menu_callbacks = []
    keep._gtk_menu_callbacks.append(cb)
    _gobject().g_signal_connect_data(sub, b"key-press-event", cb, None, None, 0)


_gobj = None


def _gobject():
    global _gobj
    if _gobj is None:
        lib = ctypes.CDLL("libgobject-2.0.so.0")
        lib.g_signal_connect_data.restype = ctypes.c_ulong
        lib.g_signal_connect_data.argtypes = [ctypes.c_void_p, ctypes.c_char_p, _KEY_CB,
                                              ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
        lib.g_signal_emit_by_name.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        _gobj = lib
    return _gobj


def open_menus(menubar):
    """Indices des menus ouverts : pour les tests."""
    g, _gl = _lib()
    return [i for i, it in enumerate(bar_items(menubar))
            if g.gtk_widget_get_mapped(g.gtk_menu_item_get_submenu(it))]


def close(menubar):
    """Referme la barre (tests)."""
    if available() and isinstance(menubar, wx.MenuBar):
        g, _gl = _lib()
        g.gtk_menu_shell_deactivate(int(menubar.GetGtkWidget()))
