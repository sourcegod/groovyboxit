import wx
from rack import InstrumentType
from pattern import Pattern, bank_header, with_bank_header
from .dialogs import TrackPropertiesDialog


class TrackMixin:
    """Méthodes MainWindow relatives aux pistes (tracks), slots et sélection."""

    def _assign_track_slot(self):
        track_idx = self._player._cur_track
        slot_idx  = self._cur_slot
        # Choix de l'utilisateur : règle du canal (kit → 10, Phase 7 étape 10f1)
        self._router.assign_slot_by_user(track_idx, slot_idx)
        self._refresh_track_list()
        slot = self._rack.get_slot(slot_idx)
        self._show_status(
            f"Piste {track_idx + 1} → Slot_{slot_idx + 1:02d} ({slot.name}), "
            f"canal {self._router.get_track_channel(track_idx) + 1}"
        )

    def _set_track_volume_undo(self, tidx, vol):
        """Volume de piste avec Undo regroupé (Phase 7 étape 13b1, D1/D2) :
        rien n'est fait si la valeur ne change pas. Retourne le volume."""
        vol = max(0, min(100, vol))
        if vol != self._router.get_track_volume(tidx):
            self._add_mix_undo(f"Volume piste {tidx + 1}: {vol}", ("track_volume", tidx))
            self._router.set_track_volume(tidx, vol)
        return vol

    def _set_track_pan_undo(self, tidx, pan):
        """Pan de piste avec Undo regroupé (Phase 7 étape 15b1, D1) :
        rien n'est fait si la valeur ne change pas. Retourne le pan."""
        pan = max(-100, min(100, pan))
        if pan != self._router.get_track_pan(tidx):
            self._add_mix_undo(f"Pan piste {tidx + 1}: {pan}", ("track_pan", tidx))
            self._router.set_track_pan(tidx, pan)
        return pan

    def _slot_gm_tuning(self, slot_idx):
        """(transposition, gain_db) GM du slot pour TrackPropertiesDialog
        (Phase 7 étape 12h1, docs/DESIGN.md § 12a2 D6) : transposition pour
        un synthé seulement, gain pour tout slot non vide sauf une banque,
        dont le programme est réel (17h1, § 17e2 R8) ; None sinon."""
        slot = self._rack.get_slot(slot_idx)
        transpose = slot.gm_transpose() if slot.type == InstrumentType.SYNTH else None
        gain_db   = None if slot.is_empty or slot.type == InstrumentType.BANK \
            else slot.gm_gain_db()
        return transpose, gain_db

    def _bank_info(self, slot_idx, channel, msb=None, lsb=None, instruments=None):
        """Banque d'un slot pour TrackPropertiesDialog (Phase 7 étape 17h1,
        § 17e3 O5) : None hors slot Banque. MSB None : instrument du canal
        (le canal impose son instrument), lu dans instruments (état des 16
        canaux à l'ouverture du dialogue) ou, à défaut, dans le routeur ;
        sinon noms de la banque demandée, programme inchangé (None)."""
        if self._rack.get_slot(slot_idx).type != InstrumentType.BANK:
            return None
        r = self._router
        program = None
        if msb is None:
            program, msb, lsb = instruments[channel] if instruments is not None \
                else r.channel_instrument(channel)
        engine = r.bank_engine
        return {"names": r.program_names(slot_idx, channel, msb, lsb),
                "program": program, "msb": msb, "lsb": lsb,
                "drums": channel == Pattern.KIT_CHANNEL,
                "gs": engine is None or engine.bank_select == "gs"}

    def _track_properties_dialog(self):
        tidx = self._player._cur_track
        orig = dict(
            slot    = self._router.slot_for_track(tidx),
            volume  = self._router.get_track_volume(tidx),
            pan     = self._router.get_track_pan(tidx),
            mute    = self._router._track_mutes[tidx],
            solo    = self._router._track_solos[tidx],
            channel = self._router.get_track_channel(tidx),
        )
        orig['program'] = self._rack.get_slot(orig['slot']).gm_program()
        orig['transpose'], orig['gain_db'] = self._slot_gm_tuning(orig['slot'])   # 12a2 D6
        orig['msb'] = orig['lsb'] = None
        if self._rack.get_slot(orig['slot']).type == InstrumentType.BANK:
            # instrument du canal de la piste (17h1, § 17e3 O5)
            orig['program'], orig['msb'], orig['lsb'] = \
                self._router.channel_instrument(self._router.track_channel_now(tidx))
        orig_key = (orig['channel'], orig['program'], orig['msb'], orig['lsb'])
        # Piste temporaire (17f2) : copie des pistes à l'ouverture ; chaque
        # changement repart de la copie et y écrit l'entête, que le bouclage
        # rejoue ; Annuler remet la copie.
        live = self._player._pattern
        with live._lock:
            saved_tape = [list(events) for events in live._tape]
        bank_state = {"last": orig_key, "others": []}
        # Instrument des 16 canaux à l'ouverture (correctif de l'essai de
        # 17h1) : un canal que la piste quitte garde son instrument, même si
        # elle seule le définissait — sans cela, la poursuite le remettait
        # à l'état GM par défaut (piano) et le retour de la piste sur son
        # canal d'origine imposait ce piano.
        instruments = [self._router.channel_instrument(c) for c in range(16)]
        # config d'origine de chaque slot dont le programme a été changé,
        # pour Annuler (Phase 7 étape 10h3) ; set_gm_program remplace config
        saved_configs = {}
        # Undo avant le dialog, retiré si Annuler ou rien de changé (Phase 7
        # étape 10f1, même schéma que F2) ; le retrait rétablit l'état
        # « modifié » (16d1).
        self._add_undo(f"Propriétés piste {tidx + 1}")

        def apply(slot, vol, pan, mute, solo, channel, program, transpose, gain_db,
                  msb=None, lsb=None):
            was_bank = self._router._bank_slot_of(tidx) is not None
            if slot != self._router.slot_for_track(tidx):
                self._router.assign_slot(tidx, slot)
                self._cur_slot = slot
                self._slot_choice.SetSelection(slot)
            self._router.set_track_volume(tidx, vol)
            self._router.set_track_pan(tidx, pan)
            self._router._track_mutes[tidx] = mute
            self._router._track_solos[tidx] = solo
            self._router.set_track_channel(tidx, channel)
            slot_obj = self._rack.get_slot(slot)
            is_bank  = slot_obj.type == InstrumentType.BANK
            if is_bank or was_bank:
                self._apply_bank_header(tidx, live, saved_tape, bank_state, orig_key,
                                        is_bank, slot, channel, program, msb, lsb)
            elif program is not None and slot_obj.gm_program() != program:
                saved_configs.setdefault(slot, slot_obj.config)
                slot_obj.set_gm_program(program)
            if transpose is not None and slot_obj.gm_transpose() != transpose:
                saved_configs.setdefault(slot, slot_obj.config)
                slot_obj.set_gm_transpose(transpose)
            if gain_db is not None and slot_obj.gm_gain_db() != gain_db:
                saved_configs.setdefault(slot, slot_obj.config)
                slot_obj.set_gm_gain_db(gain_db)
            self._refresh_track_list()

        def slot_program(slot):
            slot_obj = self._rack.get_slot(slot)
            kind = {InstrumentType.SYNTH: "synth", InstrumentType.KIT: "kit"}.get(slot_obj.type)
            return kind, slot_obj.gm_program()

        dlg    = TrackPropertiesDialog(
            self, tidx, self._rack,
            orig['slot'], orig['volume'], orig['pan'], orig['mute'], orig['solo'],
            on_change=apply, on_play_toggle=self._play_toggle,
            channel=orig['channel'],
            channel_after_slot=lambda slot, ch: self._router.channel_after_slot(tidx, slot, ch),
            slot_program=slot_program,
            slot_gm_tuning=self._slot_gm_tuning,
            bank_info=lambda slot, ch, msb=None, lsb=None:
                self._bank_info(slot, ch, msb, lsb, instruments),
        )
        result = dlg.ShowModal()
        values = (dlg.get_slot_idx(), dlg.get_volume(), dlg.get_pan(),
                  dlg.get_mute(), dlg.get_solo(), dlg.get_channel(), dlg.get_program(),
                  dlg.get_transpose(), dlg.get_gain_db(), dlg.get_msb(), dlg.get_lsb())
        if result == wx.ID_OK and values != tuple(orig.values()):
            apply(*values)
            others = bank_state["others"]
            self._show_status(f"Piste {tidx + 1}: propriétés mises à jour" + (
                "; entête mis à jour aussi sur les pistes "
                + ", ".join(str(t + 1) for t in others) if others else ""))
        else:
            apply(*orig.values())
            for slot, config in saved_configs.items():
                self._rack.get_slot(slot).config = config
            self._pop_last_undo()
            if result == wx.ID_OK:
                self._show_status(f"Piste {tidx + 1}: propriétés inchangées")
            else:
                self._show_status(f"Piste {tidx + 1}: modifications annulées")
        dlg.Destroy()

    def _apply_bank_header(self, tidx, live, saved_tape, state, orig_key,
                           is_bank, slot, channel, program, msb, lsb):
        """Propriétés de piste (Alt+Entrée) sur une piste Banque, en direct (Phase 7 étape 17h1,
        docs/DESIGN.md § 17e3 O5, précision 17f2). Repart des pistes copiées
        à l'ouverture ; si canal, programme ou banque diffèrent de
        l'origine, écrit l'entête (CC0, CC32, Program Change à 1.1.1) de la
        piste et des autres pistes Banque dont l'entête est sur ce canal ;
        puis poursuite à la position courante, pour que le moteur suive les
        pistes. Note d'aperçu à chaque nouvel instrument ou canal (D16)."""
        r = self._router
        key = (channel, program, msb, lsb)
        others = []
        with live._lock:
            for t, events in enumerate(saved_tape):
                live._tape[t] = list(events)
            if is_bank and program is not None and key != orig_key:
                live._tape[tidx] = with_bank_header(saved_tape[tidx], channel, program, msb, lsb)
                for t, events in enumerate(saved_tape):
                    if t == tidx or t >= r.NUM_TRACKS or r._bank_slot_of(t) is None:
                        continue
                    header = bank_header(events)
                    if header is not None and header[0] == channel \
                            and header != (channel, program, msb, lsb):
                        live._tape[t] = with_bank_header(events, channel, program, msb, lsb)
                        others.append(t)
        state["others"] = others
        r.chase(live._tape, self._player._current_offset())
        if is_bank and key != state["last"] and r.bank_slot_ready(slot):
            note = r.DRUM_GRID_BASE if channel == Pattern.KIT_CHANNEL else 60
            r.bank_note(channel, note, 100, 400)
        state["last"] = key

    def _rename_track(self):
        """F2 : renomme la piste courante via un TextEntryDialog."""
        idx = self._player._cur_track
        old = self._player.voice_manager.get_name(idx)
        self._add_undo(f"Renommer piste {idx + 1}")
        dlg = wx.TextEntryDialog(self, f"Nom de la piste {idx + 1}:", "Renommer", old)
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name == old:
                self._pop_last_undo()
            else:
                self._player.voice_manager.set_name(idx, name)
                cur = self._pattern_list[self._cur_pattern_idx]
                cur._voices[idx]["name"] = name
                self._refresh_track_list()
                self._show_status(f"Piste {idx + 1}: {name or '(sans nom)'}")
        else:
            self._pop_last_undo()
        dlg.Destroy()

    def _track_label(self, idx):
        slot_idx  = self._router.slot_for_track(idx)
        # piste sur slot Banque : nom du preset de la piste (17f1, § 17e2 R7)
        slot_name = self._router.bank_preset_name(idx) or self._router.slot_name(idx)
        prefix    = "* " if self._track_editor.is_selected(idx) else "  "
        track_name = self._player.voice_manager.get_name(idx)
        if track_name:
            label = f"{prefix}Track_{idx + 1:02d} ({track_name}) - Slot_{slot_idx + 1:02d} - {slot_name}"
        else:
            label = f"{prefix}Track_{idx + 1:02d} - Slot_{slot_idx + 1:02d} - {slot_name}"
        if self._player._cur_track == idx and self._player.recording:
            label += " [REC]"
        if self._router._track_mutes[idx]:
            label += " [M]"
        if self._router._track_solos[idx]:
            label += " [S]"
        return label

    def _refresh_track_list(self):
        for i in range(self._track_list.GetCount()):
            self._track_list.SetString(i, self._track_label(i))

    def _on_track_list_activate(self, event):
        if wx.GetKeyState(wx.WXK_RETURN) and wx.GetKeyState(wx.WXK_CONTROL):
            self._track_select_dialog()
        elif wx.GetKeyState(wx.WXK_RETURN) and wx.GetKeyState(wx.WXK_ALT):
            self._track_properties_dialog()
        elif wx.GetKeyState(wx.WXK_RETURN):
            self._assign_track_slot()
        else:
            self._play(self._cur_row)

    def _on_pattern_list_activate(self, event):
        if wx.GetKeyState(wx.WXK_ALT):
            self._pattern_properties_dialog()
        else:
            self._play(self._cur_row)

    def _on_listbox_play_activate(self, event):
        self._play(self._cur_row)

    def _on_slot_list_activate(self, event):
        self._assign_track_slot()

    def _on_midi_port_activate(self, event):
        self._midi_handler.connect()

    def _on_track_select(self, event):
        idx = self._track_list.GetSelection()
        if idx < 0:
            return
        if self._skip_next_track_select:
            self._skip_next_track_select = False
            return
        if self._player.recording or self._player._count_in > 0:
            self._track_list.SetSelection(self._player._cur_track)
            self._show_status("Changement de piste interdit pendant l'enregistrement")
            return
        self._track_editor.clear_selection()
        self._refresh_track_list()
        self._go_to_track(idx)

    def _go_to_track(self, idx):
        from rack import InstrumentType
        if self._player.recording or self._player._count_in > 0:
            self._track_list.SetSelection(self._player._cur_track)
            self._show_status("Changement de piste interdit pendant l'enregistrement")
            return
        self._player._cur_track = idx
        self._cur_slot = self._router.slot_for_track(idx)
        self._slot_choice.SetSelection(self._cur_slot)
        self._router.reset_kit_pad()
        self._refresh_grid()
        slot = self._rack.get_slot(self._cur_slot)
        self._show_status(f"Piste {idx + 1} — {slot.name}")
        if slot.plays_notes:                        # synthé ou banque (17d1)
            self._router.load_slot_preview(self._cur_slot)
        elif slot.type == InstrumentType.KIT:
            self._load_kit_slot(self._cur_slot)
        if self._midi_editor_window is not None:
            self._midi_editor_window.refresh()

    def _on_slot_choice(self, event):
        from rack import InstrumentType
        self._cur_slot = self._slot_choice.GetSelection()
        slot = self._rack.get_slot(self._cur_slot)
        if slot.is_empty:
            self._show_status(f"Slot {self._cur_slot + 1:02d}: vide — Alt+X pour charger")
        else:
            self._show_status(
                f"Slot {self._cur_slot + 1:02d}: {slot.name} (Ctrl+T pour assigner)"
            )
            if slot.plays_notes:                    # synthé ou banque (17d1)
                self._router.load_slot_preview(self._cur_slot)
            elif slot.type == InstrumentType.KIT:
                self._load_kit_slot(self._cur_slot)

    def _update_slot_list(self):
        self._slot_choice.Set(self._rack.labels())
        self._slot_choice.SetSelection(self._cur_slot)
