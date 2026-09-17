import wx
from synth_engine import midi_to_note_name
from pattern import ETYPE_GRID


class _NoteEditDialog(wx.Dialog):
    """Dialog d'édition d'une note (pad/pitch, position, durée, vélocité)."""

    def __init__(self, parent, ev, pattern, pad_names, title="Éditer note"):
        from synth_engine import midi_to_note_name
        etype     = ev.get("etype", ETYPE_GRID)
        super().__init__(parent, title=title,
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        num_bars  = pattern._num_bars
        num_steps = pattern._num_steps
        num_pads  = pattern._num_pads
        self._etype = etype

        # Sélecteur instrument : pad (GRID, index 0..num_pads-1) ou note MIDI
        # brute (KIT/PATCH, 0..127 — voir TrackRouter.on_kit_tape/on_patch_tape,
        # même convention que _MidiEventEditDialog).
        if etype == ETYPE_GRID:
            inst_lbl      = wx.StaticText(self, label="Pad :")
            self._inst_lb = wx.ListBox(self, choices=pad_names,
                                       style=wx.LB_SINGLE, size=(140, 200))
            self._inst_lb.SetSelection(min(max(ev["pad"], 0), num_pads - 1))
        else:
            inst_lbl      = wx.StaticText(self, label="Note :")
            note_choices  = [f"{i:3d}  {midi_to_note_name(i)}" for i in range(128)]
            self._inst_lb = wx.ListBox(self, choices=note_choices,
                                       style=wx.LB_SINGLE, size=(160, 200))
            self._inst_lb.SetSelection(min(max(ev["pad"], 0), 127))

        bar_lbl         = wx.StaticText(self, label="Mesure :")
        self._bar_ctrl  = wx.SpinCtrl(self, min=1, max=num_bars,
                                      initial=ev["bar"] + 1, size=(70, -1))
        step_lbl        = wx.StaticText(self, label="Pas :")
        self._step_ctrl = wx.SpinCtrl(self, min=1, max=num_steps,
                                      initial=ev["step"] + 1, size=(70, -1))

        # Durée : éditable pour les événements tape (KIT/PATCH), lecture seule pour GRID
        dur_lbl        = wx.StaticText(self, label="Durée (ms) :")
        self._dur_ctrl = wx.SpinCtrl(self, min=10, max=30000,
                                     initial=max(10, ev.get("dur", 500)), size=(80, -1))
        if etype == ETYPE_GRID:
            self._dur_ctrl.Enable(False)

        vel_lbl        = wx.StaticText(self, label="Vélocité :")
        self._vel_ctrl = wx.SpinCtrl(self, min=1, max=127,
                                     initial=max(1, ev["vel"]), size=(80, -1))

        ok_btn     = wx.Button(self, wx.ID_OK,     "Ok")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        ok_btn.SetDefault()

        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()

        pos_hbox = wx.BoxSizer(wx.HORIZONTAL)
        pos_hbox.Add(bar_lbl,         0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        pos_hbox.Add(self._bar_ctrl,  0, wx.RIGHT, 12)
        pos_hbox.Add(step_lbl,        0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        pos_hbox.Add(self._step_ctrl, 0)

        right_vbox = wx.BoxSizer(wx.VERTICAL)
        right_vbox.Add(wx.StaticText(self, label="Position :"), 0, wx.BOTTOM, 2)
        right_vbox.Add(pos_hbox,       0, wx.BOTTOM, 10)
        right_vbox.Add(dur_lbl,        0, wx.BOTTOM, 2)
        right_vbox.Add(self._dur_ctrl, 0, wx.BOTTOM, 10)
        right_vbox.Add(vel_lbl,        0, wx.BOTTOM, 2)
        right_vbox.Add(self._vel_ctrl, 0)

        left_vbox = wx.BoxSizer(wx.VERTICAL)
        left_vbox.Add(inst_lbl,       0, wx.BOTTOM, 2)
        left_vbox.Add(self._inst_lb,  1, wx.EXPAND)

        top_hbox = wx.BoxSizer(wx.HORIZONTAL)
        top_hbox.Add(left_vbox,  0, wx.EXPAND | wx.RIGHT, 12)
        top_hbox.Add(right_vbox, 1, wx.EXPAND)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(top_hbox,  1, wx.EXPAND | wx.ALL, 8)
        vbox.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._inst_lb.SetFocus()

    def get_inst(self):
        return self._inst_lb.GetSelection()

    def get_bar(self):
        return self._bar_ctrl.GetValue() - 1

    def get_step(self):
        return self._step_ctrl.GetValue() - 1

    def get_dur(self):
        return self._dur_ctrl.GetValue()

    def get_vel(self):
        return self._vel_ctrl.GetValue()


class _MidiEventEditDialog(wx.Dialog):
    """Dialog d'édition MIDI : note (C0..G10), position BBT, durée BBT, vélocité."""

    def __init__(self, parent, ev, pattern):
        etype          = ev.get("etype", ETYPE_GRID)
        num_bars       = pattern._num_bars
        num_steps      = pattern._num_steps
        num_beats      = pattern._num_beats
        steps_per_beat = max(1, num_steps // num_beats)
        bpm            = max(1, pattern._bpm)

        bar  = ev["bar"]
        step = ev["step"]
        beat = step // steps_per_beat
        tick = step % steps_per_beat

        ms_per_tick     = (60000.0 / bpm) / steps_per_beat
        dur_ms          = max(10, ev.get("dur", 500))
        dur_total_ticks = round(dur_ms / ms_per_tick)
        dur_bars        = dur_total_ticks // num_steps
        dur_rem         = dur_total_ticks % num_steps
        dur_beats       = dur_rem // steps_per_beat
        dur_ticks       = dur_rem % steps_per_beat

        self._steps_per_beat   = steps_per_beat
        self._num_steps        = num_steps
        self._num_bars         = num_bars
        self._num_beats        = num_beats
        self._ms_per_tick      = ms_per_tick
        self._etype            = etype
        self._updating         = False
        self._ev               = ev
        self._parent_window    = parent   # MidiEditorWindow

        super().__init__(parent, title="Éditer événement MIDI",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        # --- Note / pad (choix selon etype — voir _dialog_note_choices) ---
        note_choices, sel = parent._dialog_note_choices(ev, pattern)
        note_lbl      = wx.StaticText(self, label="Pad :" if etype == ETYPE_GRID else "Note :")
        self._note_lb = wx.ListBox(self, choices=note_choices,
                                   style=wx.LB_SINGLE, size=(160, 240))
        self._note_lb.SetSelection(sel)
        self._note_lb.SetFirstItem(max(0, sel - 4))
        self._note_lb.Bind(wx.EVT_LISTBOX,       self._on_note_select)
        self._note_lb.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.EndModal(wx.ID_OK))

        # --- Position ---
        pos_lbl       = wx.StaticText(self, label="Position :")
        bar_lbl       = wx.StaticText(self, label="Bar")
        beat_lbl      = wx.StaticText(self, label="Beat")
        tick_lbl      = wx.StaticText(self, label="Tick")
        self._bar_sp  = wx.SpinCtrl(self, min=1, max=num_bars,       initial=bar+1,  size=(55, -1))
        self._beat_sp = wx.SpinCtrl(self, min=1, max=num_beats,      initial=beat+1, size=(55, -1))
        self._tick_sp = wx.SpinCtrl(self, min=1, max=steps_per_beat, initial=tick+1, size=(55, -1))
        # Noms accessibles distincts (lecteur d'écran) : un SpinCtrl seul
        # n'annonce que sa valeur, jamais le StaticText voisin — voir
        # feedback_accessibility_spinctrl.
        self._bar_sp.SetName("Bar")
        self._beat_sp.SetName("Beat")
        self._tick_sp.SetName("Tick")
        bbt_lbl       = wx.StaticText(self, label="bar:batt:tck :")
        self._pos_txt = wx.TextCtrl(self, value=f"{bar+1}:{beat+1}:{tick+1}",
                                    size=(90, -1), style=wx.TE_PROCESS_ENTER)

        self._bar_sp.Bind(wx.EVT_SPINCTRL,   self._on_spin_change)
        self._beat_sp.Bind(wx.EVT_SPINCTRL,  self._on_spin_change)
        self._tick_sp.Bind(wx.EVT_SPINCTRL,  self._on_spin_change)
        self._pos_txt.Bind(wx.EVT_TEXT_ENTER, self._on_pos_confirm)
        self._pos_txt.Bind(wx.EVT_KILL_FOCUS, self._on_pos_confirm)

        # --- Durée BBT (désactivée pour GRID : dérive des réglages du pad) ---
        dur_lbl       = wx.StaticText(self, label="Durée (mes:batt:tck) :")
        self._dur_txt = wx.TextCtrl(self, value=f"{dur_bars}:{dur_beats}:{dur_ticks}",
                                    size=(90, -1))
        if etype == ETYPE_GRID:
            self._dur_txt.Enable(False)

        # --- Vélocité ---
        vel_lbl      = wx.StaticText(self, label="Vélocité :")
        self._vel_sp = wx.SpinCtrl(self, min=1, max=127,
                                   initial=max(1, ev.get("vel", 100)), size=(70, -1))

        # --- Boutons ---
        ok_btn     = wx.Button(self, wx.ID_OK,     "Ok")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()

        # --- Layout ---
        spin_hbox = wx.BoxSizer(wx.HORIZONTAL)
        spin_hbox.Add(bar_lbl,        0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        spin_hbox.Add(self._bar_sp,   0, wx.RIGHT, 6)
        spin_hbox.Add(beat_lbl,       0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        spin_hbox.Add(self._beat_sp,  0, wx.RIGHT, 6)
        spin_hbox.Add(tick_lbl,       0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        spin_hbox.Add(self._tick_sp,  0)

        right_vbox = wx.BoxSizer(wx.VERTICAL)
        right_vbox.Add(pos_lbl,        0, wx.BOTTOM, 2)
        right_vbox.Add(spin_hbox,      0, wx.BOTTOM, 4)
        right_vbox.Add(bbt_lbl,        0, wx.BOTTOM, 2)
        right_vbox.Add(self._pos_txt,  0, wx.BOTTOM, 10)
        right_vbox.Add(dur_lbl,        0, wx.BOTTOM, 2)
        right_vbox.Add(self._dur_txt,  0, wx.BOTTOM, 10)
        right_vbox.Add(vel_lbl,        0, wx.BOTTOM, 2)
        right_vbox.Add(self._vel_sp,   0)

        left_vbox = wx.BoxSizer(wx.VERTICAL)
        left_vbox.Add(note_lbl,       0, wx.BOTTOM, 2)
        left_vbox.Add(self._note_lb,  1, wx.EXPAND)

        top_hbox = wx.BoxSizer(wx.HORIZONTAL)
        top_hbox.Add(left_vbox,  0, wx.EXPAND | wx.RIGHT, 12)
        top_hbox.Add(right_vbox, 1, wx.EXPAND)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(top_hbox,  1, wx.EXPAND | wx.ALL, 8)
        vbox.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._note_lb.SetFocus()

    def _on_spin_change(self, evt):
        if self._updating:
            return
        self._updating = True
        bar  = self._bar_sp.GetValue()
        beat = self._beat_sp.GetValue()
        tick = self._tick_sp.GetValue()
        self._pos_txt.ChangeValue(f"{bar}:{beat}:{tick}")
        self._updating = False

    def _on_pos_confirm(self, evt):
        if self._updating:
            evt.Skip()
            return
        self._updating = True
        parts = self._pos_txt.GetValue().strip().split(":")
        if len(parts) == 3:
            try:
                bar  = int(parts[0])
                beat = int(parts[1])
                tick = int(parts[2])
                if (1 <= bar  <= self._num_bars and
                        1 <= beat <= self._num_beats and
                        1 <= tick <= self._steps_per_beat):
                    self._bar_sp.SetValue(bar)
                    self._beat_sp.SetValue(beat)
                    self._tick_sp.SetValue(tick)
            except ValueError:
                pass
        self._updating = False
        evt.Skip()

    def _on_note_select(self, evt):
        """Preview de la note sélectionnée dans la liste."""
        idx = self._note_lb.GetSelection()
        if idx < 0:
            return
        temp = dict(self._ev)
        temp["pad"] = idx
        self._parent_window._play_event(temp)

    def get_note(self):
        return self._note_lb.GetSelection()

    def get_bar(self):
        return self._bar_sp.GetValue() - 1

    def get_step(self):
        beat = self._beat_sp.GetValue() - 1
        tick = self._tick_sp.GetValue() - 1
        return beat * self._steps_per_beat + tick

    def get_dur_ms(self):
        parts = self._dur_txt.GetValue().strip().split(":")
        if len(parts) == 3:
            try:
                bars  = int(parts[0])
                beats = int(parts[1])
                ticks = int(parts[2])
                total = bars * self._num_steps + beats * self._steps_per_beat + ticks
                return max(10, round(total * self._ms_per_tick))
            except ValueError:
                pass
        return 500

    def get_vel(self):
        return self._vel_sp.GetValue()


class _CcEventEditDialog(wx.Dialog):
    """Dialog d'édition d'un événement d'automation (bend/mod) : position BBT + valeur."""

    def __init__(self, parent, ev, pattern):
        num_bars       = pattern._num_bars
        num_steps      = pattern._num_steps
        num_beats      = pattern._num_beats
        steps_per_beat = max(1, num_steps // num_beats)

        bar  = ev["bar"]
        step = ev["step"]
        beat = step // steps_per_beat
        tick = step % steps_per_beat

        self._steps_per_beat = steps_per_beat
        self._updating       = False

        is_bend = ev["type"] == "bend"
        title   = "Éditer pitch bend" if is_bend else "Éditer CC (mod wheel)"
        super().__init__(parent, title=title,
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        # --- Position ---
        pos_lbl       = wx.StaticText(self, label="Position :")
        bar_lbl       = wx.StaticText(self, label="Bar")
        beat_lbl      = wx.StaticText(self, label="Beat")
        tick_lbl      = wx.StaticText(self, label="Tick")
        self._bar_sp  = wx.SpinCtrl(self, min=1, max=num_bars,       initial=bar+1,  size=(55, -1))
        self._beat_sp = wx.SpinCtrl(self, min=1, max=num_beats,      initial=beat+1, size=(55, -1))
        self._tick_sp = wx.SpinCtrl(self, min=1, max=steps_per_beat, initial=tick+1, size=(55, -1))
        # Noms accessibles distincts (lecteur d'écran) : un SpinCtrl seul
        # n'annonce que sa valeur, jamais le StaticText voisin — voir
        # feedback_accessibility_spinctrl.
        self._bar_sp.SetName("Bar")
        self._beat_sp.SetName("Beat")
        self._tick_sp.SetName("Tick")
        bbt_lbl       = wx.StaticText(self, label="bar:batt:tck :")
        self._pos_txt = wx.TextCtrl(self, value=f"{bar+1}:{beat+1}:{tick+1}",
                                    size=(90, -1), style=wx.TE_PROCESS_ENTER)

        self._bar_sp.Bind(wx.EVT_SPINCTRL,   self._on_spin_change)
        self._beat_sp.Bind(wx.EVT_SPINCTRL,  self._on_spin_change)
        self._tick_sp.Bind(wx.EVT_SPINCTRL,  self._on_spin_change)
        self._pos_txt.Bind(wx.EVT_TEXT_ENTER, self._on_pos_confirm)
        self._pos_txt.Bind(wx.EVT_KILL_FOCUS, self._on_pos_confirm)

        # --- Valeur ---
        if is_bend:
            val_lbl      = wx.StaticText(self, label="Bend (-8192..8191) :")
            self._val_sp = wx.SpinCtrl(self, min=-8192, max=8191,
                                       initial=ev["value"], size=(90, -1))
        else:
            val_lbl      = wx.StaticText(self, label="Valeur CC (0..127) :")
            self._val_sp = wx.SpinCtrl(self, min=0, max=127,
                                       initial=ev["value"], size=(90, -1))

        # --- Boutons ---
        ok_btn     = wx.Button(self, wx.ID_OK,     "Ok")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annuler")
        ok_btn.SetDefault()
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()

        # --- Layout ---
        spin_hbox = wx.BoxSizer(wx.HORIZONTAL)
        spin_hbox.Add(bar_lbl,        0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        spin_hbox.Add(self._bar_sp,   0, wx.RIGHT, 6)
        spin_hbox.Add(beat_lbl,       0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        spin_hbox.Add(self._beat_sp,  0, wx.RIGHT, 6)
        spin_hbox.Add(tick_lbl,       0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        spin_hbox.Add(self._tick_sp,  0)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(pos_lbl,        0, wx.ALL, 6)
        vbox.Add(spin_hbox,      0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        vbox.Add(bbt_lbl,        0, wx.LEFT | wx.RIGHT, 6)
        vbox.Add(self._pos_txt,  0, wx.ALL, 6)
        vbox.Add(val_lbl,        0, wx.LEFT | wx.RIGHT, 6)
        vbox.Add(self._val_sp,   0, wx.ALL, 6)
        vbox.Add(btn_sizer,      0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._val_sp.SetFocus()

    def _on_spin_change(self, evt):
        if self._updating:
            return
        self._updating = True
        bar  = self._bar_sp.GetValue()
        beat = self._beat_sp.GetValue()
        tick = self._tick_sp.GetValue()
        self._pos_txt.ChangeValue(f"{bar}:{beat}:{tick}")
        self._updating = False

    def _on_pos_confirm(self, evt):
        if self._updating:
            evt.Skip()
            return
        self._updating = True
        parts = self._pos_txt.GetValue().strip().split(":")
        if len(parts) == 3:
            try:
                bar  = int(parts[0])
                beat = int(parts[1])
                tick = int(parts[2])
                if (1 <= bar  <= self._bar_sp.GetMax() and
                        1 <= beat <= self._beat_sp.GetMax() and
                        1 <= tick <= self._steps_per_beat):
                    self._bar_sp.SetValue(bar)
                    self._beat_sp.SetValue(beat)
                    self._tick_sp.SetValue(tick)
            except ValueError:
                pass
        self._updating = False
        evt.Skip()

    def get_bar(self):
        return self._bar_sp.GetValue() - 1

    def get_step(self):
        beat = self._beat_sp.GetValue() - 1
        tick = self._tick_sp.GetValue() - 1
        return beat * self._steps_per_beat + tick

    def get_value(self):
        return self._val_sp.GetValue()
