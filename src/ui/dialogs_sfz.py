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

from sfz_sources import (list_sources, source_entry, SfzBankDraft, KIND_SFZ,
                         KIND_SFZBANK, MAX_PROGRAMS, SFZBANK_EXT)

from .gtk_listbox import select_with_cursor


class SfzSlotDialog(wx.Dialog):
    """Source et gain d'un slot Synth SFZ. Ordre Tab : Sources → Gain →
    Fichier… → Dossier… → Nouvelle banque SFZ… → Modifier la banque… →
    boutons (Annuler puis Ok sous GTK)."""

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
        # Banque SFZ JSON composée dans l'appli (Phase 8 étape 7j1, Z21)
        new_bank_btn = wx.Button(self, label="Nouvelle banque SFZ…")
        self._edit_bank_btn = wx.Button(self, label="Modifier la banque…")
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
        browse_row.Add(folder_btn, 0, wx.RIGHT, 6)
        browse_row.Add(new_bank_btn, 0, wx.RIGHT, 6)
        browse_row.Add(self._edit_bank_btn, 0)

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
        new_bank_btn.Bind(wx.EVT_BUTTON, lambda e: self._compose_bank(None))
        self._edit_bank_btn.Bind(wx.EVT_BUTTON,
                                 lambda e: self._compose_bank(self.get_source()))
        self._list.Bind(wx.EVT_LISTBOX, self._on_select)
        self._update_edit_button()
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
                self._update_edit_button()
                return True
        entry = source_entry(path, self._sfz_dir if _inside(path, self._sfz_dir) else None)
        if entry is None:
            self._note.SetLabel(f"Aucun programme SFZ dans {os.path.basename(path)}")
            return False
        self._entries.insert(0, entry)
        self._list.Insert(entry.label, 0)
        select_with_cursor(self._list, 0)
        self._note.SetLabel(f"Ajouté : {entry.label}")
        self._update_edit_button()
        return True

    # -- banque SFZ JSON (7j1) --------------------------------------------------

    BANK_DIALOG = None          # remplaçable par les tests ; défaut : SfzBankDialog

    def _on_select(self, event):
        self._update_edit_button()
        event.Skip()

    def _update_edit_button(self):
        entry = self.get_entry()
        self._edit_bank_btn.Enable(entry is not None and entry.kind == KIND_SFZBANK)

    def _compose_bank(self, path):
        """Nouvelle banque (path None) ou modification de la banque path ;
        une fois enregistrée, elle est sélectionnée dans la liste (sa ligne
        mise à jour si elle y était)."""
        factory = self.BANK_DIALOG or SfzBankDialog
        dlg = factory(self, self._sfz_dir, entries=self._entries, path=path)
        saved = dlg.get_path() if dlg.ShowModal() == wx.ID_OK else None
        dlg.Destroy()
        self._list.SetFocus()
        if saved:
            self.refresh_source(saved)

    def refresh_source(self, path):
        """Relit la source path (banque enregistrée) : sa ligne est mise à
        jour, ou ajoutée en tête ; elle est sélectionnée."""
        entry = source_entry(path, self._sfz_dir if _inside(path, self._sfz_dir) else None)
        if entry is None:
            return False
        for i, e in enumerate(self._entries):
            if _same(e.path, path):
                self._entries[i] = entry
                self._list.SetString(i, entry.label)
                select_with_cursor(self._list, i)
                break
        else:
            self._entries.insert(0, entry)
            self._list.Insert(entry.label, 0)
            select_with_cursor(self._list, 0)
        self._note.SetLabel(f"Banque enregistrée : {entry.label}")
        self._update_edit_button()
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


class SfzBankDialog(wx.Dialog):
    """Composition d'une banque SFZ JSON (Phase 8 étape 7j1, docs/DESIGN.md
    § 7a3 Z21) : nom, liste des programmes (numéro, nom, fichier), choix
    des .sfz parmi ceux de sfz_dir ou par Parcourir…, enregistrement en
    .sfzbank.json (chemins relatifs au fichier).

    Clavier, liste des programmes : Suppr retire, F2 renomme, Alt+Haut /
    Alt+Bas monte / descend (échange le numéro avec le voisin) ; liste des
    .sfz disponibles : Entrée ou double-clic ajoute. Ordre Tab : Nom →
    Programmes → Numéro → Monter → Descendre → Renommer… → Retirer →
    Disponibles → Ajouter → Parcourir… → boutons."""

    def __init__(self, parent, sfz_dir, entries=None, path=None):
        """entries : sources déjà lues (list_sources) dont on garde les .sfz
        seuls ; path : banque à modifier (sinon nouvelle)."""
        super().__init__(parent, title="Banque SFZ — modifier" if path else "Nouvelle banque SFZ")
        self._sfz_dir = sfz_dir
        self._path    = path
        self._draft   = SfzBankDraft.from_file(path) if path else SfzBankDraft("")
        entries = list(entries) if entries is not None else list_sources(sfz_dir)
        self._available = [e for e in entries if e.kind == KIND_SFZ]

        name_label = wx.StaticText(self, label="Nom de la banque :")
        self._name = wx.TextCtrl(self, value=self._draft.name, size=(360, -1))
        self._name.SetName("Nom de la banque")

        prog_label = wx.StaticText(self, label="Programmes :")
        self._programs = wx.ListBox(self, style=wx.LB_SINGLE, size=(560, 180))
        self._programs.SetName("Programmes de la banque")

        number_label = wx.StaticText(self, label="Numéro du programme :")
        self._number = wx.SpinCtrl(self, min=1, max=MAX_PROGRAMS, initial=1)
        self._number.SetName("Numéro du programme")
        up_btn     = wx.Button(self, label="Monter")
        down_btn   = wx.Button(self, label="Descendre")
        rename_btn = wx.Button(self, label="Renommer…")
        remove_btn = wx.Button(self, label="Retirer")

        avail_label = wx.StaticText(self, label=f"Fichiers SFZ disponibles ({len(self._available)}) :")
        self._avail = wx.ListBox(self, choices=[e.label for e in self._available],
                                 style=wx.LB_SINGLE, size=(560, 180))
        self._avail.SetName("Fichiers SFZ disponibles")
        if self._available:
            select_with_cursor(self._avail, 0)
        add_btn    = wx.Button(self, label="Ajouter")
        browse_btn = wx.Button(self, label="Parcourir…")

        self._note = wx.StaticText(self, label="")
        ok_btn = wx.Button(self, wx.ID_OK, "Enregistrer")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL, "Annuler"))
        btn_sizer.Realize()

        edit_row = wx.BoxSizer(wx.HORIZONTAL)
        edit_row.Add(number_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        edit_row.Add(self._number, 0, wx.RIGHT, 12)
        for b in (up_btn, down_btn, rename_btn, remove_btn):
            edit_row.Add(b, 0, wx.RIGHT, 6)
        add_row = wx.BoxSizer(wx.HORIZONTAL)
        add_row.Add(add_btn, 0, wx.RIGHT, 6)
        add_row.Add(browse_btn, 0)

        vbox = wx.BoxSizer(wx.VERTICAL)
        for w, flag in ((name_label, wx.LEFT | wx.TOP | wx.RIGHT),
                        (self._name, wx.LEFT | wx.RIGHT | wx.BOTTOM),
                        (prog_label, wx.LEFT | wx.RIGHT),
                        (self._programs, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM),
                        (edit_row, wx.LEFT | wx.RIGHT | wx.BOTTOM),
                        (avail_label, wx.LEFT | wx.RIGHT),
                        (self._avail, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM),
                        (add_row, wx.LEFT | wx.RIGHT | wx.BOTTOM),
                        (self._note, wx.LEFT | wx.RIGHT | wx.BOTTOM)):
            vbox.Add(w, 0, flag, 8)
        vbox.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()

        self._programs.Bind(wx.EVT_LISTBOX, self._on_program_select)
        self._number.Bind(wx.EVT_SPINCTRL, self._on_number)
        up_btn.Bind(wx.EVT_BUTTON, lambda e: self.move(-1))
        down_btn.Bind(wx.EVT_BUTTON, lambda e: self.move(+1))
        rename_btn.Bind(wx.EVT_BUTTON, lambda e: self._ask_rename())
        remove_btn.Bind(wx.EVT_BUTTON, lambda e: self.remove())
        add_btn.Bind(wx.EVT_BUTTON, lambda e: self.add_selected())
        self._avail.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.add_selected())
        browse_btn.Bind(wx.EVT_BUTTON, self._on_browse)
        ok_btn.Bind(wx.EVT_BUTTON, self._on_save)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

        self._refresh(0 if len(self._draft) else None)
        self._name.SetFocus()

    # -- affichage -----------------------------------------------------------

    def _label(self, i):
        number, name, path = self._draft.programs[i]
        rel = os.path.relpath(path, self._sfz_dir) if _inside(path, self._sfz_dir) else path
        return f"{number + 1} - {name} — {rel}"

    def _refresh(self, select=None):
        """Lignes de la liste mises à jour sur place (SetString, Insert,
        Delete : Orca annonce le changement, Set le perdrait)."""
        count = len(self._draft)
        while self._programs.GetCount() > count:
            self._programs.Delete(self._programs.GetCount() - 1)
        while self._programs.GetCount() < count:
            self._programs.Append("")
        for i in range(count):
            if self._programs.GetString(i) != self._label(i):
                self._programs.SetString(i, self._label(i))
        if select is not None and count:
            select_with_cursor(self._programs, max(0, min(count - 1, select)))
        self._sync_number()

    def _sync_number(self):
        i = self._programs.GetSelection()
        enabled = 0 <= i < len(self._draft)
        self._number.Enable(enabled)
        if enabled:
            self._number.SetValue(self._draft.programs[i][0] + 1)

    def _on_program_select(self, event):
        self._sync_number()
        event.Skip()

    # -- actions -------------------------------------------------------------

    def selected(self):
        i = self._programs.GetSelection()
        return i if 0 <= i < len(self._draft) else None

    def add_path(self, path, name=None):
        """Ajoute le .sfz path au premier numéro libre après le dernier ;
        le sélectionne. Retourne son indice, ou None (banque pleine)."""
        index = self._draft.add(path, name)
        if index is None:
            self._note.SetLabel(f"Banque pleine ({MAX_PROGRAMS} programmes)")
            return None
        self._refresh(index)
        number, pname, _ = self._draft.programs[index]
        self._note.SetLabel(f"Ajouté : programme {number + 1}, {pname}")
        return index

    def add_selected(self):
        sel = self._avail.GetSelection()
        if 0 <= sel < len(self._available):
            entry = self._available[sel]
            return self.add_path(entry.path, entry.name)
        return None

    def remove(self):
        i = self.selected()
        if i is None:
            return
        _, name, _ = self._draft.programs[i]
        self._draft.remove(i)
        self._refresh(min(i, len(self._draft) - 1) if len(self._draft) else None)
        self._note.SetLabel(f"Retiré : {name}")

    def rename(self, name):
        i = self.selected()
        if i is not None:
            self._draft.rename(i, name)
            self._refresh(i)

    def set_number(self, number):
        """Numéro (1..128) du programme sélectionné, échangé avec celui qui
        l'avait."""
        i = self.selected()
        if i is not None:
            self._refresh(self._draft.set_number(i, number - 1))

    def move(self, delta):
        i = self.selected()
        if i is not None:
            self._refresh(self._draft.move(i, delta))

    def _on_number(self, event):
        self.set_number(self._number.GetValue())
        event.Skip()

    def _ask_rename(self):
        i = self.selected()
        if i is None:
            return
        dlg = wx.TextEntryDialog(self, "Nom du programme :", "Renommer",
                                 self._draft.programs[i][1])
        if dlg.ShowModal() == wx.ID_OK:
            self.rename(dlg.GetValue())
        dlg.Destroy()
        self._programs.SetFocus()

    def _on_key(self, event):
        key = event.GetKeyCode()
        if wx.Window.FindFocus() is self._programs:
            if key == wx.WXK_DELETE:
                self.remove()
                return
            if key == wx.WXK_F2:
                self._ask_rename()
                return
            if event.AltDown() and key in (wx.WXK_UP, wx.WXK_DOWN):
                self.move(-1 if key == wx.WXK_UP else 1)
                return
        event.Skip()

    def _on_browse(self, event):
        start = self._sfz_dir if self._sfz_dir and os.path.isdir(self._sfz_dir) \
            else os.path.expanduser("~")
        dlg = wx.FileDialog(self, "Ajouter un fichier SFZ", defaultDir=start,
                            wildcard="Fichiers SFZ (*.sfz)|*.sfz;*.SFZ",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            self.add_path(dlg.GetPath())
        dlg.Destroy()
        self._programs.SetFocus()

    # -- enregistrement --------------------------------------------------------

    def default_path(self):
        name = self.get_name() or "Banque SFZ"
        safe = "".join(c for c in name if c not in '/\\:*?"<>|').strip() or "Banque SFZ"
        return os.path.join(self._sfz_dir or os.path.expanduser("~"), safe + SFZBANK_EXT)

    def save(self, path):
        """Écrit la banque dans path ; False (avec un message) si elle est
        vide ou si l'écriture échoue."""
        if not len(self._draft):
            self._note.SetLabel("Banque vide : ajoutez au moins un programme")
            return False
        if not path.lower().endswith(SFZBANK_EXT):
            path += SFZBANK_EXT
        self._draft.name = self.get_name() or os.path.basename(path)[:-len(SFZBANK_EXT)]
        try:
            self._draft.save(path)
        except OSError as e:
            self._note.SetLabel(f"Enregistrement impossible : {e}")
            return False
        self._path = path
        return True

    def _on_save(self, event):
        path = self._path
        if path is None:
            dlg = wx.FileDialog(self, "Enregistrer la banque SFZ",
                                defaultDir=os.path.dirname(self.default_path()),
                                defaultFile=os.path.basename(self.default_path()),
                                wildcard=f"Banque SFZ (*{SFZBANK_EXT})|*{SFZBANK_EXT}",
                                style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
            ok = dlg.ShowModal() == wx.ID_OK
            path = dlg.GetPath() if ok else None
            dlg.Destroy()
            if not path:
                return
        if self.save(path):
            self.EndModal(wx.ID_OK)

    def get_name(self):
        return self._name.GetValue().strip()

    def get_path(self):
        return self._path
