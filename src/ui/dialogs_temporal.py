import wx


class BBTHelper:
    """Conversion step ↔ bar:beat:tick, partagée par les dialogs temporels."""

    def __init__(self, num_steps, steps_per_beat, total_steps):
        self._num_steps      = num_steps
        self._steps_per_beat = steps_per_beat
        self._total_steps    = total_steps

    def fmt(self, step):
        """step 0-based → 'bar:beat:tick' 1-based."""
        step = max(0, min(step, self._total_steps - 1))
        bar  = step // self._num_steps
        rem  = step % self._num_steps
        beat = rem // self._steps_per_beat
        tick = rem % self._steps_per_beat
        return f"{bar + 1}:{beat + 1}:{tick + 1}"

    def parse(self, s):
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
        self._bbt            = BBTHelper(num_steps, self._steps_per_beat, self._total_steps)

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
        self._start.SetValue(self._bbt.fmt(start_step))

        end_label = wx.StaticText(self, label="Fin sélection :")
        self._end  = wx.TextCtrl(self, size=(120, -1), style=wx.TE_PROCESS_ENTER)
        self._end.SetValue(self._bbt.fmt(end_step))

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
    # Compatibilité tests (délèguent à BBTHelper)
    # ------------------------------------------------------------------

    def _fmt_bbt(self, step):
        return self._bbt.fmt(step)

    def _parse_bbt(self, s):
        return self._bbt.parse(s)

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
        v = self._bbt.parse(self._start.GetValue())
        return v if v is not None else 0

    def get_end_step(self):
        """Step de fin (0-based) ; total_steps-1 si saisie invalide."""
        v = self._bbt.parse(self._end.GetValue())
        return v if v is not None else self._total_steps - 1


# ---------------------------------------------------------------------------

_LOOP_SOURCES = [
    "Position courante",
    "Début du pattern",
    "Fin du pattern",
    "Limiteur gauche",
    "Limiteur droit",
    "Personnalisé",
]
_SRC_CUR    = 0
_SRC_START  = 1
_SRC_END    = 2
_SRC_LIM_L  = 3
_SRC_LIM_R  = 4
_SRC_CUSTOM = 5


class LoopSelectDialog(wx.Dialog):
    """Définit la fenêtre de boucle du pattern (_loop_start/_loop_end/_loop_count)."""

    def __init__(self, parent,
                 num_bars, num_beats, num_steps,
                 cur_step, loop_start, loop_end, loop_count,
                 looping=True, lim_left=None, lim_right=None,
                 on_play_toggle=None):
        super().__init__(parent, title="Points de boucle")
        self._on_play_toggle = on_play_toggle

        self._num_steps      = num_steps
        self._steps_per_beat = max(1, num_steps // num_beats)
        self._total_steps    = num_bars * num_steps
        self._cur_step       = max(0, min(cur_step, self._total_steps - 1))
        self._lim_left       = lim_left
        self._lim_right      = lim_right
        self._updating       = False   # évite les boucles de MAJ ListBox ↔ TextCtrl
        self._bbt            = BBTHelper(num_steps, self._steps_per_beat, self._total_steps)

        # --- Fenêtre Début ---
        start_box    = wx.StaticBox(self, label="Début de boucle")
        start_sizer  = wx.StaticBoxSizer(start_box, wx.VERTICAL)
        self._start_list = wx.ListBox(self, choices=_LOOP_SOURCES, style=wx.LB_SINGLE,
                                      size=(-1, 110))
        start_label = wx.StaticText(self, label="Position (bar:beat:tick) :")
        self._start_ctrl = wx.TextCtrl(self, size=(140, -1), style=wx.TE_PROCESS_ENTER)
        start_sizer.Add(self._start_list,  1, wx.EXPAND | wx.ALL, 4)
        start_sizer.Add(start_label,       0, wx.LEFT | wx.RIGHT, 4)
        start_sizer.Add(self._start_ctrl,  0, wx.EXPAND | wx.ALL, 4)

        # --- Fenêtre Fin ---
        end_box   = wx.StaticBox(self, label="Fin de boucle")
        end_sizer = wx.StaticBoxSizer(end_box, wx.VERTICAL)
        self._end_list = wx.ListBox(self, choices=_LOOP_SOURCES, style=wx.LB_SINGLE,
                                    size=(-1, 110))
        end_label = wx.StaticText(self, label="Position (bar:beat:tick) :")
        self._end_ctrl = wx.TextCtrl(self, size=(140, -1), style=wx.TE_PROCESS_ENTER)
        end_sizer.Add(self._end_list,  1, wx.EXPAND | wx.ALL, 4)
        end_sizer.Add(end_label,       0, wx.LEFT | wx.RIGHT, 4)
        end_sizer.Add(self._end_ctrl,  0, wx.EXPAND | wx.ALL, 4)

        panels = wx.BoxSizer(wx.HORIZONTAL)
        panels.Add(start_sizer, 1, wx.EXPAND | wx.ALL, 6)
        panels.Add(end_sizer,   1, wx.EXPAND | wx.ALL, 6)

        # --- Boucle Active ---
        self._looping_cb = wx.CheckBox(self, label="Boucle Active")
        self._looping_cb.SetValue(looping)

        # --- Répétitions ---
        rep_label   = wx.StaticText(self, label="Répétitions (0 = infini) :")
        self._rep_spin = wx.SpinCtrl(self, min=0, max=999, initial=loop_count)

        rep_row = wx.BoxSizer(wx.HORIZONTAL)
        rep_row.Add(rep_label,      0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        rep_row.Add(self._rep_spin, 0)

        # --- Boutons ---
        self._ok_btn     = wx.Button(self, wx.ID_OK,     "Ok")
        self._cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        self._ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(self._ok_btn)
        btn_sizer.AddButton(self._cancel_btn)
        btn_sizer.Realize()

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(panels,           0, wx.EXPAND)
        vbox.Add(self._looping_cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(rep_row,          0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vbox.Add(btn_sizer,        0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)

        # Initialiser les valeurs
        start_val = loop_start if loop_start is not None else 0
        end_val   = loop_end   if loop_end   is not None else self._total_steps - 1
        self._start_ctrl.SetValue(self._bbt.fmt(start_val))
        self._end_ctrl.SetValue(self._bbt.fmt(end_val))
        self._start_list.SetSelection(self._step_to_source(start_val))
        self._end_list.SetSelection(self._step_to_source(end_val))

        self.Fit()
        # GTK réinitialise SpinCtrl au layout ; réappliquer après Fit()
        self._rep_spin.SetValue(loop_count)

        # Liaisons
        self._start_list.Bind(wx.EVT_LISTBOX, self._on_start_source)
        self._end_list.Bind(wx.EVT_LISTBOX,   self._on_end_source)
        self._start_ctrl.Bind(wx.EVT_TEXT_ENTER, self._on_start_text)
        self._end_ctrl.Bind(wx.EVT_TEXT_ENTER,   self._on_end_text)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

        self._start_list.SetFocus()

    # ------------------------------------------------------------------
    # Compatibilité tests (délèguent à BBTHelper)
    # ------------------------------------------------------------------

    def _fmt_bbt(self, step):
        return self._bbt.fmt(step)

    def _parse_bbt(self, s):
        return self._bbt.parse(s)

    # ------------------------------------------------------------------
    # Helpers source ↔ step
    # ------------------------------------------------------------------

    def _step_to_source(self, step):
        """Trouve l'indice de source correspondant à step, ou _SRC_CUSTOM."""
        if step == self._cur_step:
            return _SRC_CUR
        if step == 0:
            return _SRC_START
        if step == self._total_steps - 1:
            return _SRC_END
        if self._lim_left is not None and step == self._lim_left:
            return _SRC_LIM_L
        if self._lim_right is not None and step == self._lim_right:
            return _SRC_LIM_R
        return _SRC_CUSTOM

    def _source_to_step(self, src_idx):
        """Retourne la valeur de step pour une source, ou None si Personnalisé."""
        if src_idx == _SRC_CUR:
            return self._cur_step
        if src_idx == _SRC_START:
            return 0
        if src_idx == _SRC_END:
            return self._total_steps - 1
        if src_idx == _SRC_LIM_L:
            return self._lim_left if self._lim_left is not None else 0
        if src_idx == _SRC_LIM_R:
            return self._lim_right if self._lim_right is not None else self._total_steps - 1
        return None  # Personnalisé

    # ------------------------------------------------------------------
    # Événements
    # ------------------------------------------------------------------

    def _on_start_source(self, event):
        src = self._start_list.GetSelection()
        if src == wx.NOT_FOUND or src == _SRC_CUSTOM or self._updating:
            return
        step = self._source_to_step(src)
        if step is not None:
            self._updating = True
            self._start_ctrl.SetValue(self._bbt.fmt(step))
            self._updating = False

    def _on_end_source(self, event):
        src = self._end_list.GetSelection()
        if src == wx.NOT_FOUND or src == _SRC_CUSTOM or self._updating:
            return
        step = self._source_to_step(src)
        if step is not None:
            self._updating = True
            self._end_ctrl.SetValue(self._bbt.fmt(step))
            self._updating = False

    def _on_start_text(self, event):
        if self._updating:
            return
        self._updating = True
        self._start_list.SetSelection(_SRC_CUSTOM)
        self._updating = False

    def _on_end_text(self, event):
        if self._updating:
            return
        self._updating = True
        self._end_list.SetSelection(_SRC_CUSTOM)
        self._updating = False

    def _on_key(self, event):
        key  = event.GetKeyCode()
        ctrl = event.ControlDown()
        if key == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        if ctrl and key == ord('P'):
            if self._on_play_toggle:
                self._on_play_toggle()
            return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            focused = wx.Window.FindFocus()
            if focused in (self._start_ctrl, self._end_ctrl):
                self._on_start_text(None)
                self._on_end_text(None)
            self.EndModal(wx.ID_OK)
            return
        event.Skip()

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def get_looping(self):
        return self._looping_cb.GetValue()

    def get_loop_start(self):
        """None si début du pattern, sinon step 0-based."""
        v = self._bbt.parse(self._start_ctrl.GetValue())
        step = v if v is not None else 0
        return None if step == 0 else step

    def get_loop_end(self):
        """None si fin du pattern, sinon step 0-based."""
        v = self._bbt.parse(self._end_ctrl.GetValue())
        step = v if v is not None else self._total_steps - 1
        return None if step == self._total_steps - 1 else step

    def get_loop_count(self):
        return self._rep_spin.GetValue()
