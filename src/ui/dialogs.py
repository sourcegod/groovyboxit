import os
import wx
from drum_player import DrumPlayer


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
            choices=DrumPlayer.QUANT_LIST,
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


class QuantizeDialog(wx.Dialog):
    def __init__(self, parent, cur_idx):
        super().__init__(parent, title="Quantisation du pattern")

        list_label = wx.StaticText(self, label="Valeur de quantisation :")
        self._list = wx.ListBox(
            self,
            choices=DrumPlayer.QUANT_LIST,
            style=wx.LB_SINGLE,
        )
        self._list.SetSelection(cur_idx)

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
        vbox.Add(list_label,  0, wx.ALL, 6)
        vbox.Add(self._list,  1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(btn_sizer,   0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._list.SetFocus()

    def get_selection(self):
        return self._list.GetSelection()


class SavePatternDialog(wx.Dialog):
    def __init__(self, parent, cur_idx, cur_name=""):
        super().__init__(parent, title="Enregistrer le pattern")

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
