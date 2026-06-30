import os
import wx
from pattern import Pattern
from song import Song
from rack import InstrumentType
from project_manager import ProjectManager


class ProjectMixin:
    """Méthodes MainWindow relatives à la gestion de projet (.gvp)."""

    def _resolve_project_path(self):
        default = os.path.join(self._projects_dir, ProjectManager.DEFAULT_NAME)
        legacy  = os.path.join(self._presets_dir, "preset_01.json")
        if os.path.exists(default):
            return default
        if os.path.exists(legacy):
            return legacy
        return default

    def _find_free_project_path(self):
        projects_dir = self._projects_dir
        os.makedirs(projects_dir, exist_ok=True)
        for i in range(1, 1000):
            path = os.path.join(projects_dir, f"noname_{i:03d}.gvp")
            if not os.path.exists(path):
                return path
        return os.path.join(projects_dir, ProjectManager.DEFAULT_NAME)

    def _new_project(self):
        if self._project_modified:
            dlg = wx.MessageDialog(
                self,
                "Le projet a été modifié.\nEnregistrer avant de créer un nouveau projet ?",
                "Nouveau projet",
                wx.YES_NO | wx.CANCEL | wx.YES_DEFAULT | wx.ICON_QUESTION,
            )
            resp = dlg.ShowModal()
            dlg.Destroy()
            if resp == wx.ID_CANCEL:
                return
            if resp == wx.ID_YES:
                self._save_project()
        self._add_undo("Nouveau projet")
        self._player.stop_all()
        self._router.stop_all_synth_voices()
        self._pattern_list    = [Pattern() for _ in range(99)]
        self._cur_pattern_idx = 0
        self._pattern_cache       = [None] * len(self._pattern_list)
        self._pattern_cache_dirty = set(range(len(self._pattern_list)))
        self._song_list       = [Song(i) for i in range(Song.MAX_SONGS)]
        self._cur_song_idx    = 0
        self._player._pattern_list_ref = self._pattern_list
        new = self._pattern_list[0]
        self._apply_pattern_from_store(new)
        self._player._compute_offsets()
        self._refresh_pattern_listbox()
        self._refresh_grid()
        self._refresh_all_voice_display()
        self._refresh_track_list()
        self._refresh_pad_list()
        if self._song_window:
            self._song_window.set_cur_song(0)
        self._project_path     = self._find_free_project_path()
        self._project_modified = False
        self._update_title()
        self._show_status(f"Nouveau projet : {os.path.basename(self._project_path)}")

    def _update_title(self):
        name = os.path.basename(self._project_path)
        star = "*" if self._project_modified else ""
        self.SetTitle(f"{name}{star} — GroovyboxIt")

    def _mark_modified(self):
        if not self._project_modified:
            self._project_modified = True
            self._update_title()

    def _save_project(self):
        try:
            cur = self._pattern_list[self._cur_pattern_idx]
            cur._voices = self._player.voice_manager.to_list()
            self._flush_pattern_to_store(cur)
            data = {
                "version":  ProjectManager.VERSION,
                "rack":     self._rack.to_dict(),
                "patterns": [pat.to_dict() for pat in self._pattern_list],
                "songs":    [s.to_dict() for s in self._song_list],
                "cur_song": self._cur_song_idx,
            }
            ProjectManager.save(self._project_path, data)
            self._project_modified = False
            self._update_title()
            self._show_status(f"Projet sauvegardé : {os.path.basename(self._project_path)}")
        except Exception as e:
            self._show_status(f"ERREUR sauvegarde : {e}")

    def _save_project_as(self):
        projects_dir = self._projects_dir
        os.makedirs(projects_dir, exist_ok=True)
        dlg = wx.FileDialog(
            self,
            message="Enregistrer le projet sous…",
            defaultDir=projects_dir,
            defaultFile=os.path.splitext(os.path.basename(self._project_path))[0] + ".gvp",
            wildcard=ProjectManager.WILDCARD,
            style=wx.FD_SAVE,
        )
        result = dlg.ShowModal()
        path   = dlg.GetPath() if result == wx.ID_OK else ""
        dlg.Destroy()
        if result != wx.ID_OK or not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".gvp"
        if os.path.exists(path):
            msg = wx.MessageDialog(
                self,
                f"'{os.path.basename(path)}' existe déjà.\nRemplacer ?",
                "Remplacer le fichier",
                wx.YES_NO | wx.YES_DEFAULT | wx.ICON_WARNING,
            )
            replace = msg.ShowModal()
            msg.Destroy()
            if replace != wx.ID_YES:
                return
        self._project_path = path
        self._save_project()

    def _open_project(self):
        if self._project_modified:
            dlg = wx.MessageDialog(
                self,
                "Le projet a été modifié.\nEnregistrer avant d'ouvrir un autre projet ?",
                "Ouvrir un projet",
                wx.YES_NO | wx.CANCEL | wx.YES_DEFAULT | wx.ICON_QUESTION,
            )
            resp = dlg.ShowModal()
            dlg.Destroy()
            if resp == wx.ID_CANCEL:
                return
            if resp == wx.ID_YES:
                self._save_project()
        projects_dir = self._projects_dir
        os.makedirs(projects_dir, exist_ok=True)
        dlg = wx.FileDialog(
            self, "Ouvrir un projet…",
            defaultDir=projects_dir,
            wildcard=ProjectManager.WILDCARD,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        result = dlg.ShowModal()
        path   = dlg.GetPath() if result == wx.ID_OK else ""
        dlg.Destroy()
        if result != wx.ID_OK or not path:
            return
        self._project_path = path
        self._load_project()
        self._show_status(f"Projet chargé : {os.path.basename(self._project_path)}")

    def _load_project(self):
        if not os.path.exists(self._project_path):
            self._project_modified = False
            self._update_title()
            return
        try:
            data = ProjectManager.load(self._project_path)
        except Exception as e:
            self._show_status(f"ERREUR chargement : {e}")
            return
        if "rack" in data:
            self._rack.from_dict(data["rack"])
            self._update_slot_list()
        for i, p in enumerate(data.get("patterns", [])):
            if i >= len(self._pattern_list):
                break
            self._pattern_list[i].from_dict(p)
        for i, s in enumerate(data.get("songs", [])):
            if i < len(self._song_list):
                self._song_list[i].from_dict(s)
        self._cur_song_idx = max(0, min(data.get("cur_song", 0), len(self._song_list) - 1))
        if self._song_window:
            self._song_window.set_cur_song(self._cur_song_idx)
        self._refresh_pattern_listbox()
        self._cur_pattern_idx = 0
        new = self._pattern_list[0]
        self._apply_pattern_from_store(new)
        self._router.clear_slot_synths()
        for track_idx, slot_idx in enumerate(new._track_slots):
            slot = self._rack.get_slot(slot_idx)
            if slot.type == InstrumentType.SYNTH:
                self._router.assign_slot(track_idx, slot_idx)
        loaded_kit_slots = set()
        for slot_idx in new._track_slots:
            if slot_idx not in loaded_kit_slots:
                slot = self._rack.get_slot(slot_idx)
                if slot.type == InstrumentType.KIT:
                    self._load_kit_slot(slot_idx)
                    loaded_kit_slots.add(slot_idx)
        cur_slot = new._track_slots[self._player._cur_track] \
                   if self._player._cur_track < len(new._track_slots) else 0
        self._cur_slot = cur_slot
        self._slot_choice.SetSelection(cur_slot)
        slot = self._rack.get_slot(cur_slot)
        if slot.type == InstrumentType.SYNTH:
            self._router.load_slot_preview(cur_slot)
        elif slot.type == InstrumentType.KIT and cur_slot not in loaded_kit_slots:
            self._load_kit_slot(cur_slot)
        self._player._compute_offsets()
        self._refresh_grid()
        self._refresh_all_voice_display()
        self._refresh_track_list()
        self._refresh_pad_list()
        self._project_modified = False
        self._update_title()

    # Alias de compatibilité
    _load_preset = _load_project

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

    def _capture_state(self):
        """Sérialise l'état complet de l'application pour l'undo/redo.

        Seuls les patterns marqués dirty sont re-sérialisés ; les autres
        réutilisent leur dict précédent (partage de référence read-only).
        En pratique, seul le pattern courant change entre deux _add_undo().
        """
        cur = self._pattern_list[self._cur_pattern_idx]
        cur._voices = self._player.voice_manager.to_list()
        self._flush_pattern_to_store(cur)
        live = self._player._pattern
        cur._loop_start = live._loop_start
        cur._loop_end   = live._loop_end
        cur._loop_count = live._loop_count
        cur._looping    = live._looping

        self._pattern_cache_dirty.add(self._cur_pattern_idx)
        for i in sorted(self._pattern_cache_dirty):
            if i < len(self._pattern_list):
                self._pattern_cache[i] = self._pattern_list[i].to_dict()
        self._pattern_cache_dirty.clear()

        p = self._player
        return {
            "cur_pattern_idx": self._cur_pattern_idx,
            "cur_song_idx":    self._cur_song_idx,
            "patterns":        list(self._pattern_cache),
            "songs":           [s.to_dict() for s in self._song_list],
            "rack":            self._rack.to_dict(),
            "clipboard":       self._clipboard_to_dict(),
            "quant_params": {
                "res_idx":        p._quant_res_idx,
                "force_idx":      p._quant_force_idx,
                "swing_idx":      p._quant_swing_idx,
                "window_idx":     p._quant_window_idx,
                "quant_starts":   p._quant_starts,
                "quant_durations":p._quant_durations,
                "grid_idx":       p._grid_idx,
            },
        }

    def _clipboard_to_dict(self):
        """Sérialise le presse-papier TrackEditor."""
        cb = self._track_editor._clipboard
        if cb is None:
            return None
        tape_list = []
        for (t, b, s), events in cb.tape.items():
            for ev in events:
                if ev.etype == "K":
                    tape_list.append(["K", t, b, s, ev.note, ev.vel, ev.dur])
                else:
                    tape_list.append(["P", t, b, s, ev.note, ev.vel, ev.dur, ev.bend])
        import copy
        return {
            "num_tracks": cb.num_tracks,
            "num_bars":   cb.num_bars,
            "num_steps":  cb.num_steps,
            "grid":       copy.deepcopy(cb.grid),
            "tape":       tape_list,
        }

    def _clipboard_from_dict(self, d):
        """Restaure le presse-papier TrackEditor depuis un dict."""
        import copy
        from track_editor import _ClipboardData
        from pattern import TapeEvent
        if d is None:
            self._track_editor._clipboard = None
            return
        tape = {}
        for rec in d["tape"]:
            etype, t, b, s, note, vel, dur = (
                rec[0], rec[1], rec[2], rec[3], rec[4], rec[5], rec[6])
            bend = rec[7] if len(rec) > 7 else 0
            tape.setdefault((t, b, s), []).append(TapeEvent(etype, note, vel, dur, bend))
        self._track_editor._clipboard = _ClipboardData(
            num_tracks = d["num_tracks"],
            num_bars   = d["num_bars"],
            num_steps  = d["num_steps"],
            grid       = copy.deepcopy(d["grid"]),
            tape       = tape,
        )

    def _restore_state(self, state):
        """Restaure l'état de l'application depuis un snapshot undo/redo."""
        for i, pd in enumerate(state["patterns"]):
            self._pattern_list[i].from_dict(pd)
        # Les dicts du state sont déjà la sérialisation à jour — on les réutilise
        # comme cache pour le prochain _capture_state().
        self._pattern_cache = list(state["patterns"])
        self._pattern_cache_dirty.clear()
        for i, sd in enumerate(state["songs"]):
            self._song_list[i].from_dict(sd)
        self._rack.from_dict(state["rack"])
        self._cur_pattern_idx = state["cur_pattern_idx"]
        self._cur_song_idx    = state["cur_song_idx"]
        self._clipboard_from_dict(state.get("clipboard"))
        new = self._pattern_list[self._cur_pattern_idx]
        self._apply_pattern_from_store(new)
        live = self._player._pattern
        live._loop_start = new._loop_start
        live._loop_end   = new._loop_end
        live._loop_count = new._loop_count
        self._player._compute_offsets()
        qp = state.get("quant_params", {})
        if qp:
            from pattern import Pattern
            p = self._player
            p._quant_res_idx     = qp.get("res_idx",        -1)
            p._quant_force_idx   = qp.get("force_idx",       4)
            p._quant_swing_idx   = qp.get("swing_idx",       0)
            p._quant_window_idx  = qp.get("window_idx",      4)
            p._quant_starts      = qp.get("quant_starts",    True)
            p._quant_durations   = qp.get("quant_durations", False)
            p._grid_idx          = qp.get("grid_idx",        Pattern.GRID_DEFAULT_IDX)
        self._pattern_listbox.SetSelection(self._cur_pattern_idx)
        self._refresh_pattern_listbox()
        self._refresh_grid()
        self._refresh_all_voice_display()
        self._refresh_track_list()
        self._refresh_pad_list()
        self._update_bpm_display()
        if self._song_window:
            self._song_window.set_cur_song(self._cur_song_idx)
        self._mark_modified()

    def _add_undo(self, title):
        """Capture l'état courant et l'enregistre dans l'historique undo."""
        import time
        t = time.time()              # horodatage avant la sérialisation (lente)
        self._undo.add(title, self._capture_state(), timestamp=t)

    def _pop_last_undo(self):
        """Retire la dernière entrée undo (dialog annulé ou aucun changement)."""
        self._undo.pop_last()

    def _undo_action(self):
        """Ctrl+Z : annule la dernière action."""
        entry = self._undo.undo()
        if entry is None:
            self._show_status("Undo: rien à annuler")
            return
        current = self._capture_state()
        self._undo.push_future(entry.title, current)
        self._restore_state(entry.state)
        self._show_status(f"Undo: {entry.title}  ({entry.rel_time()})")

    def _redo_action(self):
        """Shift+Z : refait la dernière action annulée."""
        entry = self._undo.redo()
        if entry is None:
            self._show_status("Redo: rien à refaire")
            return
        current = self._capture_state()
        self._undo.push_history(entry.title, current)
        self._restore_state(entry.state)
        self._show_status(f"Redo: {entry.title}  ({entry.rel_time()})")

    def _undo_history_dialog(self):
        """Ctrl+Shift+Z : dialog historique undo multi-niveaux."""
        from ui.dialogs import UndoHistoryDialog
        entries = self._undo.history_list()
        if not entries:
            self._show_status("Historique Undo: vide")
            return
        dlg = UndoHistoryDialog(self, entries)
        if dlg.ShowModal() == wx.ID_OK:
            steps = dlg.get_steps()
            for _ in range(steps):
                self._undo_action()
        dlg.Destroy()
