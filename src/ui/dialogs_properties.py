import wx


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
