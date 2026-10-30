import os
import re
import time
import wx
from pattern import Pattern, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH, ETYPE_CC, ETYPE_PGM, ETYPE_BEND
from song import Song
from rack import InstrumentType
from project_manager import ProjectManager
from midi.midi_export import export_pattern
from midi.midi_import import import_pattern
from tempo_map import format_bpm


class ProjectMixin:
    """Méthodes MainWindow relatives à la gestion de projet (.gvp)."""

    # « Modifié » = l'état courant n'est pas celui du fichier (Phase 7 étape
    # 16d1, docs/DESIGN.md § 16a1 D1) : numéros d'état tenus par UndoManager.
    # Le setter garde les écritures existantes : False = l'état courant est
    # celui du fichier, True = nouvel état.
    @property
    def _project_modified(self):
        return not self._undo.is_clean()

    @_project_modified.setter
    def _project_modified(self, value):
        if value:
            self._undo.new_state()
        else:
            self._undo.mark_saved()

    # Regroupement des Undo de mixage (Phase 7 étape 13b1, docs/DESIGN.md
    # § 13a1 D2) : fenêtre glissante, horloge remplaçable dans les tests.
    MIX_UNDO_WINDOW = 1.0
    _mix_clock      = staticmethod(time.monotonic)
    _mix_undo_last  = None       # (key, entrée Undo, instant) du dernier réglage

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
        self._take_end_if_idle()
        if self._project_modified:
            from ui.dialogs import SaveConfirmDialog
            dlg = SaveConfirmDialog(
                self,
                "Le projet a été modifié.\nEnregistrer avant de créer un nouveau projet ?",
                "Nouveau projet",
            )
            resp = dlg.ShowModal()
            dlg.Destroy()
            if resp == wx.ID_CANCEL:
                return
            if resp == wx.ID_YES:
                self._save_project()
        self._undo.clear()                 # l'historique appartient au projet (16d1, D3)
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
        self._apply_master(*self._master_defaults)     # 15d1 D3
        self._player._compute_offsets()
        self._refresh_pattern_listbox()
        self._refresh_grid()
        self._refresh_all_voice_display()
        self._refresh_track_list()
        self._refresh_pad_list()
        if self._song_window:
            self._song_window.set_cur_song(0)
        self._project_path     = self._find_free_project_path()
        self._take             = None
        self._project_modified = False
        self._update_title()
        self._show_status(f"Nouveau projet : {os.path.basename(self._project_path)}")

    #--------------------------------------------------------------------------
    # Export MIDI du pattern courant (Phase 7 étape 10j1, docs/DESIGN.md
    # § 10a1 D10) : les états hors Pattern viennent du router, du Rack, du
    # player et du kit chargé.

    def _midi_export_params(self):
        """Arguments de build_pattern_midi pour le pattern courant."""
        r     = self._router
        slots = [self._rack.get_slot(s) for s in r._track_slots]
        idx   = self._cur_pattern_idx
        vm    = self._player.voice_manager
        is_bank = [s.type == InstrumentType.BANK for s in slots]
        # Piste sur slot Banque (17f1, § 17e3 O8) : banque et programme
        # viennent des événements de _tape ; nom = preset de son canal.
        preset_names = [r.bank_preset_name(t) if is_bank[t] else None
                        for t in range(len(slots))]
        return dict(
            name             = self._pattern_list[idx]._name or f"Pat_{idx + 1:02d}",
            bpm              = self._player.bpm,
            track_channels   = list(r._track_channels),
            track_is_synth   = [s.type == InstrumentType.SYNTH for s in slots],
            track_is_bank    = is_bank,
            track_names      = [preset_names[t] or s.name        # nom du slot (10h2 D12)
                                for t, s in enumerate(slots)],
            kit_pad_notes    = list(self._snd.pad_notes),        # 11a1 D1
            kit_gm_map       = dict(self._snd.gm_note_map),      # 11a1 D2
            synth_grid_notes = list(r._kb_notes_play),
            voice_durations  = [vm.get_duration_ms(i) for i in range(Pattern.NUM_PADS)],
            pad_volumes      = [vm.get_voice(i).volume for i in range(Pattern.NUM_PADS)],  # 12a1 D2
            track_programs   = [s.gm_program() for s in slots],  # None pour une banque
            track_transposes = [s.gm_transpose() for s in slots],      # 12a2 D4
            track_gain_db    = [s.gm_gain_db() for s in slots],        # 12a2 D5
            track_audible    = [r._track_is_audible(t) for t in range(len(r._track_slots))],  # 12a3 D7
            pad_audible      = [vm.is_audible(i) for i in range(Pattern.NUM_PADS)],
            track_volumes    = list(r._track_volumes),
            track_pans       = list(r._track_pans),
        )

    def _midi_export_filename(self):
        """Nom de fichier proposé : Pat_NN[_nom].mid, nom nettoyé."""
        idx  = self._cur_pattern_idx
        base = f"Pat_{idx + 1:02d}"
        name = re.sub(r"[^\w\-]+", "_", self._pattern_list[idx]._name).strip("_")
        return f"{base}_{name}.mid" if name else f"{base}.mid"

    def _export_midi(self, parent=None, status=None):
        """Alt+Shift+E : exporte le pattern courant en .mid. parent : fenêtre
        du dialog (éditeur MIDI) ; status : où annoncer le résultat."""
        status = status or self._show_status
        try:
            os.makedirs(self._exports_dir, exist_ok=True)
        except OSError:
            pass   # le dialog s'ouvrira ailleurs ; l'écriture dira l'erreur
        dlg = wx.FileDialog(
            parent or self, "Exporter le pattern en MIDI…",
            defaultDir=self._exports_dir,
            defaultFile=self._midi_export_filename(),
            wildcard="Fichiers MIDI (*.mid)|*.mid",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        result = dlg.ShowModal()
        path   = dlg.GetPath() if result == wx.ID_OK else ""
        dlg.Destroy()
        if not path:
            status("Export MIDI annulé")
            return
        if not path.lower().endswith(".mid"):
            path += ".mid"
        unmapped = set()
        try:
            export_pattern(path, self._player._pattern, unmapped=unmapped,
                           **self._midi_export_params())
        except Exception as e:
            status(f"ERREUR export MIDI : {e}")
            return
        msg = f"Pattern {self._cur_pattern_idx + 1:02d} exporté : {os.path.basename(path)}"
        if unmapped:
            # Sons de kit sans équivalent GM, écrits tels quels (11a1 D4)
            labels = self._snd.note_labels
            names  = ", ".join(f"{labels.get(n, f'Note {n}')} ({n})"
                               for n in sorted(unmapped))
            msg += f" — non converti en GM : {names}"
        status(msg)

    #--------------------------------------------------------------------------
    # Import MIDI dans le pattern courant (Phase 7 étape 18d1, docs/DESIGN.md
    # § 18a1 I1-I3, I5, I11) : midi_import construit le pattern, l'UI choisit
    # le slot Banque, remplace le pattern courant et pose l'Undo.

    _import_dir = None          # dernier dossier d'import validé (session)

    def _import_bank_slot(self):
        """(slot, emplacement, créé) du slot Banque des pistes importées
        (I3) : le premier slot Banque du Rack ; sinon un slot à créer dans le
        premier slot vide, sur l'emplacement qui tient déjà gm_soundfont,
        sinon le premier emplacement libre, sinon le premier. None : Rack
        plein sans slot Banque. Ne modifie pas le Rack."""
        rack  = self._rack
        slots = [rack.get_slot(i) for i in range(rack.NUM_SLOTS)]
        for s in slots:
            if s.type == InstrumentType.BANK:
                return s.index, s.bank_slot(), False
        empty = next((s.index for s in slots if s.is_empty), None)
        if empty is None:
            return None
        files = rack.bank_files
        if self._gm_soundfont in files:
            bank_slot = files.index(self._gm_soundfont)
        else:
            bank_slot = next((i for i, f in enumerate(files) if f is None), 0)
        return empty, bank_slot, True

    def _import_midi(self, parent=None, status=None):
        """Alt+Shift+I : importe un .mid dans le pattern courant. parent :
        fenêtre des dialogs (éditeur MIDI) ; status : où annoncer le
        résultat. Le fichier est lu avant toute question : une erreur de
        lecture ne pose ni confirmation ni Undo."""
        status = status or self._show_status
        # Dernier dossier validé de la session, sinon EXPORTS (18d3)
        start  = next((d for d in (self._import_dir, self._exports_dir)
                       if d and os.path.isdir(d)), os.path.expanduser("~"))
        dlg = wx.FileDialog(
            parent or self, "Importer un fichier MIDI…",
            defaultDir=start,
            wildcard="Fichiers MIDI (*.mid;*.midi)|*.mid;*.midi",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        result = dlg.ShowModal()
        path   = dlg.GetPath() if result == wx.ID_OK else ""
        dlg.Destroy()
        if not path:
            status("Import MIDI annulé")
            return
        self._import_dir = os.path.dirname(path)
        base = os.path.basename(path)
        try:
            imported, report = import_pattern(path)
        except Exception as e:
            status(f"ERREUR import MIDI : {e}")
            return
        target = self._import_bank_slot()
        if target is None:
            status("Import MIDI refusé : aucun slot Banque, et aucun slot vide dans le Rack")
            return
        idx = self._cur_pattern_idx
        if not self._player._pattern.is_empty():
            msg = wx.MessageDialog(
                parent or self,
                f"Le pattern {idx + 1:02d} n'est pas vide.\nLe remplacer par '{base}' ?",
                "Importer un fichier MIDI",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
            )
            answer = msg.ShowModal()
            msg.Destroy()
            if answer != wx.ID_YES:
                status("Import MIDI annulé")
                return

        self._take_end_if_idle()
        self._player.stop_all()
        self._player.goto_start()      # nouveau morceau joué depuis 1.1.1 (18d5)
        self._router.stop_all_synth_voices()
        self._add_undo(f"Import MIDI : {base}")

        slot_idx, bank_slot, created = target
        if created:
            name = os.path.splitext(os.path.basename(self._gm_soundfont))[0] \
                   or f"Banque {bank_slot + 1}"
            if self._rack.bank_files[bank_slot] is None:
                self._rack.set_bank_file(bank_slot, self._gm_soundfont)
            self._rack.set_slot(slot_idx, InstrumentType.BANK, name, {"bank_slot": bank_slot})
            self._update_slot_list()
        for t in range(report.num_tracks):
            imported._track_slots[t] = slot_idx

        # Pattern entièrement remplacé (I2) : le store, puis le player et le
        # router comme à un changement de pattern ; boucle remise à zéro.
        stored = self._pattern_list[idx]
        stored.from_dict(imported.to_dict())
        self._pattern_cache_dirty.add(idx)
        self._apply_pattern_from_store(stored)
        live = self._player._pattern
        live._loop_start = live._loop_end = None
        live._loop_count = 0
        self._player._loop_remaining = 0
        self._router.sync_banks()

        cur_track = self._player._cur_track
        self._cur_slot = stored._track_slots[cur_track] \
                         if cur_track < len(stored._track_slots) else slot_idx
        self._slot_choice.SetSelection(self._cur_slot)
        if self._rack.get_slot(self._cur_slot).plays_notes:
            self._router.load_slot_preview(self._cur_slot)
        self._player._compute_offsets()
        self._refresh_pattern_listbox()
        self._refresh_grid()
        self._refresh_all_voice_display()
        self._refresh_track_list()
        self._refresh_pad_list()
        self._update_bpm_display()

        n = report.num_tracks
        msg = (f"Import MIDI : {base} → Pattern {idx + 1:02d}, {n} piste{'s' if n > 1 else ''}, "
               f"{report.num_bars} mesure{'s' if report.num_bars > 1 else ''}, "
               f"{format_bpm(report.bpm)} BPM, résolution 1/{report.resolution}")
        if created:
            msg += f" ; slot {slot_idx + 1:02d} créé : banque {self._rack.get_slot(slot_idx).name}"
        details = report.details()
        if details:
            msg += " ; " + " ; ".join(details)
        status(msg)

    def _update_title(self):
        name = os.path.basename(self._project_path)
        star = "*" if self._project_modified else ""
        self.SetTitle(f"{name}{star} — GroovyboxIt")

    def _mark_modified(self):
        """Nouvel état après une modification (Phase 7 étape 16d1, D1)."""
        was_clean = self._undo.is_clean()
        self._undo.new_state()
        if was_clean:
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
                "master":   self._master_dict(),        # 15d1 D2
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
        self._take_end_if_idle()
        if self._project_modified:
            from ui.dialogs import SaveConfirmDialog
            dlg = SaveConfirmDialog(
                self,
                "Le projet a été modifié.\nEnregistrer avant d'ouvrir un autre projet ?",
                "Ouvrir un projet",
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
        self._take = None
        try:
            data = ProjectManager.load(self._project_path)
        except Exception as e:
            self._show_status(f"ERREUR chargement : {e}")
            return
        self._undo.clear()                     # l'historique appartient au projet (16d1, D3)
        if "rack" in data:
            self._rack.from_dict(data["rack"])
            self._update_slot_list()
        is_kit_slot = lambda slot_idx: self._rack.get_slot(slot_idx).type == InstrumentType.KIT
        for i, p in enumerate(data.get("patterns", [])):
            if i >= len(self._pattern_list):
                break
            self._pattern_list[i].from_dict(p)
            # Projet d'avant les canaux : pistes kit → canal 10 (10h7)
            self._pattern_list[i].apply_kit_channels(is_kit_slot)
        # Tous les patterns ont changé : le cache de _capture_state (Undo)
        # ne doit plus servir les dicts du projet précédent (Phase 7 étape 10h9)
        self._pattern_cache_dirty = set(range(len(self._pattern_list)))
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
        self._apply_master(*self._master_from_dict(data.get("master")))   # 15d1 D2, D3
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
        if slot.plays_notes:                        # synthé ou banque (17d1)
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
            "event_filter_params": p._event_filter_state,
            "master":              self._master_dict(),      # 15d1 D2
        }

    def _clipboard_to_dict(self):
        """Sérialise le presse-papier TrackEditor (grille GRID + tape
        KIT/PATCH/CC/PGM/BEND, unifiées — BEND depuis la Phase 7 étape 6f1 :
        `[ETYPE_BEND, t, b, s, value, channel, frac]`).

        Chaque etype a sa propre branche explicite : avant la Phase 7 étape
        4o, un `else` fourre-tout sérialisait tout etype inconnu comme un
        ETYPE_PATCH (note=None), ce qui corrompait un CC/Program Change pris
        dans la plage copiée (_extract copie tous les etypes).

        Dernier champ de chaque enregistrement (`frac`, Phase 7 étape 5d) :
        fraction de pas de `ev.time` (CC en temps flottant depuis 5b) — t/b/s
        sont le pas entier tronqué (clé du bucket), `frac` complète la
        position exacte. Toujours 0.0 pour GRID/KIT/PATCH (notes au pas
        entier). Ajouté en fin de liste : lecture rétrocompatible par
        `_clipboard_from_dict` (absent → 0.0) des presse-papiers .gvp
        sauvés avant 5d.
        """
        cb = self._track_editor._clipboard
        if cb is None:
            return None
        tape_list = []
        for (t, b, s), events in cb.tape.items():
            for ev in events:
                frac = ev.time - int(ev.time)
                if ev.etype == ETYPE_GRID:
                    tape_list.append([ETYPE_GRID, t, b, s, ev.payload.get("pad"), ev.payload.get("vel"),
                                       ev.channel, frac])
                elif ev.etype == ETYPE_KIT:
                    tape_list.append([ETYPE_KIT, t, b, s, ev.payload.get("note"), ev.payload.get("vel"),
                                       ev.dur, ev.channel, frac])
                elif ev.etype == ETYPE_PATCH:
                    # rec[7] : ancien champ "bend" par note, toujours 0 depuis
                    # la Phase 7 étape 7h1 — position gardée pour relire les
                    # presse-papiers sauvés avant.
                    tape_list.append([ETYPE_PATCH, t, b, s, ev.payload.get("note"), ev.payload.get("vel"),
                                       ev.dur, 0, ev.channel, frac])
                elif ev.etype == ETYPE_CC:
                    tape_list.append([ETYPE_CC, t, b, s, ev.payload.get("cc_num"),
                                       ev.payload.get("value"), ev.channel, frac])
                elif ev.etype == ETYPE_PGM:
                    tape_list.append([ETYPE_PGM, t, b, s, ev.payload.get("program"), ev.channel, frac])
                elif ev.etype == ETYPE_BEND:
                    tape_list.append([ETYPE_BEND, t, b, s, ev.payload.get("value"), ev.channel, frac])
        return {
            "num_tracks": cb.num_tracks,
            "num_bars":   cb.num_bars,
            "num_steps":  cb.num_steps,
            "tape":       tape_list,
        }

    def _clipboard_from_dict(self, d):
        """Restaure le presse-papier TrackEditor depuis un dict.

        `time=frac` (Phase 7 étape 5d) : seule la fraction de pas est
        reconstituée ici (0..1, 0.0 par défaut pour un enregistrement sans
        ce champ, rétrocompatible) — la position bar/step pleine n'a pas
        besoin d'être recomposée, `TrackEditor.paste` additionne cette
        fraction à la position de destination (voir son commentaire).
        """
        from track_editor import _ClipboardData
        from pattern import TapeEvent
        if d is None:
            self._track_editor._clipboard = None
            return
        tape = {}
        for rec in d["tape"]:
            etype = rec[0]
            if etype == ETYPE_GRID:
                t, b, s, pad, vel = rec[1], rec[2], rec[3], rec[4], rec[5]
                channel = rec[6] if len(rec) > 6 else 0
                frac    = rec[7] if len(rec) > 7 else 0.0
                tape.setdefault((t, b, s), []).append(
                    TapeEvent(ETYPE_GRID, channel=channel, payload={"pad": pad, "vel": vel}, time=frac)
                )
            elif etype == ETYPE_CC:
                t, b, s, cc_num, value = rec[1], rec[2], rec[3], rec[4], rec[5]
                channel = rec[6] if len(rec) > 6 else 0
                frac    = rec[7] if len(rec) > 7 else 0.0
                tape.setdefault((t, b, s), []).append(
                    TapeEvent(ETYPE_CC, channel=channel,
                              payload={"cc_num": cc_num, "value": value}, time=frac)
                )
            elif etype == ETYPE_PGM:
                t, b, s, program = rec[1], rec[2], rec[3], rec[4]
                channel = rec[5] if len(rec) > 5 else 0
                frac    = rec[6] if len(rec) > 6 else 0.0
                tape.setdefault((t, b, s), []).append(
                    TapeEvent(ETYPE_PGM, channel=channel, payload={"program": program}, time=frac)
                )
            elif etype == ETYPE_BEND:
                # Branche explicite (Phase 7 étape 6f1) : la branche `else`
                # ci-dessous lirait un BEND comme une note KIT/PATCH.
                t, b, s, value = rec[1], rec[2], rec[3], rec[4]
                channel = rec[5] if len(rec) > 5 else 0
                frac    = rec[6] if len(rec) > 6 else 0.0
                tape.setdefault((t, b, s), []).append(
                    TapeEvent(ETYPE_BEND, channel=channel, payload={"value": value}, time=frac)
                )
            else:
                t, b, s, note, vel, dur = rec[1], rec[2], rec[3], rec[4], rec[5], rec[6]
                payload = {"note": note, "vel": vel}
                if etype == ETYPE_PATCH:
                    # rec[7] (ancien bend par note) ignoré depuis la Phase 7 étape 7h1
                    channel = rec[8] if len(rec) > 8 else 0
                    frac    = rec[9] if len(rec) > 9 else 0.0
                else:
                    channel = rec[7] if len(rec) > 7 else 0
                    frac    = rec[8] if len(rec) > 8 else 0.0
                tape.setdefault((t, b, s), []).append(
                    TapeEvent(etype, dur=dur, channel=channel, payload=payload, time=frac)
                )
        self._track_editor._clipboard = _ClipboardData(
            num_tracks = d["num_tracks"],
            num_bars   = d["num_bars"],
            num_steps  = d["num_steps"],
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
        if "master" in state:
            self._apply_master(*self._master_from_dict(state["master"]))
        new = self._pattern_list[self._cur_pattern_idx]
        self._apply_pattern_from_store(new)
        live = self._player._pattern
        live._loop_start = new._loop_start
        live._loop_end   = new._loop_end
        live._loop_count = new._loop_count
        # Boucles rétablies (Phase 7 étape 15f1, D5) : compteur de répétitions,
        # boucle du song en lecture, réveil du thread comme Ctrl+L / Alt+L.
        p = self._player
        p._loop_remaining = live._loop_count
        if p._song_mode:
            p._song_looping = self._song_list[self._cur_song_idx]._looping
        if p.playing or p.clicking or p._note_repeat_active:
            p._wakeup.set()
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
        self._player._event_filter_state = state.get("event_filter_params")
        self._pattern_listbox.SetSelection(self._cur_pattern_idx)
        self._refresh_pattern_listbox()
        self._refresh_grid()
        self._refresh_all_voice_display()
        self._refresh_track_list()
        self._refresh_pad_list()
        self._update_bpm_display()
        if self._song_window:
            self._song_window.set_cur_song(self._cur_song_idx)

    def _add_undo(self, title):
        """Capture l'état courant et l'enregistre dans l'historique undo."""
        t = time.time()              # horodatage avant la sérialisation (lente)
        self._undo.add(title, self._capture_state(), timestamp=t)
        self._mark_modified()

    #--------------------------------------------------------------------------
    # Volume et pan globaux (Phase 7 étape 15d1, docs/DESIGN.md § 15a1 D2-D4,
    # avenant 15a2) : une valeur par projet, clé "master" du .gvp ; défauts
    # de data/config.json (_master_defaults) pour un nouveau projet ou un
    # projet qui n'a pas la clé.

    def _master_dict(self):
        return {"volume": self._player.volume, "pan": self._player.pan}

    def _master_from_dict(self, d):
        """(volume, pan) d'une clé "master" ; défauts de la config pour ce
        qui manque ou est invalide."""
        vol, pan = self._master_defaults
        if isinstance(d, dict):
            v, p = d.get("volume"), d.get("pan")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vol = max(0, min(100, int(v)))
            if isinstance(p, (int, float)) and not isinstance(p, bool):
                pan = max(-100, min(100, int(p)))
        return vol, pan

    def _apply_master(self, volume, pan):
        """Applique au player (et au pilote audio) et aux deux SpinCtrl."""
        self._player.set_volume(volume)
        self._player.set_pan(pan)
        self._router.set_master_pan(self._player.pan)     # CC10 des banques (17d1, D13)
        self._volume_ctrl.SetValue(self._player.volume)
        self._pan_ctrl.SetValue(self._player.pan)

    def _set_master_volume_undo(self, vol):
        """Volume global avec Undo regroupé (D4) : rien si la valeur ne
        change pas. Retourne le volume."""
        vol = max(0, min(100, int(vol)))
        if vol != self._player.volume:
            self._add_mix_undo(f"Volume global: {vol}", ("master_volume",))
            self._player.set_volume(vol)
        self._volume_ctrl.SetValue(vol)
        return vol

    def _set_master_pan_undo(self, pan):
        """Pan global avec Undo regroupé (D4) : rien si la valeur ne change
        pas. Retourne le pan."""
        pan = max(-100, min(100, int(pan)))
        if pan != self._player.pan:
            self._add_mix_undo(f"Pan global: {pan}", ("master_pan",))
            self._player.set_pan(pan)
            self._router.set_master_pan(pan)
        self._pan_ctrl.SetValue(pan)
        return pan

    def _add_mix_undo(self, title, key=None):
        """Undo avant un changement de mute, de solo ou de volume (Phase 7
        étape 13b1, D1/D2). Un changement de la même `key` moins de
        MIX_UNDO_WINDOW s après le précédent, dont l'entrée est toujours la
        dernière, ne fait que relancer la fenêtre et prendre le nouveau titre
        (« Volume piste 2: 80 », valeur atteinte) : un tour de bouton ne
        donne qu'une entrée. key=None (bascules) : une entrée à chaque fois."""
        now  = self._mix_clock()
        last = self._mix_undo_last
        if key is not None and last is not None and last[0] == key \
                and self._undo.last_entry() is last[1] \
                and now - last[2] < self.MIX_UNDO_WINDOW:
            last[1].title = title
            self._mix_undo_last = (key, last[1], now)
            self._mark_modified()
            return
        self._add_undo(title)
        self._mix_undo_last = (key, self._undo.last_entry(), now) if key is not None else None

    def _pop_last_undo(self):
        """Retire la dernière entrée undo (dialog annulé ou aucun changement) ;
        son numéro d'état est rétabli, et avec lui l'état « modifié » (16d1, D2)."""
        self._undo.pop_last()
        self._update_title()

    #--------------------------------------------------------------------------
    # Prise d'enregistrement live (Phase 7 étape 10d2) : un Undo avant la
    # prise (R, Shift+R, Ctrl+R, Erase), retiré à la fin si _tape n'a pas
    # changé. Effacer sans rien jouer (Remplacement, Erase) change _tape :
    # la prise est alors gardée, et le projet reste marqué modifié.

    def _tape_signature(self):
        """Contenu de _tape du pattern live, comparable entre deux instants."""
        live = self._player._pattern
        with live._lock:
            tape = [[(ev.time, ev.etype, ev.dur, ev.channel, sorted(ev.payload.items()))
                     for ev in track_list] for track_list in live._tape]
        return self._cur_pattern_idx, tape

    def _take_begin(self, title):
        """Ouvre une prise : Undo de l'état d'avant. Sans effet si une prise
        est déjà ouverte (ex. Erase pendant un Rec : même prise)."""
        if self._take is not None:
            return
        sig = self._tape_signature()
        self._add_undo(title)
        self._take = (sig, self._undo.last_entry())

    def _take_end_if_idle(self):
        """Ferme la prise si le player n'enregistre ni n'efface plus. Si _tape
        n'a pas changé et que l'Undo de la prise est toujours le dernier, il
        est retiré et l'état « modifié » d'avant la prise est rétabli par
        pop_last (Phase 7 étape 16d1, D2, sauvegarde entre-temps comprise)."""
        if self._take is None:
            return
        p = self._player
        if p.recording or p.erasing or p._count_in > 0:
            return
        sig, entry = self._take
        self._take = None
        if entry is not None and self._undo.last_entry() is entry \
                and self._tape_signature() == sig:
            self._pop_last_undo()

    def _undo_action(self):
        """Ctrl+Z : annule la dernière action."""
        entry = self._undo.undo()
        if entry is None:
            self._show_status("Undo: rien à annuler")
            return
        current = self._capture_state()
        self._undo.push_future(entry.title, current)
        self._restore_state(entry.state)
        self._undo.current_id = entry.state_id     # point propre (16d1, D1)
        self._update_title()
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
        self._undo.current_id = entry.state_id     # point propre (16d1, D1)
        self._update_title()
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
