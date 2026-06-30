import threading
import wx
from midi_editor import MidiEditor
from synth_engine import midi_to_note_name
from rack import InstrumentType


class _NoteEditDialog(wx.Dialog):
    """Dialog d'édition d'une note (pad/pitch, position, durée, vélocité)."""

    def __init__(self, parent, ev, pattern, pad_names):
        from synth_engine import midi_to_note_name
        etype     = ev.get("etype", "G")
        super().__init__(parent, title="Éditer note",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        num_bars  = pattern._num_bars
        num_steps = pattern._num_steps
        num_pads  = pattern._num_pads
        self._etype = etype

        # Sélecteur instrument : pad (G/K) ou note MIDI (P)
        if etype == "P":
            inst_lbl      = wx.StaticText(self, label="Note :")
            note_choices  = [f"{i:3d}  {midi_to_note_name(i)}" for i in range(128)]
            self._inst_lb = wx.ListBox(self, choices=note_choices,
                                       style=wx.LB_SINGLE, size=(160, 200))
            self._inst_lb.SetSelection(min(max(ev["pad"], 0), 127))
        else:
            inst_lbl      = wx.StaticText(self, label="Pad :")
            self._inst_lb = wx.ListBox(self, choices=pad_names,
                                       style=wx.LB_SINGLE, size=(140, 200))
            self._inst_lb.SetSelection(min(max(ev["pad"], 0), num_pads - 1))

        bar_lbl         = wx.StaticText(self, label="Mesure :")
        self._bar_ctrl  = wx.SpinCtrl(self, min=1, max=num_bars,
                                      initial=ev["bar"] + 1, size=(70, -1))
        step_lbl        = wx.StaticText(self, label="Pas :")
        self._step_ctrl = wx.SpinCtrl(self, min=1, max=num_steps,
                                      initial=ev["step"] + 1, size=(70, -1))

        # Durée : éditable pour les événements tape (K/P), lecture seule pour G
        dur_lbl        = wx.StaticText(self, label="Durée (ms) :")
        self._dur_ctrl = wx.SpinCtrl(self, min=10, max=30000,
                                     initial=max(10, ev.get("dur", 500)), size=(80, -1))
        if etype == "G":
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


_NOTE_NAMES_C0 = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]

def _midi_display_name(midi):
    """Convention C0=MIDI 0 : C0…G10 (128 notes)."""
    return f"{_NOTE_NAMES_C0[midi % 12]}{midi // 12}"


class _MidiEventEditDialog(wx.Dialog):
    """Dialog d'édition MIDI : note (C0..G10), position BBT, durée BBT, vélocité."""

    def __init__(self, parent, ev, pattern):
        etype          = ev.get("etype", "G")
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

        # --- Note (C0=MIDI 0 … G10=MIDI 127) ---
        note_choices  = [f"{i:3d}  {_midi_display_name(i)}" for i in range(128)]
        note_lbl      = wx.StaticText(self, label="Note :")
        self._note_lb = wx.ListBox(self, choices=note_choices,
                                   style=wx.LB_SINGLE, size=(160, 240))
        sel = min(max(ev.get("pad", 0), 0), 127)
        self._note_lb.SetSelection(sel)
        self._note_lb.SetFirstItem(max(0, sel - 4))
        self._note_lb.Bind(wx.EVT_LISTBOX,       self._on_note_select)
        self._note_lb.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.EndModal(wx.ID_OK))

        # --- Position ---
        pos_lbl       = wx.StaticText(self, label="Position :")
        bar_lbl       = wx.StaticText(self, label="Mes.")
        beat_lbl      = wx.StaticText(self, label="Batt.")
        tick_lbl      = wx.StaticText(self, label="Tck")
        self._bar_sp  = wx.SpinCtrl(self, min=1, max=num_bars,       initial=bar+1,  size=(55, -1))
        self._beat_sp = wx.SpinCtrl(self, min=1, max=num_beats,      initial=beat+1, size=(55, -1))
        self._tick_sp = wx.SpinCtrl(self, min=1, max=steps_per_beat, initial=tick+1, size=(55, -1))
        bbt_lbl       = wx.StaticText(self, label="bar:batt:tck :")
        self._pos_txt = wx.TextCtrl(self, value=f"{bar+1}:{beat+1}:{tick+1}",
                                    size=(90, -1), style=wx.TE_PROCESS_ENTER)

        self._bar_sp.Bind(wx.EVT_SPINCTRL,   self._on_spin_change)
        self._beat_sp.Bind(wx.EVT_SPINCTRL,  self._on_spin_change)
        self._tick_sp.Bind(wx.EVT_SPINCTRL,  self._on_spin_change)
        self._pos_txt.Bind(wx.EVT_TEXT_ENTER, self._on_pos_confirm)
        self._pos_txt.Bind(wx.EVT_KILL_FOCUS, self._on_pos_confirm)

        # --- Durée BBT (désactivée pour G : dérive des réglages du pad) ---
        dur_lbl       = wx.StaticText(self, label="Durée (mes:batt:tck) :")
        self._dur_txt = wx.TextCtrl(self, value=f"{dur_bars}:{dur_beats}:{dur_ticks}",
                                    size=(90, -1))
        if etype == "G":
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


class MidiEditorWindow(wx.Frame):
    """Fenêtre d'éditeur MIDI — deux modes : notes (Ctrl+1) et tous les événements (Ctrl+2).

    Navigation :
      ←/→  : groupe précédent/suivant (même offset = accord)
      ↑/↓  : note précédente/suivante dans l'accord courant
      Entrée : éditer la note sélectionnée
      Suppr  : supprimer la note sélectionnée
    """

    MODE_NOTES = 0   # notes de la piste courante (grille séquenceur)
    MODE_ALL   = 1   # tous les événements MIDI (grille + tape K/P + CC)

    def __init__(self, parent, view_mode=MODE_NOTES):
        super().__init__(parent, title="Éditeur MIDI",
                         size=(780, 460),
                         style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT)
        self._parent               = parent
        self._view_mode            = view_mode
        self._events               = []
        self._midi_editor          = MidiEditor()
        self._skip_listbox_announce = False   # évite que EVT_LISTBOX écrase l'annonce clavier
        self._preview_midis        = []       # notes MIDI en cours de preview (accord)
        self._preview_timer        = None     # Timer d'arrêt automatique
        self._group_entry          = False    # ←/→ vient d'atterrir sur un groupe
        self._selected_indices     = set()    # indices sélectionnés dans self._events
        self._build_ui()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE,     self._on_close)
        self.Bind(wx.EVT_ACTIVATE,  self._on_activate)
        self._refresh()

    # ------------------------------------------------------------------
    # Construction UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        panel = wx.Panel(self)
        vbox  = wx.BoxSizer(wx.VERTICAL)

        self._mode_label = wx.StaticText(panel, label="")
        vbox.Add(self._mode_label, 0, wx.ALL, 6)

        self._event_lb = wx.ListBox(panel, style=wx.LB_SINGLE, size=(-1, 320))
        vbox.Add(self._event_lb, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        self._event_lb.Bind(wx.EVT_LISTBOX,       self._on_listbox_select)
        # GTK : Enter sur ListBox génère EVT_LISTBOX_DCLICK (pas EVT_CHAR_HOOK)
        self._event_lb.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._edit_note_dialog())

        # ListBox status (annoncée en temps réel par le lecteur d'écran)
        self._status_ctrl = wx.ListBox(panel, choices=[""], style=wx.LB_SINGLE)
        vbox.Add(self._status_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        panel.SetSizer(vbox)
        self._event_lb.SetFocus()

    # ------------------------------------------------------------------
    # Helpers d'affichage
    # ------------------------------------------------------------------

    def _pad_name(self, pad_idx):
        """Nom du pad du kit/drum (voice_manager ou label par défaut)."""
        vm   = self._parent._player.voice_manager
        name = vm.get_name(pad_idx) if pad_idx < 16 else ""
        return name if name else f"Pad_{pad_idx+1:02d}"

    def _event_note_name(self, ev):
        """Nom affiché pour un événement note selon son etype et le slot de sa piste.

        - etype P : note MIDI brute (enregistrement live synth) → nom directement
        - etype K : index pad kit (enregistrement live kit) → nom du pad
        - etype G : index pad grille → MIDI (synth) ou nom pad (kit) selon slot
        """
        etype   = ev.get("etype", "G")
        pad_val = ev["pad"]

        if etype == "P":
            return midi_to_note_name(pad_val)

        if etype == "K":
            return self._pad_name(pad_val)

        # etype == "G" : vérifier le slot de la piste
        track_idx = ev["track"]
        slot_idx  = self._parent._router.slot_for_track(track_idx)
        slot      = self._parent._rack.get_slot(slot_idx)
        if slot.type == InstrumentType.SYNTH:
            kb = self._parent._router.kb_notes_input
            if pad_val < len(kb):
                return midi_to_note_name(kb[pad_val])
            return f"Note_{pad_val+1:02d}"
        return self._pad_name(pad_val)

    def _pad_names_list(self, num_pads, track_idx):
        """Liste des noms pour le dialog d'édition (notes ou pads selon le slot)."""
        slot_idx = self._parent._router.slot_for_track(track_idx)
        slot     = self._parent._rack.get_slot(slot_idx)
        if slot.type == InstrumentType.SYNTH:
            kb = self._parent._router.kb_notes_input
            return [midi_to_note_name(kb[i]) if i < len(kb) else f"Note_{i+1:02d}"
                    for i in range(num_pads)]
        return [self._pad_name(i) for i in range(num_pads)]

    def _bbt_str(self, bar, step):
        """Formate (bar, step) en 'Bar:Beat:Tick' 1-based."""
        pat            = self._parent._player._pattern
        num_steps      = pat._num_steps
        num_beats      = pat._num_beats
        steps_per_beat = max(1, num_steps // num_beats)
        beat = step // steps_per_beat
        tick = step % steps_per_beat
        return f"{bar + 1}:{beat + 1}:{tick + 1}"

    def _update_mode_label(self):
        pat  = self._parent._player._pattern
        tidx = self._parent._player._cur_track
        n    = len(self._events)
        if self._view_mode == self.MODE_NOTES:
            tname = self._parent._player.voice_manager.get_name(tidx)
            tstr  = f"Piste {tidx+1}" + (f" ({tname})" if tname else "")
            self._mode_label.SetLabel(
                f"Mode: Notes (Ctrl+1)  {tstr}  "
                f"Pat:{pat._num_bars}M×{pat._num_steps}P  {n} note(s)"
            )
        else:
            self._mode_label.SetLabel(
                f"Mode: Tous les événements (Ctrl+2)  "
                f"Pat:{pat._num_bars}M×{pat._num_steps}P  {n} événement(s)"
            )

    def _refresh(self):
        pat   = self._parent._player._pattern
        track = self._parent._player._cur_track
        te    = self._parent._track_editor
        lim_l = te._lim_left
        lim_r = te._lim_right

        me = self._midi_editor
        if self._view_mode == self.MODE_NOTES:
            self._events = me.get_note_events(pat, track, lim_l, lim_r)
        else:
            sel          = te.get_effective_tracks(track)
            self._events = me.get_all_events(pat, sel, lim_l, lim_r)

        self._selected_indices.clear()
        labels = [self._event_label(e, False) for e in self._events]
        self._event_lb.Set(labels)
        if self._events:
            cur = min(me._cur_idx, len(self._events) - 1)
            me._cur_idx = cur
            self._skip_listbox_announce = True
            self._event_lb.SetSelection(cur)
        self._update_mode_label()

    def _event_label(self, e, selected=False):
        mark = "[*] " if selected else "    "
        if e["type"] == "note":
            name = self._event_note_name(e)
            bbt  = self._bbt_str(e["bar"], e["step"])
            if e["etype"] == "G":
                return (f"{mark}{bbt}  Tr{e['track']+1:02d}  "
                        f"{name:<6}  Vel:{e['vel']:3d}")
            else:
                return (f"{mark}{bbt}  Tr{e['track']+1:02d}  "
                        f"{name:<6}  Vel:{e['vel']:3d}  "
                        f"Dur:{e['dur']}ms  [{e['etype']}]")
        elif e["type"] == "bend":
            bbt = self._bbt_str(e["bar"], e["step"])
            return f"{mark}{bbt}  Tr{e['track']+1:02d}  Bend:{e['value']:+d}"
        elif e["type"] == "mod":
            bbt = self._bbt_str(e["bar"], e["step"])
            return f"{mark}{bbt}  Tr{e['track']+1:02d}  Mod:{e['value']}"
        return str(e)

    def _update_label(self, idx):
        """Met à jour le label d'un seul item dans la ListBox."""
        if 0 <= idx < len(self._events):
            self._event_lb.SetString(
                idx, self._event_label(self._events[idx], idx in self._selected_indices)
            )

    def _refresh_labels(self):
        """Remet à jour tous les labels (après changement de sélection globale)."""
        for i, e in enumerate(self._events):
            self._event_lb.SetString(i, self._event_label(e, i in self._selected_indices))

    def _set_status(self, msg):
        self._status_ctrl.SetString(0, msg)

    # ------------------------------------------------------------------
    # Lecture sonore (preview)
    # ------------------------------------------------------------------

    def _stop_preview(self):
        """Annule le timer en cours et arrête toutes les notes preview."""
        if self._preview_timer is not None:
            self._preview_timer.cancel()
            self._preview_timer = None
        if self._preview_midis:
            router = self._parent._router
            if router.synth_ready():
                for midi in self._preview_midis:
                    router.synth.stop(midi)
            self._preview_midis = []

    def _play_event(self, ev):
        """Joue le son d'un événement note (appelé depuis _play_group_at)."""
        if ev.get("type") != "note":
            return
        etype = ev.get("etype")
        slot  = self._parent._rack.get_slot(self._parent._cur_slot)
        if slot.type == InstrumentType.SYNTH:
            router = self._parent._router
            if not router.synth_ready():
                router.load_slot_preview(self._parent._cur_slot)
                return
            if etype == "G":
                pad = ev["pad"]
                if pad >= len(router.kb_notes_input):
                    return
                midi = router.kb_notes_input[pad]
            elif etype == "P":
                midi = ev["pad"]
            else:
                return
            dur_ms = max(50, ev.get("dur", 500))
            router.synth.play(midi, maxtime_ms=dur_ms)
            self._preview_midis.append(midi)
            return dur_ms
        elif etype == "G":
            self._parent._player.play_sound(ev["pad"])
        return None

    def _play_group_at(self, idx):
        """Joue tous les événements du groupe à l'offset courant."""
        self._stop_preview()
        dur_ms = 500
        for i in self._midi_editor.group_indices(self._events, idx):
            result = self._play_event(self._events[i])
            if result is not None:
                dur_ms = result
        if self._preview_midis:
            self._preview_timer = threading.Timer(
                dur_ms / 1000.0,
                lambda: wx.CallAfter(self._stop_preview)
            )
            self._preview_timer.start()

    def _play_single_at(self, idx):
        """Stop le preview précédent et joue uniquement la note à idx."""
        self._stop_preview()
        dur_ms = self._play_event(self._events[idx])
        if self._preview_midis:
            self._preview_timer = threading.Timer(
                (dur_ms or 500) / 1000.0,
                lambda: wx.CallAfter(self._stop_preview)
            )
            self._preview_timer.start()

    # ------------------------------------------------------------------
    # Annonces de statut
    # ------------------------------------------------------------------

    def _announce_group(self, idx):
        """Annonce ←/→ : position BBT + nom de note (seule) ou nombre (accord)."""
        if not self._events or idx >= len(self._events):
            return
        group = self._midi_editor.group_indices(self._events, idx)
        ev    = self._events[idx]
        bbt   = self._bbt_str(ev["bar"], ev["step"])
        suf   = self._sel_status_suffix()
        if len(group) == 1:
            name = self._event_note_name(ev)
            self._set_status(f"{bbt}  ({name}){suf}")
        else:
            self._set_status(f"{bbt}  {len(group)} notes{suf}")

    def _announce_note(self, idx):
        """Annonce ↑/↓ : nom de note + position BBT."""
        if not self._events or idx >= len(self._events):
            return
        ev   = self._events[idx]
        bbt  = self._bbt_str(ev["bar"], ev["step"])
        name = self._event_note_name(ev)
        suf  = self._sel_status_suffix()
        self._set_status(f"({name})  {bbt}{suf}")

    def _announce_event(self, idx):
        """Annonce générique (clic listbox) : position BBT + nom + vélocité."""
        if not self._events or idx >= len(self._events):
            return
        e = self._events[idx]
        if e["type"] == "note":
            bbt  = self._bbt_str(e["bar"], e["step"])
            name = self._event_note_name(e)
            self._set_status(f"{bbt}  Tr{e['track']+1}  {name}  Vel:{e['vel']}")
        else:
            bbt = self._bbt_str(e["bar"], e["step"])
            self._set_status(f"{bbt}  Tr{e['track']+1}  "
                             f"{e['type'].capitalize()}:{e['value']}")

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _on_listbox_select(self, evt):
        idx = self._event_lb.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        self._midi_editor._cur_idx = idx
        if self._skip_listbox_announce:
            self._skip_listbox_announce = False
            return
        self._announce_event(idx)

    def _navigate_to(self, idx):
        """Déplace la sélection sans déclencher l'annonce EVT_LISTBOX.
        Synchronise aussi le playhead sur l'offset de l'événement cible,
        afin que I/O enregistrent la position courante dans la liste."""
        if not self._events:
            return
        idx = max(0, min(idx, len(self._events) - 1))
        self._midi_editor._cur_idx = idx
        self._skip_listbox_announce = True
        self._event_lb.SetSelection(idx)
        self._parent._player._go_to_offset(float(self._events[idx]["offset"]))

    def _move_right(self):
        """→ : groupe temporel suivant, joue le groupe, annonce position."""
        if not self._events:
            return
        cur = self._midi_editor._cur_idx
        nxt = self._midi_editor.first_of_next_group(self._events, cur)
        if nxt >= 0:
            self._navigate_to(nxt)
            self._play_group_at(nxt)
            group = self._midi_editor.group_indices(self._events, nxt)
            self._group_entry = len(group) > 1
            wx.CallAfter(self._announce_group, nxt)
        else:
            self._set_status("Dernier groupe")

    def _move_left(self):
        """← : groupe temporel précédent, joue le groupe, annonce position."""
        if not self._events:
            return
        cur = self._midi_editor._cur_idx
        prv = self._midi_editor.first_of_prev_group(self._events, cur)
        if prv >= 0:
            self._navigate_to(prv)
            self._play_group_at(prv)
            group = self._midi_editor.group_indices(self._events, prv)
            self._group_entry = len(group) > 1
            wx.CallAfter(self._announce_group, prv)
        else:
            self._set_status("Premier groupe")

    def _move_down_in_group(self):
        """↓ : note suivante dans l'accord courant ; joue et annonce toujours."""
        if not self._events:
            return
        cur   = self._midi_editor._cur_idx
        group = self._midi_editor.group_indices(self._events, cur)
        if not group:
            return
        if self._group_entry:
            target = group[0]
            self._group_entry = False
        else:
            pos = group.index(cur) if cur in group else 0
            if pos < len(group) - 1:
                target = group[pos + 1]
                self._navigate_to(target)
            else:
                target = group[-1]
        self._play_single_at(target)
        wx.CallAfter(self._announce_note, target)

    def _move_up_in_group(self):
        """↑ : note précédente dans l'accord courant ; joue et annonce toujours."""
        if not self._events:
            return
        cur   = self._midi_editor._cur_idx
        group = self._midi_editor.group_indices(self._events, cur)
        if not group:
            return
        if self._group_entry:
            target = group[0]
            self._group_entry = False
        else:
            pos = group.index(cur) if cur in group else 0
            if pos > 0:
                target = group[pos - 1]
                self._navigate_to(target)
            else:
                target = group[0]
        self._play_single_at(target)
        wx.CallAfter(self._announce_note, target)

    # ------------------------------------------------------------------
    # Undo / Redo — délégation vers la fenêtre principale
    # ------------------------------------------------------------------

    def _add_undo(self, title):
        self._parent._add_undo(title)

    def _undo_action(self):
        hist = self._parent._undo.history_list()
        title = hist[0].title if hist else None
        self._parent._undo_action()
        self._refresh()
        self._set_status(f"Undo: {title}" if title else "Undo: rien à annuler")

    def _redo_action(self):
        fut = self._parent._undo.future_list()
        title = fut[0].title if fut else None
        self._parent._redo_action()
        self._refresh()
        self._set_status(f"Redo: {title}" if title else "Redo: rien à refaire")

    def _undo_history_dialog(self):
        from ui.dialogs import UndoHistoryDialog
        entries = self._parent._undo.history_list()
        if not entries:
            self._set_status("Historique Undo: vide")
            return
        prev_focus = wx.Window.FindFocus()
        dlg = UndoHistoryDialog(self, entries)
        if dlg.ShowModal() == wx.ID_OK:
            steps = dlg.get_steps()
            for _ in range(steps):
                self._undo_action()
        dlg.Destroy()
        if prev_focus:
            prev_focus.SetFocus()

    # ------------------------------------------------------------------
    # Sélection
    # ------------------------------------------------------------------

    def _sync_lims_from_selection(self):
        """Synchronise lim_left/right sur l'étendue des événements sélectionnés.
        Réinitialise les limiteurs si la sélection est vide."""
        te = self._parent._track_editor
        if not self._selected_indices:
            te.reset_lims()
            return
        offsets = [self._events[i]["offset"]
                   for i in self._selected_indices if i < len(self._events)]
        if offsets:
            te.set_lim_left(min(offsets))
            te.set_lim_right(max(offsets))

    def _toggle_group_selection(self, idx):
        """Toggle la sélection de tous les indices du groupe à idx."""
        group = self._midi_editor.group_indices(self._events, idx)
        if all(i in self._selected_indices for i in group):
            for i in group:
                self._selected_indices.discard(i)
        else:
            for i in group:
                self._selected_indices.add(i)
        for i in group:
            self._update_label(i)
        self._sync_lims_from_selection()

    def _toggle_note_selection(self, idx):
        """Toggle la sélection d'une seule note."""
        if idx in self._selected_indices:
            self._selected_indices.discard(idx)
        else:
            self._selected_indices.add(idx)
        self._update_label(idx)
        self._sync_lims_from_selection()

    def _select_all(self):
        self._selected_indices = set(range(len(self._events)))
        self._refresh_labels()
        self._sync_lims_from_selection()
        self._set_status(f"{len(self._selected_indices)} événement(s) sélectionné(s)")

    def _deselect_all(self):
        self._selected_indices.clear()
        self._refresh_labels()
        self._sync_lims_from_selection()   # reset_lims() implicite
        self._set_status("Sélection effacée")

    def _clear_selection(self):
        """Vide la sélection et synchronise les limiteurs sans message."""
        self._selected_indices.clear()
        self._sync_lims_from_selection()

    def _sel_status_suffix(self):
        n = len(self._selected_indices)
        return f"  [{n} sél.]" if n else ""

    def _select_move_right(self):
        """Shift+→ : groupe suivant + toggle sélection du groupe + joue."""
        if not self._events:
            return
        cur = self._midi_editor._cur_idx
        nxt = self._midi_editor.first_of_next_group(self._events, cur)
        if nxt >= 0:
            self._navigate_to(nxt)
            self._toggle_group_selection(nxt)
            self._play_group_at(nxt)
            group = self._midi_editor.group_indices(self._events, nxt)
            self._group_entry = len(group) > 1
            wx.CallAfter(self._announce_group, nxt)
        else:
            self._set_status("Dernier groupe")

    def _select_move_left(self):
        """Shift+← : groupe précédent + toggle sélection du groupe + joue."""
        if not self._events:
            return
        cur = self._midi_editor._cur_idx
        prv = self._midi_editor.first_of_prev_group(self._events, cur)
        if prv >= 0:
            self._navigate_to(prv)
            self._toggle_group_selection(prv)
            self._play_group_at(prv)
            group = self._midi_editor.group_indices(self._events, prv)
            self._group_entry = len(group) > 1
            wx.CallAfter(self._announce_group, prv)
        else:
            self._set_status("Premier groupe")

    def _select_move_down(self):
        """Shift+↓ : note suivante dans le groupe + toggle sélection."""
        if not self._events:
            return
        cur   = self._midi_editor._cur_idx
        group = self._midi_editor.group_indices(self._events, cur)
        if not group:
            return
        if self._group_entry:
            target = group[0]
            self._group_entry = False
        else:
            pos = group.index(cur) if cur in group else 0
            target = group[pos + 1] if pos < len(group) - 1 else group[-1]
            if target != cur:
                self._navigate_to(target)
        self._toggle_note_selection(target)
        self._play_single_at(target)
        wx.CallAfter(self._announce_note, target)

    def _select_move_up(self):
        """Shift+↑ : note précédente dans le groupe + toggle sélection."""
        if not self._events:
            return
        cur   = self._midi_editor._cur_idx
        group = self._midi_editor.group_indices(self._events, cur)
        if not group:
            return
        if self._group_entry:
            target = group[0]
            self._group_entry = False
        else:
            pos = group.index(cur) if cur in group else 0
            target = group[pos - 1] if pos > 0 else group[0]
            if target != cur:
                self._navigate_to(target)
        self._toggle_note_selection(target)
        self._play_single_at(target)
        wx.CallAfter(self._announce_note, target)

    # ------------------------------------------------------------------
    # Édition
    # ------------------------------------------------------------------

    def _edit_note_dialog(self):
        if not self._events:
            return
        cur = self._midi_editor._cur_idx
        ev  = self._events[cur]
        if ev.get("type") != "note":
            self._set_status("Pas une note — édition non disponible")
            return
        etype = ev.get("etype", "G")
        pat   = self._parent._player._pattern
        self._add_undo(
            f"Éditer note Tr{ev['track']+1} B{ev['bar']+1}:S{ev['step']+1}"
        )
        dlg = _MidiEventEditDialog(self, ev, pat)
        if dlg.ShowModal() == wx.ID_OK:
            if etype == "G":
                new_note = min(dlg.get_note(), pat._num_pads - 1)
                new_ev = self._midi_editor.edit_grid_note(
                    pat, ev,
                    new_pad  = new_note,
                    new_vel  = dlg.get_vel(),
                    new_bar  = dlg.get_bar(),
                    new_step = dlg.get_step(),
                )
            else:
                new_ev = self._midi_editor.edit_tape_note(
                    pat, ev,
                    new_note = dlg.get_note(),
                    new_vel  = dlg.get_vel(),
                    new_bar  = dlg.get_bar(),
                    new_step = dlg.get_step(),
                    new_dur  = dlg.get_dur_ms(),
                )
            if new_ev:
                # Pour les notes grille, reconstruire les entrées G du tape
                # (_curpattern → tape["G"]) afin que le player joue les nouvelles notes.
                if etype == "G":
                    self._parent._player._compute_offsets()
                if self._parent._player.playing:
                    self._parent._player._wakeup.set()
                self._refresh()
                found = None
                for i, e in enumerate(self._events):
                    if (e["etype"] == new_ev["etype"] and
                            e["track"] == new_ev["track"] and
                            e["bar"]   == new_ev["bar"] and
                            e["step"]  == new_ev["step"] and
                            e["pad"]   == new_ev["pad"]):
                        found = i
                        break
                if found is not None:
                    self._navigate_to(found)
                    self._play_group_at(found)
                bbt  = self._bbt_str(new_ev["bar"], new_ev["step"])
                name = self._event_note_name(new_ev)
                self._set_status(f"Note modifiée → ({name})  {bbt}  Vel:{new_ev['vel']}")
            else:
                self._parent._pop_last_undo()
                self._set_status("Édition annulée (hors limites)")
        else:
            self._parent._pop_last_undo()
        dlg.Destroy()

    def _quantize_dialog(self):
        """Ouvre le dialog de quantisation depuis l'éditeur MIDI.

        Le dialog est créé avec self comme parent wxPython afin que ESC/Annuler
        redonne le focus à l'éditeur et non à la fenêtre principale.
        """
        from ui.dialogs_simple import QuantizeDialog
        from pattern import Pattern
        p   = self._parent._player
        dlg = QuantizeDialog(self,
                             res_idx        = p._quant_res_idx,
                             force_idx      = p._quant_force_idx,
                             swing_idx      = p._quant_swing_idx,
                             window_idx     = p._quant_window_idx,
                             quant_starts   = p._quant_starts,
                             quant_durations= p._quant_durations)
        result = dlg.ShowModal()
        if result in (wx.ID_OK, wx.ID_APPLY):
            p._quant_res_idx    = dlg.get_resolution()
            p._quant_force_idx  = dlg.get_force_idx()
            p._quant_swing_idx  = dlg.get_swing_idx()
            p._quant_window_idx = dlg.get_window_idx()
            p._quant_starts     = dlg.get_quant_starts()
            p._quant_durations  = dlg.get_quant_durations()
            res = p._quant_res_idx
            if res == -2:
                _, kind, val = Pattern.GRID_RESOLUTIONS[p._grid_idx]
                res = (Pattern.QUANT_STEPS.index(val)
                       if kind == "snaps" and val in Pattern.QUANT_STEPS else -1)
            if result == wx.ID_APPLY and res >= 0:
                self._parent._add_undo("Quantiser pattern (éditeur MIDI)")
                p.apply_quant_to_pattern(
                    res,
                    force_idx      = p._quant_force_idx,
                    swing_idx      = p._quant_swing_idx,
                    window_idx     = p._quant_window_idx,
                    quant_starts   = p._quant_starts,
                    quant_durations= p._quant_durations,
                )
                p._compute_offsets()
                self._parent._refresh_grid()
                self._refresh()
                self._set_status(f"Pattern quantisé : {Pattern.QUANT_LIST[res]}")
            elif res >= 0:
                self._set_status(f"Quantisation mémorisée : {Pattern.QUANT_LIST[res]}")
            else:
                self._set_status("Quantisation : aucune résolution sélectionnée")
        dlg.Destroy()
        self._event_lb.SetFocus()

    def _delete_event(self):
        if not self._events:
            return
        pat = self._parent._player._pattern
        cur = self._midi_editor._cur_idx

        if self._selected_indices:
            # Supprimer toutes les notes sélectionnées (G uniquement)
            targets = sorted(
                [i for i in self._selected_indices
                 if self._events[i].get("type") == "note"],
                reverse=True
            )
            if not targets:
                self._set_status("Aucune note sélectionnée supprimable")
                return
            self._add_undo(f"Suppr {len(targets)} note(s) sélectionnée(s)")
            deleted = 0
            for idx in targets:
                if self._midi_editor.delete_event(pat, self._events[idx]):
                    deleted += 1
            if deleted:
                self._parent._player._compute_offsets()
                self._clear_selection()
                self._midi_editor._cur_idx = max(0, cur - deleted)
                self._refresh()
                self._set_status(f"{deleted} note(s) supprimée(s)")
            else:
                self._parent._pop_last_undo()
        else:
            # Supprimer le groupe (accord) courant
            group = self._midi_editor.group_indices(self._events, cur)
            targets = [i for i in group if self._events[i].get("type") == "note"]
            if not targets:
                self._set_status("Suppression non disponible pour ce type")
                return
            n = len(targets)
            ev0 = self._events[targets[0]]
            self._add_undo(
                f"Suppr {'accord' if n > 1 else 'note'} "
                f"Tr{ev0['track']+1} B{ev0['bar']+1}:S{ev0['step']+1}"
            )
            deleted = sum(
                1 for idx in sorted(targets, reverse=True)
                if self._midi_editor.delete_event(pat, self._events[idx])
            )
            if deleted:
                self._parent._player._compute_offsets()
                self._midi_editor._cur_idx = max(0, cur - deleted)
                self._refresh()
                self._set_status(
                    f"{'Accord' if n > 1 else 'Note'} supprimé(e) ({deleted} note(s))"
                )
            else:
                self._parent._pop_last_undo()

    # ------------------------------------------------------------------
    # Limiteurs (délégation vers TrackEditor du parent)
    # ------------------------------------------------------------------

    def _lim_bbt(self, step):
        pat   = self._parent._player._pattern
        ns    = pat._num_steps
        spb   = max(1, ns // pat._num_beats)
        total = pat._num_bars * ns
        return self._parent._track_editor.fmt_bbt(step, ns, spb, total)

    def _set_lim_left(self, step):
        self._parent._track_editor.set_lim_left(step)
        self._refresh()
        wx.CallAfter(self._set_status, f"Limiteur Gauche: {self._lim_bbt(step)}")

    def _set_lim_right(self, step):
        self._parent._track_editor.set_lim_right(step)
        self._refresh()
        wx.CallAfter(self._set_status, f"Limiteur Droit: {self._lim_bbt(step)}")

    def _reset_lims(self):
        self._parent._track_editor.reset_lims()
        self._refresh()
        wx.CallAfter(self._set_status, "Limiteurs réinitialisés")

    def _go_first_event(self):
        if self._events:
            self._navigate_to(0)
            wx.CallAfter(self._announce_group, 0)

    def _go_last_event(self):
        if self._events:
            last = len(self._events) - 1
            self._navigate_to(last)
            wx.CallAfter(self._announce_group, last)

    # ------------------------------------------------------------------
    # Presse-papier événements
    # ------------------------------------------------------------------

    def _source_events(self):
        """Retourne les notes source pour copier/couper/supprimer.

        Priorité :
        1. Sélection manuelle (_selected_indices non vide)
        2. Limiteurs actifs → tous les événements dans [lim_left, lim_right]
        3. Groupe courant (accord à la position du curseur)
        """
        if self._selected_indices:
            return [self._events[i] for i in sorted(self._selected_indices)
                    if self._events[i].get("type") == "note"]
        te    = self._parent._track_editor
        lim_l = te._lim_left
        lim_r = te._lim_right
        if lim_l is not None or lim_r is not None:
            lo    = lim_l if lim_l is not None else 0
            hi    = lim_r if lim_r is not None else float("inf")
            notes = [e for e in self._events
                     if e.get("type") == "note" and lo <= e["offset"] <= hi]
            if notes:
                return notes
        if not self._events:
            return []
        cur   = self._midi_editor._cur_idx
        group = self._midi_editor.group_indices(self._events, cur)
        return [self._events[i] for i in group
                if self._events[i].get("type") == "note"]

    def _copy_events(self):
        src = self._source_events()
        n   = self._parent._track_editor.copy_events(src)
        self._set_status(f"{n} note(s) copiée(s)" if n else "Rien à copier")

    def _cut_events(self):
        src = self._source_events()
        if not src:
            self._set_status("Rien à couper")
            return
        self._parent._track_editor.copy_events(src)
        pat  = self._parent._player._pattern
        n    = len(src)
        self._add_undo(f"Couper {n} note(s)")
        deleted = sum(
            1 for ev in src
            if self._midi_editor.delete_event(pat, ev)
        )
        if deleted:
            self._parent._player._compute_offsets()
            self._clear_selection()
            cur = self._midi_editor._cur_idx
            self._midi_editor._cur_idx = max(0, cur - deleted)
            self._refresh()
            self._set_status(f"{deleted} note(s) coupée(s)")
        else:
            self._parent._pop_last_undo()
            self._set_status("Coupe impossible")

    def _paste_events(self):
        te = self._parent._track_editor
        if not te.has_event_clipboard():
            self._set_status("Presse-papier vide")
            return
        pat         = self._parent._player._pattern
        cur_track   = self._parent._player._cur_track
        cur_offset  = (self._events[self._midi_editor._cur_idx]["offset"]
                       if self._events else 0)
        self._add_undo(f"Coller notes Tr{cur_track + 1} @{cur_offset}")
        n = te.paste_events(pat, cur_track, cur_offset)
        if n:
            self._parent._player._compute_offsets()
            self._refresh()
            self._set_status(f"{n} note(s) collée(s)")
        else:
            self._parent._pop_last_undo()
            self._set_status("Coller: hors limites du pattern")

    # ------------------------------------------------------------------
    # Clavier
    # ------------------------------------------------------------------

    def _on_key(self, evt):
        key   = evt.GetKeyCode()
        ukey  = evt.GetUnicodeKey()
        ctrl  = evt.ControlDown()
        shift = evt.ShiftDown()

        if key == wx.WXK_ESCAPE:
            self.Close()
            return

        # Ctrl+1 : mode notes de la piste courante
        if ctrl and not shift and (ukey == ord('1') or key == ord('1')):
            self._view_mode = self.MODE_NOTES
            self._parent._midi_editor_view_mode = self.MODE_NOTES
            self._refresh()
            self._set_status("Mode : Notes de la piste courante")
            return

        # Ctrl+2 : mode tous les événements
        if ctrl and not shift and (ukey == ord('2') or key == ord('2')):
            self._view_mode = self.MODE_ALL
            self._parent._midi_editor_view_mode = self.MODE_ALL
            self._refresh()
            self._set_status("Mode : Tous les événements MIDI")
            return

        # ←/→ : navigation entre groupes temporels
        if not ctrl and not shift and key == wx.WXK_LEFT:
            self._move_left()
            return
        if not ctrl and not shift and key == wx.WXK_RIGHT:
            self._move_right()
            return

        # Shift+←/→ : navigation + sélection du groupe
        if not ctrl and shift and key == wx.WXK_LEFT:
            self._select_move_left()
            return
        if not ctrl and shift and key == wx.WXK_RIGHT:
            self._select_move_right()
            return

        # ↑/↓ : navigation dans l'accord courant
        if not ctrl and not shift and key == wx.WXK_UP:
            self._move_up_in_group()
            return
        if not ctrl and not shift and key == wx.WXK_DOWN:
            self._move_down_in_group()
            return

        # Shift+↑/↓ : navigation + sélection de la note
        if not ctrl and shift and key == wx.WXK_UP:
            self._select_move_up()
            return
        if not ctrl and shift and key == wx.WXK_DOWN:
            self._select_move_down()
            return

        # Ctrl+A : sélectionner tout
        if ctrl and not shift and (ukey == ord('a') or ukey == ord('A')):
            self._select_all()
            return

        # Ctrl+Shift+A : désélectionner tout
        if ctrl and shift and (ukey == ord('a') or ukey == ord('A')):
            self._deselect_all()
            return

        # Ctrl+C : copier
        if ctrl and not shift and (ukey == ord('c') or ukey == ord('C')):
            self._copy_events()
            return

        # Ctrl+X : couper
        if ctrl and not shift and (ukey == ord('x') or ukey == ord('X')):
            self._cut_events()
            return

        # Ctrl+V : coller
        if ctrl and not shift and (ukey == ord('v') or ukey == ord('V')):
            self._paste_events()
            return

        # Ctrl+Z : annuler
        if ctrl and not shift and (ukey == ord('z') or ukey == ord('Z')):
            self._undo_action()
            return

        # Shift+Z : refaire
        if not ctrl and shift and (ukey == ord('z') or ukey == ord('Z')):
            self._redo_action()
            return

        # Ctrl+Shift+Z : historique undo
        if ctrl and shift and (ukey == ord('z') or ukey == ord('Z')):
            self._undo_history_dialog()
            return

        # Entrée : éditer la note sélectionnée
        if not ctrl and not shift and key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._edit_note_dialog()
            return

        # Suppr / Backspace : supprimer l'événement sélectionné
        if not ctrl and key in (wx.WXK_DELETE, wx.WXK_BACK):
            self._delete_event()
            return

        # R : rafraîchir
        if not ctrl and not shift and (ukey == ord('r') or key == ord('R')):
            self._refresh()
            self._set_status("Rafraîchi")
            return

        # i : limiteur gauche à la position du playhead
        if not ctrl and not shift and (ukey == ord('i') or ukey == ord('I')):
            step = int(self._parent._player._current_offset())
            self._set_lim_left(step)
            return

        # o : limiteur droit à la position du playhead
        if not ctrl and not shift and (ukey == ord('o') or ukey == ord('O')):
            step = int(self._parent._player._current_offset())
            self._set_lim_right(step)
            return

        # Shift+I : limiteur gauche au début du pattern
        if not ctrl and shift and (ukey == ord('i') or ukey == ord('I')):
            self._set_lim_left(0)
            return

        # Shift+O : limiteur droit à la fin du pattern
        if not ctrl and shift and (ukey == ord('o') or ukey == ord('O')):
            pat  = self._parent._player._pattern
            step = pat._num_bars * pat._num_steps - 1
            self._set_lim_right(step)
            return

        # Home : premier événement de la liste filtrée
        if not ctrl and not shift and key == wx.WXK_HOME:
            self._go_first_event()
            return

        # End : dernier événement de la liste filtrée
        if not ctrl and not shift and key == wx.WXK_END:
            self._go_last_event()
            return

        # Ctrl+Home : réinitialise les limiteurs + premier événement
        if ctrl and not shift and key == wx.WXK_HOME:
            self._reset_lims()
            self._go_first_event()
            return

        # Ctrl+End : réinitialise les limiteurs + dernier événement
        if ctrl and not shift and key == wx.WXK_END:
            self._reset_lims()
            self._go_last_event()
            return

        # Ctrl+Shift+Q : boite de quantisation (même dialog que le pattern)
        if ctrl and shift and (ukey == ord('q') or ukey == ord('Q')):
            self._quantize_dialog()
            return

        # Transport partagé (Space/P, V, G, Shift+G, PageUp/Down…)
        if self._parent._key_manager.handle_transport(evt):
            pat   = self._parent._player._pattern
            step  = int(self._parent._player._current_offset())
            ns    = pat._num_steps
            spb   = max(1, ns // pat._num_beats)
            total = pat._num_bars * ns
            bbt   = self._parent._track_editor.fmt_bbt(step, ns, spb, total)
            wx.CallAfter(self._set_status, f"Position: {bbt}")
            return

        evt.Skip()

    def _on_activate(self, evt):
        if evt.GetActive():
            self._event_lb.SetFocus()
        evt.Skip()

    def _on_close(self, evt):
        self._stop_preview()
        self._parent._midi_editor_window = None
        evt.Skip()

    # ------------------------------------------------------------------

    def refresh(self):
        """Appelé depuis MainWindow si le pattern ou la piste change."""
        self._refresh()
