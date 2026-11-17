import os
import wx
from pattern import Pattern
from ui.dialogs_temporal import BBTHelper


def _load_keyboard_help():
    path = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "shortcuts.md")
    )
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return f"(Fichier d'aide introuvable : {path})"

_KEYBOARD_HELP = _load_keyboard_help()


class KeyboardHelpDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Aide clavier")

        text = wx.TextCtrl(
            self,
            value=_KEYBOARD_HELP,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_LEFT | wx.HSCROLL,
            size=(420, 460),
        )
        text.SetFont(wx.Font(
            10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL
        ))

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(self, wx.ID_OK, "Fermer")
        ok_btn.SetDefault()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.Realize()

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(text,      1, wx.EXPAND | wx.ALL, 6)
        vbox.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        ok_btn.SetFocus()


class GenRowDialog(wx.Dialog):
    def __init__(self, parent, cur_row, cur_quant_idx, num_rows=16):
        super().__init__(parent, title="Générer un motif sur une ligne")

        row_label = wx.StaticText(self, label="Ligne :")
        self._row_ctrl = wx.SpinCtrl(self, min=1, max=num_rows, size=(70, -1))

        quant_label = wx.StaticText(self, label="Valeur de quantisation :")
        self._quant_list = wx.ListBox(
            self,
            choices=Pattern.QUANT_LIST,
            style=wx.LB_SINGLE,
        )
        self._quant_list.SetSelection(cur_quant_idx)

        ok_btn     = wx.Button(self, wx.ID_OK,     "Ok")
        apply_btn  = wx.Button(self, wx.ID_APPLY,  "Appliquer")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        ok_btn.SetDefault()
        apply_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_APPLY))

        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(apply_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()

        row_box = wx.BoxSizer(wx.HORIZONTAL)
        row_box.Add(row_label,      0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row_box.Add(self._row_ctrl, 0)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(row_box,          0, wx.ALL, 6)
        vbox.Add(quant_label,      0, wx.LEFT | wx.RIGHT, 6)
        vbox.Add(self._quant_list, 1, wx.EXPAND | wx.ALL, 6)
        vbox.Add(btn_sizer,        0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._row_ctrl.SetValue(cur_row + 1)  # après Fit() : GTK réinitialise la valeur au layout
        self._row_ctrl.SetFocus()

    def get_row(self):
        return self._row_ctrl.GetValue() - 1  # 0-based

    def get_quant_idx(self):
        sel = self._quant_list.GetSelection()
        return sel if sel != wx.NOT_FOUND else 7


class GridDialog(wx.Dialog):
    """Boîte de sélection de la résolution de grille globale (navigation + quantisation)."""

    def __init__(self, parent, cur_idx=None):
        if cur_idx is None:
            cur_idx = Pattern.GRID_DEFAULT_IDX
        super().__init__(parent, title="Grille — résolution")

        lbl       = wx.StaticText(self, label="Résolution de la grille :")
        self._lb  = wx.ListBox(self, choices=Pattern.GRID_LABELS, style=wx.LB_SINGLE)
        self._lb.SetSelection(max(0, min(cur_idx, len(Pattern.GRID_LABELS) - 1)))
        self._lb.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.EndModal(wx.ID_OK))

        ok_btn     = wx.Button(self, wx.ID_OK,     "Ok")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        ok_btn.SetDefault()

        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(lbl,      0, wx.ALL, 6)
        vbox.Add(self._lb, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._lb.SetFocus()

    def get_grid_idx(self):
        sel = self._lb.GetSelection()
        return sel if sel != wx.NOT_FOUND else Pattern.GRID_DEFAULT_IDX


class QuantizeDialog(wx.Dialog):
    """Boîte de quantisation du pattern : résolution, force, swing, fenêtre,
    débuts / durées ; « Enlever les doublons » et « Quantiser la vélocité »
    avec sa liste (Phase 8 étape 13d1, docs/DESIGN.md § 13a V7, V8).
    record=True (Phase 8 étape 13d2, Alt+Shift+Q) : « Quantisation à
    l'enregistrement » — case « Quantiser à l'enregistrement » en tête,
    résolution « Quant courante » / « Grille courante » / QUANT_LIST, ni
    débuts / durées ni Appliquer : Ok mémorise seulement, aucune note
    existante n'est touchée."""

    VELOCITIES = (127, 120, 110, 100, 90, 80, 70, 64, 50, 40, 30, 20, 10)
    _VELOCITY_LABELS = [f"Vélocité: {v}" for v in VELOCITIES]

    _FORCE_LABELS  = [f"Force: {v} %"   for v in (0, 25, 50, 75, 100)]
    _SWING_LABELS  = [f"Swing: {v} %"   for v in (0, 25, 50, 75, 100)]
    _WINDOW_LABELS = [f"Fenêtre: {v} %" for v in (0, 25, 50, 75, 100)]

    # résolution : -2=Grille courante, -1=Aucune, 0..13=QUANT_LIST
    _RES_OFFSET = 2   # ListBox[0]=Grille courante, [1]=Aucune, [2+]= QUANT_LIST

    def __init__(self, parent, res_idx=-1, force_idx=4, swing_idx=0,
                 window_idx=4, quant_starts=True, quant_durations=False,
                 direction_idx=0, remove_duplicates=True, quant_velocity=False,
                 velocity_value=100, record=False, enabled=True):
        super().__init__(parent, title="Quantisation à l'enregistrement" if record
                         else "Quantisation")
        self._record = record

        self._enabled_cb = None
        if record:
            self._enabled_cb = wx.CheckBox(self, label="Quantiser à l'enregistrement")
            self._enabled_cb.SetValue(enabled)
            first = ["Résolution: Quant courante", "Résolution: Grille courante"]
            self._res_values = [-3, -2]
        else:
            first = ["Résolution: Grille courante", "Résolution: Aucune"]
            self._res_values = [-2, -1]
        self._res_values += list(range(len(Pattern.QUANT_LIST)))
        res_choices = first + [f"Résolution: {q}" for q in Pattern.QUANT_LIST]

        self._res_lb   = wx.ListBox(self, choices=res_choices, style=wx.LB_SINGLE, size=(-1, 130))
        self._res_lb.SetSelection(self._res_values.index(res_idx)
                                  if res_idx in self._res_values else 0)

        self._force_lb  = wx.ListBox(self, choices=self._FORCE_LABELS, style=wx.LB_SINGLE)
        self._force_lb.SetSelection(max(0, min(force_idx, len(self._FORCE_LABELS) - 1)))

        self._swing_lb  = wx.ListBox(self, choices=self._SWING_LABELS, style=wx.LB_SINGLE)
        self._swing_lb.SetSelection(max(0, min(swing_idx, len(self._SWING_LABELS) - 1)))

        self._window_lb = wx.ListBox(self, choices=self._WINDOW_LABELS, style=wx.LB_SINGLE)
        self._window_lb.SetSelection(max(0, min(window_idx, len(self._WINDOW_LABELS) - 1)))

        self._direction_lb = wx.ListBox(self, choices=Pattern.QUANT_DIRECTIONS, style=wx.LB_SINGLE)
        self._direction_lb.SetSelection(max(0, min(direction_idx, len(Pattern.QUANT_DIRECTIONS) - 1)))

        self._starts_cb = self._durations_cb = None
        if not record:                   # à l'enregistrement : la frappe, sans durée
            self._starts_cb    = wx.CheckBox(self, label="Quantiser les débuts")
            self._durations_cb = wx.CheckBox(self, label="Quantiser les durées")
            self._starts_cb.SetValue(quant_starts)
            self._durations_cb.SetValue(quant_durations)

        # 13d1 (V7, V8) : doublons (cochée par défaut), vélocité et sa liste
        self._dedupe_cb   = wx.CheckBox(self, label="Enlever les doublons")
        self._dedupe_cb.SetValue(remove_duplicates)
        self._velocity_cb = wx.CheckBox(self, label="Quantiser la vélocité")
        self._velocity_cb.SetValue(quant_velocity)
        self._velocity_lb = wx.ListBox(self, choices=self._VELOCITY_LABELS, style=wx.LB_SINGLE)
        self._velocity_lb.SetSelection(self.VELOCITIES.index(velocity_value)
                                       if velocity_value in self.VELOCITIES
                                       else self.VELOCITIES.index(100))
        self._velocity_lb.Enable(quant_velocity)
        self._velocity_cb.Bind(wx.EVT_CHECKBOX,
                               lambda e: self._velocity_lb.Enable(self._velocity_cb.GetValue()))

        ok_btn     = wx.Button(self, wx.ID_OK,     "Ok")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        if not record:                   # Appliquer quantise : pas à l'enregistrement
            apply_btn = wx.Button(self, wx.ID_APPLY, "Appliquer")
            apply_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_APPLY))
            btn_sizer.AddButton(apply_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()

        vbox = wx.BoxSizer(wx.VERTICAL)
        if self._enabled_cb is not None:
            vbox.Add(self._enabled_cb, 0, wx.ALL, 6)
        for lb in (self._res_lb, self._force_lb, self._swing_lb, self._window_lb,
                   self._direction_lb):
            vbox.Add(lb, 0, wx.EXPAND | wx.ALL, 6)
        for cb in (self._starts_cb, self._durations_cb):
            if cb is not None:
                vbox.Add(cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(self._dedupe_cb,    0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(self._velocity_cb,  0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(self._velocity_lb,  0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(btn_sizer,          0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._res_lb.SetFocus()

    def get_resolution(self):
        """Retourne -2 (Grille courante), -1 (Aucune) ou 0..13 (QUANT_LIST) ;
        à l'enregistrement, -3 (Quant courante), -2 ou 0..13."""
        sel = self._res_lb.GetSelection()
        if sel == wx.NOT_FOUND:
            return -1
        return self._res_values[sel]

    def get_enabled(self):
        """Case « Quantiser à l'enregistrement » (True hors enregistrement)."""
        return self._enabled_cb.GetValue() if self._enabled_cb is not None else True

    def get_force_idx(self):
        sel = self._force_lb.GetSelection()
        return sel if sel != wx.NOT_FOUND else 4

    def get_swing_idx(self):
        sel = self._swing_lb.GetSelection()
        return sel if sel != wx.NOT_FOUND else 0

    def get_window_idx(self):
        sel = self._window_lb.GetSelection()
        return sel if sel != wx.NOT_FOUND else 3

    def get_quant_starts(self):
        return self._starts_cb.GetValue() if self._starts_cb is not None else True

    def get_quant_durations(self):
        return self._durations_cb.GetValue() if self._durations_cb is not None else False

    def get_direction_idx(self):
        sel = self._direction_lb.GetSelection()
        return sel if sel != wx.NOT_FOUND else 0

    def get_remove_duplicates(self):
        return self._dedupe_cb.GetValue()

    def get_quant_velocity(self):
        return self._velocity_cb.GetValue()

    def get_velocity_value(self):
        sel = self._velocity_lb.GetSelection()
        return self.VELOCITIES[sel] if sel != wx.NOT_FOUND else 100


class ExportTargetDialog(wx.Dialog):
    """Ce qu'exportent Alt+Shift+E et Alt+Shift+W depuis la fenêtre
    principale et l'éditeur MIDI (Phase 8 étape 4b1, docs/DESIGN.md § 4a
    X1, X4) : le pattern courant ou le song courant. Liste de deux lignes
    au libellé complet ; Entrée sur la liste valide (GTK :
    EVT_LISTBOX_DCLICK)."""

    TARGET_PATTERN = 0
    TARGET_SONG    = 1

    def __init__(self, parent, title, pattern_label, song_label, target_idx=0):
        super().__init__(parent, title=title)
        choices = [f"Exporter : Pattern courant ({pattern_label})",
                   f"Exporter : Song courant ({song_label})"]
        self._target_lb = wx.ListBox(self, choices=choices, style=wx.LB_SINGLE)
        self._target_lb.SetSelection(max(0, min(target_idx, len(choices) - 1)))
        self._target_lb.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.EndModal(wx.ID_OK))

        ok_btn     = wx.Button(self, wx.ID_OK,     "Ok")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(self._target_lb, 0, wx.EXPAND | wx.ALL, 6)
        vbox.Add(btn_sizer,       0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._target_lb.SetFocus()

    def get_target_idx(self):
        sel = self._target_lb.GetSelection()
        return sel if sel != wx.NOT_FOUND else self.TARGET_PATTERN


class ImportModeDialog(wx.Dialog):
    """Comment Alt+Shift+I joue le fichier importé (Phase 8 étape 5f1,
    docs/DESIGN.md § 5a M8, M17) : toutes les pistes sur le slot Banque
    (GM), ou pattern en mode Rack 16 canaux. Liste de deux lignes au
    libellé complet ; Entrée sur la liste valide (GTK : EVT_LISTBOX_DCLICK)."""

    MODE_BANK = 0
    MODE_RACK = 1
    LABELS = ["Importer : Banque GM (toutes les pistes sur le slot Banque)",
              "Importer : Rack 16 canaux (le canal N joue le slot N)"]

    def __init__(self, parent, file_name, mode_idx=0):
        super().__init__(parent, title=f"Importer {file_name}")
        self._mode_lb = wx.ListBox(self, choices=self.LABELS, style=wx.LB_SINGLE)
        self._mode_lb.SetSelection(max(0, min(mode_idx, len(self.LABELS) - 1)))
        self._mode_lb.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.EndModal(wx.ID_OK))

        ok_btn     = wx.Button(self, wx.ID_OK,     "Ok")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(self._mode_lb, 0, wx.EXPAND | wx.ALL, 6)
        vbox.Add(btn_sizer,     0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._mode_lb.SetFocus()

    def get_mode_idx(self):
        sel = self._mode_lb.GetSelection()
        return sel if sel != wx.NOT_FOUND else self.MODE_BANK


class AudioExportDialog(wx.Dialog):
    """Export audio WAV — un seul dialogue (Phase 8 étape 15b1, docs/DESIGN.md
    § Phase 8 étape 15a, X1-X5 ; avant : 1h1, 1h15, 2l1, 4b1), suivi du nom
    du fichier :
    Source (Pattern courant, Song courant, Sélection, Presse-papier) ;
    « Exporter les pistes sélectionnées » (grisée pour le presse-papier) ;
    « Tenir compte des Mutes », « Tenir compte des Solos » ; Début et Fin de
    la sélection en mesure:temps:pas (source Sélection seulement) ; puis
    Fin, Format, Sortie, Normaliser, Mesure, Niveau.
    Listes navigables au lecteur d'écran, chaque choix préfixé de son champ
    ; Entrée sur une liste valide (GTK : EVT_LISTBOX_DCLICK) ; libellés
    créés avant leur champ (lus par Orca). Ok valide la sélection : champs
    invalides ou fin avant début → message, le dialogue reste ouvert."""

    SOURCE_PATTERN, SOURCE_SONG, SOURCE_SELECTION, SOURCE_CLIPBOARD = range(4)
    SOURCE_UNITS = ["Pattern", "Song", "Sélection", "Presse-papier"]
    END_LABELS     = ["Fin : Boucle exacte (résonance repliée)",
                      "Fin : Pattern + résonance"]
    FORMAT_LABELS  = ["Format : 16 bits", "Format : 24 bits", "Format : 32 bits flottant"]
    # Sortie : mix, pistes séparées, ou les deux (Phase 8 étape 2l1, § 2a E14)
    OUTPUT_LABELS  = ["Sortie : Mix", "Sortie : Pistes séparées", "Sortie : Mix + pistes"]
    MEASURE_LABELS = ["Mesure : Crête", "Mesure : RMS", "Mesure : LUFS-I"]

    def __init__(self, parent, end_idx=0, format_idx=0, normalize=False,
                 measure_idx=2, level_db=-14, level_min=-24, level_max=0,
                 output_idx=0, source_idx=0, source_labels=None,
                 selected_tracks=False, use_mutes=True, use_solos=True,
                 num_bars=1, num_beats=4, num_steps=16, lim_left=None, lim_right=None):
        super().__init__(parent, title="Exporter en audio")
        names = source_labels or self.SOURCE_UNITS
        total = num_bars * num_steps
        self._bbt = BBTHelper(num_steps, max(1, num_steps // max(1, num_beats)), total)
        left  = 0 if lim_left is None else lim_left
        right = total - 1 if lim_right is None else lim_right

        self._source_lb = wx.ListBox(self, choices=[f"Source : {n}" for n in names],
                                     style=wx.LB_SINGLE)
        self._source_lb.SetSelection(max(0, min(source_idx, len(names) - 1)))
        self._tracks_cb = wx.CheckBox(self, label="Exporter les pistes sélectionnées")
        self._tracks_cb.SetValue(bool(selected_tracks))
        self._mutes_cb = wx.CheckBox(self, label="Tenir compte des Mutes")
        self._mutes_cb.SetValue(bool(use_mutes))
        self._solos_cb = wx.CheckBox(self, label="Tenir compte des Solos")
        self._solos_cb.SetValue(bool(use_solos))
        left_label  = wx.StaticText(self, label="Début de la sélection (mesure:temps:pas) :")
        self._left  = wx.TextCtrl(self, value=self._bbt.fmt(left), size=(140, -1))
        self._left.SetName("Début de la sélection")
        right_label = wx.StaticText(self, label="Fin de la sélection (mesure:temps:pas) :")
        self._right = wx.TextCtrl(self, value=self._bbt.fmt(right), size=(140, -1))
        self._right.SetName("Fin de la sélection")
        self._end_lb = wx.ListBox(self, choices=list(self.END_LABELS), style=wx.LB_SINGLE)
        self._end_lb.SetSelection(max(0, min(end_idx, len(self.END_LABELS) - 1)))
        self._format_lb = wx.ListBox(self, choices=self.FORMAT_LABELS, style=wx.LB_SINGLE)
        self._format_lb.SetSelection(max(0, min(format_idx, len(self.FORMAT_LABELS) - 1)))
        self._output_lb = wx.ListBox(self, choices=self.OUTPUT_LABELS, style=wx.LB_SINGLE)
        self._output_lb.SetSelection(max(0, min(output_idx, len(self.OUTPUT_LABELS) - 1)))
        self._normalize_cb = wx.CheckBox(self, label="Normaliser")
        self._normalize_cb.SetValue(normalize)
        self._measure_lb = wx.ListBox(self, choices=self.MEASURE_LABELS, style=wx.LB_SINGLE)
        self._measure_lb.SetSelection(max(0, min(measure_idx, len(self.MEASURE_LABELS) - 1)))
        level_label = wx.StaticText(self, label="Niveau visé (dB) :")
        self._level = wx.SpinCtrl(self, min=level_min, max=level_max,
                                  initial=max(level_min, min(level_max, int(level_db))))
        self._level.SetName("Niveau visé (dB)")
        for lb in (self._source_lb, self._end_lb, self._format_lb, self._output_lb,
                   self._measure_lb):
            lb.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._on_ok(None))
        self._source_lb.Bind(wx.EVT_LISTBOX, lambda e: self._update_enabled())
        self._normalize_cb.Bind(wx.EVT_CHECKBOX, lambda e: self._update_enabled())

        ok_btn     = wx.Button(self, wx.ID_OK,     "Ok")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        ok_btn.SetDefault()
        ok_btn.Bind(wx.EVT_BUTTON, self._on_ok)
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()

        grid = wx.FlexGridSizer(2, 2, 6, 6)
        grid.Add(left_label,  0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._left,  0)
        grid.Add(right_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._right, 0)
        level_row = wx.BoxSizer(wx.HORIZONTAL)
        level_row.Add(level_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        level_row.Add(self._level, 0)
        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(self._source_lb,    0, wx.EXPAND | wx.ALL, 6)
        for cb in (self._tracks_cb, self._mutes_cb, self._solos_cb):
            vbox.Add(cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(grid,               0, wx.ALL, 6)
        vbox.Add(self._end_lb,       0, wx.EXPAND | wx.ALL, 6)
        vbox.Add(self._format_lb,    0, wx.EXPAND | wx.ALL, 6)
        vbox.Add(self._output_lb,    0, wx.EXPAND | wx.ALL, 6)
        vbox.Add(self._normalize_cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(self._measure_lb,   0, wx.EXPAND | wx.ALL, 6)
        vbox.Add(level_row,          0, wx.ALL, 6)
        vbox.Add(btn_sizer,          0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._update_enabled()
        self._source_lb.SetFocus()

    def _update_enabled(self):
        """Champs actifs selon la source et « Normaliser » ; la fin suit la
        source (« Fin : Song + résonance »…)."""
        source = self.get_source_idx()
        self._tracks_cb.Enable(source != self.SOURCE_CLIPBOARD)
        selection = source == self.SOURCE_SELECTION
        self._left.Enable(selection)
        self._right.Enable(selection)
        self._end_lb.SetString(1, f"Fin : {self.SOURCE_UNITS[source]} + résonance")
        on = self._normalize_cb.GetValue()
        self._measure_lb.Enable(on)
        self._level.Enable(on)

    def _validate(self):
        """Message d'erreur, ou None si les champs sont valides (ou sans objet)."""
        if self.get_source_idx() != self.SOURCE_SELECTION:
            return None
        left  = self._bbt.parse(self._left.GetValue())
        right = self._bbt.parse(self._right.GetValue())
        if left is None or right is None:
            return "Position invalide : mesure:temps:pas attendu (par exemple 2:1:1)"
        if right < left:
            return "La fin de la sélection est avant son début"
        return None

    def _on_ok(self, event):
        error = self._validate()
        if error is not None:
            wx.MessageBox(error, "Exporter en audio", wx.OK | wx.ICON_WARNING, self)
            return
        self.EndModal(wx.ID_OK)

    def get_source_idx(self):
        sel = self._source_lb.GetSelection()
        return sel if sel != wx.NOT_FOUND else 0

    def get_selected_tracks(self):
        return self._tracks_cb.GetValue()

    def get_use_mutes(self):
        return self._mutes_cb.GetValue()

    def get_use_solos(self):
        return self._solos_cb.GetValue()

    def get_window(self):
        """(début, fin) de la sélection en pas, fin comprise ; None si invalide."""
        left  = self._bbt.parse(self._left.GetValue())
        right = self._bbt.parse(self._right.GetValue())
        if left is None or right is None or right < left:
            return None
        return left, right

    def get_end_idx(self):
        sel = self._end_lb.GetSelection()
        return sel if sel != wx.NOT_FOUND else 0

    def get_format_idx(self):
        sel = self._format_lb.GetSelection()
        return sel if sel != wx.NOT_FOUND else 0

    def get_output_idx(self):
        sel = self._output_lb.GetSelection()
        return sel if sel != wx.NOT_FOUND else 0

    def get_normalize(self):
        return self._normalize_cb.GetValue()

    def get_measure_idx(self):
        sel = self._measure_lb.GetSelection()
        return sel if sel != wx.NOT_FOUND else 2

    def get_level_db(self):
        return self._level.GetValue()


class RecordOptionsDialog(wx.Dialog):
    """Options de l'enregistrement (Ctrl+Shift+R, Phase 8 étape 16b1,
    docs/DESIGN.md § 16a O2, O6, O7) : Mode (liste construite depuis la table
    record_modes.MODES — d'autres modes viendront : Punch In/Out, Automation,
    Live Looper), « Clic pendant la lecture », « Décompte pendant la
    lecture » (16b1, essai), « Clic pendant l'enregistrement », « Décompte pendant
    l'enregistrement ». Focus sur le mode ; Entrée sur une liste valide
    (GTK : EVT_LISTBOX_DCLICK)."""

    def __init__(self, parent, options):
        from record_modes import MODES, COUNT_IN_CHOICES, normalize, mode_index, count_label
        super().__init__(parent, title="Options de l'enregistrement")
        opts = normalize(options)
        self._modes = MODES
        self._counts = COUNT_IN_CHOICES
        self._mode_lb = wx.ListBox(self, choices=[f"Mode : {m.label}" for m in MODES],
                                   style=wx.LB_SINGLE)
        self._mode_lb.SetSelection(mode_index(opts["mode"]))
        self._click_play = wx.CheckBox(self, label="Clic pendant la lecture")
        self._click_play.SetValue(opts["click_play"])
        self._count_play_lb = wx.ListBox(
            self, style=wx.LB_SINGLE,
            choices=[f"Décompte pendant la lecture : {count_label(n)}" for n in COUNT_IN_CHOICES])
        self._count_play_lb.SetSelection(COUNT_IN_CHOICES.index(opts["count_in_play"]))
        self._click_record = wx.CheckBox(self, label="Clic pendant l'enregistrement")
        self._click_record.SetValue(opts["click_record"])
        self._count_lb = wx.ListBox(
            self, style=wx.LB_SINGLE,
            choices=[f"Décompte pendant l'enregistrement : {count_label(n)}"
                     for n in COUNT_IN_CHOICES])
        self._count_lb.SetSelection(COUNT_IN_CHOICES.index(opts["count_in"]))
        for lb in (self._mode_lb, self._count_play_lb, self._count_lb):
            lb.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.EndModal(wx.ID_OK))

        ok_btn     = wx.Button(self, wx.ID_OK,     "Ok")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(self._mode_lb, 0, wx.EXPAND | wx.ALL, 6)
        vbox.Add(self._click_play, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(self._count_play_lb, 0, wx.EXPAND | wx.ALL, 6)
        vbox.Add(self._click_record, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(self._count_lb, 0, wx.EXPAND | wx.ALL, 6)
        vbox.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._mode_lb.SetFocus()

    def get_options(self):
        """Options choisies, au format de la clé record_options."""
        m = self._mode_lb.GetSelection()
        c = self._count_lb.GetSelection()
        cp = self._count_play_lb.GetSelection()
        return {
            "mode": self._modes[m if m != wx.NOT_FOUND else 0].id,
            "click_play": self._click_play.GetValue(),
            "count_in_play": self._counts[cp if cp != wx.NOT_FOUND else 0],
            "click_record": self._click_record.GetValue(),
            "count_in": self._counts[c if c != wx.NOT_FOUND else 1],
        }


class SaveSongDialog(wx.Dialog):
    def __init__(self, parent, cur_idx, cur_name=""):
        super().__init__(parent, title="Enregistrer le song")

        list_label = wx.StaticText(self, label="Numéro de song :")
        self._list = wx.ListBox(
            self,
            choices=[f"{i:02d}" for i in range(1, 17)],
            style=wx.LB_SINGLE,
        )
        self._list.SetSelection(cur_idx)

        name_label = wx.StaticText(self, label="Nom (optionnel) :")
        self._name_ctrl = wx.TextCtrl(self, value=cur_name)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(self, wx.ID_OK, "Ok")
        ok_btn.SetDefault()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL, "Annuler"))
        btn_sizer.Realize()

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(list_label,      0, wx.ALL, 6)
        vbox.Add(self._list,      1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(name_label,      0, wx.LEFT | wx.RIGHT, 6)
        vbox.Add(self._name_ctrl, 0, wx.EXPAND | wx.ALL, 6)
        vbox.Add(btn_sizer,       0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._list.SetFocus()

    def get_selection(self):
        return self._list.GetSelection()

    def get_name(self):
        return self._name_ctrl.GetValue().strip()


class SavePatternDialog(wx.Dialog):
    def __init__(self, parent, cur_idx, cur_name=""):
        super().__init__(parent, title="Dupliquer le pattern")

        list_label = wx.StaticText(self, label="Numéro de pattern :")
        self._list = wx.ListBox(
            self,
            choices=[f"{i:02d}" for i in range(1, 100)],
            style=wx.LB_SINGLE,
        )
        self._list.SetSelection(cur_idx)

        name_label = wx.StaticText(self, label="Nom (optionnel) :")
        self._name_ctrl = wx.TextCtrl(self, value=cur_name)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(self, wx.ID_OK, "Ok")
        ok_btn.SetDefault()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL, "Annuler"))
        btn_sizer.Realize()

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(list_label,      0, wx.ALL, 6)
        vbox.Add(self._list,      1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(name_label,      0, wx.LEFT | wx.RIGHT, 6)
        vbox.Add(self._name_ctrl, 0, wx.EXPAND | wx.ALL, 6)
        vbox.Add(btn_sizer,       0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._list.SetFocus()

    def get_selection(self):
        return self._list.GetSelection()

    def get_name(self):
        return self._name_ctrl.GetValue().strip()


class ExplorerDialog(wx.Dialog):
    """Choix du type de fichier à charger : Kit, Patch, Sound, Banque
    (slot Banque, Phase 7 étape 17h1) ou SFZ (slot Synth SFZ, Phase 8 étape
    7h1)."""
    ITEMS = ["Projects", "Preset", "Kit", "Patch", "Sound", "Banque", "SFZ"]

    def __init__(self, parent):
        super().__init__(parent, title="Explorateur")
        self._listbox = wx.ListBox(self, choices=self.ITEMS, style=wx.LB_SINGLE)
        self._listbox.SetSelection(0)

        ok_btn = wx.Button(self, wx.ID_OK, "Ok")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL, "Annuler"))
        btn_sizer.Realize()

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(self._listbox, 1, wx.EXPAND | wx.ALL, 8)
        vbox.Add(btn_sizer,     0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.SetSize((220, 225))
        self.Centre()

        self._listbox.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.EndModal(wx.ID_OK))
        self._listbox.SetFocus()

    def get_selection(self):
        return self._listbox.GetStringSelection()


class UndoHistoryDialog(wx.Dialog):
    """Affiche l'historique Undo pour permettre un saut multi-niveaux."""

    def __init__(self, parent, entries):
        super().__init__(parent, title="Historique Undo")

        self._entries = entries  # list[UndoEntry], plus récent en tête

        choices = [f"{e.title}  ({e.rel_time()})" for e in entries]
        self._listbox = wx.ListBox(self, choices=choices, style=wx.LB_SINGLE,
                                   size=(320, 220))
        if choices:
            self._listbox.SetSelection(0)

        ok_btn     = wx.Button(self, wx.ID_OK,     "Restaurer")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        ok_btn.SetDefault()

        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(self._listbox, 1, wx.EXPAND | wx.ALL, 6)
        vbox.Add(btn_sizer,     0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._listbox.SetFocus()

        self._listbox.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.EndModal(wx.ID_OK))

    def get_steps(self):
        """Nombre d'annulations à effectuer (1 = premier, 2 = deuxième, etc.)."""
        sel = self._listbox.GetSelection()
        return sel + 1 if sel != wx.NOT_FOUND else 0


class SaveConfirmDialog(wx.Dialog):
    """Oui/Non/Annuler pour proposer d'enregistrer un projet modifié.

    Entrée valide le bouton qui a le focus (comportement natif restauré
    explicitement — voir _on_key). Raccourcis O/Y = Oui, N = Non,
    A/C = Annuler (en plus du clic), Échap = Annuler."""

    def __init__(self, parent, message, title):
        super().__init__(parent, title=title)

        text = wx.StaticText(self, label=message)

        self._yes_btn    = wx.Button(self, wx.ID_YES,    "Oui")
        self._no_btn     = wx.Button(self, wx.ID_NO,     "Non")
        self._cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        self._yes_btn.SetDefault()

        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(self._yes_btn)
        btn_sizer.AddButton(self._no_btn)
        btn_sizer.AddButton(self._cancel_btn)
        btn_sizer.Realize()

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(text,      0, wx.ALL, 12)
        vbox.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._yes_btn.SetFocus()

        # EVT_BUTTON explicite (plutôt que de compter sur la fin de modal
        # automatique de wx.Dialog pour les ID standard) : passe par _end()
        # comme le clavier, pour partager le garde-fou anti double appel.
        for btn in (self._yes_btn, self._no_btn, self._cancel_btn):
            btn.Bind(wx.EVT_BUTTON, lambda evt: self._end(evt.GetId()))

        self._answered = False
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

    def _end(self, result_id):
        """Termine le dialog une seule fois — un second appel (clic + touche
        quasi simultanés, ou double événement clavier) est ignoré au lieu
        d'écraser silencieusement le résultat déjà renvoyé par ShowModal()."""
        if self._answered:
            return
        self._answered = True
        self.EndModal(result_id)

    def _on_key(self, evt):
        key = evt.GetKeyCode()

        # Entrée : valide le bouton qui a le focus (comportement natif
        # attendu pour un wx.Button focusé) — géré explicitement ici car
        # EVT_CHAR_HOOK, une fois bindé sur ce dialog, empêche l'activation
        # native du bouton par défaut sur GTK même avec evt.Skip() (bug
        # d'origine de ce dialog : Entrée ne validait plus aucun bouton).
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            focus = wx.Window.FindFocus()
            for btn in (self._yes_btn, self._no_btn, self._cancel_btn):
                if focus is btn:
                    self._end(btn.GetId())
                    return
            self._end(wx.ID_YES)   # aucun bouton focus : action par défaut
            return
        if key == wx.WXK_ESCAPE or key == ord('C') or key == ord('A'):
            self._end(wx.ID_CANCEL)
            return
        if key == ord('O') or key == ord('Y'):
            self._end(wx.ID_YES)
            return
        if key == ord('N'):
            self._end(wx.ID_NO)
            return
        evt.Skip()
