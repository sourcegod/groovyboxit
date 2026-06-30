import os
import wx
from pattern import Pattern


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
    """Boîte de quantisation du pattern : résolution, force, swing, fenêtre, débuts/durées."""

    _FORCE_LABELS  = [f"Force: {v} %"   for v in (0, 25, 50, 75, 100)]
    _SWING_LABELS  = [f"Swing: {v} %"   for v in (0, 25, 50, 75, 100)]
    _WINDOW_LABELS = [f"Fenêtre: {v} %" for v in (0, 25, 50, 75, 100)]

    # résolution : -2=Grille courante, -1=Aucune, 0..13=QUANT_LIST
    _RES_OFFSET = 2   # ListBox[0]=Grille courante, [1]=Aucune, [2+]= QUANT_LIST

    def __init__(self, parent, res_idx=-1, force_idx=4, swing_idx=0,
                 window_idx=4, quant_starts=True, quant_durations=False):
        super().__init__(parent, title="Quantisation")

        res_choices = (["Résolution: Grille courante", "Résolution: Aucune"]
                       + [f"Résolution: {q}" for q in Pattern.QUANT_LIST])

        self._res_lb   = wx.ListBox(self, choices=res_choices, style=wx.LB_SINGLE, size=(-1, 130))
        lb_sel = res_idx + self._RES_OFFSET if res_idx >= -1 else 0
        self._res_lb.SetSelection(max(0, lb_sel))

        self._force_lb  = wx.ListBox(self, choices=self._FORCE_LABELS, style=wx.LB_SINGLE)
        self._force_lb.SetSelection(max(0, min(force_idx, len(self._FORCE_LABELS) - 1)))

        self._swing_lb  = wx.ListBox(self, choices=self._SWING_LABELS, style=wx.LB_SINGLE)
        self._swing_lb.SetSelection(max(0, min(swing_idx, len(self._SWING_LABELS) - 1)))

        self._window_lb = wx.ListBox(self, choices=self._WINDOW_LABELS, style=wx.LB_SINGLE)
        self._window_lb.SetSelection(max(0, min(window_idx, len(self._WINDOW_LABELS) - 1)))

        self._starts_cb    = wx.CheckBox(self, label="Quantiser les débuts")
        self._durations_cb = wx.CheckBox(self, label="Quantiser les durées")
        self._starts_cb.SetValue(quant_starts)
        self._durations_cb.SetValue(quant_durations)

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

        vbox = wx.BoxSizer(wx.VERTICAL)
        for lb in (self._res_lb, self._force_lb, self._swing_lb, self._window_lb):
            vbox.Add(lb, 0, wx.EXPAND | wx.ALL, 6)
        vbox.Add(self._starts_cb,    0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(self._durations_cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(btn_sizer,          0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._res_lb.SetFocus()

    def get_resolution(self):
        """Retourne -2 (Grille courante), -1 (Aucune) ou 0..13 (QUANT_LIST)."""
        sel = self._res_lb.GetSelection()
        if sel == wx.NOT_FOUND:
            return -1
        return sel - self._RES_OFFSET

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
        return self._starts_cb.GetValue()

    def get_quant_durations(self):
        return self._durations_cb.GetValue()


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
    """Choix du type de fichier à charger : Kit, Patch ou Sound."""
    ITEMS = ["Projects", "Preset", "Kit", "Patch", "Sound"]

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
        self.SetSize((220, 185))
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
