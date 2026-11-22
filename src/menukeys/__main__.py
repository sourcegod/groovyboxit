#python3
"""
    File: src/menukeys/__main__.py
    Démonstration du paquet menukeys : python3 -m menukeys (depuis src/).
    Une petite fenêtre, sa barre de menus et un champ de saisie : F10 ou Alt
    seul ouvrent Fichier ; Alt+A alterne entre Affichage et Aide ; Alt+W
    ouvre Fenêtre (lettre absente du titre) ; Outils > Réglages est un
    sous-menu (Échap y remonte) ; les raccourcis sont affichés et lus par
    Orca, et seul le clavier de la fenêtre les déclenche (Ctrl+S annonce
    « Enregistrer » dans la barre d'état ; dans le champ, une lettre s'écrit).
    Date: Sun, 22/11/2026
    Author: Coolbrother
"""
import wx

import menukeys


class DemoFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="menukeys — démonstration", size=(520, 300))
        panel = wx.Panel(self)
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(wx.StaticText(panel, label="Champ de saisie"), 0, wx.ALL, 6)
        self.field = wx.TextCtrl(panel)
        box.Add(self.field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        panel.SetSizer(box)
        self.CreateStatusBar()

        self.commands = {}              # raccourci → texte annoncé
        accels = {}
        bar = wx.MenuBar()

        def menu(entries):
            m = wx.Menu()
            for entry in entries:
                if entry is None:
                    m.AppendSeparator()
                    continue
                label, accel = entry
                if isinstance(accel, list):                     # sous-menu
                    m.AppendSubMenu(menu(accel), label)
                    continue
                item = m.Append(wx.ID_ANY, label)
                text = label.replace("&", "")
                if accel:
                    accels[item.GetId()] = accel
                    self.commands[accel] = text
                self.Bind(wx.EVT_MENU, lambda e, t=text: self.say(t), item)
            return m

        bar.Append(menu([("&Nouveau", "Ctrl+N"), ("&Ouvrir…", "Ctrl+O"),
                         ("&Enregistrer", "Ctrl+S"), None, ("&Quitter", None)]), "&Fichier")
        bar.Append(menu([("&Annuler", "Ctrl+Z"), ("&Refaire", "Shift+Z")]), "&Edition")
        bar.Append(menu([("&Grille", "Ctrl+G"), ("&Zoom", None)]), "&Affichage")
        bar.Append(menu([("&Réglages", [("&Son", "F5"), ("&Clavier", "F6")]),
                         ("&Options…", None)]), "&Outils")
        bar.Append(menu([("&1 - Principale", None), ("&2 - Seconde", None)]), "Fenêtre")
        bar.Append(menu([("&À propos", "F1")]), "&Aide")
        self.SetMenuBar(bar)
        self.keys = menukeys.enable(self, accels=accels, letters={4: "W"})
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)

    def say(self, text):
        self.SetStatusText(text)

    def on_key(self, evt):
        accel = menukeys.accel_of(evt)
        if accel in self.commands and not (self.field.HasFocus() and "+" not in accel):
            self.say(f"{self.commands[accel]} (clavier)")
            return
        if self.keys.handle_key(evt):
            return
        evt.Skip()


def main():
    app = wx.App(False)
    DemoFrame().Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
