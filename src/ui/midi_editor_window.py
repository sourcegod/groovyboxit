import wx
from midi_editor import MidiEditor
from synth_engine import midi_to_note_name
from rack import InstrumentType


class _NoteEditDialog(wx.Dialog):
    """Dialog d'édition d'un événement grille (pad, position, vélocité)."""

    def __init__(self, parent, ev, pattern, pad_names):
        super().__init__(parent, title="Éditer note",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        num_bars  = pattern._num_bars
        num_steps = pattern._num_steps
        num_pads  = pattern._num_pads

        pad_lbl       = wx.StaticText(self, label="Pad :")
        self._pad_lb  = wx.ListBox(self, choices=pad_names,
                                   style=wx.LB_SINGLE, size=(140, 200))
        self._pad_lb.SetSelection(min(max(ev["pad"], 0), num_pads - 1))

        bar_lbl         = wx.StaticText(self, label="Mesure :")
        self._bar_ctrl  = wx.SpinCtrl(self, min=1, max=num_bars,
                                      initial=ev["bar"] + 1, size=(70, -1))
        step_lbl        = wx.StaticText(self, label="Pas :")
        self._step_ctrl = wx.SpinCtrl(self, min=1, max=num_steps,
                                      initial=ev["step"] + 1, size=(70, -1))

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
        right_vbox.Add(vel_lbl,        0, wx.BOTTOM, 2)
        right_vbox.Add(self._vel_ctrl, 0)

        left_vbox = wx.BoxSizer(wx.VERTICAL)
        left_vbox.Add(pad_lbl,    0, wx.BOTTOM, 2)
        left_vbox.Add(self._pad_lb, 1, wx.EXPAND)

        top_hbox = wx.BoxSizer(wx.HORIZONTAL)
        top_hbox.Add(left_vbox,  0, wx.EXPAND | wx.RIGHT, 12)
        top_hbox.Add(right_vbox, 1, wx.EXPAND)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(top_hbox,  1, wx.EXPAND | wx.ALL, 8)
        vbox.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(vbox)
        self.Fit()
        self._pad_lb.SetFocus()

    def get_pad(self):
        return self._pad_lb.GetSelection()

    def get_bar(self):
        return self._bar_ctrl.GetValue() - 1

    def get_step(self):
        return self._step_ctrl.GetValue() - 1

    def get_vel(self):
        return self._vel_ctrl.GetValue()


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
        self._build_ui()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE,     self._on_close)
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
        self._event_lb.Bind(wx.EVT_LISTBOX, self._on_listbox_select)

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

        labels = [self._event_label(e) for e in self._events]
        self._event_lb.Set(labels)
        if self._events:
            cur = min(me._cur_idx, len(self._events) - 1)
            me._cur_idx = cur
            self._skip_listbox_announce = True
            self._event_lb.SetSelection(cur)
        self._update_mode_label()

    def _event_label(self, e):
        if e["type"] == "note":
            name = self._event_note_name(e)
            bbt  = self._bbt_str(e["bar"], e["step"])
            if e["etype"] == "G":
                return (f"{bbt}  Tr{e['track']+1:02d}  "
                        f"{name:<6}  Vel:{e['vel']:3d}")
            else:
                return (f"{bbt}  Tr{e['track']+1:02d}  "
                        f"{name:<6}  Vel:{e['vel']:3d}  "
                        f"Dur:{e['dur']}ms  [{e['etype']}]")
        elif e["type"] == "bend":
            bbt = self._bbt_str(e["bar"], e["step"])
            return f"{bbt}  Tr{e['track']+1:02d}  Bend:{e['value']:+d}"
        elif e["type"] == "mod":
            bbt = self._bbt_str(e["bar"], e["step"])
            return f"{bbt}  Tr{e['track']+1:02d}  Mod:{e['value']}"
        return str(e)

    def _set_status(self, msg):
        self._status_ctrl.SetString(0, msg)

    # ------------------------------------------------------------------
    # Lecture sonore (preview)
    # ------------------------------------------------------------------

    def _play_event(self, ev):
        """Joue le son du pad correspondant à un événement grille."""
        if ev.get("type") == "note" and ev.get("etype") == "G":
            self._parent._play(ev["pad"])

    def _play_group_at(self, idx):
        """Joue tous les événements du groupe à l'offset courant."""
        for i in self._midi_editor.group_indices(self._events, idx):
            self._play_event(self._events[i])

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
        if len(group) == 1:
            name = self._event_note_name(ev)
            self._set_status(f"{bbt}  ({name})")
        else:
            self._set_status(f"{bbt}  {len(group)} notes")

    def _announce_note(self, idx):
        """Annonce ↑/↓ : nom de note + position BBT."""
        if not self._events or idx >= len(self._events):
            return
        ev   = self._events[idx]
        bbt  = self._bbt_str(ev["bar"], ev["step"])
        name = self._event_note_name(ev)
        self._set_status(f"({name})  {bbt}")

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
        """Déplace la sélection sans déclencher l'annonce EVT_LISTBOX."""
        if not self._events:
            return
        idx = max(0, min(idx, len(self._events) - 1))
        self._midi_editor._cur_idx = idx
        self._skip_listbox_announce = True
        self._event_lb.SetSelection(idx)

    def _move_right(self):
        """→ : groupe temporel suivant, joue le groupe, annonce position."""
        if not self._events:
            return
        cur = self._midi_editor._cur_idx
        nxt = self._midi_editor.first_of_next_group(self._events, cur)
        if nxt >= 0:
            self._navigate_to(nxt)
            self._play_group_at(nxt)
            self._announce_group(nxt)
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
            self._announce_group(prv)
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
        pos = group.index(cur) if cur in group else 0
        if pos < len(group) - 1:
            target = group[pos + 1]
            self._navigate_to(target)
        else:
            target = group[-1]   # déjà à la dernière note, reste dessus
        self._play_event(self._events[target])
        self._announce_note(target)

    def _move_up_in_group(self):
        """↑ : note précédente dans l'accord courant ; joue et annonce toujours."""
        if not self._events:
            return
        cur   = self._midi_editor._cur_idx
        group = self._midi_editor.group_indices(self._events, cur)
        if not group:
            return
        pos = group.index(cur) if cur in group else 0
        if pos > 0:
            target = group[pos - 1]
            self._navigate_to(target)
        else:
            target = group[0]    # déjà à la première note, reste dessus
        self._play_event(self._events[target])
        self._announce_note(target)

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
        if ev.get("etype") != "G":
            self._set_status("Édition directe des événements tape non disponible ici")
            return
        pat       = self._parent._player._pattern
        track_idx = self._parent._player._cur_track
        pad_names = self._pad_names_list(pat._num_pads, track_idx)
        self._parent._add_undo(
            f"Éditer note Tr{ev['track']+1} B{ev['bar']+1}:S{ev['step']+1}"
        )
        dlg = _NoteEditDialog(self, ev, pat, pad_names)
        if dlg.ShowModal() == wx.ID_OK:
            new_ev = self._midi_editor.edit_grid_note(
                pat, ev,
                new_pad  = dlg.get_pad(),
                new_vel  = dlg.get_vel(),
                new_bar  = dlg.get_bar(),
                new_step = dlg.get_step(),
            )
            if new_ev:
                self._refresh()
                for i, e in enumerate(self._events):
                    if (e["etype"] == "G" and
                            e["track"] == new_ev["track"] and
                            e["bar"]   == new_ev["bar"] and
                            e["step"]  == new_ev["step"] and
                            e["pad"]   == new_ev["pad"]):
                        self._navigate_to(i)
                        break
                bbt  = self._bbt_str(new_ev["bar"], new_ev["step"])
                name = self._event_note_name(new_ev)
                self._set_status(f"Note modifiée → ({name})  {bbt}  Vel:{new_ev['vel']}")
            else:
                self._parent._pop_last_undo()
                self._set_status("Édition annulée (hors limites)")
        else:
            self._parent._pop_last_undo()
        dlg.Destroy()

    def _delete_event(self):
        if not self._events:
            return
        cur = self._midi_editor._cur_idx
        ev  = self._events[cur]
        if ev.get("type") != "note":
            self._set_status("Suppression non disponible pour ce type")
            return
        pat = self._parent._player._pattern
        self._parent._add_undo(
            f"Supprimer note Tr{ev['track']+1} B{ev['bar']+1}:S{ev['step']+1}"
        )
        if self._midi_editor.delete_event(pat, ev):
            new_idx = min(cur, max(0, len(self._events) - 2))
            self._midi_editor._cur_idx = new_idx
            self._refresh()
            self._set_status("Note supprimée")
        else:
            self._parent._pop_last_undo()

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
            self._refresh()
            self._set_status("Mode : Notes de la piste courante")
            return

        # Ctrl+2 : mode tous les événements
        if ctrl and not shift and (ukey == ord('2') or key == ord('2')):
            self._view_mode = self.MODE_ALL
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

        # ↑/↓ : navigation dans l'accord courant
        if not ctrl and not shift and key == wx.WXK_UP:
            self._move_up_in_group()
            return
        if not ctrl and not shift and key == wx.WXK_DOWN:
            self._move_down_in_group()
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

        # Transport partagé (Space/P, V, G, Shift+G, PageUp/Down…)
        if self._parent._key_manager.handle_transport(evt):
            return

        evt.Skip()

    def _on_close(self, evt):
        self._parent._midi_editor_window = None
        evt.Skip()

    # ------------------------------------------------------------------

    def refresh(self):
        """Appelé depuis MainWindow si le pattern ou la piste change."""
        self._refresh()
