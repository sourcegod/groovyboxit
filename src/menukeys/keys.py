#python3
"""
    File: src/menukeys/keys.py
    Paquet menukeys — raccourcis écrits « Ctrl+Shift+S » (GroovyboxIt,
    Phase 9 étapes 1b1-1d1 ; réunis ici en 2b3). AUTONOME : wx seulement.
    - key_event(accel) : wx.KeyEvent (EVT_CHAR_HOOK) du raccourci, tel que le
      clavier le donne (pour rejouer un raccourci depuis un menu) ;
    - accel_of(evt) : l'inverse, pour les lettres, chiffres et F1-F12 ;
    - gtk_accel(accel) : la même chose dans la syntaxe de GTK
      (« <Control><Shift>s »).
    Noms de touches : Ctrl, Shift, Alt ; Espace, Entrée, Échap, PageUp,
    PageDown ; F1 à F12 ; une lettre ou un chiffre.
    Date: Sun, 22/11/2026
    Author: Coolbrother
"""
import wx

_KEYS = {"Espace": (wx.WXK_SPACE, ord(" ")), "Entrée": (wx.WXK_RETURN, 13),
         "Échap": (wx.WXK_ESCAPE, 27), "PageUp": (wx.WXK_PAGEUP, 0),
         "PageDown": (wx.WXK_PAGEDOWN, 0)}

_GTK_KEYS = {"Espace": "space", "Entrée": "Return", "Échap": "Escape",
             "PageUp": "Page_Up", "PageDown": "Page_Down"}

_GTK_MODS = {"Ctrl": "<Control>", "Shift": "<Shift>", "Alt": "<Alt>"}


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


def accel_of(evt):
    """« Ctrl+Shift+S » d'un événement clavier (lettres, chiffres, F1-F12),
    None pour les autres touches."""
    key = evt.GetKeyCode()
    if ord("A") <= key <= ord("Z") or ord("0") <= key <= ord("9"):
        name = chr(key)
    elif wx.WXK_F1 <= key <= wx.WXK_F12:
        name = f"F{key - wx.WXK_F1 + 1}"
    else:
        return None
    mods = [m for m, down in (("Ctrl", evt.ControlDown()), ("Alt", evt.AltDown()),
                              ("Shift", evt.ShiftDown())) if down]
    return "+".join(mods + [name])


def gtk_accel(accel):
    """« Ctrl+Shift+S » → « <Control><Shift>s » (syntaxe de GTK)."""
    parts = accel.split("+")
    prefix = "".join(_GTK_MODS[p] for p in parts[:-1])
    key = parts[-1]
    return prefix + _GTK_KEYS.get(key, key.lower() if len(key) == 1 else key)
