from synth_engine import midi_to_note_name
from rack import InstrumentType
from pattern import ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH


class DisplayMixin:
    """MidiEditorWindow — formatage/affichage : noms de pad/note, labels
    d'événements, rafraîchissement de la ListBox et statuts."""

    def _pad_name(self, pad_idx):
        """Nom du pad du kit/drum (voice_manager ou label par défaut)."""
        vm   = self._parent._player.voice_manager
        name = vm.get_name(pad_idx) if pad_idx < 16 else ""
        return name if name else f"Pad_{pad_idx+1:02d}"

    def _event_note_name(self, ev):
        """Nom affiché pour un événement note selon son etype et le slot de sa piste.

        - etype PATCH : note MIDI brute (enregistrement live synth) → nom directement
        - etype KIT : index pad kit (enregistrement live kit) → nom du pad
        - etype GRID : index pad grille → MIDI (synth) ou nom pad (kit) selon slot
        """
        etype   = ev.get("etype", ETYPE_GRID)
        pad_val = ev["pad"]

        if etype == ETYPE_PATCH:
            return midi_to_note_name(pad_val)

        if etype == ETYPE_KIT:
            return self._pad_name(pad_val)

        # etype == ETYPE_GRID : vérifier le slot de la piste
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

    def _dialog_note_choices(self, ev, pattern):
        """Choix + sélection initiale du listbox « Note » du dialog d'édition
        (Entrée) — même convention que _event_note_name/_event_pitch_number :
        GRID → pad["pad"] est un index de pad (résolu en note réelle pour un
        slot synthé, en nom de pad sinon), KIT/PATCH → pad["pad"] est déjà la
        valeur brute affichée directement (nom de pad pour KIT, note MIDI pour
        PATCH). Avant ce correctif, le dialog traitait toujours "pad" comme
        une note MIDI brute 0-127, ce qui désynchronisait la présélection
        pour GRID (bug signalé : la note affichée dans la liste, ex. « A3 »,
        ne correspondait pas à l'item présélectionné dans le dialog)."""
        etype   = ev.get("etype", ETYPE_GRID)
        pad_val = ev.get("pad", 0)
        if etype == ETYPE_GRID:
            num_pads  = pattern._num_pads
            names     = self._pad_names_list(num_pads, ev["track"])
            choices   = [f"{i+1:3d}  {name}" for i, name in enumerate(names)]
            sel       = min(max(pad_val, 0), num_pads - 1)
        elif etype == ETYPE_KIT:
            choices   = [f"{i:3d}  {self._pad_name(i)}" for i in range(128)]
            sel       = min(max(pad_val, 0), 127)
        else:  # ETYPE_PATCH : note MIDI brute — même fonction de nommage
               # que _event_note_name (midi_to_note_name, C4=60), PAS
               # midi_display_name (C0=0, convention différente du clavier
               # virtuel) : sinon la note présélectionnée dans ce dialog
               # n'affiche pas le même nom que celui vu dans la liste des
               # événements (ex. MIDI 57 = "A3" dans la liste vs "A4" avec
               # midi_display_name — bug signalé).
            choices   = [f"{i:3d}  {midi_to_note_name(i)}" for i in range(128)]
            sel       = min(max(pad_val, 0), 127)
        return choices, sel

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
        labels = [self._event_label(i, e, False) for i, e in enumerate(self._events)]
        self._event_lb.Set(labels)
        if self._events:
            cur = min(me._cur_idx, len(self._events) - 1)
            me._cur_idx = cur
            self._skip_listbox_announce = True
            self._event_lb.SetSelection(cur)
        self._update_mode_label()

    def _event_pitch_number(self, e):
        """Numéro affiché à côté du nom (_event_note_name) : note MIDI brute
        (0-127) pour PATCH et GRID/synth, numéro de pad 1-based sinon —
        même logique de branchement que _event_note_name (canal/pitch réel
        par piste non modélisé pour l'instant, voir
        project_event_list_window_todo)."""
        etype   = e.get("etype", ETYPE_GRID)
        pad_val = e["pad"]
        if etype == ETYPE_PATCH:
            return pad_val
        if etype == ETYPE_KIT:
            return pad_val + 1
        track_idx = e["track"]
        slot_idx  = self._parent._router.slot_for_track(track_idx)
        slot      = self._parent._rack.get_slot(slot_idx)
        if slot.type == InstrumentType.SYNTH:
            kb = self._parent._router.kb_notes_input
            if pad_val < len(kb):
                return kb[pad_val]
        return pad_val + 1

    def _event_label(self, i, e, selected=False):
        """i = position (0-based) de l'événement dans self._events.

        MODE_NOTES (Ctrl+1, piano roll) : ancien format inchangé.
        MODE_ALL (Ctrl+2, liste plate) : nouveau format
        "index: position, canal, type, numéro, val1, val2"."""
        if self._view_mode == self.MODE_NOTES:
            return self._event_label_notes(e, selected)
        return self._event_label_all(i, e, selected)

    def _event_label_notes(self, e, selected=False):
        """Format historique du mode Notes (Ctrl+1) — inchangé."""
        mark = "[*] " if selected else "    "
        if e["type"] == "note":
            name = self._event_note_name(e)
            bbt  = self._bbt_str(e["bar"], e["step"])
            if e["etype"] == ETYPE_GRID:
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

    def _event_label_all(self, i, e, selected=False):
        """Format du mode Tous les événements (Ctrl+2) — liste plate,
        "index: position, canal, type, numéro, val1, val2". i = position
        0-based dans self._events, affichée en index 1-based en tête de
        ligne. Canal : pour une note, vrai TapeEvent.channel (0-15, Phase 7
        étape 1i) ; pour bend/mod (automation, pas des TapeEvent), pas de
        canal réel — numéro de piste en substitut, comme avant."""
        mark = "[*] " if selected else "    "
        bbt  = self._bbt_str(e["bar"], e["step"])
        if e["type"] == "note":
            name   = self._event_note_name(e)
            number = self._event_pitch_number(e)
            canal  = e.get("channel", 0)
            return (f"{mark}{i+1}: {bbt}, Canal {canal}, Note, "
                    f"{number} ({name}), Durée {e['dur']}ms, Vel {e['vel']}")
        elif e["type"] == "bend":
            return f"{mark}{bbt}  Tr{e['track']+1:02d}  Bend:{e['value']:+d}"
        elif e["type"] == "mod":
            canal = e["track"] + 1
            return (f"{mark}{i+1}: {bbt}, Canal {canal}, CC, "
                    f"Numéro 1, Valeur {e['value']}")
        return str(e)

    def _update_label(self, idx):
        """Met à jour le label d'un seul item dans la ListBox."""
        if 0 <= idx < len(self._events):
            self._event_lb.SetString(
                idx, self._event_label(idx, self._events[idx], idx in self._selected_indices)
            )

    def _refresh_labels(self):
        """Remet à jour tous les labels (après changement de sélection globale)."""
        for i, e in enumerate(self._events):
            self._event_lb.SetString(i, self._event_label(i, e, i in self._selected_indices))

    def _set_status(self, msg):
        self._status_ctrl.SetString(0, msg)

    def _set_midi_status(self, msg):
        """Statut MIDI live — appelé depuis MidiHandler à chaque message entrant
        (Note On/Off, CC, Pitch Bend) tant que cette fenêtre est ouverte."""
        self._midi_status_ctrl.SetString(0, msg)
