#python3
"""
    Paquet menukeys — le clavier d'une barre de menus wxPython sous GTK3,
    accessible (Orca) et « comme sous Windows » (GroovyboxIt, Phase 9
    étapes 1 et 2 ; paquet depuis 2b3, docs/DESIGN.md § Phase 9 étape 2a,
    avenant 2b2).

    Paquet AUTONOME : il n'importe rien de GroovyboxIt et peut être copié
    tel quel dans une autre application wxPython. Dépendances : wxPython
    (GTK3), ctypes. Hors de GTK, ou GTK introuvable : sans effet, la barre
    reste celle de wx.

    Usage, une fois la barre posée (frame.SetMenuBar) :

        import menukeys
        mk = menukeys.enable(frame, accels={item.GetId(): "Ctrl+S"},
                             letters={3: "W"}, taken="X")
        # dans le clavier de la fenêtre (EVT_CHAR_HOOK), APRÈS ses commandes :
        if mk.handle_key(evt):
            return

    Ce que la barre gagne :
    - raccourcis AFFICHÉS dans les éléments (« Enregistrer… Ctrl+S ») et lus
      par Orca, sans être enregistrés dans GTK : le clavier de la fenêtre
      reste seul à déclencher les commandes (pas de double déclenchement,
      rien dans les champs de saisie) ;
    - F10 et **Alt seul** (appuyé puis relâché sans autre touche ; pas
      AltGr) ouvrent le premier menu ; Alt seul, menu ouvert, referme ;
    - Alt+lettre ouvre son menu, aussi menu ouvert ; une lettre partagée
      ALTERNE entre ses menus (Alt+A : Affichage, Aide, Affichage…) ;
      `letters` donne une lettre à un menu dont le titre ne la contient pas,
      `taken` retire les lettres prises par les commandes de la fenêtre ;
    - Échap dans un sous-menu où l'on est entré remonte d'un niveau ;
      ailleurs, il ferme la barre.
    Recettes d'accessibilité (dans la doc de GroovyboxIt) : garder au moins
    un élément actif par menu (GTK ne prend pas le clavier dans un menu tout
    grisé) ; après une boîte modale d'une AUTRE fenêtre, rendre le focus en
    différé (wx.CallLater).

    - menukeys.keys : key_event, accel_of, gtk_accel ;
    - menukeys.gtk_menu : accès GTK par ctypes ;
    - python3 -m menukeys : fenêtre de démonstration.

    Date: Sun, 22/11/2026
    Author: Coolbrother
"""
import wx

from . import gtk_menu
from .keys import accel_of, gtk_accel, key_event

__all__ = ["enable", "MenuKeys", "key_event", "accel_of", "gtk_accel", "title_letter"]


def title_letter(label):
    """Lettre d'un titre wx (« &Fichier » → « F », « Pis&te » → « T »), ou
    None ; « && » est un « & » écrit, pas une lettre."""
    i = 0
    while True:
        i = label.find("&", i)
        if i < 0 or i + 1 >= len(label):
            return None
        if label[i + 1] != "&":
            return label[i + 1].upper()
        i += 2


class MenuKeys:
    """Clavier de la barre de menus d'une wx.Frame (voir le paquet)."""

    def __init__(self, frame, accels=None, letters=None, taken=()):
        self.frame = frame
        self.bar = frame.GetMenuBar()
        self.accels = dict(accels or {})
        self.extra_letters = {i: l.upper() for i, l in (letters or {}).items()}
        self.taken = {l.upper() for l in taken}
        self.letters = set()
        for i in range(self.bar.GetMenuCount() if self.bar else 0):
            letter = title_letter(self.bar.GetMenuLabel(i)) or self.extra_letters.get(i)
            if letter and letter not in self.taken:
                self.letters.add(letter)
        self.alt_state = gtk_menu.AltState()
        if self.bar and gtk_menu.available():
            self._decorate()

    # --- installation -------------------------------------------------

    def _decorate(self):
        frame, bar = self.frame, self.bar
        gtk_menu.watch_alt(gtk_menu.toplevel(bar), self.alt_state,
                           lambda: wx.CallAfter(self._alt_alone), keep=frame)
        for i, bar_item in enumerate(gtk_menu.bar_items(bar)):
            letter = self.extra_letters.get(i)
            if letter and letter not in self.taken:
                gtk_menu.add_mnemonic(bar, letter, bar_item)
            self._decorate_menu(bar.GetMenu(i), bar_item, nested=False)

    def _decorate_menu(self, menu, gtk_parent, nested):
        frame = self.frame
        gtk_menu.watch_alt(gtk_menu.submenu(gtk_parent), self.alt_state,
                           lambda: wx.CallAfter(self._alt_alone_in_menu), keep=frame)
        gtk_menu.on_menu_alt_letter(gtk_parent, self.open_menu, keep=frame,
                                    escape_to_parent=nested)
        for item, gtk_item in zip(menu.GetMenuItems(), gtk_menu.menu_items(gtk_parent)):
            if item.GetSubMenu() is not None:
                self._decorate_menu(item.GetSubMenu(), gtk_item, nested=True)
            elif item.GetId() in self.accels:
                gtk_menu.set_accel_text(gtk_item, self.accels[item.GetId()])

    # --- Alt seul -----------------------------------------------------

    def _alive(self):
        return bool(self.frame) and not self.frame.IsBeingDeleted()

    def _alt_alone(self):
        """Alt seul relâché dans la fenêtre : premier menu, si la fenêtre est
        toujours là et active (retour par Alt+Tab : rien)."""
        if self._alive() and self.frame.IsActive():
            self.open_first()

    def _alt_alone_in_menu(self):
        """Alt seul relâché dans un menu ouvert : la barre se referme."""
        if self._alive():
            self.close()

    # --- commandes ----------------------------------------------------

    def open_menu(self, letter):
        """Ouvre le menu de Alt+lettre (alternance si la lettre est partagée) ;
        False si ce n'est pas une lettre de menu de la fenêtre."""
        if not letter or letter.upper() not in self.letters:
            return False
        return gtk_menu.activate_mnemonic(self.bar, letter)

    def open_first(self):
        """Ouvre le premier menu (F10, Alt seul)."""
        return gtk_menu.open_item(self.bar, 0) if self.bar else False

    def close(self):
        gtk_menu.close(self.bar)

    def open_menus(self):
        """Indices des menus ouverts."""
        return gtk_menu.open_menus(self.bar) if gtk_menu.available() else []

    def handle_key(self, evt):
        """Clavier de la fenêtre (EVT_CHAR_HOOK), à appeler après ses propres
        commandes : Alt+lettre d'un menu, F10. True si la touche est prise."""
        key, ukey = evt.GetKeyCode(), evt.GetUnicodeKey()
        ctrl, shift, alt = evt.ControlDown(), evt.ShiftDown(), evt.AltDown()
        if alt and not (ctrl or shift) and 0 < ukey < 128 and chr(ukey).isalpha():
            return self.open_menu(chr(ukey))
        if key == wx.WXK_F10 and not (ctrl or shift or alt):
            return self.open_first()
        return False


def enable(frame, accels=None, letters=None, taken=()):
    """Donne à la barre de menus de frame (déjà posée) le clavier du paquet ;
    rend l'objet MenuKeys, gardé aussi sur frame._menukeys.
    accels : {id d'élément wx : « Ctrl+S »} — raccourcis affichés ;
    letters : {indice de menu : lettre} — lettres absentes des titres ;
    taken : lettres prises par les commandes Alt+lettre de la fenêtre."""
    mk = MenuKeys(frame, accels, letters, taken)
    frame._menukeys = mk
    return mk
