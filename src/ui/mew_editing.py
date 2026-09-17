import wx
from rack import InstrumentType
from pattern import ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH
from ui.midi_editor_dialogs import _NoteEditDialog, _MidiEventEditDialog, _CcEventEditDialog


class EditingMixin:
    """MidiEditorWindow — dialogues d'édition note/CC, duplication, insertion."""

    def _edit_note_dialog(self):
        if not self._events:
            return
        cur = self._midi_editor._cur_idx
        ev  = self._events[cur]
        if ev.get("type") in ("bend", "mod"):
            self._edit_cc_dialog(ev)
            return
        if ev.get("type") != "note":
            self._set_status("Pas une note — édition non disponible")
            return
        etype = ev.get("etype", ETYPE_GRID)
        pat   = self._parent._player._pattern
        self._add_undo(
            f"Éditer note Tr{ev['track']+1} B{ev['bar']+1}:S{ev['step']+1}"
        )
        dlg = _MidiEventEditDialog(self, ev, pat)
        if dlg.ShowModal() == wx.ID_OK:
            if etype == ETYPE_GRID:
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
                # Pour les notes grille, rafraîchir le cache _all_offsets
                # (utilisé par erase/navigation) après une édition manuelle.
                if etype == ETYPE_GRID:
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

    def _edit_cc_dialog(self, ev):
        """Édition d'un événement d'automation (bend/mod) via Entrée — MODE_ALL."""
        pat    = self._parent._player._pattern
        is_bend = ev["type"] == "bend"
        label   = "Bend" if is_bend else "Mod"
        self._add_undo(
            f"Éditer {label} Tr{ev['track']+1} B{ev['bar']+1}:S{ev['step']+1}"
        )
        dlg = _CcEventEditDialog(self, ev, pat)
        if dlg.ShowModal() == wx.ID_OK:
            edit_fn = self._midi_editor.edit_bend_event if is_bend else self._midi_editor.edit_mod_event
            new_ev = edit_fn(
                pat, ev,
                new_value = dlg.get_value(),
                new_bar   = dlg.get_bar(),
                new_step  = dlg.get_step(),
            )
            if new_ev:
                if self._parent._player.playing:
                    self._parent._player._wakeup.set()
                self._refresh()
                found = None
                for i, e in enumerate(self._events):
                    if (e["type"]  == new_ev["type"] and
                            e["track"]  == new_ev["track"] and
                            e["offset"] == new_ev["offset"] and
                            e["value"]  == new_ev["value"]):
                        found = i
                        break
                if found is not None:
                    self._navigate_to(found)
                bbt = self._bbt_str(new_ev["bar"], new_ev["step"])
                self._set_status(f"{label} modifié → {bbt}  Valeur:{new_ev['value']}")
            else:
                self._parent._pop_last_undo()
                self._set_status("Édition annulée (hors limites)")
        else:
            self._parent._pop_last_undo()
        dlg.Destroy()

    # ------------------------------------------------------------------
    # Duplication / Insertion (étape 7i)
    # ------------------------------------------------------------------

    def _advance_playhead_by_grid(self):
        """Avance le playhead d'une valeur de grille. Ne dépasse jamais la
        fin du pattern (pas d'extension automatique, contrairement à
        move_event/Numpad4-6) : retourne False et ne bouge pas dans ce cas."""
        pat        = self._parent._player._pattern
        total      = pat._num_bars * pat._num_steps
        new_offset = self._parent._player._current_offset() + self._grid_value_steps()
        if new_offset >= total:
            return False
        self._parent._player._go_to_offset(float(new_offset))
        return True

    def _duplicate_event(self, advance):
        """D (advance=True) / Shift+D (advance=False) : duplique l'événement
        ou le groupe courant à la même position (accord empilé — voir
        MidiEditor.duplicate_event). Le nouveau doublon est toujours
        sélectionné et joué. D avance ensuite le PLAYHEAD d'une valeur de
        grille (sans dépasser la fin de piste) ; Shift+D ne le bouge pas."""
        if not self._events:
            return
        cur     = self._midi_editor._cur_idx
        targets = (self._midi_editor.group_indices(self._events, cur)
                   if self._group_entry else [cur])
        targets = sorted(targets, key=lambda i: self._events[i].get("event_idx", 0),
                          reverse=True)
        pat = self._parent._player._pattern
        self._add_undo("Dupliquer" + (" accord" if len(targets) > 1 else " note"))
        results = []
        for i in targets:
            ev = self._events[i]
            if ev.get("type") != "note":
                continue
            new_ev = self._midi_editor.duplicate_event(pat, ev)
            if new_ev is not None:
                results.append(new_ev)
        if not results:
            self._parent._pop_last_undo()
            self._set_status("Duplication non disponible")
            return
        self._parent._player._compute_offsets()
        if self._parent._player.playing:
            self._parent._player._wakeup.set()
        self._refresh()
        self._group_entry = True   # le doublon fait maintenant partie d'un accord
        found = self._find_event_index(results[-1])
        if found is not None:
            self._navigate_to(found)
            self._play_single_at(found)
        n = len(results)
        label = f"{n} note(s) dupliquée(s)"
        if advance:
            if self._advance_playhead_by_grid():
                self._set_status(f"{label} → avancé")
            else:
                self._set_status(f"{label} (fin de piste)")
        else:
            self._set_status(label)

    def _insert_target(self):
        """Détermine (etype, pad) pour une insertion rapide (Ctrl+I/Alt+I)
        sur la piste courante, selon le type d'instrument — même logique que
        le clavier virtuel (VirtualKeyboardMixin._play_virtual_keyboard_note) :
        SYNTH → PATCH (note du clavier virtuel) ; KIT pitché (note_map ou
        kit_synth chargé) → KIT (note du clavier virtuel) ; KIT classique
        (16 pads fixes, pas de notes) → GRID (dernier pad joué — le clavier
        virtuel n'a pas de correspondance pad pour ce cas)."""
        slot   = self._parent._rack.get_slot(self._parent._cur_slot)
        router = self._parent._router
        if slot.type == InstrumentType.SYNTH:
            return ETYPE_PATCH, self._vk_note
        if self._parent._snd.note_map or (router.kit_synth and router.kit_synth.is_loaded()):
            return ETYPE_KIT, self._vk_note
        return ETYPE_GRID, (self._parent._player.last_played_pad or 0)

    def _quick_insert(self, advance):
        """Ctrl+I (advance=True) / Alt+I (advance=False) : insère une note
        à la position du playhead, avec l'instrument de la piste courante.
        Ctrl+I avance ensuite le playhead d'une valeur de grille (sans
        dépasser la fin de piste) ; Alt+I ne le bouge pas."""
        pat       = self._parent._player._pattern
        track     = self._parent._player._cur_track
        bar, step = divmod(int(self._parent._player._current_offset()), pat._num_steps)
        etype, pad = self._insert_target()
        vel = self._insert_last_vel if self._insert_last_vel is not None else 100
        dur = self._insert_last_dur if self._insert_last_dur is not None else round(self._grid_value_ms())
        self._add_undo("Insérer note")
        new_ev = self._midi_editor.insert_note(pat, etype, track, bar, step, pad, vel=vel, dur=dur)
        if new_ev is None:
            self._parent._pop_last_undo()
            self._set_status("Insertion impossible")
            return
        self._parent._player._compute_offsets()
        if self._parent._player.playing:
            self._parent._player._wakeup.set()
        self._refresh()
        found = self._find_event_index(new_ev)
        if found is not None:
            self._navigate_to(found)
            self._play_single_at(found)
        name = self._event_note_name(new_ev)
        if advance:
            if self._advance_playhead_by_grid():
                self._set_status(f"Inséré ({name}) → avancé")
            else:
                self._set_status(f"Inséré ({name}) (fin de piste)")
        else:
            self._set_status(f"Inséré ({name})")

    def _insert_dialog(self):
        """Ctrl+Shift+I : dialog note/durée/vélocité, insertion sans déplacer
        le curseur d'édition/lecture (ni le playhead, ni la sélection liste)."""
        pat       = self._parent._player._pattern
        track     = self._parent._player._cur_track
        bar, step = divmod(int(self._parent._player._current_offset()), pat._num_steps)
        etype, pad = self._insert_target()
        vel = self._insert_last_vel if self._insert_last_vel is not None else 100
        dur = self._insert_last_dur if self._insert_last_dur is not None else round(self._grid_value_ms())
        ev  = {"etype": etype, "pad": pad, "bar": bar, "step": step, "dur": dur, "vel": vel}
        pad_names = self._pad_names_list(pat._num_pads, track)
        self._add_undo("Insérer note (dialog)")
        dlg = _NoteEditDialog(self, ev, pat, pad_names, title="Insérer note")
        if dlg.ShowModal() == wx.ID_OK:
            new_ev = self._midi_editor.insert_note(
                pat, etype, track, dlg.get_bar(), dlg.get_step(), dlg.get_inst(),
                vel=dlg.get_vel(), dur=dlg.get_dur(),
            )
            if new_ev:
                self._insert_last_vel = new_ev["vel"]
                self._insert_last_dur = new_ev.get("dur", dur)
                self._parent._player._compute_offsets()
                if self._parent._player.playing:
                    self._parent._player._wakeup.set()
                self._refresh()
                bbt  = self._bbt_str(new_ev["bar"], new_ev["step"])
                name = self._event_note_name(new_ev)
                self._set_status(f"Note insérée ({name})  {bbt}")
            else:
                self._parent._pop_last_undo()
                self._set_status("Insertion annulée (hors limites)")
        else:
            self._parent._pop_last_undo()
        dlg.Destroy()

    def _insert_between(self):
        """A : insère une note entre l'événement courant et le suivant
        (groupe chronologique suivant, comme →), au pas médian entre les
        deux offsets. Positionne le curseur sur la nouvelle note. Impossible
        s'il n'y a pas de groupe suivant, ou si les deux sont sur des pas
        adjacents (aucun pas disponible entre les deux)."""
        if not self._events:
            return
        cur = self._midi_editor._cur_idx
        nxt = self._midi_editor.first_of_next_group(self._events, cur)
        if nxt < 0:
            self._set_status("Insertion impossible : aucun événement suivant")
            return
        cur_ev     = self._events[cur]
        cur_offset = cur_ev["offset"]
        nxt_offset = self._events[nxt]["offset"]
        mid_offset = self._midi_editor.insert_between_offset(cur_offset, nxt_offset)
        if mid_offset is None:
            self._set_status("Insertion impossible : pas d'espace entre ces deux notes")
            return
        pat   = self._parent._player._pattern
        track = cur_ev["track"]
        bar, step  = divmod(mid_offset, pat._num_steps)
        etype, pad = self._insert_target()
        vel = self._insert_last_vel if self._insert_last_vel is not None else 100
        dur = self._insert_last_dur if self._insert_last_dur is not None else round(self._grid_value_ms())
        self._add_undo("Insérer note (entre)")
        new_ev = self._midi_editor.insert_note(pat, etype, track, bar, step, pad, vel=vel, dur=dur)
        if new_ev is None:
            self._parent._pop_last_undo()
            self._set_status("Insertion impossible")
            return
        self._parent._player._compute_offsets()
        if self._parent._player.playing:
            self._parent._player._wakeup.set()
        self._refresh()
        found = self._find_event_index(new_ev)
        if found is not None:
            self._navigate_to(found)
            self._play_single_at(found)
        bbt  = self._bbt_str(new_ev["bar"], new_ev["step"])
        name = self._event_note_name(new_ev)
        self._set_status(f"Inséré entre ({name})  {bbt}")
