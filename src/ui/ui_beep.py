#python3
"""
    File: src/ui/ui_beep.py
    Bip des boîtes d'alerte et de question depuis n'importe quelle fenêtre
    (Phase 8 étape 20b1, docs/DESIGN.md § Phase 8 étape 20a, B3) : le bip
    passe par la fenêtre principale (MainWindow._alert_beep, pilote audio de
    l'appli et audio_beep) ; trouvée en remontant les parents de window, sinon
    la fenêtre de tête de l'appli ; wx.Bell() en dernier recours.
    Date: Fri, 20/11/2026
    Author: Coolbrother
"""
import wx


def _beeper(window):
    w = window
    while w is not None:
        if callable(getattr(w, "_alert_beep", None)):
            return w
        w = w.GetParent() if hasattr(w, "GetParent") else None
    app = wx.GetApp()
    top = app.GetTopWindow() if app is not None else None
    if top is not None and callable(getattr(top, "_alert_beep", None)):
        return top
    return None


def alert(window=None):
    """Bip d'alerte ou de question (audio_beep.ALERT) avant une boîte."""
    beeper = _beeper(window)
    if beeper is None:
        wx.Bell()
        return
    beeper._alert_beep()
