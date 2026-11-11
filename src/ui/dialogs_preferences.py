#python3
"""
    File: src/ui/dialogs_preferences.py
    Dialogue des Préférences à onglets (Phase 8 étape 10d1, docs/DESIGN.md
    § Phase 8 étape 10a P3-P8) : Général, Matériel (étape 11), Audio, Midi,
    Projet, Raccourcis et Divers (plus tard).
    - Le focus sur l'onglet : Gauche / Droite passent à l'onglet voisin ;
      Ctrl+Tab / Ctrl+Shift+Tab depuis n'importe quel champ : onglet suivant /
      précédent, en boucle, le focus posé sur l'onglet (annoncé par Orca).
    - Ok / Annuler / Appliquer : Ok et Appliquer passent les réglages changés
      à on_apply(changes) ; changes = {clé: valeur}, None = clé retirée
      (retour à la valeur de data/config.json) : un réglage égal à sa valeur
      par défaut est passé à None, preferences.json ne garde que les écarts.
    - Bouton « Valeurs par défaut » au bas des onglets réglables (Phase 8
      étape 10f2) : remet les champs de l'onglet aux valeurs par défaut,
      sans rien appliquer (Ok ou Appliquer ensuite).
    Date: Wed, 11/11/2026
    Author: Coolbrother
"""
import wx

from app_config import AppConfig


class PreferencesDialog(wx.Dialog):
    """Préférences de l'utilisateur, lues dans cfg (AppConfig)."""

    TAB_LABELS = ["Général", "Matériel", "Audio", "Midi", "Projet", "Raccourcis", "Divers"]

    STARTUP_LABELS = ["Ouvrir le dernier projet", "Nouveau projet"]     # AppConfig.STARTUP_CHOICES
    BANK_SELECT_LABELS = ["GS (MSB seul)", "MMA (MSB × 128 + LSB)"]
    BANK_SELECT_VALUES = ["gs", "mma"]

    # Clés réglées par chaque onglet (bouton « Valeurs par défaut », 10f2)
    TAB_KEYS = {
        "Général": ("startup", "autoplay", "explorer_autoplay"),
        "Audio":   ("live_limiter", "fluidsynth", "sfizz", "fluidsynth_gain",
                    "sfizz_gain", "master_volume", "master_pan"),
        "Midi":    ("midi_bank_select",),
        "Projet":  ("app_projects_dir", "projects_dir", "app_banks_dir", "user_banks_dir"),
    }

    # (clé, libellé) des chemins de l'onglet Projet (P8)
    PATH_FIELDS = [
        ("app_projects_dir", "Projets de l'appli (démos) :"),
        ("projects_dir",     "Projets de l'utilisateur :"),
        ("app_banks_dir",    "Banques de l'appli :"),
        ("user_banks_dir",   "Banques de l'utilisateur :"),
    ]

    def __init__(self, parent, cfg, on_apply=None, page=0):
        super().__init__(parent, title="Préférences",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._cfg      = cfg
        self._on_apply = on_apply
        self._dir_dialog = None        # fabrique de wx.DirDialog (tests)

        self._book = wx.Notebook(self)
        self._pages = {}
        builders = {
            "Général": self._build_general,
            "Matériel": lambda p: self._build_later(p, "Les pilotes et les périphériques audio et "
                                                       "MIDI viendront à l'étape 11."),
            "Audio": self._build_audio,
            "Midi": self._build_midi,
            "Projet": self._build_project,
            "Raccourcis": lambda p: self._build_later(p, "À compléter plus tard."),
            "Divers": lambda p: self._build_later(p, "À compléter plus tard."),
        }
        for label in self.TAB_LABELS:
            panel = wx.Panel(self._book)
            builders[label](panel)
            self._book.AddPage(panel, label)
            self._pages[label] = panel

        # Valeurs par défaut (10f2) : bouton créé en dernier, au bas de l'onglet
        self._defaults = self.values_of(cfg.defaults_only())
        self._default_btns = {}
        for label in self.TAB_KEYS:
            panel = self._pages[label]
            btn = wx.Button(panel, label="Valeurs par défaut")
            btn.SetName(f"Valeurs par défaut — onglet {label}")
            btn.Bind(wx.EVT_BUTTON, lambda e, t=label: self.restore_defaults(t))
            panel.GetSizer().Add(btn, 0, wx.LEFT | wx.BOTTOM, 10)
            self._default_btns[label] = btn

        ok_btn = wx.Button(self, wx.ID_OK, "Ok")
        ok_btn.SetDefault()
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        self._apply_btn = wx.Button(self, wx.ID_APPLY, "Appliquer")
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.AddButton(self._apply_btn)
        btn_sizer.Realize()

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(self._book, 1, wx.EXPAND | wx.ALL, 8)
        vbox.Add(btn_sizer,  0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self.SetMinSize(self.GetSize())
        self.Centre()

        self._baseline = self.values()
        ok_btn.Bind(wx.EVT_BUTTON, self._on_ok)
        self._apply_btn.Bind(wx.EVT_BUTTON, self._on_apply_btn)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

        self._book.SetSelection(max(0, min(page, len(self.TAB_LABELS) - 1)))
        self._book.SetFocus()

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    # Accessibilité : chaque libellé (StaticText) est créé JUSTE AVANT son
    # champ. Orca prend pour nom d'un champ le texte qui le précède dans
    # l'ordre de création (wxGTK ne pose pas de relation « libellé de ») ;
    # un libellé créé après son champ n'est pas annoncé (essai de 10d1).

    @staticmethod
    def _labeled(panel, grid, label, make):
        """Crée le libellé, puis le champ (make(panel)), et les range dans
        grid ; retourne le champ."""
        grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        ctrl = make(panel)
        grid.Add(ctrl, 0, wx.EXPAND)
        return ctrl

    @staticmethod
    def _grid():
        grid = wx.FlexGridSizer(0, 2, 6, 8)
        grid.AddGrowableCol(1, 1)
        return grid

    @staticmethod
    def _finish(panel, sizer):
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(sizer, 0, wx.EXPAND | wx.ALL, 10)
        panel.SetSizer(box)

    def _build_later(self, panel, text):
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(wx.StaticText(panel, label=text), 0, wx.ALL, 10)
        self._finish(panel, box)

    def _build_general(self, panel):
        cfg = self._cfg
        grid = self._grid()
        self._startup = self._labeled(panel, grid, "Au démarrage :",
                                      lambda p: wx.Choice(p, choices=self.STARTUP_LABELS))
        self._startup.SetSelection(AppConfig.STARTUP_CHOICES.index(cfg.startup))
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(grid, 0, wx.EXPAND)
        self._autoplay = wx.CheckBox(panel, label="Autoplay de la grille et des pads")
        self._autoplay.SetValue(cfg.autoplay)
        self._explorer_autoplay = wx.CheckBox(panel, label="Autoplay de l'Explorateur")
        self._explorer_autoplay.SetValue(cfg.explorer_autoplay)
        box.Add(self._autoplay, 0, wx.TOP, 8)
        box.Add(self._explorer_autoplay, 0, wx.TOP, 6)
        self._finish(panel, box)

    def _build_audio(self, panel):
        cfg = self._cfg
        box = wx.BoxSizer(wx.VERTICAL)
        self._live_limiter = wx.CheckBox(panel, label="Limiteur à l'écoute")
        self._live_limiter.SetValue(cfg.live_limiter_enabled)
        self._fluidsynth = wx.CheckBox(panel, label="Moteur FluidSynth (au prochain lancement)")
        self._fluidsynth.SetValue(cfg.fluidsynth_enabled)
        self._sfizz = wx.CheckBox(panel, label="Moteur sfizz (au prochain lancement)")
        self._sfizz.SetValue(cfg.sfizz_enabled)
        for chk in (self._live_limiter, self._fluidsynth, self._sfizz):
            box.Add(chk, 0, wx.BOTTOM, 6)
        grid = self._grid()
        def spin(lo, hi, value):
            return lambda p: wx.SpinCtrl(p, min=lo, max=hi, initial=value)
        self._fluidsynth_gain = self._labeled(panel, grid, "Gain FluidSynth (en dixièmes) :",
                                              spin(0, 100, round(cfg.fluidsynth_gain * 10)))
        self._sfizz_gain = self._labeled(panel, grid, "Gain sfizz (en dixièmes) :",
                                         spin(0, 100, round(cfg.sfizz_gain * 10)))
        self._master_volume = self._labeled(panel, grid, "Volume global d'un nouveau projet :",
                                            spin(0, AppConfig.MASTER_VOLUME_MAX,
                                                 cfg.master_volume))
        self._master_pan = self._labeled(panel, grid, "Pan global d'un nouveau projet :",
                                         spin(-100, 100, cfg.master_pan))
        box.Add(grid, 0, wx.EXPAND | wx.TOP, 4)
        self._finish(panel, box)

    def _build_midi(self, panel):
        grid = self._grid()
        self._bank_select = self._labeled(panel, grid, "Sélection de banque :",
                                          lambda p: wx.Choice(p, choices=self.BANK_SELECT_LABELS))
        self._bank_select.SetSelection(self.BANK_SELECT_VALUES.index(self._cfg.midi_bank_select))
        self._finish(panel, grid)

    def _build_project(self, panel):
        grid = wx.FlexGridSizer(0, 3, 6, 8)
        grid.AddGrowableCol(1, 1)
        self._paths = {}
        for key, label in self.PATH_FIELDS:
            grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            text = wx.TextCtrl(panel, value=getattr(self._cfg, key), size=(380, -1))
            text.SetName(label.rstrip(" :"))
            btn = wx.Button(panel, label="Parcourir…")
            btn.SetName(f"Parcourir — {label.rstrip(' :')}")
            btn.Bind(wx.EVT_BUTTON, lambda e, k=key: self._browse(k))
            grid.Add(text, 1, wx.EXPAND)
            grid.Add(btn, 0)
            self._paths[key] = text
        self._finish(panel, grid)

    def _browse(self, key):
        text = self._paths[key]
        label = dict(self.PATH_FIELDS)[key].rstrip(" :")
        make = self._dir_dialog or (lambda parent, msg, path: wx.DirDialog(
            parent, msg, defaultPath=path, style=wx.DD_DEFAULT_STYLE))
        dlg = make(self, label, text.GetValue())
        try:
            if dlg.ShowModal() == wx.ID_OK:
                text.SetValue(dlg.GetPath())
        finally:
            dlg.Destroy()
        text.SetFocus()

    # ------------------------------------------------------------------
    # Valeurs
    # ------------------------------------------------------------------

    def values(self):
        """Réglages affichés, {clé de preferences.json: valeur}."""
        vals = {
            "startup": AppConfig.STARTUP_CHOICES[self._startup.GetSelection()],
            "autoplay": self._autoplay.GetValue(),
            "explorer_autoplay": self._explorer_autoplay.GetValue(),
            "live_limiter": self._live_limiter.GetValue(),
            "fluidsynth": self._fluidsynth.GetValue(),
            "sfizz": self._sfizz.GetValue(),
            "fluidsynth_gain": self._fluidsynth_gain.GetValue() / 10,
            "sfizz_gain": self._sfizz_gain.GetValue() / 10,
            "master_volume": self._master_volume.GetValue(),
            "master_pan": self._master_pan.GetValue(),
            "midi_bank_select": self.BANK_SELECT_VALUES[self._bank_select.GetSelection()],
        }
        for key, text in self._paths.items():
            vals[key] = text.GetValue().strip() or None      # vide : retour au défaut
        return vals

    def values_of(self, cfg):
        """Réglages d'une configuration, comme values() les rendrait (gains
        au dixième, chemins tels que les champs les montrent)."""
        vals = {
            "startup": cfg.startup,
            "autoplay": cfg.autoplay,
            "explorer_autoplay": cfg.explorer_autoplay,
            "live_limiter": cfg.live_limiter_enabled,
            "fluidsynth": cfg.fluidsynth_enabled,
            "sfizz": cfg.sfizz_enabled,
            "fluidsynth_gain": round(cfg.fluidsynth_gain * 10) / 10,
            "sfizz_gain": round(cfg.sfizz_gain * 10) / 10,
            "master_volume": cfg.master_volume,
            "master_pan": cfg.master_pan,
            "midi_bank_select": cfg.midi_bank_select,
        }
        for key, _ in self.PATH_FIELDS:
            vals[key] = getattr(cfg, key) or None
        return vals

    def show_values(self, vals):
        """Met les champs aux valeurs données (clés de values(), sous-ensemble
        permis) ; n'applique rien."""
        setters = {
            "startup": lambda v: self._startup.SetSelection(AppConfig.STARTUP_CHOICES.index(v)),
            "autoplay": self._autoplay.SetValue,
            "explorer_autoplay": self._explorer_autoplay.SetValue,
            "live_limiter": self._live_limiter.SetValue,
            "fluidsynth": self._fluidsynth.SetValue,
            "sfizz": self._sfizz.SetValue,
            "fluidsynth_gain": lambda v: self._fluidsynth_gain.SetValue(round(v * 10)),
            "sfizz_gain": lambda v: self._sfizz_gain.SetValue(round(v * 10)),
            "master_volume": self._master_volume.SetValue,
            "master_pan": self._master_pan.SetValue,
            "midi_bank_select": lambda v: self._bank_select.SetSelection(
                self.BANK_SELECT_VALUES.index(v)),
        }
        for key, value in vals.items():
            if key in self._paths:
                self._paths[key].SetValue(value or "")
            else:
                setters[key](value)

    def restore_defaults(self, tab):
        """Bouton « Valeurs par défaut » (10f2) : champs de l'onglet tab remis
        aux valeurs par défaut ; Ok ou Appliquer les appliquent."""
        self.show_values({k: self._defaults[k] for k in self.TAB_KEYS[tab]})

    def changes(self):
        """Réglages changés depuis l'ouverture ou le dernier Appliquer."""
        return {k: v for k, v in self.values().items() if self._baseline.get(k) != v}

    def _apply(self):
        # valeur par défaut → None : la clé quitte preferences.json (10f2)
        changes = {k: (None if v == self._defaults.get(k) else v)
                   for k, v in self.changes().items()}
        if changes and self._on_apply is not None:
            self._on_apply(changes)
        self._baseline = self.values()
        return changes

    def _on_ok(self, event):
        self._apply()
        self.EndModal(wx.ID_OK)

    def _on_apply_btn(self, event):
        self._apply()

    # ------------------------------------------------------------------
    # Onglets au clavier (P4)
    # ------------------------------------------------------------------

    def select_tab(self, step):
        """Onglet voisin (step = +1 / −1), en boucle ; focus sur l'onglet."""
        n = self._book.GetPageCount()
        self._book.SetSelection((self._book.GetSelection() + step) % n)
        self._book.SetFocus()

    def _on_char_hook(self, event):
        key  = event.GetKeyCode()
        ctrl = event.ControlDown()
        if key == wx.WXK_TAB and ctrl and not event.AltDown():
            self.select_tab(-1 if event.ShiftDown() else 1)
            return
        if key in (wx.WXK_LEFT, wx.WXK_RIGHT) and not (ctrl or event.AltDown()
                                                      or event.ShiftDown()) \
                and wx.Window.FindFocus() is self._book:
            self.select_tab(-1 if key == wx.WXK_LEFT else 1)
            return
        event.Skip()
