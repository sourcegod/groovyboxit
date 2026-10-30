#python3
"""
    File: src/ui/dialogs_tempo.py
    Dialogue « Tempo » (Alt+Shift+T, Phase 7 étape 19f1, docs/DESIGN.md
    § 19a1 T8, § 19d2 R3) : liste des tempos du pattern (départ puis
    changements), Insérer, Modifier (« Changer le tempo récent » ou « Tous
    les tempos »), Supprimer, Fermer ; et le dialogue d'édition d'un tempo,
    partagé avec la liste des événements (Entrée sur une ligne Tempo, T9).
    Les modifications passent par la fenêtre principale (TempoMixin), qui
    pose l'Undo : en lecture, elles s'entendent aussitôt.
    Date: Thu, 29/10/2026
    Author: Coolbrother
"""
import wx

from tempo_map import format_bpm, BPM_MIN, BPM_MAX

# Choix « Portée » du dialogue d'édition (§ 19d2 R3, précisé à l'essai :
# « tous les tempos » seul pouvait vouloir dire « tous à cette valeur »)
SCOPES       = ["recent", "set_all", "scale_all"]    # DrumPlayer.SCOPE_*
SCOPE_LABELS = ["Changer le tempo le plus récent",
                "Changer tous les tempos à cette valeur",
                "Changer tous les tempos proportionnellement"]
SCOPE_RECENT = SCOPES[0]


def parse_bpm(text):
    """« 92 », « 46,5 », « 46.5 » → float dans 1..600, sinon None."""
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError:
        return None
    return value if BPM_MIN <= value <= BPM_MAX else None


class TempoEditDialog(wx.Dialog):
    """Position (mesure, temps, pas) et BPM d'un tempo ; avec `with_scope`,
    le choix « Changer le tempo récent » / « Tous les tempos » (R3).
    Ordre Tab : Mesure → Temps → Pas → BPM → Portée → Ok → Annuler.

    pos           : position en pas (peut être fractionnaire : gardée telle
                    quelle si mesure, temps et pas ne changent pas)
    position_fixed: départ (1.1.1) — position non modifiable
    """

    def __init__(self, parent, title, pos, bpm, num_bars, num_steps, steps_per_beat,
                 position_fixed=False, with_scope=False):
        super().__init__(parent, title=title)
        self._pos            = pos
        self._num_steps      = int(num_steps)
        # Entier : Pattern.steps_per_beat() rend un float (16 / 4 = 4.0), que
        # wx.SpinCtrl refuse (le dialogue ne s'ouvrait pas, 19f1)
        self._steps_per_beat = max(1, int(steps_per_beat))
        num_steps            = self._num_steps
        self._position_fixed = position_fixed
        bar, rem = divmod(int(pos), num_steps)
        beat, tick = divmod(rem, self._steps_per_beat)
        self._initial = (bar + 1, beat + 1, tick + 1)

        num_beats = max(1, num_steps // self._steps_per_beat)
        self._bar  = wx.SpinCtrl(self, min=1, max=max(1, num_bars), initial=bar + 1, size=(80, -1))
        self._beat = wx.SpinCtrl(self, min=1, max=num_beats, initial=beat + 1, size=(60, -1))
        self._tick = wx.SpinCtrl(self, min=1, max=self._steps_per_beat, initial=tick + 1,
                                 size=(60, -1))
        self._bar.SetName("Mesure")
        self._beat.SetName("Temps")
        self._tick.SetName("Pas")
        self._bpm = wx.TextCtrl(self, value=format_bpm(bpm), size=(90, -1))
        self._bpm.SetName("BPM")

        self._scope = None
        if with_scope:
            self._scope = wx.RadioBox(self, label="Portée", choices=SCOPE_LABELS,
                                      majorDimension=1, style=wx.RA_SPECIFY_COLS)
            self._scope.Bind(wx.EVT_RADIOBOX, lambda e: self._update_position_enabled())

        ok_btn = wx.Button(self, wx.ID_OK, "Ok")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL, "Annuler"))
        btn_sizer.Realize()

        pos_row = wx.BoxSizer(wx.HORIZONTAL)
        for label, ctrl in (("Mesure :", self._bar), ("Temps :", self._beat), ("Pas :", self._tick)):
            pos_row.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
            pos_row.Add(ctrl, 0, wx.RIGHT, 10)
        bpm_row = wx.BoxSizer(wx.HORIZONTAL)
        bpm_row.Add(wx.StaticText(self, label="BPM :"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        bpm_row.Add(self._bpm, 0)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(pos_row, 0, wx.ALL, 8)
        vbox.Add(bpm_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        if self._scope is not None:
            vbox.Add(self._scope, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()

        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self._update_position_enabled()
        (self._bpm if position_fixed else self._bar).SetFocus()
        if position_fixed:
            self._bpm.SelectAll()

    def _update_position_enabled(self):
        on = not self._position_fixed and self.get_scope() == SCOPE_RECENT
        for ctrl in (self._bar, self._beat, self._tick):
            ctrl.Enable(on)

    def _on_ok(self, event):
        if self.get_bpm() is None:
            wx.MessageBox(f"Tempo invalide : un nombre de {BPM_MIN} à {BPM_MAX} BPM "
                          "(décimales avec une virgule).", "Tempo", wx.OK | wx.ICON_WARNING, self)
            self._bpm.SetFocus()
            return
        if not self._position_fixed and self.get_scope() == SCOPE_RECENT \
                and self.get_position() <= 0:
            wx.MessageBox("La position 1:1:1 est celle du tempo de départ : "
                          "choisissez une position plus loin.", "Tempo",
                          wx.OK | wx.ICON_WARNING, self)
            self._bar.SetFocus()
            return
        event.Skip()

    # ------------------------------------------------------------------

    def get_bpm(self):
        return parse_bpm(self._bpm.GetValue())

    def get_position(self):
        """Position en pas ; la position d'origine (fraction comprise) si
        mesure, temps et pas n'ont pas changé."""
        values = (self._bar.GetValue(), self._beat.GetValue(), self._tick.GetValue())
        if values == self._initial:
            return self._pos
        bar, beat, tick = values
        return (bar - 1) * self._num_steps + (beat - 1) * self._steps_per_beat + (tick - 1)

    def get_scope(self):
        """Portée choisie (DrumPlayer.SCOPE_*) ; SCOPE_RECENT sans choix."""
        return SCOPE_RECENT if self._scope is None else SCOPES[self._scope.GetSelection()]


class TempoDialog(wx.Dialog):
    """Liste des tempos du pattern courant. owner : la fenêtre principale
    (TempoMixin) — tempo_items, positions, insertion, modification,
    suppression avec Undo. Entrée (double-clic) = Modifier, Suppr =
    Supprimer, Échap = Fermer."""

    def __init__(self, parent, owner):
        super().__init__(parent, title="Tempo")
        self._owner = owner
        self._items = []

        label = wx.StaticText(self, label="Tempos du pattern :")
        self._list = wx.ListBox(self, style=wx.LB_SINGLE, size=(320, 220))
        self._list.SetName("Tempos du pattern")
        insert_btn = wx.Button(self, label="&Insérer…")
        modify_btn = wx.Button(self, label="&Modifier…")
        delete_btn = wx.Button(self, label="&Supprimer")
        # Tap Tempo (Phase 7 étape 19i1) : Entrée ou Espace = une frappe
        self._tap_btn = tap_btn = wx.Button(self, label="&Tap Tempo")
        # Click du métronome, pour taper en mesure (19i1) : comme la touche C
        self._click_cb = wx.CheckBox(self, label="&Click (métronome)")
        self._click_cb.SetValue(bool(owner._player.clicking))
        close_btn  = wx.Button(self, wx.ID_CANCEL, "&Fermer")
        self.SetEscapeId(wx.ID_CANCEL)
        # Action de chaque bouton, pour Entrée / Espace (voir _on_char_hook)
        self._actions = {insert_btn: self.insert, modify_btn: self.modify,
                         delete_btn: self.delete, tap_btn: self.tap,
                         close_btn: lambda: self.EndModal(wx.ID_CANCEL)}

        btns = wx.BoxSizer(wx.HORIZONTAL)
        for b in (insert_btn, modify_btn, delete_btn, tap_btn, self._click_cb, close_btn):
            btns.Add(b, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(label,      0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        vbox.Add(self._list, 1, wx.EXPAND | wx.ALL, 8)
        vbox.Add(btns,       0, wx.ALL, 8)
        self.SetSizer(vbox)
        self.Fit()

        insert_btn.Bind(wx.EVT_BUTTON, lambda e: self.insert())
        modify_btn.Bind(wx.EVT_BUTTON, lambda e: self.modify())
        delete_btn.Bind(wx.EVT_BUTTON, lambda e: self.delete())
        tap_btn.Bind(wx.EVT_BUTTON, lambda e: self.tap())
        self._click_cb.Bind(wx.EVT_CHECKBOX, lambda e: self.toggle_click())
        # GTK garde Entrée pour la ListBox : elle arrive en double-clic
        # (cf. feedback_gtk_listbox_enter)
        self._list.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.modify())
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

        self.refresh(select_pos=self._owner._player._current_offset())
        self._list.SetFocus()

    def _on_char_hook(self, event):
        """Suppr sur la liste = Supprimer. EVT_CHAR_HOOK casse sur GTK
        l'activation native d'un bouton par Entrée ou Espace, même avec
        Skip() (cf. feedback_char_hook_enter_dialog_bug) : le dialogue les
        traite donc lui-même — bouton qui a le focus, ou Modifier depuis la
        liste."""
        key   = event.GetKeyCode()
        focus = wx.Window.FindFocus()
        if key == wx.WXK_DELETE and focus is self._list:
            self.delete()
            return
        if key == wx.WXK_SPACE and focus is self._click_cb:
            # Même piège que les boutons : la case est cochée ici
            self._click_cb.SetValue(not self._click_cb.GetValue())
            self.toggle_click()
            return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE):
            if focus in self._actions:
                self._actions[focus]()
                return
            if focus is self._list and key != wx.WXK_SPACE:
                self.modify()
                return
        event.Skip()

    # ------------------------------------------------------------------

    def refresh(self, select_idx=None, select_pos=None):
        """Recharge la liste ; sélectionne l'élément d'indice select_idx, ou
        le tempo en vigueur à select_pos."""
        self._items = self._owner._player.tempo_items()
        self._list.Set([self._owner._tempo_item_label(i, pos, bpm)
                        for i, pos, bpm in self._items])
        row = 0
        if select_idx is not None:
            row = next((r for r, it in enumerate(self._items) if it[0] == select_idx), 0)
        elif select_pos is not None:
            row = max(r for r, it in enumerate(self._items) if it[1] <= select_pos)
        self._list.SetSelection(row)
        # SetString fait relire l'élément par le lecteur d'écran
        self._list.SetString(row, self._list.GetString(row))

    def _selected(self):
        row = self._list.GetSelection()
        return self._items[row] if 0 <= row < len(self._items) else self._items[0]

    def _edit_dialog(self, title, pos, bpm, position_fixed=False, with_scope=False):
        pat = self._owner._player._pattern
        return TempoEditDialog(self, title, pos, bpm, pat._num_bars, pat._num_steps,
                               pat.steps_per_beat(), position_fixed, with_scope)

    def insert(self):
        player = self._owner._player
        pos    = player._current_offset()
        dlg    = self._edit_dialog("Insérer un tempo", pos, player.tempo_at(pos))
        if dlg.ShowModal() == wx.ID_OK:
            pos, bpm = dlg.get_position(), dlg.get_bpm()
            self._owner._tempo_insert(pos, bpm)
            self.refresh(select_pos=pos)
        dlg.Destroy()
        self._list.SetFocus()

    def modify(self):
        idx, pos, bpm = self._selected()
        dlg = self._edit_dialog("Modifier le tempo", pos, bpm,
                                position_fixed=(idx < 0), with_scope=True)
        if dlg.ShowModal() == wx.ID_OK:
            scope   = dlg.get_scope()
            recent  = scope == SCOPE_RECENT
            new_pos = dlg.get_position() if recent and idx >= 0 else pos
            self._owner._tempo_modify(idx, new_pos, dlg.get_bpm(), scope)
            if recent and idx >= 0:
                self.refresh(select_pos=new_pos)      # le tempo, à sa nouvelle place
            else:
                self.refresh(select_idx=idx)          # disparu (à cette valeur) : départ
        dlg.Destroy()
        self._list.SetFocus()

    def tap(self):
        """Une frappe : le tempo sélectionné prend la valeur tapée, tous les
        autres suivent en proportion (comme H). Le libellé du bouton, qui
        garde le focus, dit le tempo obtenu ; la ligne de la liste suit."""
        idx = self._selected()[0]
        bpm = self._owner._tempo_tap(idx)
        if bpm is None:
            return
        self.refresh(select_idx=idx)
        self._tap_btn.SetLabel(f"&Tap Tempo : {format_bpm(bpm)} BPM")

    def toggle_click(self):
        """Case « Click (métronome) » : active ou coupe le click, comme la
        touche C de la fenêtre principale (19i1)."""
        player = self._owner._player
        if self._click_cb.GetValue():
            if not player.clicking:
                player.play_click()
            self._owner._show_status("Click: On")
        else:
            if player.clicking:
                player.stop_click()
            self._owner._show_status("Click: Off")

    def delete(self):
        idx, pos, _bpm = self._selected()
        if idx < 0:
            wx.Bell()
            self._owner._show_status("Le tempo de départ ne se supprime pas")
            return
        self._owner._tempo_delete(idx)
        self.refresh(select_pos=pos)
        self._list.SetFocus()
