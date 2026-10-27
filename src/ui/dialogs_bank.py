#python3
"""
    File: src/ui/dialogs_bank.py
    Dialogue du slot Banque (Phase 7 étape 17h1, docs/DESIGN.md § 17e2 R9,
    § 17e3) : fichier de banque (SF2 / SF3) et emplacement 1..4 du slot
    courant. L'instrument ne se choisit pas ici mais par piste (propriétés de piste, Alt+Entrée) :
    le canal est l'instrument.
    Date: Tue, 27/10/2026
    Author: Coolbrother
"""
import os

import wx


class BankSlotDialog(wx.Dialog):
    """Fichier et emplacement d'un slot Banque. Ordre Tab : Emplacement →
    Fichier → Parcourir → Ok → Annuler."""

    WILDCARD = "Banques de sons (*.sf2;*.sf3)|*.sf2;*.SF2;*.sf3;*.SF3|Tous les fichiers (*.*)|*.*"

    def __init__(self, parent, slot_idx, bank_files, bank_slot, default_file, soundfonts_dir):
        """bank_files : fichier de chaque emplacement (chemin ou None) ;
        bank_slot : emplacement proposé ; default_file : fichier proposé
        pour un emplacement vide (gm_soundfont) ; soundfonts_dir : dossier
        ouvert par Parcourir."""
        super().__init__(parent, title=f"Banque — Slot {slot_idx + 1:02d}")
        self._bank_files     = list(bank_files)
        self._default_file   = default_file or ""
        self._soundfonts_dir = soundfonts_dir

        slot_label  = wx.StaticText(self, label="Emplacement :")
        self._slots = wx.ListBox(self, choices=[self._slot_label(i)
                                                for i in range(len(self._bank_files))],
                                 style=wx.LB_SINGLE)
        self._slots.SetSelection(bank_slot)

        file_label  = wx.StaticText(self, label="Fichier :")
        self._file  = wx.TextCtrl(self, size=(420, -1))
        self._file.SetName("Fichier de banque")
        browse      = wx.Button(self, label="Parcourir…")

        self._note  = wx.StaticText(self, label="")

        ok_btn = wx.Button(self, wx.ID_OK, "Ok")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL, "Annuler"))
        btn_sizer.Realize()

        file_row = wx.BoxSizer(wx.HORIZONTAL)
        file_row.Add(self._file, 1, wx.EXPAND | wx.RIGHT, 6)
        file_row.Add(browse,     0)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(slot_label,  0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        vbox.Add(self._slots, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(file_label,  0, wx.LEFT | wx.RIGHT, 8)
        vbox.Add(file_row,    0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(self._note,  0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(btn_sizer,   0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()

        self._slots.Bind(wx.EVT_LISTBOX, self._on_slot_change)
        browse.Bind(wx.EVT_BUTTON, self._on_browse)
        self._show_slot_file()
        self._slots.SetFocus()

    def _slot_label(self, i):
        path = self._bank_files[i]
        return f"Emplacement {i + 1} — {os.path.basename(path) if path else '(vide)'}"

    def _show_slot_file(self):
        """Fichier de l'emplacement choisi, ou le fichier proposé s'il est vide."""
        path = self._bank_files[self.get_bank_slot()]
        self._file.SetValue(path or self._default_file)
        self._note.SetLabel("Changer ce fichier change le son de tous les slots "
                            "de cet emplacement." if path else "Emplacement vide.")

    def _on_slot_change(self, event):
        self._show_slot_file()
        event.Skip()

    def _on_browse(self, event):
        start = os.path.dirname(self.get_path()) or self._soundfonts_dir
        if not os.path.isdir(start):
            start = os.path.expanduser("~")
        dlg = wx.FileDialog(self, "Choisir une banque de sons", defaultDir=start,
                            wildcard=self.WILDCARD,
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            self._file.SetValue(dlg.GetPath())
        dlg.Destroy()
        self._file.SetFocus()

    def get_bank_slot(self):
        return max(0, self._slots.GetSelection())

    def get_path(self):
        return self._file.GetValue().strip()
