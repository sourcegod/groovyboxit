#python3
"""
    File: src/ui/menu_bar.py
    Barre de menus (Phase 9 étape 1b1, docs/DESIGN.md § Phase 9 étape 1a).
    - Une seule description (MENUS) pour toutes les fenêtres (K5, T2) : chaque
      fenêtre construit sa copie (un wx.MenuBar n'appartient qu'à une fenêtre),
      les éléments sans objet dans la fenêtre y sont grisés.
    - Raccourcis AFFICHÉS mais jamais enregistrés dans GTK (T1) : le clavier
      de la fenêtre reste seul à les déclencher (paquet menukeys, 2b3).
    - Un élément refait son raccourci par le vrai chemin du clavier de la
      fenêtre (T3 : jamais une copie du code), ou appelle une méthode quand
      l'action dépend du focus ou n'a pas de raccourci ; lancé après
      MENU_DELAY_MS (wx.CallLater, 3b1), menu refermé et focus revenu et lu.
    - F10 ouvre la barre (K1) ; Alt+lettre ouvre un menu, en alternance si la
      lettre est partagée (K2, fait par GTK) ; une lettre déjà prise par une
      commande de la fenêtre n'est pas donnée au menu (K3).
    Date: Sat, 21/11/2026
    Author: Coolbrother
"""
import wx

import menukeys
from menukeys.keys import accel_of, key_event   # noqa: F401 (rejeu des raccourcis)

MAIN, MIDI, SONGS = "main", "midi", "songs"
ALL = (MAIN, MIDI, SONGS)


class Item:
    """Élément de menu : label (avec « & » devant sa lettre), accel (raccourci
    affiché et rejoué, ou None), call (méthode de la fenêtre, sinon le
    raccourci est rejoué), windows (fenêtres où il est actif), main (le
    raccourci est rejoué par le clavier de la fenêtre principale, depuis
    toutes les fenêtres : essai de 1d1, Fichier accessible de partout), args
    (arguments de la méthode : Phase 9 étape 3b1, pas des volumes)."""

    def __init__(self, label, accel=None, call=None, windows=ALL, main=False, args=()):
        self.label, self.accel, self.call, self.windows = label, accel, call, tuple(windows)
        self.main, self.args = main, tuple(args)

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

P, PM, S = (MAIN,), (MAIN, MIDI), (SONGS,)

# Menus : (titre, lettre de Alt+lettre, éléments). Fenêtres d'un élément : celles
# dont le clavier connaît son raccourci (1d1 : relevé dans KeyManager,
# mew_keymap._on_key, SongWindow._on_key) ; ailleurs, il est grisé (K5).
MENUS = [
    ("Fichier", "F", [
        Item("&Nouveau projet", "Ctrl+N", main=True),
        Item("&Ouvrir un projet…", "Ctrl+O", main=True),
        Item("&Enregistrer", "Ctrl+S", main=True),
        Item("Enregistrer &sous…", "Ctrl+Shift+S", main=True),
        SEP,
        Item("Enre&gistrer le song", "Ctrl+W", windows=S),
        Item("D&upliquer le song…", "Ctrl+Shift+W", windows=S),
        SEP,
        Item("&Importer un fichier MIDI…", "Alt+Shift+I", windows=PM),
        Item("Exporter en &MIDI…", "Alt+Shift+E"),
        Item("Exporter en &audio…", "Alt+Shift+W"),
        SEP,
        Item("&Quitter", "Alt+F4", call="_menu_quit"),
    ]),
    ("Edition", "E", [
        Item("&Annuler", "Ctrl+Z", windows=PM),
        Item("&Refaire", "Shift+Z", windows=PM),
        Item("&Historique des annulations…", "Ctrl+Shift+Z", windows=PM),
        SEP,
        # Phase 9 étape 3b1 (§ 3a E1) : Suppr par méthode (focus de la liste
        # des pistes dans la principale ; l'éditeur MIDI rejoue la touche)
        Item("Co&uper", "Ctrl+X", windows=PM),
        Item("&Copier", "Ctrl+C", windows=PM),
        Item("Co&ller", "Ctrl+V", windows=PM),
        Item("Coller par &fusion", "Shift+V", windows=P),
        Item("&Supprimer", "Suppr", call="_menu_delete", windows=PM),
        Item("Supprimer a&vec presse-papier", "Ctrl+D", windows=P),
        Item("&Effacer sans presse-papier", "Ctrl+Suppr", windows=P),
        SEP,
        Item("Sélect&ionner tout", "Ctrl+A", windows=PM),
        Item("Tout &désélectionner", "Ctrl+Shift+A", windows=PM),
        Submenu("Sélecti&on", [
            Item("&Sélectionner la piste courante", "Shift+Espace",
                 call="_menu_select_track", args=(True,), windows=P),
            Item("&Désélectionner la piste courante", "Shift+Espace",
                 call="_menu_select_track", args=(False,), windows=P),
            Item("Sélection des &pistes…", "Ctrl+Entrée", call="_track_select_dialog", windows=P),
        ]),
        SEP,
        Item("Renommer la &piste…", "F2", call="_rename_track", windows=P),
        Item("Renommer le pa&ttern…", "F2", call="_rename_pattern", windows=P),
        Item("Renommer le so&ng…", "F2", call="_rename_song", windows=S),
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
        SEP,
        # Métronome (avenant 3b2, A2 ; Régler le tempo… : 3d1)
        Submenu("&Métronome", [
            Item("&Click On / Off", "C", windows=P),
            Item("&Tap Tempo", "H", call="_menu_tap_tempo", windows=P),
            Item("&BPM +5", "(", windows=P),
            Item("BP&M −5", ")", windows=P),
            Item("&Régler le tempo…", call="_menu_set_tempo", windows=P),
        ]),
        SEP,
        # Limiteurs (avenant 3b4, B1)
        Submenu("L&imiteurs", [
            Item("Limiteur &gauche ici", "I", windows=P),
            Item("Limiteur dr&oit ici", "O", windows=P),
            Item("Limiteur gauche au dé&but", "Shift+I", windows=P),
            Item("Limiteur droit à la &fin", "Shift+O", windows=P),
            SEP,
            Item("&Assigner la boucle aux limiteurs", "Alt+Début", windows=P),
            Item("Assigner les &limiteurs à la boucle", "Alt+Fin", windows=P),
        ]),
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
        SEP,
        Item("Au limiteur gauc&he", "Début", windows=P),
        Item("Au limiteur dr&oit", "Fin", windows=P),
        Item("Au début de &la boucle", "Shift+Début", windows=P),
        Item("À la f&in de la boucle", "Shift+Fin", windows=P),
    ]),
    ("Insertion", "I", [
        Item("&Tempos…", "Alt+Shift+T", windows=PM),
    ]),
    ("Piste", "T", [
        Item("Piste pré&cédente", call="_menu_step_track", args=(-1,), windows=P),
        Item("Piste suiva&nte", call="_menu_step_track", args=(1,), windows=P),
        SEP,
        Item("&Propriétés de la piste…", "Ctrl+Shift+T", windows=P),
        SEP,
        # avenant 3b2 (A1) : piste courante quel que soit le focus
        Item("M&ute de la piste", "X", call="_menu_track_mute", windows=P),
        Item("&Démuter toutes les pistes", "Shift+X", call="_menu_unmute_all", windows=P),
        Item("S&olo de la piste", "S", call="_menu_track_solo", windows=P),
        Item("Désactiver tous les So&los", "Shift+S", call="_menu_unsolo_all", windows=P),
        SEP,
        Item("&Mute exclusif", "F3", windows=P),
        Item("&Solo exclusif", "F4", windows=P),
        Item("&Réinitialiser les Mute et Solo", "F5", windows=P),
    ]),
    # Pattern (Phase 9 étape 3b1, § 3a E5) : Alt+P ; Ctrl+W et Ctrl+Shift+W
    # viennent de Fichier
    ("Pattern", "P", [
        Submenu("&Changer de pattern", [
            Item("Pattern &précédent", call="_menu_step_pattern", args=(-1,), windows=P),
            Item("Pattern &suivant", call="_menu_step_pattern", args=(1,), windows=P),
            Item("&Choisir un pattern…", call="_menu_choose_pattern", windows=P),   # 3d1
        ]),
        Item("&Propriétés du pattern…", "Alt+Entrée", call="_pattern_properties_dialog",
             windows=P),
        SEP,
        Item("&Enregistrer le pattern", "Ctrl+W", windows=P),
        Item("&Dupliquer le pattern…", "Ctrl+Shift+W", windows=P),
        SEP,
        Submenu("&Redimensionner", [
            Item("&Doubler", "Ctrl+F", windows=P),
            Item("D&iviser", "Shift+F", windows=P),
            Item("&Vider le pattern", "Shift+Suppr", call="_menu_reset_pattern", windows=P),
            Item("&Redimensionner le pattern…", call="_menu_resize_pattern", windows=P),
        ]),
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
    # Mixer (Phase 9 étape 3b1, § 3a E6) : Alt+M ; pas des raccourcis ;
    # piste courante par méthode, quel que soit le focus
    ("Mixer", "M", [
        Submenu("&Volume", [
            Item("Volume &global +1", "Ctrl+Haut", windows=P),
            Item("Volume glo&bal −1", "Ctrl+Bas", windows=P),
            Item("&Régler le volume global…", call="_menu_set_master_volume", windows=P),
            SEP,
            Item("Volume de la &piste +5", "Alt+Haut", call="_menu_track_volume",
                 args=(5,), windows=P),
            Item("Volume de la pis&te −5", "Alt+Bas", call="_menu_track_volume",
                 args=(-5,), windows=P),
            Item("Régler le &volume de la piste…", call="_menu_set_track_volume", windows=P),
        ]),
        Submenu("&Pan", [
            Item("Pan global à &droite +1", "Ctrl+Droite", windows=P),
            Item("Pan global à &gauche −1", "Ctrl+Gauche", windows=P),
            Item("Rég&ler le pan global…", call="_menu_set_master_pan", windows=P),
            SEP,
            Item("Pan de la piste à d&roite +10", "Alt+Droite", call="_menu_track_pan",
                 args=(10,), windows=P),
            Item("Pan de la piste à ga&uche −10", "Alt+Gauche", call="_menu_track_pan",
                 args=(-10,), windows=P),
            Item("Régler le &pan de la piste…", call="_menu_set_track_pan", windows=P),
        ]),
        SEP,
        Item("Volume et pan globaux &normaux", "Ctrl+Retour arrière",
             call="_menu_master_mix_reset", windows=P),
        Item("Volume et pan de la pis&te normaux", "Shift+Retour arrière",
             call="_menu_track_mix_reset", windows=P),
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
        Item("&2 - Éditeur MIDI", "Alt+4", call="_menu_midi_editor"),
        Item("&3 - Songs", "Alt+5", call="_menu_songs"),
    ]),
    ("Aide", "A", [
        Item("Aide &clavier", "F1", call="_menu_help"),
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


NOTHING_HERE = "&Aucune commande dans cette fenêtre"


def _build_menu(win, kind, items):
    """Menu de la fenêtre kind ; un menu dont tous les éléments seraient
    grisés reçoit en dernier un élément actif « Aucune commande dans cette
    fenêtre » (essai de 1d1 : GTK ne prenait pas le clavier dans un tel
    menu, Gauche / Droite et Échap retombaient sur la fenêtre)."""
    menu = wx.Menu()
    if not any(it is not SEP and kind in it.windows for it in items):
        items = list(items) + [SEP, Item(NOTHING_HERE, call="_menu_nothing_here")]
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
    """Clavier de la barre confié au paquet autonome menukeys (Phase 9
    étape 2b3) : raccourcis affichés, Alt seul, Alt+lettre et alternance,
    lettres absentes des titres (Alt+W, Alt+G), Échap de sous-menu."""
    accels = {i: it.accel for i, it in win._menu_items.items() if it.accel}
    letters = {i: letter for i, (title, letter, _it) in enumerate(MENUS)
               if letter.lower() not in title.lower()}
    menukeys.enable(win, accels=accels, letters=letters, taken=TAKEN.get(kind, ()))


# ----------------------------------------------------------------------
# Actions
# ----------------------------------------------------------------------

# Délai avant l'action d'un élément (Phase 9 étape 3b1, essai : Piste
# suivante, focus sur la grille, Orca perdait le focus) : le menu refermé,
# GTK rend le focus à la fenêtre et Orca doit le lire avant le flot de
# changements de l'action (listes des pistes et des pads, barre d'état)
MENU_DELAY_MS = 150


def _on_menu(win, evt):
    item = getattr(win, "_menu_items", {}).get(evt.GetId())
    if item is None:
        evt.Skip()
        return
    wx.CallLater(MENU_DELAY_MS, run, win, item)


def run(win, item):
    """Exécute l'élément : sa méthode, sinon son raccourci rejoué par le
    clavier de la fenêtre ; annonce si le raccourci est sans effet ici."""
    if not win or (hasattr(win, "IsBeingDeleted") and win.IsBeingDeleted()):
        return
    if item.call:
        getattr(win, item.call)(*item.args)
        return
    replay(win, item.accel, item.text(), main=item.main)


def replay(win, accel, text, main=False):
    """Rejoue le raccourci accel par le clavier de la fenêtre (T3) ; annonce
    « text : sans effet ici » si la fenêtre ne le prend pas."""
    evt = key_event(accel)
    evt.SetEventObject(win)
    # clavier de la fenêtre : MainWindow._on_char_hook, éditeur MIDI et
    # Songs : _on_key (1d1)
    if main and win._menu_main() is not win:        # Fichier depuis l'éditeur, Songs
        run_on_main(win, evt)
        return
    handler = getattr(win, "_on_char_hook", None) or win._on_key
    handler(evt)
    if evt.GetSkipped():
        _status(win, f"{text} : sans effet ici")


def _status(win, msg):
    """Barre d'état de la fenêtre (principale : _show_status ; éditeur MIDI
    et Songs : _set_status)."""
    fn = getattr(win, "_show_status", None) or getattr(win, "_set_status", None)
    if fn:
        fn(msg)


def run_on_main(win, evt):
    """Raccourci d'un élément Fichier (Item.main) depuis l'éditeur MIDI ou
    Songs : joué par le clavier de la fenêtre principale, puis la fenêtre
    d'origine reprend le focus (essai de 1d1 : les boîtes de la fenêtre
    principale — Ouvrir, Enregistrer sous, Annuler — le lui laissaient)."""
    main = win._menu_main()
    main._on_menu_key(evt)
    _back_to(win, main)


BACK_DELAY_MS = 200


def _back_to(win, main):
    """Rend le focus à win, sauf si win ou la fenêtre principale se ferme.
    Différé (essai de 1d1) : une boîte modale refermée, GTK et le
    gestionnaire de fenêtres réactivent ensuite sa fenêtre parente (la
    principale) ; un Raise immédiat était aussitôt défait."""
    if win is main:
        return

    def _raise():
        if not win or not main or main.IsBeingDeleted() or win.IsBeingDeleted():
            return
        win.Raise()                     # active la fenêtre, GTK y rend son focus
    wx.CallLater(BACK_DELAY_MS, _raise)


def _main_items():
    return {it.accel: it for _t, _l, items in MENUS for it in items
            if it is not SEP and not isinstance(it, Submenu) and it.main and it.accel}


def handle_key(win, evt):
    """Clavier de l'éditeur MIDI et de Songs (1d1), en tête de _on_key :
    Alt+lettre d'un menu (K2 ; les lettres prises par une commande de la
    fenêtre ne sont pas des lettres de menu, K3), F10 (K1), raccourcis du
    menu Fichier (Ctrl+N, Ctrl+O, Ctrl+S, Ctrl+Shift+S) joués par la fenêtre
    principale (essai de 1d1). True si la touche est prise."""
    key, ukey = evt.GetKeyCode(), evt.GetUnicodeKey()
    ctrl, shift, alt = evt.ControlDown(), evt.ShiftDown(), evt.AltDown()
    if alt and not (ctrl or shift) and 0 < ukey < 128 and chr(ukey).isalpha():
        return open_menu(win, chr(ukey))
    if key == wx.WXK_F10 and not (ctrl or shift or alt):
        return open_first(win)
    if getattr(win, "_menu_kind", MAIN) != MAIN and accel_of(evt) in _main_items():
        run_on_main(win, evt)
        return True
    return False


def open_menu(win, letter):
    """Alt+lettre (K2) : ouvre le menu de la lettre, en alternance si elle est
    partagée ; False si la lettre n'est pas celle d'un menu de la fenêtre."""
    if getattr(win, "_menu_kind", None) is None or getattr(win, "_menukeys", None) is None:
        return False
    return win._menukeys.open_menu(letter)


def open_first(win):
    """F10 (K1) : ouvre le premier menu de la barre (Fichier)."""
    if getattr(win, "_menu_kind", None) is None or getattr(win, "_menukeys", None) is None:
        return False
    return win._menukeys.open_first()


class MenuBarMixin:
    """Actions des éléments appelés par méthode, pour les trois fenêtres
    (1d1) : la fenêtre principale est self, ou le parent de l'éditeur MIDI
    et de Songs."""

    def _menu_main(self):
        return self if getattr(self, "_menu_kind", MAIN) == MAIN else self._parent

    def _menu_quit(self):
        main = self._menu_main()
        main.Close()
        _back_to(self, main)            # Annuler : retour à la fenêtre d'origine

    def _menu_nothing_here(self):
        _status(self, "Aucune commande de ce menu dans cette fenêtre")

    def _menu_no_effect(self):
        _status(self, "Aucun effet pour l'instant")

    def _menu_delete(self):
        """Edition > Supprimer : la touche Suppr de la fenêtre (éditeur MIDI) ;
        la fenêtre principale a sa méthode (MainMenuActions, 3b1)."""
        replay(self, "Suppr", "Supprimer")

    def _menu_no_audio_process(self):
        _status(self, "Aucun traitement audio pour l'instant")

    def _menu_main_window(self):
        main = self._menu_main()
        main.Raise()
        main.SetFocus()
        main._show_status("Fenêtre principale")

    def _menu_midi_editor(self):
        self._menu_main()._open_midi_editor_window()

    def _menu_songs(self):
        self._menu_main()._open_song_window()

    def _menu_help(self):
        from .dialogs import KeyboardHelpDialog
        dlg = KeyboardHelpDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def _menu_about(self):
        wx.MessageBox("GroovyboxIt\n\nGroovebox : pads, patterns, songs, MIDI et audio.\n"
                      "Prototype en Python et wxPython.", "À propos de GroovyboxIt",
                      wx.OK | wx.ICON_INFORMATION, self)
