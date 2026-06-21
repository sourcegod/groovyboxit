import os
import wx
from rack import InstrumentType
from project_manager import ProjectManager
from .dialogs import ExplorerDialog, PadPropertiesDialog


class PadMixin:
    """Méthodes MainWindow relatives aux pads, kits, voix et explorer."""

    def _on_pad_select(self, event):
        idx = self._pad_list.GetSelection()
        if idx < 0:
            return
        self._cur_row = idx

    def _on_pad_list_key_nav(self, event):
        idx = self._pad_list.GetSelection()
        if idx < 0:
            return
        self._cur_row = idx
        if self._autoplay:
            self._play(idx)

    def _on_pad_list_activate(self, event):
        if wx.GetKeyState(wx.WXK_ALT):
            self._pad_properties_dialog()
        else:
            self._play(self._cur_row)

    def _pad_label(self, pad_idx):
        name = self._player.voice_manager.get_name(pad_idx)
        if name:
            return f"Pad_{pad_idx + 1:02d} - {name}"
        return f"Pad_{pad_idx + 1:02d}"

    def _refresh_pad_list(self):
        sel = self._pad_list.GetSelection()
        self._pad_list.Set([self._pad_label(i) for i in range(self.ROWS)])
        self._pad_list.SetSelection(sel if sel != wx.NOT_FOUND else 0)

    def _pad_properties_dialog(self):
        pad_idx = self._cur_row
        vm      = self._player.voice_manager
        v       = vm.get_voice(pad_idx)
        orig    = dict(
            volume      = v.volume,
            pan         = v.pan,
            mute        = v.mute,
            solo        = v.solo,
            duration_ms = v.duration_ms,
        )

        def apply(vol, pan, mute, solo, dur):
            vm.set_volume(pad_idx, vol)
            vm.set_pan(pad_idx, pan)
            vm.set_mute(pad_idx, mute)
            vm.set_solo(pad_idx, solo)
            vm.set_duration_ms(pad_idx, dur)
            self._refresh_voice_display(pad_idx)

        def play_pad():
            self._play(pad_idx)

        dlg = PadPropertiesDialog(
            self, pad_idx,
            orig['volume'], orig['pan'],
            orig['mute'], orig['solo'], orig['duration_ms'],
            on_change=apply, on_play=play_pad, on_play_toggle=self._play_toggle,
        )
        result = dlg.ShowModal()
        if result == wx.ID_OK:
            apply(dlg.get_volume(), dlg.get_pan(),
                  dlg.get_mute(), dlg.get_solo(), dlg.get_duration_ms())
            self._show_status(f"Pad {pad_idx + 1}: propriétés mises à jour")
        else:
            apply(orig['volume'], orig['pan'],
                  orig['mute'], orig['solo'], orig['duration_ms'])
            self._show_status(f"Pad {pad_idx + 1}: modifications annulées")
        dlg.Destroy()

    def _debug_pad_status(self, pad_idx, midi_note_in=None):
        slot = self._rack.get_slot(self._cur_slot)
        parts = [f"Pad {pad_idx + 1}"]
        if midi_note_in is not None:
            parts.append(f"MIDI in: {midi_note_in}")
        if slot.type == InstrumentType.KIT and self._snd.note_map:
            kit_note = midi_note_in if midi_note_in is not None \
                       else self._snd.kit_base + self._snd.kit_offset + pad_idx
            parts.append(f"kit_note: {kit_note}")
        parts.append(f"shift_pad: {self._shift_pad}")
        msg = " | ".join(parts)
        print(msg)
        self._show_status(msg)

    def _kit_status(self):
        base   = self._snd.kit_base + self._snd.kit_offset
        offset = self._snd.kit_offset
        sign   = f"+{offset}" if offset >= 0 else str(offset)
        return (f"Kit: {self._snd._kit_name} | "
                f"Pads 1-16 → notes {base}–{base + 15} | "
                f"shift: {sign}")

    def _shift_kit(self, delta):
        new_labels = self._snd.shift_kit(delta)
        for i, label in enumerate(new_labels):
            self._player.voice_manager.set_name(i, label)
        self._refresh_pad_list()
        msg = self._kit_status()
        print(msg)
        self._show_status(msg)

    def _load_kit_slot(self, slot_idx):
        slot = self._rack.get_slot(slot_idx)
        if slot.type != InstrumentType.KIT:
            return
        kit_path = slot.config.get("kit", "")
        if kit_path and os.path.isfile(kit_path):
            try:
                labels, wav_paths = self._snd.load_kit(kit_path)
                for i, label in enumerate(labels):
                    self._player.voice_manager.set_name(i, label)
                for i, group in enumerate(self._snd.mute_groups):
                    self._player.voice_manager.set_mute_group(i, group)
                self._refresh_pad_list()
                self._show_status(self._kit_status())
                return
            except Exception as e:
                self._show_status(f"Erreur kit JSON: {e}")
        self._snd.load_sounds()
        self._show_status("Kit: sons media par défaut")

    def _open_explorer(self):
        dlg = ExplorerDialog(self)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        choice = dlg.get_selection()
        dlg.Destroy()
        if choice == "Projects":
            self._explorer_projects()
        elif choice == "Preset":
            self._explorer_preset()
        elif choice == "Kit":
            self._explorer_kit()
        elif choice == "Patch":
            self._explorer_patch()
        elif choice == "Sound":
            self._explorer_sound()

    def _explorer_projects(self):
        projects_dir = self._projects_dir
        os.makedirs(projects_dir, exist_ok=True)
        dlg = wx.FileDialog(self, "Ouvrir un projet…",
                            defaultDir=projects_dir,
                            wildcard=ProjectManager.WILDCARD,
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            self._project_path = dlg.GetPath()
            self._load_project()
            self._show_status(f"Projet chargé : {os.path.basename(self._project_path)}")
        dlg.Destroy()

    def _explorer_preset(self):
        start = self._presets_dir if os.path.isdir(self._presets_dir) else os.path.expanduser("~")
        dlg = wx.FileDialog(self, "Choisir un preset (*.json)",
                            defaultDir=start,
                            wildcard="Preset JSON (*.json)|*.json",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            self._preset_path = dlg.GetPath()
            self._load_preset()
            self._show_status(f"Preset: {os.path.basename(self._preset_path)}")
        dlg.Destroy()

    def _explorer_kit(self):
        start = self._kits_dir if os.path.isdir(self._kits_dir) else os.path.expanduser("~")
        dlg = wx.FileDialog(self, "Choisir un kit (*.json)",
                            defaultDir=start,
                            wildcard="Kit JSON (*.json)|*.json",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            json_path = dlg.GetPath()
            kit_name  = os.path.splitext(os.path.basename(json_path))[0]
            self._rack.set_slot(self._cur_slot, InstrumentType.KIT,
                                kit_name, {"kit": json_path})
            self._update_slot_list()
            self._load_kit_slot(self._cur_slot)
        dlg.Destroy()

    def _explorer_patch(self):
        start = self._patches_dir if os.path.isdir(self._patches_dir) else os.path.expanduser("~")
        dlg = wx.FileDialog(self, "Choisir un patch (*.json)",
                            defaultDir=start,
                            wildcard="Patch JSON (*.json)|*.json",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            json_path  = dlg.GetPath()
            patch_name = os.path.splitext(os.path.basename(json_path))[0]
            self._rack.set_slot(self._cur_slot, InstrumentType.SYNTH,
                                patch_name, {"patch": json_path})
            self._update_slot_list()
            self._router.reload_slot(self._cur_slot)
        dlg.Destroy()

    def _explorer_sound(self):
        start = self._samples_dir if os.path.isdir(self._samples_dir) else os.path.expanduser("~")
        dlg = wx.FileDialog(self, "Choisir un sample (*.wav)",
                            defaultDir=start,
                            wildcard="Fichiers WAV (*.wav)|*.wav",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            wav_path  = dlg.GetPath()
            pad_name  = os.path.splitext(os.path.basename(wav_path))[0]
            pad_idx   = self._cur_row
            self._snd.load_pad_sound(pad_idx, wav_path)
            if pad_idx < len(self._snd.media_lst):
                self._snd.media_lst[pad_idx] = wav_path
            self._player.voice_manager.set_name(pad_idx, pad_name)
            self._refresh_pad_list()
            self._show_status(f"Pad {pad_idx + 1}: {pad_name}")
        dlg.Destroy()

    def _refresh_voice_display(self, pad_idx):
        vm = self._player.voice_manager
        v  = vm.get_voice(pad_idx)
        self._mute_btns[pad_idx].SetValue(v.mute)
        self._solo_btns[pad_idx].SetValue(v.solo)
        self._vol_ctrls[pad_idx].SetValue(v.volume)
        self._pan_ctrls[pad_idx].SetValue(v.pan)

    def _on_vol_spin(self, pad_idx):
        val = self._vol_ctrls[pad_idx].GetValue()
        self._player.voice_manager.set_volume(pad_idx, val)
        self._show_status(f"Pad {pad_idx + 1}: Volume {val}")

    def _on_pan_spin(self, pad_idx):
        val = self._pan_ctrls[pad_idx].GetValue()
        self._player.voice_manager.set_pan(pad_idx, val)
        self._show_status(f"Pad {pad_idx + 1}: Pan {val}")

    def _refresh_all_voice_display(self):
        for r in range(self.ROWS):
            self._refresh_voice_display(r)

    def _on_mute_btn(self, pad_idx):
        muted = self._player.voice_manager.toggle_mute(pad_idx)
        self._mute_btns[pad_idx].SetValue(muted)
        self._show_status(f"Pad {pad_idx + 1}: Mute {'On' if muted else 'Off'}")

    def _on_solo_btn(self, pad_idx):
        soloed = self._player.voice_manager.toggle_solo(pad_idx)
        self._solo_btns[pad_idx].SetValue(soloed)
        self._show_status(f"Pad {pad_idx + 1}: Solo {'On' if soloed else 'Off'}")

    def _play_kit_pitched(self, note_idx):
        last    = self._player.last_played_pad
        pad_idx = last if last is not None else (self._cur_row + self._shift_pad)
        wav_path = self._snd.media_lst[pad_idx] if pad_idx < len(self._snd.media_lst) else None
        self._router.play_kit_pitched(
            note_idx, pad_idx, wav_path, self._player.play_sound
        )
