#python3
"""
    File: gtk_listbox.py
    Sélection d'une ligne de wx.ListBox qui déplace aussi le curseur clavier
    (Phase 8 étape 5d2, trouvé à l'essai de 5d1 par l'utilisateur ;
    docs/DESIGN.md § Phase 8 étape 5).

    Sous wxGTK (3.2), ListBox.SetSelection sélectionne la ligne sans y
    placer le curseur du GtkTreeView : les flèches repartent de l'ancienne
    ligne (souvent la première), et Haut ne remonte pas depuis la ligne
    sélectionnée. gtk_tree_view_set_cursor place le curseur, sans prendre le
    focus ni émettre d'événement wx (la ligne est déjà sélectionnée).
    Ailleurs que sous GTK, ou si GTK est introuvable : SetSelection seul.
    Date: Mon, 02/11/2026
    Author: Coolbrother
"""

import ctypes

import wx

_gtk = None          # libgtk-3 chargée, False si indisponible


def _lib():
    global _gtk
    if _gtk is None:
        try:
            lib = ctypes.CDLL("libgtk-3.so.0")
            lib.gtk_bin_get_child.restype = ctypes.c_void_p
            lib.gtk_bin_get_child.argtypes = [ctypes.c_void_p]
            lib.gtk_widget_get_name.restype = ctypes.c_char_p
            lib.gtk_widget_get_name.argtypes = [ctypes.c_void_p]
            lib.gtk_tree_path_new_from_string.restype = ctypes.c_void_p
            lib.gtk_tree_path_new_from_string.argtypes = [ctypes.c_char_p]
            lib.gtk_tree_path_free.argtypes = [ctypes.c_void_p]
            lib.gtk_tree_view_set_cursor.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                     ctypes.c_void_p, ctypes.c_int]
            _gtk = lib
        except (OSError, AttributeError):
            _gtk = False
    return _gtk


def _tree_view(listbox):
    """GtkTreeView d'une wx.ListBox (enfant de son GtkScrolledWindow), ou None."""
    lib = _lib()
    if not lib or "__WXGTK__" not in wx.PlatformInfo or not hasattr(listbox, "GetGtkWidget"):
        return None
    widget = listbox.GetGtkWidget()
    if not widget:
        return None
    child = lib.gtk_bin_get_child(int(widget))
    if not child or lib.gtk_widget_get_name(child) != b"GtkTreeView":
        return None
    return child


def select_with_cursor(listbox, idx):
    """Sélectionne la ligne idx de listbox et y place le curseur clavier."""
    listbox.SetSelection(idx)
    if not 0 <= idx < listbox.GetCount():
        return
    tree = _tree_view(listbox)
    if tree is None:
        return
    lib = _lib()
    path = lib.gtk_tree_path_new_from_string(str(idx).encode())
    try:
        lib.gtk_tree_view_set_cursor(tree, path, None, 0)
    finally:
        lib.gtk_tree_path_free(path)


def cursor_row(listbox):
    """Ligne du curseur clavier (GTK), ou None : pour les tests."""
    tree = _tree_view(listbox)
    if tree is None:
        return None
    lib = _lib()
    lib.gtk_tree_view_get_cursor.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                                             ctypes.c_void_p]
    lib.gtk_tree_path_to_string.restype = ctypes.c_char_p
    lib.gtk_tree_path_to_string.argtypes = [ctypes.c_void_p]
    path = ctypes.c_void_p()
    lib.gtk_tree_view_get_cursor(tree, ctypes.byref(path), None)
    if not path.value:
        return None
    try:
        return int(lib.gtk_tree_path_to_string(path))
    finally:
        lib.gtk_tree_path_free(path)
