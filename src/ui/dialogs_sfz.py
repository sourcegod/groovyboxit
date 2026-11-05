#python3
"""
    File: src/ui/dialogs_sfz.py
    Dialogue du slot Synth SFZ (Phase 8 étape 7h1, docs/DESIGN.md § 7a2 Z6,
    Z15, § 7a3 Z26 ; gain : 7f2) : source de programmes du slot courant,
    choisie dans la liste des sources de sfz_dir (banques Sforzando,
    banques SFZ, dossiers, .sfz seuls) ou par « Fichier… » / « Dossier… » ;
    gain du slot en dB.
    Date: Thu, 05/11/2026
    Author: Coolbrother
"""
import os

import wx

from sfz_sources import list_sources, source_entry

from .gtk_listbox import select_with_cursor


class SfzSlotDialog(wx.Dialog):
    """Source et gain d'un slot Synth SFZ. Ordre Tab : Sources → Gain →
    Fichier… → Dossier… → Ok → Annuler."""

    WILDCARD = ("Sources SFZ (*.sfz;*.bank.xml;*.sfzbank.json)|*.sfz;*.SFZ;*.bank.xml;"
                "*.sfzbank.json|Tous les fichiers (*.*)|*.*")
    GAIN_MIN, GAIN_MAX = -24, 12

    def __init__(self, parent, slot_idx, sfz_dir, current=None, gain_db=0, entries=None):
        """sfz_dir : dossier des instruments, parcouru pour la liste ;
        current : source actuelle du slot (chemin absolu) ou None ;
        gain_db : gain actuel du slot ; entries : liste des sources déjà
        lue (tests), sinon list_sources(sfz_dir)."""
        super().__init__(parent, title=f"Synth SFZ — Slot {slot_idx + 1:02d}")
        self._sfz_dir = sfz_dir
        self._entries = list(entries) if entries is not None else list_sources(sfz_dir)
        if current and not any(_same(e.path, current) for e in self._entries):
            extra = source_entry(current, sfz_dir if _inside(current, sfz_dir) else None)
            if extra is not None:                  # source hors de sfz_dir : en tête
                self._entries.insert(0, extra)

        list_label = wx.StaticText(self, label=f"Sources ({len(self._entries)}) :")
        self._list = wx.ListBox(self, choices=[e.label for e in self._entries],
                                style=wx.LB_SINGLE, size=(560, 260))
        self._list.SetName("Sources SFZ")
        index = next((i for i, e in enumerate(self._entries) if _same(e.path, current)), 0)
        if self._entries:
            select_with_cursor(self._list, index)

        gain_label = wx.StaticText(self, label="Gain du slot (dB) :")
        self._gain = wx.SpinCtrl(self, min=self.GAIN_MIN, max=self.GAIN_MAX,
                                 initial=max(self.GAIN_MIN, min(self.GAIN_MAX, int(gain_db))))
        self._gain.SetName("Gain du slot")

        file_btn   = wx.Button(self, label="Fichier…")
        folder_btn = wx.Button(self, label="Dossier…")
        self._note = wx.StaticText(self, label="" if self._entries else
                                   f"Aucune source SFZ dans {sfz_dir}")

        ok_btn = wx.Button(self, wx.ID_OK, "Ok")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL, "Annuler"))
        btn_sizer.Realize()

        gain_row = wx.BoxSizer(wx.HORIZONTAL)
        gain_row.Add(gain_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        gain_row.Add(self._gain, 0)
        browse_row = wx.BoxSizer(wx.HORIZONTAL)
        browse_row.Add(file_btn,   0, wx.RIGHT, 6)
        browse_row.Add(folder_btn, 0)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(list_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        vbox.Add(self._list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(gain_row,   0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(browse_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(self._note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(btn_sizer,  0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()

        file_btn.Bind(wx.EVT_BUTTON, self._on_file)
        folder_btn.Bind(wx.EVT_BUTTON, self._on_folder)
        self._list.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.EndModal(wx.ID_OK))
        (self._list if self._entries else file_btn).SetFocus()

    # -- Parcourir ------------------------------------------------------------

    def _start_dir(self):
        path = self.get_source()
        start = os.path.dirname(path) if path else self._sfz_dir
        return start if start and os.path.isdir(start) else os.path.expanduser("~")

    def _on_file(self, event):
        dlg = wx.FileDialog(self, "Choisir une source SFZ", defaultDir=self._start_dir(),
                            wildcard=self.WILDCARD, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            self.add_source(dlg.GetPath())
        dlg.Destroy()
        self._list.SetFocus()

    def _on_folder(self, event):
        dlg = wx.DirDialog(self, "Choisir un dossier de programmes SFZ",
                           defaultPath=self._start_dir(), style=wx.DD_DIR_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            self.add_source(dlg.GetPath())
        dlg.Destroy()
        self._list.SetFocus()

    def add_source(self, path):
        """Ajoute (ou retrouve) la source path dans la liste et la
        sélectionne. Retourne False si elle n'a aucun programme."""
        for i, e in enumerate(self._entries):
            if _same(e.path, path):
                select_with_cursor(self._list, i)
                return True
        entry = source_entry(path, self._sfz_dir if _inside(path, self._sfz_dir) else None)
        if entry is None:
            self._note.SetLabel(f"Aucun programme SFZ dans {os.path.basename(path)}")
            return False
        self._entries.insert(0, entry)
        self._list.Insert(entry.label, 0)
        select_with_cursor(self._list, 0)
        self._note.SetLabel(f"Ajouté : {entry.label}")
        return True

    # -- résultat -------------------------------------------------------------

    def get_entry(self):
        sel = self._list.GetSelection()
        return self._entries[sel] if 0 <= sel < len(self._entries) else None

    def get_source(self):
        entry = self.get_entry()
        return entry.path if entry else None

    def get_gain_db(self):
        return self._gain.GetValue()


def _same(a, b):
    return bool(a and b) and os.path.normpath(os.path.abspath(a)) == \
        os.path.normpath(os.path.abspath(b))


def _inside(path, folder):
    """Vrai si path est dans folder."""
    if not path or not folder:
        return False
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(folder)]) == \
            os.path.abspath(folder)
    except ValueError:
        return False


def stored_source(path, sfz_dir):
    """Chemin enregistré dans le slot (Z10, Z20) : relatif à sfz_dir s'il
    s'y trouve (projet portable), absolu sinon."""
    if _inside(path, sfz_dir):
        return os.path.relpath(os.path.abspath(path), os.path.abspath(sfz_dir))
    return os.path.abspath(path)
