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
        self._player.stop_all()
        self._router.stop_all_synth_voices()
        self._pattern_list    = [Pattern() for _ in range(99)]
        self._cur_pattern_idx = 0
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
