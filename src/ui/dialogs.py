import os
import wx
from drum_player import DrumPlayer
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


class QuantizeDialog(wx.Dialog):
    def __init__(self, parent, cur_idx, quant_in_rec=True):
        super().__init__(parent, title="Quantisation du pattern")

        list_label = wx.StaticText(self, label="Valeur de quantisation :")
        self._list = wx.ListBox(
            self,
            choices=["None"] + Pattern.QUANT_LIST,
            style=wx.LB_SINGLE,
        )
        # cur_idx 0..13 → indice dialogue 1..14 ; -1 (None) → 0
        self._list.SetSelection(cur_idx + 1 if cur_idx >= 0 else 0)

        self._quant_in_rec_cb = wx.CheckBox(self, label="Auto in Recording")
        self._quant_in_rec_cb.SetValue(quant_in_rec)

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
        vbox.Add(list_label,            0, wx.ALL, 6)
        vbox.Add(self._list,            1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(self._quant_in_rec_cb, 0, wx.ALL, 6)
        vbox.Add(btn_sizer,             0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._list.SetFocus()

    def get_selection(self):
        """Retourne -1 (None) ou 0..13 (indice dans QUANT_LIST)."""
        return self._list.GetSelection() - 1

    def get_quant_in_recording(self):
        return self._quant_in_rec_cb.GetValue()


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


class TrackPropertiesDialog(wx.Dialog):
    def __init__(self, parent, track_idx, rack, cur_slot_idx, volume, pan, mute, solo,
                 on_change=None, on_play_toggle=None):
        super().__init__(parent, title=f"Propriétés — Piste {track_idx + 1}")

        self._on_change      = on_change
        self._on_play_toggle = on_play_toggle

        # Ordre Tab : Mute → Solo → Slots → Volume → Pan
        self._mute = wx.CheckBox(self, label="Mute")
        self._mute.SetValue(mute)
        self._solo = wx.CheckBox(self, label="Solo")
        self._solo.SetValue(solo)

        slot_label  = wx.StaticText(self, label="Slot :")
        self._slots = wx.ListBox(self, choices=rack.labels(), style=wx.LB_SINGLE)
        self._slots.SetSelection(cur_slot_idx)

        vol_label  = wx.StaticText(self, label="Volume :")
        self._vol  = wx.SpinCtrl(self, min=0, max=100, initial=volume)

        pan_label  = wx.StaticText(self, label="Pan :")
        self._pan  = wx.SpinCtrl(self, min=-100, max=100, initial=pan)

        ok_btn = wx.Button(self, wx.ID_OK, "Ok")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL, "Annuler"))
        btn_sizer.Realize()

        check_sizer = wx.BoxSizer(wx.HORIZONTAL)
        check_sizer.Add(self._mute, 0, wx.RIGHT, 16)
        check_sizer.Add(self._solo, 0)

        grid = wx.FlexGridSizer(rows=2, cols=2, vgap=6, hgap=8)
        grid.Add(vol_label,  0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._vol,  0, wx.EXPAND)
        grid.Add(pan_label,  0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._pan,  0, wx.EXPAND)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(slot_label,  0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        vbox.Add(self._slots, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(check_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(grid,        0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(btn_sizer,   0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()

        # Aperçu en temps réel
        self._mute.Bind(wx.EVT_CHECKBOX, self._on_widget_change)
        self._solo.Bind(wx.EVT_CHECKBOX, self._on_widget_change)
        self._slots.Bind(wx.EVT_LISTBOX, self._on_widget_change)
        self._vol.Bind(wx.EVT_SPINCTRL,  self._on_widget_change)
        self._pan.Bind(wx.EVT_SPINCTRL,  self._on_widget_change)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

        self._mute.SetFocus()

    def _on_widget_change(self, event):
        if self._on_change:
            self._on_change(
                self._slots.GetSelection(),
                self._vol.GetValue(),
                self._pan.GetValue(),
                self._mute.GetValue(),
                self._solo.GetValue(),
            )
        event.Skip()

    def _on_key(self, event):
        if event.ControlDown() and event.GetKeyCode() == ord('P'):
            if self._on_play_toggle:
                self._on_play_toggle()
        else:
            event.Skip()

    def get_slot_idx(self): return self._slots.GetSelection()
    def get_volume(self):   return self._vol.GetValue()
    def get_pan(self):      return self._pan.GetValue()
    def get_mute(self):     return self._mute.GetValue()
    def get_solo(self):     return self._solo.GetValue()


class PatternPropertiesDialog(wx.Dialog):
    _LIST_H  = 90   # hauteur fixe des ListBox à contenu long
    _ACTIONS = ["Courant", "Nouveau", "Doubler", "Diviser par 2"]

    def __init__(self, parent, pat_idx, name, start_bar, num_bars, num_steps,
                 looping, max_bars, valid_steps, on_play_toggle=None):
        super().__init__(parent, title=f"Propriétés — Pattern {pat_idx + 1:02d}")

        self._on_play_toggle = on_play_toggle
        self._max_bars       = max_bars

        # Ordre Tab : Nom → Début → Longueur → Pas → Boucler → Actions

        name_label  = wx.StaticText(self, label="Nom :")
        self._name  = wx.TextCtrl(self, value=name)

        start_label  = wx.StaticText(self, label="Début :")
        self._start  = wx.ListBox(
            self,
            choices=[f"Mesure {i + 1}" for i in range(num_bars)],
            style=wx.LB_SINGLE,
            size=(-1, self._LIST_H),
        )
        self._start.SetSelection(min(start_bar, num_bars - 1))

        length_label  = wx.StaticText(self, label="Longueur :")
        self._length  = wx.ListBox(
            self,
            choices=[str(i) for i in range(1, max_bars + 1)],
            style=wx.LB_SINGLE,
            size=(-1, self._LIST_H),
        )
        self._length.SetSelection(num_bars - 1)
        self._length.Bind(wx.EVT_LISTBOX, self._on_length_change)

        steps_label  = wx.StaticText(self, label="Pas :")
        self._steps  = wx.ListBox(
            self,
            choices=[str(n) for n in valid_steps],
            style=wx.LB_SINGLE,
        )
        self._steps.SetSelection(list(valid_steps).index(num_steps))

        self._loop = wx.CheckBox(self, label="Boucler")
        self._loop.SetValue(looping)

        action_label   = wx.StaticText(self, label="Action :")
        self._actions  = wx.ListBox(
            self,
            choices=self._ACTIONS,
            style=wx.LB_SINGLE,
            size=(-1, self._LIST_H),
        )
        self._actions.SetSelection(0)   # "Courant" par défaut

        ok_btn = wx.Button(self, wx.ID_OK, "Ok")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL, "Annuler"))
        btn_sizer.Realize()

        grid = wx.FlexGridSizer(rows=6, cols=2, vgap=6, hgap=8)
        grid.AddGrowableCol(1)
        grid.Add(name_label,   0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._name,   0, wx.EXPAND)
        grid.Add(start_label,  0, wx.ALIGN_TOP | wx.TOP, 2)
        grid.Add(self._start,  0, wx.EXPAND)
        grid.Add(length_label, 0, wx.ALIGN_TOP | wx.TOP, 2)
        grid.Add(self._length, 0, wx.EXPAND)
        grid.Add(steps_label,  0, wx.ALIGN_TOP | wx.TOP, 2)
        grid.Add(self._steps,  0, wx.EXPAND)
        grid.Add(wx.StaticText(self, label=""), 0)
        grid.Add(self._loop,   0)
        grid.Add(action_label, 0, wx.ALIGN_TOP | wx.TOP, 2)
        grid.Add(self._actions, 0, wx.EXPAND)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(grid,      0, wx.EXPAND | wx.ALL, 8)
        vbox.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()

        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self._name.SetFocus()

    def _on_length_change(self, event):
        new_bars  = event.GetSelection() + 1
        old_start = self._start.GetSelection()
        self._start.Set([f"Mesure {i + 1}" for i in range(new_bars)])
        self._start.SetSelection(min(old_start, new_bars - 1))

    def _on_key(self, event):
        if event.ControlDown() and event.GetKeyCode() == ord('P'):
            if self._on_play_toggle:
                self._on_play_toggle()
        else:
            event.Skip()

    def get_name(self):      return self._name.GetValue().strip()
    def get_start_bar(self): return self._start.GetSelection()          # 0-indexed
    def get_num_bars(self):  return self._length.GetSelection() + 1
    def get_num_steps(self): return int(self._steps.GetStringSelection())
    def get_looping(self):   return self._loop.GetValue()
    def get_action(self):
        sel = self._actions.GetSelection()
        return self._ACTIONS[sel] if sel != wx.NOT_FOUND else "Courant"


class PadPropertiesDialog(wx.Dialog):
    def __init__(self, parent, pad_idx, volume, pan, mute, solo, duration_ms,
                 on_change=None, on_play=None, on_play_toggle=None):
        super().__init__(parent, title=f"Propriétés — Pad {pad_idx + 1}")

        self._on_change      = on_change
        self._on_play        = on_play
        self._on_play_toggle = on_play_toggle
        self._dur_prev       = duration_ms   # pour le pas directionnel de 100 ms

        # Ordre Tab : Mute/Solo → Volume → Pan → Durée
        self._mute = wx.CheckBox(self, label="Mute")
        self._mute.SetValue(mute)
        self._solo = wx.CheckBox(self, label="Solo")
        self._solo.SetValue(solo)

        vol_label = wx.StaticText(self, label="Volume :")
        self._vol = wx.SpinCtrl(self, min=0, max=100, initial=volume)

        pan_label = wx.StaticText(self, label="Pan :")
        self._pan = wx.SpinCtrl(self, min=-100, max=100, initial=pan)

        dur_label = wx.StaticText(self, label="Durée (ms) :")
        self._dur = wx.SpinCtrl(self, min=0, max=9900, initial=duration_ms)
        dur_hint  = wx.StaticText(self, label="(0 = fin du fichier WAV, pas de 100 ms)")

        ok_btn = wx.Button(self, wx.ID_OK, "Ok")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL, "Annuler"))
        btn_sizer.Realize()

        check_sizer = wx.BoxSizer(wx.HORIZONTAL)
        check_sizer.Add(self._mute, 0, wx.RIGHT, 16)
        check_sizer.Add(self._solo, 0)

        grid = wx.FlexGridSizer(rows=3, cols=2, vgap=6, hgap=8)
        grid.AddGrowableCol(1)
        grid.Add(vol_label,  0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._vol,  0, wx.EXPAND)
        grid.Add(pan_label,  0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._pan,  0, wx.EXPAND)
        grid.Add(dur_label,  0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self._dur,  0, wx.EXPAND)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(check_sizer, 0, wx.ALL, 8)
        vbox.Add(grid,        0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(dur_hint,    0, wx.LEFT | wx.BOTTOM, 8)
        vbox.Add(btn_sizer,   0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()

        self._mute.Bind(wx.EVT_CHECKBOX, self._on_check_change)
        self._solo.Bind(wx.EVT_CHECKBOX, self._on_check_change)
        self._vol.Bind(wx.EVT_SPINCTRL,  self._on_spin_change)
        self._pan.Bind(wx.EVT_SPINCTRL,  self._on_spin_change)
        self._dur.Bind(wx.EVT_SPINCTRL,  self._on_dur_spin)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

        self._mute.SetFocus()

    def _notify_change(self):
        if self._on_change:
            self._on_change(
                self._vol.GetValue(),
                self._pan.GetValue(),
                self._mute.GetValue(),
                self._solo.GetValue(),
                self._dur.GetValue(),
            )

    def _on_check_change(self, event):
        self._notify_change()
        event.Skip()

    def _on_spin_change(self, event):
        self._notify_change()
        if self._on_play:
            self._on_play()
        event.Skip()

    def _on_dur_spin(self, event):
        """Pas de 100 ms : snap directionnel pour que flèche haut/bas avance de 100."""
        val  = self._dur.GetValue()
        prev = self._dur_prev
        if val > prev:
            snapped = ((val - 1) // 100 + 1) * 100   # arrondir vers le haut
        elif val < prev:
            snapped = (val // 100) * 100              # arrondir vers le bas
        else:
            snapped = val
        snapped = max(0, min(9900, snapped))
        self._dur_prev = snapped
        self._dur.SetValue(snapped)
        self._notify_change()
        if self._on_play:
            self._on_play()
        event.Skip()

    def _on_key(self, event):
        if event.ControlDown() and event.GetKeyCode() == ord('P'):
            if self._on_play_toggle:
                self._on_play_toggle()
        else:
            event.Skip()

    def get_volume(self):      return self._vol.GetValue()
    def get_pan(self):         return self._pan.GetValue()
    def get_mute(self):        return self._mute.GetValue()
    def get_solo(self):        return self._solo.GetValue()
    def get_duration_ms(self): return self._dur.GetValue()


class ExplorerDialog(wx.Dialog):
    """Choix du type de fichier à charger : Kit, Patch ou Sound."""
    ITEMS = ["Preset", "Kit", "Patch", "Sound"]

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
        self.SetSize((220, 160))
        self.Centre()

        self._listbox.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.EndModal(wx.ID_OK))
        self._listbox.SetFocus()

    def get_selection(self):
        return self._listbox.GetStringSelection()


class GotoDialog(wx.Dialog):
    """Boîte de dialogue 'Aller à' — unité + SpinCtrl + TextCtrl (bar:beat:tick)."""

    UNITS = ["Mesures", "Battements", "Ticks", "Temps (s)"]

    def __init__(self, parent, step_idx, num_bars, num_beats, num_steps, step_duration):
        super().__init__(parent, title="Aller à")
        self._num_bars       = num_bars
        self._num_beats      = num_beats
        self._num_steps      = num_steps
        self._step_duration  = step_duration
        self._steps_per_beat = max(1, num_steps // num_beats)
        self._total_steps    = num_bars * num_steps
        self._cur_unit       = 0
        self._cur_step       = max(0, int(step_idx))

        unit_label = wx.StaticText(self, label="Unité :")
        self._unit_list = wx.ListBox(self, choices=self.UNITS, style=wx.LB_SINGLE)
        self._unit_list.SetSelection(0)

        spin_label     = wx.StaticText(self, label="Valeur :")
        self._spin     = wx.SpinCtrl(self, min=1, max=max(1, num_bars), size=(90, -1))

        self._hint_label = wx.StaticText(self, label="bar:beat:tick :")
        self._text       = wx.TextCtrl(self, size=(110, -1), style=wx.TE_PROCESS_ENTER)

        ok_btn     = wx.Button(self, wx.ID_OK, "Ok")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()

        spin_row = wx.BoxSizer(wx.HORIZONTAL)
        spin_row.Add(spin_label,  0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        spin_row.Add(self._spin, 0)

        text_row = wx.BoxSizer(wx.HORIZONTAL)
        text_row.Add(self._hint_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        text_row.Add(self._text,       1, wx.EXPAND)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(unit_label,       0, wx.ALL, 6)
        vbox.Add(self._unit_list,  1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(spin_row,         0, wx.ALL, 6)
        vbox.Add(text_row,         0, wx.EXPAND | wx.ALL, 6)
        vbox.Add(btn_sizer,        0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)

        self._unit_list.Bind(wx.EVT_LISTBOX,        self._on_unit_change)
        self._unit_list.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.EndModal(wx.ID_OK))
        self._spin.Bind(wx.EVT_SPINCTRL,            self._on_spin_change)
        self._spin.Bind(wx.EVT_KEY_DOWN,            self._on_spin_key)
        self._text.Bind(wx.EVT_TEXT_ENTER,          self._on_text_enter)

        self.Fit()
        # GTK réinitialise SpinCtrl au layout : reposer range + valeurs après Fit()
        self._refresh_unit(0)
        self._unit_list.SetFocus()

    # ------------------------------------------------------------------
    # Helpers internes
    # ------------------------------------------------------------------

    def _step_to_spin(self, unit, step):
        """step (0-based) → valeur SpinCtrl pour l'unité."""
        if unit == 0:   return step // self._num_steps + 1
        elif unit == 1: return step // self._steps_per_beat + 1
        elif unit == 2: return step + 1
        else:           return int(step * self._step_duration)

    def _step_to_text(self, unit, step):
        """step (0-based) → chaîne affichée dans le TextCtrl."""
        step = max(0, step)
        bar  = step // self._num_steps
        rem  = step % self._num_steps
        beat = rem // self._steps_per_beat
        tick = rem % self._steps_per_beat
        if unit == 3:
            return f"{step * self._step_duration:.1f}"
        return f"{bar + 1}:{beat + 1}:{tick + 1}"

    def _spin_range(self, unit):
        # Pas de borne supérieure liée au pattern : l'utilisateur peut saisir
        # une mesure au-delà de la fin pour positionner le collage.
        if unit == 0:   return (1, 9999)
        elif unit == 1: return (1, 9999 * max(1, self._num_beats))
        elif unit == 2: return (1, 9999 * max(1, self._num_steps))
        else:           return (0, 99999)

    def _refresh_unit(self, unit):
        """Met à jour range SpinCtrl, sa valeur et le TextCtrl depuis _cur_step."""
        mn, mx = self._spin_range(unit)
        self._spin.SetRange(mn, mx)
        self._spin.SetValue(self._step_to_spin(unit, self._cur_step))
        self._text.ChangeValue(self._step_to_text(unit, self._cur_step))
        hint = "secondes :" if unit == 3 else "bar:beat:tick :"
        self._hint_label.SetLabel(hint)

    def _parse_text(self, unit, s):
        """Parse la saisie libre → step_idx (0-based) ou None si invalide."""
        s = s.strip()
        parts = s.split(":")
        try:
            if unit == 3:
                off = float(s) / max(self._step_duration, 1e-9)
            elif len(parts) == 3:
                bar, beat, tick = int(parts[0]) - 1, int(parts[1]) - 1, int(parts[2]) - 1
                off = bar * self._num_steps + beat * self._steps_per_beat + tick
            elif len(parts) == 2:
                bar, beat = int(parts[0]) - 1, int(parts[1]) - 1
                off = bar * self._num_steps + beat * self._steps_per_beat
            else:
                val = int(s)
                off = self.to_offset(unit, val, self._num_bars, self._num_beats,
                                     self._num_steps, self._step_duration)
            return int(max(0, off))
        except (ValueError, IndexError):
            return None

    # ------------------------------------------------------------------
    # Handlers événements
    # ------------------------------------------------------------------

    def _on_unit_change(self, event):
        new_unit = self._unit_list.GetSelection()
        if new_unit == wx.NOT_FOUND or new_unit == self._cur_unit:
            return
        self._cur_unit = new_unit
        self._refresh_unit(new_unit)

    def _on_spin_change(self, event):
        val = self._spin.GetValue()
        off = self.to_offset(self._cur_unit, val, self._num_bars, self._num_beats,
                             self._num_steps, self._step_duration)
        self._cur_step = int(max(0, off))
        self._text.ChangeValue(self._step_to_text(self._cur_unit, self._cur_step))

    def _on_spin_key(self, event):
        """Flèche Bas → augmente, Flèche Haut → diminue (inverse du comportement standard)."""
        key = event.GetKeyCode()
        mn, mx = self._spin_range(self._cur_unit)
        val = self._spin.GetValue()
        if key == wx.WXK_DOWN:
            self._spin.SetValue(min(mx, val + 1))
            self._on_spin_change(None)
        elif key == wx.WXK_UP:
            self._spin.SetValue(max(mn, val - 1))
            self._on_spin_change(None)
        else:
            event.Skip()

    def _on_text_enter(self, event):
        step = self._parse_text(self._cur_unit, self._text.GetValue())
        if step is not None:
            self._cur_step = step
            mn, mx = self._spin_range(self._cur_unit)
            self._spin.SetValue(
                max(mn, min(mx, self._step_to_spin(self._cur_unit, step)))
            )
        self.EndModal(wx.ID_OK)

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    @staticmethod
    def to_offset(unit_idx, value, num_bars, num_beats, num_steps, step_duration):
        """Convertit (unité, valeur) → offset flottant 0-based, sans borne supérieure."""
        steps_per_beat = max(1, num_steps // num_beats)
        if unit_idx == 0:    off = (value - 1) * num_steps
        elif unit_idx == 1:  off = (value - 1) * steps_per_beat
        elif unit_idx == 2:  off = value - 1
        else:                off = value / max(step_duration, 1e-9)
        return float(max(0, off))

    def get_offset(self):
        """Retourne l'offset courant en pas (float, 0-based)."""
        return float(self._cur_step)


class TrackSelectDialog(wx.Dialog):
    """Sélection de pistes (checkboxes) + plage temporelle (bar:beat:tick)."""

    def __init__(self, parent, num_tracks, sel_tracks, track_labels,
                 num_bars, num_beats, num_steps, cur_step,
                 lim_left=None, lim_right=None):
        super().__init__(parent, title="Sélection de pistes")

        self._num_steps      = num_steps
        self._steps_per_beat = max(1, num_steps // num_beats)
        self._total_steps    = num_bars * num_steps

        # --- Checkboxes pistes ---
        checks_box   = wx.StaticBox(self, label="Pistes")
        checks_sizer = wx.StaticBoxSizer(checks_box, wx.VERTICAL)
        self._checks = []
        for i in range(num_tracks):
            lbl = track_labels[i] if i < len(track_labels) else f"Track {i + 1:02d}"
            cb  = wx.CheckBox(self, label=lbl)
            cb.SetValue(i in sel_tracks)
            self._checks.append(cb)
            checks_sizer.Add(cb, 0, wx.LEFT | wx.TOP, 4)
        checks_sizer.AddSpacer(4)

        start_step = lim_left  if lim_left  is not None else cur_step
        end_step   = lim_right if lim_right is not None else (self._total_steps - 1)

        # --- Champs BBT ---
        start_label = wx.StaticText(self, label="Début sélection :")
        self._start = wx.TextCtrl(self, size=(120, -1), style=wx.TE_PROCESS_ENTER)
        self._start.SetValue(self._fmt_bbt(start_step))

        end_label = wx.StaticText(self, label="Fin sélection :")
        self._end  = wx.TextCtrl(self, size=(120, -1), style=wx.TE_PROCESS_ENTER)
        self._end.SetValue(self._fmt_bbt(end_step))

        range_grid = wx.FlexGridSizer(rows=2, cols=2, vgap=6, hgap=8)
        range_grid.AddGrowableCol(1)
        range_grid.Add(start_label, 0, wx.ALIGN_CENTER_VERTICAL)
        range_grid.Add(self._start, 1, wx.EXPAND)
        range_grid.Add(end_label,   0, wx.ALIGN_CENTER_VERTICAL)
        range_grid.Add(self._end,   1, wx.EXPAND)

        # --- Boutons ---
        self._ok_btn     = wx.Button(self, wx.ID_OK, "Ok")
        self._cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        self._ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(self._ok_btn)
        btn_sizer.AddButton(self._cancel_btn)
        btn_sizer.Realize()

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(checks_sizer, 0, wx.EXPAND | wx.ALL, 8)
        vbox.Add(range_grid,   0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(btn_sizer,    0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()

        # Ordre Tab manuel (même technique que MainWindow._tab_order)
        self._tab_order = self._checks + [self._start, self._end,
                                          self._ok_btn, self._cancel_btn]

        self._start.Bind(wx.EVT_TEXT_ENTER, lambda e: self.EndModal(wx.ID_OK))
        self._end.Bind(wx.EVT_TEXT_ENTER,   lambda e: self.EndModal(wx.ID_OK))
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

        if self._checks:
            self._checks[0].SetFocus()

    # ------------------------------------------------------------------
    # Helpers BBT
    # ------------------------------------------------------------------

    def _fmt_bbt(self, step):
        """step 0-based → 'bar:beat:tick' 1-based."""
        step = max(0, min(step, self._total_steps - 1))
        bar  = step // self._num_steps
        rem  = step % self._num_steps
        beat = rem // self._steps_per_beat
        tick = rem % self._steps_per_beat
        return f"{bar + 1}:{beat + 1}:{tick + 1}"

    def _parse_bbt(self, s):
        """'bar:beat:tick' | 'bar:beat' | 'bar' → step 0-based, ou None si invalide."""
        parts = s.strip().split(":")
        try:
            if len(parts) >= 3:
                off = ((int(parts[0]) - 1) * self._num_steps
                       + (int(parts[1]) - 1) * self._steps_per_beat
                       + (int(parts[2]) - 1))
            elif len(parts) == 2:
                off = ((int(parts[0]) - 1) * self._num_steps
                       + (int(parts[1]) - 1) * self._steps_per_beat)
            else:
                off = (int(parts[0]) - 1) * self._num_steps
            return int(max(0, min(self._total_steps - 1, off)))
        except (ValueError, IndexError):
            return None

    # ------------------------------------------------------------------
    # Événements
    # ------------------------------------------------------------------

    def _on_key(self, event):
        key   = event.GetKeyCode()
        shift = event.ShiftDown()
        if key == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        if key == wx.WXK_TAB:
            focused = wx.Window.FindFocus()
            order   = self._tab_order
            if focused in order:
                idx    = order.index(focused)
                target = order[idx - 1] if shift else order[(idx + 1) % len(order)]
            else:
                target = order[-1] if shift else order[0]
            wx.CallAfter(target.SetFocus)
            return
        event.Skip()

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def get_sel_tracks(self):
        """Ensemble des indices de pistes cochées (0-based)."""
        return {i for i, cb in enumerate(self._checks) if cb.GetValue()}

    def get_start_step(self):
        """Step de début (0-based) ; 0 si saisie invalide."""
        v = self._parse_bbt(self._start.GetValue())
        return v if v is not None else 0

    def get_end_step(self):
        """Step de fin (0-based) ; total_steps-1 si saisie invalide."""
        v = self._parse_bbt(self._end.GetValue())
        return v if v is not None else self._total_steps - 1
