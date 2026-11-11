import math
import os
import re
import time
import threading
import wx
from pattern import Pattern, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH, ETYPE_CC, ETYPE_PGM, ETYPE_BEND, \
    bank_header
from song import Song
from rack import InstrumentType
from project_manager import ProjectManager
from midi.midi_export import export_pattern, export_song, SongPart
from audio.synth_engine import scale_midi_notes
from track_router import TrackRouter
from voice_manager import VoiceManager
from midi.midi_import import import_pattern
from audio import audio_export
from devices import audio_device as audio_devices
from .dialogs import AudioExportDialog, SelectionExportDialog, ExportTargetDialog, \
    ImportModeDialog
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
        """Projet ouvert au démarrage (Phase 8 étape 10f1, § 10a P5) :
        « Nouveau projet » → un nom libre (noname_NNN.gvp, rien à charger) ;
        « Ouvrir le dernier projet » → last_project s'il existe ; sinon,
        comme avant, project_01.gvp (ou l'ancien preset_01.json)."""
        cfg = getattr(self, "_cfg", None)
        if cfg is not None:
            if cfg.startup == cfg.STARTUP_NEW:
                return self._find_free_project_path()
            if cfg.last_project and os.path.isfile(cfg.last_project):
                return cfg.last_project
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
        self._exclusive = self._exclusive_saved = None   # Mute / Solo exclusif quitté (6d1)
        self._rewind_playback()            # lecture arrêtée, au début (Phase 8 étape 7d2)
        self._pattern_list    = [Pattern() for _ in range(99)]
        self._cur_pattern_idx = 0
        self._pattern_cache       = [None] * len(self._pattern_list)
        self._pattern_cache_dirty = set(range(len(self._pattern_list)))
        self._apply_kit_rule()                         # kit → canal 10 (3b1, K2)
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
        r   = self._router
        idx = self._cur_pattern_idx
        return self._midi_params(
            name        = self._pattern_list[idx]._name or f"Pat_{idx + 1:02d}",
            bpm         = self._player.bpm,
            track_slots = r._track_slots,
            channels    = r._track_channels,
            volumes     = r._track_volumes,
            pans        = r._track_pans,
            audible     = [r._track_is_audible(t) for t in range(len(r._track_slots))],  # 12a3 D7
            vm          = self._player.voice_manager,
            kb_notes    = r._kb_notes_play,
            preset_name = r.bank_preset_name,
            rack_mode   = self._player._pattern._rack_mode,      # 5f1, M18
            tape        = self._player._pattern._tape)

    def _song_midi_params(self, seg):
        """Arguments de build_pattern_midi pour un segment du song (Phase 8
        étape 2f1, docs/DESIGN.md § 2a E9) : d'après l'état figé de son
        pattern (slots, mix, canaux, voix des pads, gamme), comme
        MainWindow._on_song_advance le rétablit à la lecture. Le Rack et le
        kit sont ceux du projet. Une piste en Banque prend le nom de son
        slot : le preset joué dépend de la position."""
        p  = seg.pattern
        vm = VoiceManager(Pattern.NUM_PADS)
        vm.from_list(p._voices)
        return self._midi_params(
            name        = seg.label,
            bpm         = p._bpm,
            track_slots = p._track_slots,
            channels    = p._track_channels,
            volumes     = p._track_volumes,
            pans        = p._track_pans,
            audible     = [TrackRouter.track_audible(p._track_mutes, p._track_solos, t)
                           for t in range(len(p._track_slots))],
            vm          = vm,
            kb_notes    = scale_midi_notes(p._kb_scale, p._kb_root_midi,
                                           TrackRouter.KB_NUMPAD_NOTES),
            preset_name = lambda t: None,
            rack_mode   = p._rack_mode,                          # 5f1, M18
            tape        = p._tape)

    def _midi_params(self, *, name, bpm, track_slots, channels, volumes, pans,
                     audible, vm, kb_notes, preset_name, rack_mode=False, tape=None):
        """Arguments de build_pattern_midi d'après un état : slots, canaux,
        volumes, pans, pistes audibles, voix des pads (VoiceManager), notes
        de lecture de la gamme, nom du preset d'une piste en Banque. Mode
        Rack (Phase 8 étape 5f1, docs/DESIGN.md § 5a M18) : chaque piste est
        décrite par le slot que joue son canal à 1.1.1 (celui de son entête,
        sinon le sien), et garde son canal, kit compris."""
        if rack_mode:
            track_slots = [self._rack_slot_at_start(t, ch, tape)
                           for t, ch in enumerate(channels)]
        slots = [self._rack.get_slot(s) for s in track_slots]
        # Slot à canaux (banque, ou Synth SFZ depuis la Phase 8 étape 7d1,
        # § 7a2 Z12, § 7a3 Z25) : canal qui suit les Program Change, écrits
        # tels quels, grille au canal 10 en 36 + pad, notes de kit telles
        # quelles. Le Synth SFZ garde en tête le programme GM de son slot
        # (track_programs), qu'un Program Change de la piste remplace.
        is_bank = [s.type in (InstrumentType.BANK, InstrumentType.SFZ) for s in slots]
        # Piste sur un slot Kit : toujours au canal 10 (Phase 8 étape 2p2).
        # Les patterns créés sans réglage ont toutes leurs pistes sur le
        # slot 0 (souvent un kit) mais aux canaux 1, 2, 3… : la règle « kit
        # → 10 » n'est posée qu'à l'assignation par l'utilisateur. Sur un
        # autre canal, un lecteur GM jouerait la batterie avec un instrument
        # mélodique (le programme du kit n'y désigne pas un kit).
        # En mode Rack, le canal est le slot : il est gardé (M18).
        channels = [Pattern.KIT_CHANNEL if not rack_mode and t < len(slots)
                    and slots[t].type == InstrumentType.KIT
                    else ch for t, ch in enumerate(channels)]
        # Piste sur slot Banque (17f1, § 17e3 O8) : banque et programme
        # viennent des événements de _tape ; nom = preset de son canal.
        preset_names = [preset_name(t) if slots[t].type in (InstrumentType.BANK,
                                                            InstrumentType.SFZ) else None
                        for t in range(len(slots))]       # programme SFZ aussi (7f1)
        return dict(
            name             = name,
            bpm              = bpm,
            track_channels   = list(channels),
            track_is_synth   = [s.type == InstrumentType.SYNTH for s in slots],
            track_is_bank    = is_bank,
            track_is_kit     = [s.type == InstrumentType.KIT for s in slots],   # 5f1, M11
            rack_mode        = bool(rack_mode),
            track_names      = [preset_names[t] or s.name        # nom du slot (10h2 D12)
                                for t, s in enumerate(slots)],
            kit_pad_notes    = list(self._snd.pad_notes),        # 11a1 D1
            kit_gm_map       = dict(self._snd.gm_note_map),      # 11a1 D2
            synth_grid_notes = list(kb_notes),
            voice_durations  = [vm.get_duration_ms(i) for i in range(Pattern.NUM_PADS)],
            pad_volumes      = [vm.get_voice(i).volume for i in range(Pattern.NUM_PADS)],  # 12a1 D2
            track_programs   = [s.gm_program() for s in slots],  # None pour une banque (SFZ : son programme GM)
            track_transposes = [s.gm_transpose() for s in slots],      # 12a2 D4
            track_gain_db    = [s.gm_gain_db() for s in slots],        # 12a2 D5
            track_audible    = list(audible),
            pad_audible      = [vm.is_audible(i) for i in range(Pattern.NUM_PADS)],
            track_volumes    = list(volumes),
            track_pans       = list(pans),
        )

    def _rack_slot_at_start(self, t, channel, tape):
        """Slot que joue la piste t d'un pattern en mode Rack à 1.1.1 : celui
        du canal de son entête, sinon de son canal (M18)."""
        header = bank_header(tape[t]) if tape is not None and t < len(tape) else None
        return self._router.rack_slot_idx(header[0] if header else channel)

    def _midi_export_filename(self, ext=".mid"):
        """Nom de fichier proposé : Pat_NN[_nom].mid (ou ext), nom nettoyé."""
        idx  = self._cur_pattern_idx
        base = f"Pat_{idx + 1:02d}"
        name = re.sub(r"[^\w\-]+", "_", self._pattern_list[idx]._name).strip("_")
        return f"{base}_{name}{ext}" if name else f"{base}{ext}"

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
        status(msg + self._unmapped_msg(unmapped))

    def _unmapped_msg(self, unmapped):
        """Fin du compte rendu : sons de kit sans équivalent GM, écrits tels
        quels (11a1 D4) ; "" s'il n'y en a pas."""
        if not unmapped:
            return ""
        labels = self._snd.note_labels
        names  = ", ".join(f"{labels.get(n, f'Note {n}')} ({n})"
                           for n in sorted(unmapped))
        return f" — non converti en GM : {names}"

    #--------------------------------------------------------------------------
    # Export MIDI d'un song (Phase 8 étape 2f1, docs/DESIGN.md § 2a E15) :
    # depuis la fenêtre Songs ; un SongPart par pattern du song, d'après son
    # état figé.

    #--------------------------------------------------------------------------
    # Alt+Shift+E et Alt+Shift+W de la fenêtre principale et de l'éditeur
    # MIDI : pattern courant ou song courant (Phase 8 étape 4b1,
    # docs/DESIGN.md § 4a X1-X8)

    # Choix gardé pour la session, commun au MIDI et au WAV (X3, X6)
    _export_target = ExportTargetDialog.TARGET_PATTERN

    def _export_target_labels(self):
        """(pattern, song) : libellés du pattern courant et du song courant
        pour le choix (X4, X8)."""
        idx = self._cur_pattern_idx
        pat = self._pattern_list[idx]
        pattern = f"Pat_{idx + 1:02d}" + (f" {pat._name}" if pat._name else "")
        s_idx = self._cur_song_idx
        song = self._song_list[s_idx]
        n = len(song._sequence)
        count = "vide" if n == 0 else f"{n} pattern{'s' if n > 1 else ''}"
        name = f"Song_{s_idx + 1:02d}" + (f" {song._name}" if song._name else "")
        return pattern, f"{name}, {count}"

    def _choose_export_target(self, parent, title):
        """Ouvre le choix ; retourne TARGET_PATTERN, TARGET_SONG, ou None si
        Annuler (le choix gardé ne change pas, X7)."""
        pattern, song = self._export_target_labels()
        dlg = ExportTargetDialog(parent or self, title, pattern, song, self._export_target)
        ok = dlg.ShowModal() == wx.ID_OK
        target = dlg.get_target_idx()
        dlg.Destroy()
        if not ok:
            return None
        self._export_target = target
        return target

    def _export_midi_choose(self, parent=None, status=None):
        """Alt+Shift+E (fenêtre principale, éditeur MIDI) : choix, puis
        export MIDI du pattern courant ou du song courant (X5)."""
        status = status or self._show_status
        target = self._choose_export_target(parent, "Exporter en MIDI")
        if target is None:
            status("Export MIDI annulé")
        elif target == ExportTargetDialog.TARGET_SONG:
            self._export_song_midi(self._cur_song_idx, parent=parent, status=status)
        else:
            self._export_midi(parent=parent, status=status)

    def _export_audio_choose(self, parent=None, status=None):
        """Alt+Shift+W (fenêtre principale, éditeur MIDI) : choix, puis
        export audio du pattern courant ou du song courant (X5). Un export
        en cours est refusé avant la question (X7)."""
        status = status or self._show_status
        thread = self._audio_export_thread
        if thread is not None and thread.is_alive():
            status("Export audio déjà en cours")
            return
        target = self._choose_export_target(parent, "Exporter en WAV")
        if target is None:
            status("Export audio annulé")
        elif target == ExportTargetDialog.TARGET_SONG:
            self._export_song_audio(self._cur_song_idx, parent=parent, status=status)
        else:
            self._export_audio(parent=parent, status=status)

    def _song_export_filename(self, song_idx, ext=".mid"):
        """Nom de fichier proposé : Song_NN[_nom].mid (ou ext), nom nettoyé."""
        base = f"Song_{song_idx + 1:02d}"
        name = re.sub(r"[^\w\-]+", "_", self._song_list[song_idx]._name).strip("_")
        return f"{base}_{name}{ext}" if name else f"{base}{ext}"

    def _export_song_midi(self, song_idx, parent=None, status=None):
        """Alt+Shift+E dans la fenêtre Songs : exporte le song song_idx en
        .mid. parent : fenêtre du dialog ; status : où annoncer le résultat."""
        status = status or self._show_status
        song = self._song_list[song_idx]
        if not song._sequence:
            status("Song vide — ajoutez des patterns dans la fenêtre Songs")
            return
        try:
            os.makedirs(self._exports_dir, exist_ok=True)
        except OSError:
            pass   # le dialog s'ouvrira ailleurs ; l'écriture dira l'erreur
        dlg = wx.FileDialog(
            parent or self, "Exporter le song en MIDI…",
            defaultDir=self._exports_dir,
            defaultFile=self._song_export_filename(song_idx),
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
            segments = self._song_segments(song_idx)
            parts = [SongPart(seg.pattern, seg.label, self._song_midi_params(seg))
                     for seg in segments]
            export_song(path, parts, name=song._name or f"Song_{song_idx + 1:02d}",
                        unmapped=unmapped)
        except Exception as e:
            status(f"ERREUR export MIDI : {e}")
            return
        n = len(segments)
        msg = (f"Song {song_idx + 1:02d} exporté : {os.path.basename(path)} "
               f"({n} pattern{'s' if n > 1 else ''})")
        status(msg + self._unmapped_msg(unmapped))

    #--------------------------------------------------------------------------
    # Export audio WAV du pattern courant (Phase 8 étape 1h1, docs/DESIGN.md
    # § Phase 8 étape 1a, W8) : fichier, options, rendu dans un fil
    # (audio_export, sans wx), avancement et compte rendu au statut.

    # Choix du dialogue gardés pour la session : fin, format, normaliser,
    # mesure, niveau visé (W11, § 1h6)
    _audio_export_opts   = (0, 0, False, 2, audio_export.LEVEL_DEFAULT)
    # Sortie gardée pour la session : 0 mix, 1 pistes séparées, 2 mix + pistes
    # (Phase 8 étape 2l1, § 2a E14) ; à part, pour ne pas changer les options
    _audio_export_output = 0
    OUTPUT_MIX, OUTPUT_STEMS, OUTPUT_BOTH = 0, 1, 2
    _audio_export_dir    = None     # dernier dossier choisi (session, 1h2)
    _audio_export_thread = None
    _AUDIO_ENDS          = (audio_export.END_LOOP, audio_export.END_TAIL)
    _AUDIO_FORMAT_NAMES  = ("16 bits", "24 bits", "32 bits flottant")
    _AUDIO_MEASURE_UNITS = ("dBFS crête", "dBFS RMS", "LUFS-I")   # ordre de audio_export.MEASURES

    def _export_audio(self, parent=None, status=None):
        """Alt+Shift+W : exporte le pattern courant en .wav. parent : fenêtre
        des dialogs (éditeur MIDI) ; status : où annoncer avancement et
        résultat (appelé dans le fil de l'UI)."""
        status = status or self._show_status
        if self._audio_export_ready(status):
            self._audio_export_flow(parent, status, "Exporter le pattern en WAV…", "")

    def _audio_export_ready(self, status):
        """Faux si un export tourne déjà ; sinon met la lecture en pause
        (W8 : position gardée) et retourne vrai."""
        thread = self._audio_export_thread
        if thread is not None and thread.is_alive():
            status("Export audio déjà en cours")
            return False
        if self._player.playing:
            self._player.pause_pattern()
            self._router.stop_all_synth_voices()
        return True

    def _audio_export_flow(self, parent, status, title, suffix, job=None,
                           song_idx=None):
        """Parcours commun des exports audio : dialogue du fichier (nom
        Pat_NN[_nom]suffix.wav), puis paramètres (ordre standard, 1h2),
        puis rendu de job (None : le pattern courant, voir
        _start_audio_export). song_idx : export du song (Phase 8 étape
        2j1, § 2a E2, E15) : nom Song_NN[_nom].wav, fin proposée d'après la
        boucle du song (la fin choisie n'est pas gardée pour les patterns),
        segments pris après les dialogues."""
        # Dossier : le dernier choisi dans la session, sinon EXPORTS
        start = self._audio_export_dir or self._exports_dir
        if start == self._exports_dir:
            try:
                os.makedirs(self._exports_dir, exist_ok=True)
            except OSError:
                pass   # le dialog s'ouvrira ailleurs ; l'écriture dira l'erreur
        fdlg = wx.FileDialog(
            parent or self, title,
            defaultDir=start,
            defaultFile=(self._midi_export_filename(f"{suffix}.wav") if song_idx is None
                         else self._song_export_filename(song_idx, ".wav")),
            wildcard="Fichiers WAV (*.wav)|*.wav",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        result = fdlg.ShowModal()
        path   = fdlg.GetPath() if result == wx.ID_OK else ""
        fdlg.Destroy()
        if not path:
            status("Export audio annulé")
            return
        if not path.lower().endswith(".wav"):
            path += ".wav"
        self._audio_export_dir = os.path.dirname(path)
        init = self._audio_export_opts
        extra = {}
        if job is not None and job.get("unit"):
            # « Sélection + résonance », « Presse-papier + résonance » (2o2)
            extra = dict(unit=job["unit"].capitalize())
        if song_idx is not None:
            looping = self._song_list[song_idx]._looping
            init = (0 if looping else 1,) + tuple(init[1:])          # E2
            extra = dict(unit="Song")
        dlg = AudioExportDialog(parent or self, *init,
                                level_min=audio_export.LEVEL_MIN_DB,
                                level_max=audio_export.LEVEL_MAX_DB,
                                output_idx=self._audio_export_output, **extra)
        ok = dlg.ShowModal() == wx.ID_OK
        opts = (dlg.get_end_idx(), dlg.get_format_idx(), dlg.get_normalize(),
                dlg.get_measure_idx(), dlg.get_level_db())
        output = dlg.get_output_idx()
        dlg.Destroy()
        if not ok:
            status("Export audio annulé")
            return
        self._audio_export_output = output
        if song_idx is None:
            self._audio_export_opts = opts
        else:
            # Fin du song non gardée : les patterns gardent la leur
            self._audio_export_opts = (self._audio_export_opts[0],) + tuple(opts[1:])
            segments = self._song_segments(song_idx)
            n = len(segments)
            job = dict(segments=segments, label=f"Song {song_idx + 1:02d}", verb="exporté",
                       unit="song",
                       detail=f"{n} pattern{'s' if n > 1 else ''}")
        self._start_audio_export(path, opts, status, job, output)

    def _export_song_audio(self, song_idx, parent=None, status=None):
        """Alt+Shift+W dans la fenêtre Songs : exporte le song song_idx en
        .wav (Phase 8 étape 2j1, docs/DESIGN.md § 2a E2, E11, E15). parent :
        fenêtre des dialogs ; status : où annoncer avancement et résultat."""
        status = status or self._show_status
        if not self._song_list[song_idx]._sequence:
            status("Song vide — ajoutez des patterns dans la fenêtre Songs")
            return
        if self._audio_export_ready(status):
            self._audio_export_flow(parent, status, "Exporter le song en WAV…", "",
                                    song_idx=song_idx)

    # Source du dialogue de la sélection gardée pour la session (W21), et
    # son choix Pistes : sélectionnées ou toutes (Phase 8 étape 2n1, E16)
    _audio_sel_source = 0
    _audio_sel_tracks = 0

    def _export_audio_selection(self, parent=None, status=None, editor=False):
        """Alt+Shift+S : exporte en .wav la sélection (pistes sélectionnées,
        ou la piste courante, entre les limiteurs) ou le presse-papier de la
        fenêtre (editor : celui des notes de l'éditeur MIDI, sinon celui des
        pistes). Phase 8 étape 1h15, docs/DESIGN.md § 1h11, W13-W21."""
        status = status or self._show_status
        if not self._audio_export_ready(status):
            return
        player, te = self._player, self._track_editor
        pat = player._pattern
        dlg = SelectionExportDialog(parent or self, pat._num_bars, pat._num_beats,
                                    pat._num_steps, te._lim_left, te._lim_right,
                                    self._audio_sel_source, self._audio_sel_tracks)
        ok     = dlg.ShowModal() == wx.ID_OK
        source = dlg.get_source_idx()
        window = dlg.get_window()
        which  = dlg.get_tracks_idx()
        dlg.Destroy()
        if not ok:
            status("Export audio annulé")
            return
        self._audio_sel_source = source
        if source == SelectionExportDialog.SOURCE_SELECTION:
            self._audio_sel_tracks = which
            job = self._selection_job(
                window, all_tracks=(which == SelectionExportDialog.TRACKS_ALL))
            title, suffix = "Exporter la sélection en WAV…", "_selection"
        else:
            job = self._clipboard_job(editor)
            if job is None:
                status("Presse-papier vide")
                return
            title, suffix = "Exporter le presse-papier en WAV…", "_presse-papier"
        self._audio_export_flow(parent, status, title, suffix, job)

    def _selection_job(self, window, all_tracks=False):
        """Rendu de la sélection : copie du pattern courant, pistes de la
        sélection, fenêtre [G, D + 1) (W18). all_tracks : toutes les pistes
        entre les limiteurs (2n1, E16) ; les muettes ou hors solo restent
        silencieuses, comme à l'écoute."""
        player = self._player
        pat = player._pattern
        left, right = window
        tracks = None if all_tracks else \
            self._track_editor.get_effective_tracks(player._cur_track)
        pattern = Pattern()
        pattern.copy_from(pat)
        spb = max(1, pat._num_steps // pat._num_beats)
        total = pat._num_bars * pat._num_steps
        bbt = lambda step: self._track_editor.fmt_bbt(step, pat._num_steps, spb, total)
        if tracks is None:
            which = "toutes les pistes"
        else:
            names = ", ".join(str(t + 1) for t in tracks)
            which = f"piste {names}" if len(tracks) == 1 else f"pistes {names}"
        return dict(pattern=pattern, tempo_map=player.tempo_map(),
                    window=audio_export.selection_window(left, right),
                    tracks=None if tracks is None else set(tracks),
                    label=f"Sélection ({which} ; {bbt(left)} à {bbt(right)})",
                    verb="exportée", unit="sélection")

    def _clipboard_job(self, editor):
        """Rendu du presse-papier de la fenêtre (W13) : notes (éditeur MIDI)
        ou pistes. None si vide."""
        te, player = self._track_editor, self._player
        pat = player._pattern
        if editor:
            ecb = te._event_clipboard
            pattern = audio_export.event_clipboard_pattern(ecb.events, pat) if ecb else None
            num_tracks = len({e["track"] for e in ecb.events}) if pattern else 0
        else:
            cb = te._clipboard
            pattern = audio_export.clipboard_pattern(cb, pat) if cb else None
            num_tracks = cb.num_tracks if cb else 0
        if pattern is None:
            return None
        tracks = f"{num_tracks} piste" + ("s" if num_tracks > 1 else "")
        bars = f"{pattern._num_bars} mesure" + ("s" if pattern._num_bars > 1 else "")
        return dict(pattern=pattern, tempo_map=pattern.tempo_map(start_bpm=player.bpm),
                    window=None, tracks=None,
                    label=f"Presse-papier ({tracks}, {bars})", verb="exporté",
                    unit="presse-papier")

    def _start_audio_export(self, path, opts, status, job=None, output=0):
        """Lance le rendu de path dans un fil. job : pattern, tempo_map,
        window, tracks, label, verb ; None : le pattern courant, copié dans
        le fil de l'UI (les modifications pendant le rendu ne l'atteignent
        pas). output : OUTPUT_MIX, OUTPUT_STEMS ou OUTPUT_BOTH (2l1, E3, E4,
        E12-E14) : les stems sont un rendu par piste non vide, à la longueur
        du mix et avec son gain, dans le sous-dossier stem_folder(path) ;
        un stem silencieux (piste muette…) est omis."""
        end_idx, format_idx, normalize, measure_idx, level_db = opts
        player  = self._player
        if job is None:
            pattern = Pattern()
            pattern.copy_from(player._pattern)
            job = dict(pattern=pattern, tempo_map=player.tempo_map(), window=None,
                       tracks=None, label=f"Pattern {self._cur_pattern_idx + 1:02d}",
                       verb="exporté")
        params = dict(
            router=self._router,
            voice_manager=player.voice_manager, end=self._AUDIO_ENDS[end_idx],
            master_pan=player.pan, master_volume=player.volume,
        )
        if "segments" in job:                       # song (2j1)
            render = audio_export.render_song
            params["segments"] = job["segments"]
            sources = [seg.pattern for seg in job["segments"]]
        else:
            render = audio_export.render_pattern
            params.update(pattern=job["pattern"], tempo_map=job["tempo_map"],
                          window=job["window"], tracks=job["tracks"])
            sources = [job["pattern"]]
        stems = output in (self.OUTPUT_STEMS, self.OUTPUT_BOTH)
        stem_tracks = audio_export.nonempty_tracks(sources, job.get("tracks")) if stems else []
        stem_names  = self._stem_names(job, stem_tracks) if stems else {}
        subtype = audio_export.SUBTYPES[format_idx]
        label, verb = job["label"], job["verb"]
        unit, detail = job.get("unit", "pattern"), job.get("detail")

        def say(msg):                               # fil de l'UI ; fenêtre fermée : ignoré
            try:
                status(msg)
            except RuntimeError:
                pass

        units = 1 + len(stem_tracks)                # avancement : mix puis chaque piste

        def progress(k):
            return lambda f: wx.CallAfter(say, f"Export audio : {round((k + f) / units * 100)} %")

        def run():
            notes = []
            measure = audio_export.MEASURES[measure_idx]
            stems_written = None
            try:
                res = render(**params, progress=progress(0), status_cb=notes.append)
                if output != self.OUTPUT_STEMS:
                    gain_db, limit_db = audio_export.write_wav(
                        path, res, subtype, normalize, measure, level_db)
                if stems:
                    gain = audio_export.mix_gain(res, normalize, measure, level_db)
                    gain_db, limit_db = gain.gain_db, gain.limit_db
                    folder = audio_export.stem_folder(path)
                    os.makedirs(folder, exist_ok=True)
                    stems_written = 0
                    for k, t in enumerate(stem_tracks, start=1):
                        one = dict(params, tracks={t})
                        stem = render(**one, progress=progress(k), status_cb=lambda m: None)
                        if audio_export.is_silent(stem):
                            continue
                        audio_export.write_wav(
                            audio_export.stem_path(path, t, stem_names.get(t, "")),
                            audio_export.fit_length(stem, len(res.data)), subtype,
                            gain=gain)
                        stems_written += 1
            except Exception as e:
                wx.CallAfter(say, f"ERREUR export audio : {e}")
                return
            norm = (measure_idx, level_db) if normalize else None
            stems_info = None if stems_written is None else \
                (stems_written, os.path.basename(audio_export.stem_folder(path)),
                 output == self.OUTPUT_STEMS)
            wx.CallAfter(say, self._audio_export_report(
                label, path, res, end_idx, format_idx, gain_db, limit_db, notes, norm,
                verb, unit=unit, detail=detail, stems=stems_info))

        status("Export audio : 0 %")
        self._audio_export_thread = threading.Thread(target=run, daemon=True)
        self._audio_export_thread.start()

    def _stem_names(self, job, tracks):
        """{piste: nom} des stems : nom du slot de la piste, comme l'export
        MIDI ; pour un song, celui du premier pattern où elle n'est pas
        vide (2l1, E3)."""
        if "segments" not in job:
            names = self._midi_export_params()["track_names"]
            return {t: names[t] for t in tracks if t < len(names)}
        out = {}
        for t in tracks:
            for seg in job["segments"]:
                tape = seg.pattern._tape
                if t < len(tape) and tape[t]:
                    out[t] = self._song_midi_params(seg)["track_names"][t]
                    break
        return out

    def _audio_export_report(self, label, path, res, end_idx, format_idx,
                             gain_db, limit_db, notes, norm=None, verb="exporté",
                             unit="pattern", detail=None, stems=None):
        """Compte rendu de l'export audio (W8) : fichier, durée, fin, format,
        normalisation (norm = (mesure, niveau visé) ou None, W11), réduction
        du limiteur (W10), résonance coupée, messages du passage à blanc.
        unit : ce que suit la résonance (« song + résonance ») ; detail :
        précision après le fichier (« 3 patterns »), 2j1. stems : (nombre,
        dossier, sans le mix) des pistes séparées écrites, ou None (2l1)."""
        def num(x):
            return f"{x:.2f}".replace(".", ",")
        if end_idx == 0:
            fin = "boucle exacte"
        elif res.tail_samples == 0:
            fin = f"{unit} + résonance (aucune)"
        else:
            fin = f"{unit} + résonance ({num(res.tail_samples / res.samplerate)} s)"
        name = os.path.basename(path) + (f" ({detail})" if detail else "")
        if stems is not None:
            count, folder, only = stems
            pistes = f"{count} piste{'s' if count > 1 else ''} " \
                     f"séparée{'s' if count > 1 else ''} dans {folder}/"
            if only:
                name = pistes + (f" ({detail})" if detail else "")
            else:
                name += f" + {pistes}"
        parts = [f"{label} {verb} en WAV : {name}",
                 f"{num(res.seconds)} s, {fin}, {self._AUDIO_FORMAT_NAMES[format_idx]}"]
        if norm is not None:
            measure_idx, level_db = norm
            level = f"{'−' if level_db < 0 else ''}{abs(level_db)}"
            gain  = f"{'−' if gain_db < 0 else '+'}{num(abs(gain_db))}"
            parts.append(f"normalisé à {level} {self._AUDIO_MEASURE_UNITS[measure_idx]} : "
                         f"{gain} dB")
        if limit_db < 0:
            parts.append(f"limiteur : −{num(-limit_db)} dB au plus")
        if res.tail_cut:
            parts.append(f"résonance coupée à {num(audio_export.TAIL_MAX_S)} s")
        parts.extend(notes)
        return " — ".join(parts)

    #--------------------------------------------------------------------------
    # Import MIDI dans le pattern courant (Phase 7 étape 18d1, docs/DESIGN.md
    # § 18a1 I1-I3, I5, I11) : midi_import construit le pattern, l'UI choisit
    # le slot Banque, remplace le pattern courant et pose l'Undo.

    _import_dir = None          # dernier dossier d'import validé (session)
    # Dernier choix « Banque GM / Rack 16 canaux » de la session (5f1, M17)
    _import_mode = ImportModeDialog.MODE_BANK

    def _choose_import_mode(self, parent, file_name):
        """Choix de l'import (Phase 8 étape 5f1, docs/DESIGN.md § 5a M8) :
        MODE_BANK, MODE_RACK, ou None si Annuler (choix gardé inchangé)."""
        dlg = ImportModeDialog(parent or self, file_name, self._import_mode)
        ok = dlg.ShowModal() == wx.ID_OK
        mode = dlg.get_mode_idx()
        dlg.Destroy()
        if not ok:
            return None
        self._import_mode = mode
        return mode

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
        mode = self._choose_import_mode(parent, base)
        if mode is None:
            status("Import MIDI annulé")
            return
        rack_mode = mode == ImportModeDialog.MODE_RACK
        target = self._import_bank_slot()
        # Rack plein sans banque : refusé en Banque GM ; en mode Rack, chaque
        # canal a son slot, l'import se fait sans banque (5f1, M17)
        if target is None and not rack_mode:
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

        slot_idx, bank_slot, created = target if target is not None else (None, None, False)
        if created:
            name = os.path.splitext(os.path.basename(self._gm_soundfont))[0] \
                   or f"Banque {bank_slot + 1}"
            if self._rack.bank_files[bank_slot] is None:
                self._rack.set_bank_file(bank_slot, self._gm_soundfont)
            self._rack.set_slot(slot_idx, InstrumentType.BANK, name, {"bank_slot": bank_slot})
            self._update_slot_list()
        if slot_idx is not None:
            for t in range(report.num_tracks):
                imported._track_slots[t] = slot_idx
        imported._rack_mode = rack_mode                 # M17

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
        self._cur_slot = self._router.slot_for_track(cur_track)   # slot effectif (5f1)
        self._slot_choice.SetSelection(self._cur_slot)
        self._apply_auto_input_mode()                # Phase 8 étape 9b1 (K5)
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
        if rack_mode:
            msg += " ; mode Rack 16 canaux"
        details = report.details() + (self._rack_kit_messages(stored._tape) if rack_mode else [])
        if details:
            msg += " ; " + " ; ".join(details)
        status(msg)

    def _open_preferences(self, parent=None, status=None):
        """Alt+Shift+P (Phase 8 étape 10d1, docs/DESIGN.md § 10a P3) :
        dialogue des Préférences, depuis la fenêtre principale, l'éditeur MIDI
        ou la fenêtre Songs (parent et statut de la fenêtre appelante)."""
        from ui.dialogs_preferences import PreferencesDialog
        say = status or self._show_status
        dlg = PreferencesDialog(parent or self, self._cfg,
                                on_apply=lambda changes: self._apply_preferences(changes, say))
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()

    def _apply_preferences(self, changes, status=None):
        """Écrit les réglages changés dans preferences.json (P1). Les effets
        sur l'appli viennent en 10f1."""
        say = status or self._show_status
        try:
            self._cfg.save_preferences(changes)
        except OSError as e:
            say(f"ERREUR Préférences : {e}")
            return False
        later = self._apply_preferences_now(changes)
        msg = f"Préférences enregistrées ({len(changes)} réglage{'s' if len(changes) > 1 else ''})"
        if self.PREFS_AUDIO_OUT_KEYS & changes.keys():
            note = self._apply_audio_output()
            if note:
                msg += " ; " + note
        if later:
            msg += " ; au prochain lancement : " + ", ".join(later)
        say(msg)
        return True

    # Clés qui changent la sortie principale (Phase 8 étape 11b1, H2, H16)
    PREFS_AUDIO_OUT_KEYS = {"audio_hostapi", "audio_outputs", "audio_main_output"}

    def _apply_audio_output(self):
        """Flux du pilote rouvert sur la sortie principale des Préférences
        (11b1, H2). Retourne l'annonce : « sortie audio : <nom> », la sortie
        absente (défaut gardé), ou le refus de PortAudio (sortie précédente
        gardée)."""
        cfg = self._cfg
        driver = getattr(self, "_audio_driver", None)
        if driver is None or not hasattr(driver, "set_device"):
            return ""
        hostapi = cfg.audio_hostapi or audio_devices.default_hostapi()
        device, note = audio_devices.resolve_output(cfg.audio_main_output, hostapi)
        if device == driver.device:
            return note
        try:
            driver.set_device(device)
        except Exception as e:                      # PortAudioError, ValueError
            return f"sortie audio refusée ({e}) : sortie précédente gardée"
        return note or f"sortie audio : {cfg.audio_main_output or 'défaut'}"

    # Réglages pris au prochain lancement (P2) : moteurs créés au démarrage
    PREFS_AT_RESTART = {"fluidsynth": "moteur FluidSynth", "sfizz": "moteur sfizz",
                        "midi_bank_select": "sélection de banque"}
    # Clés qui changent un dossier de l'appli
    PREFS_DIR_KEYS = {"projects_dir", "user_banks_dir", "app_projects_dir", "app_banks_dir",
                      "kits_dir", "patches_dir", "samples_dir", "presets_dir",
                      "exports_dir", "soundfonts_dir", "gm_soundfont", "sfz_dir"}

    def _apply_preferences_now(self, changes):
        """Effet immédiat des réglages changés (Phase 8 étape 10f1, § 10a
        P2), lus dans self._cfg déjà à jour : Autoplay, dossiers (prochain
        parcours), limiteur, gains FluidSynth et sfizz, volume et pan d'un
        nouveau projet. Retourne les libellés des réglages pris au prochain
        lancement."""
        cfg = self._cfg
        if "autoplay" in changes:
            self._autoplay = cfg.autoplay
        if self.PREFS_DIR_KEYS & changes.keys():
            self._refresh_dirs_from_cfg()
        if "live_limiter" in changes:
            driver = getattr(self, "_audio_driver", None)
            if driver is not None and hasattr(driver, "set_limiter"):
                driver.set_limiter(cfg.live_limiter_enabled)
        if "fluidsynth_gain" in changes and getattr(self, "_bank_engine", None) is not None:
            self._bank_engine.set_gain(cfg.fluidsynth_gain)
        if "sfizz_gain" in changes and getattr(self, "_sfz_engine", None) is not None:
            self._sfz_engine.gain = cfg.sfizz_gain
        if {"master_volume", "master_pan"} & changes.keys():
            self._master_defaults = (cfg.master_volume, cfg.master_pan)
        return [label for key, label in self.PREFS_AT_RESTART.items() if key in changes]

    def _refresh_dirs_from_cfg(self):
        """Dossiers de l'appli relus dans self._cfg (Préférences, 10f1)."""
        cfg = self._cfg
        self._patches_dir    = cfg.patches_dir
        self._samples_dir    = cfg.samples_dir
        self._kits_dir       = cfg.kits_dir
        self._presets_dir    = cfg.presets_dir
        self._projects_dir   = cfg.projects_dir
        self._exports_dir    = cfg.exports_dir
        self._soundfonts_dir = cfg.soundfonts_dir
        self._gm_soundfont   = cfg.gm_soundfont
        self._sfz_dir        = cfg.sfz_dir
        router = getattr(self, "_router", None)
        if router is not None:
            router.sfz_dir = self._sfz_dir

    def _remember_project(self):
        """Retient le projet courant dans last_project (Phase 8 étape 10f1,
        § 10a P5) après Ctrl+O, Ctrl+S, Ctrl+Shift+S et l'Explorateur :
        seulement un fichier existant, et seulement s'il a changé ; une
        erreur d'écriture est ignorée (le projet, lui, est bien là)."""
        cfg = getattr(self, "_cfg", None)
        path = getattr(self, "_project_path", "")
        if cfg is None or not path or not os.path.isfile(path):
            return
        path = os.path.abspath(path)
        if cfg.last_project == path:
            return
        try:
            cfg.save_preferences({"last_project": path})
        except OSError:
            pass

    def _relocate_rack_files(self):
        """Soundfonts et sources SFZ absolues introuvables du projet chargé :
        cherchées dans les nouveaux dossiers (Phase 8 étape 10b1, docs/DESIGN.md
        § 10a P9, AppConfig.relocate) ; le projet garde le nouveau chemin à
        son prochain enregistrement."""
        cfg = getattr(self, "_cfg", None)
        if cfg is None:
            return
        rack = self._rack
        for i, path in enumerate(rack.bank_files):
            new = cfg.relocate(path) if path else path
            if new != path:
                rack.set_bank_file(i, new)
        for i in range(rack.NUM_SLOTS):
            slot = rack.get_slot(i)
            if slot.type != InstrumentType.SFZ:
                continue
            for key in ("sfz_source", "sfz_file"):
                value = slot.config.get(key)
                if isinstance(value, str) and os.path.isabs(value.strip()):
                    new = cfg.relocate(value.strip())
                    if new != value.strip():
                        slot.config = {**slot.config, key: new}   # pas en place

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
            self._remember_project()                   # dernier projet (10f1, P5)
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

    def _rewind_playback(self):
        """Lecture arrêtée et remise au début, pour le pattern comme pour le
        song (Phase 8 étape 7d2, remarque de l'essai de 7d1) : à Ctrl+N et à
        Ctrl+O. Sans cela, la position d'une pause (_resume_offset) survivait
        au changement de projet, et la lecture du nouveau repartait de
        l'ancienne position. Le mode Song en cours est quitté : sa séquence
        appartenait à l'ancien projet."""
        p = self._player
        p.stop_all()
        self._router.stop_all_synth_voices()
        p._song_mode     = False
        p._song_looping  = False
        p._song_sequence = []
        p._song_pos      = 0
        p.goto_start()

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
        self._remember_project()                       # dernier projet (10f1, P5)
        self._show_status(self._project_loaded_msg())

    def _apply_kit_rule(self):
        """Règle « kit → canal 10 » sur les 99 patterns, d'après le Rack
        courant (Phase 8 étape 3b1, docs/DESIGN.md § 3a K4, K5) : appelée au
        démarrage, à Ctrl+N et à Ctrl+O, avant que le pattern courant passe
        au routeur. Ni Undo ni « modifié » (K6) ; les trois appelants
        marquent déjà tout le cache de _capture_state comme à refaire.
        Retourne le nombre de pistes mises au canal 10."""
        is_kit_slot = lambda slot_idx: self._rack.get_slot(slot_idx).type == InstrumentType.KIT
        return sum(len(pat.apply_kit_channels(is_kit_slot)) for pat in self._pattern_list)

    def _project_loaded_msg(self):
        """Message de Ctrl+O : fichier, et pistes kit mises au canal 10 s'il
        y en a (3b1, K7)."""
        msg = f"Projet chargé : {os.path.basename(self._project_path)}"
        n = getattr(self, "_kit_rule_count", 0)
        if n:
            msg += f" — {n} piste{'s' if n > 1 else ''} kit mise{'s' if n > 1 else ''} au canal 10"
        return msg

    def _load_project(self):
        self._kit_rule_count = 0
        if not os.path.exists(self._project_path):
            # Démarrage sans projet : patterns neufs mis en règle, et le
            # routeur suit le pattern courant (3b1, K2, K5)
            self._apply_kit_rule()
            cur = self._pattern_list[self._cur_pattern_idx]
            for t, ch in enumerate(cur._track_channels):
                if t < len(self._router._track_channels) and \
                        self._router.get_track_channel(t) != ch:
                    self._router.set_track_channel(t, ch)
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
        self._exclusive = self._exclusive_saved = None   # Mute / Solo exclusif quitté (6d1)
        self._rewind_playback()                # lecture arrêtée, au début (Phase 8 étape 7d2)
        if "rack" in data:
            self._rack.from_dict(data["rack"])
            self._relocate_rack_files()
            self._update_slot_list()
        for i, p in enumerate(data.get("patterns", [])):
            if i >= len(self._pattern_list):
                break
            self._pattern_list[i].from_dict(p)
        # Pistes kit restées sur leur canal par défaut → canal 10, pour tous
        # les patterns (Phase 8 étape 3b1, K1, K2 ; remplace 10h7)
        self._kit_rule_count = self._apply_kit_rule()
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
        if new._rack_mode:                          # moteurs des canaux (5b1, M1)
            self._router.ensure_rack_synths(new._tape)
        loaded_kit_slots = set()
        # Mode Rack : le kit du pattern est déjà chargé (_apply_rack_kit, M6)
        for slot_idx in ([] if new._rack_mode else new._track_slots):
            if slot_idx not in loaded_kit_slots:
                slot = self._rack.get_slot(slot_idx)
                if slot.type == InstrumentType.KIT:
                    self._load_kit_slot(slot_idx)
                    loaded_kit_slots.add(slot_idx)
        cur_slot = self._router.slot_for_track(self._player._cur_track) \
                   if self._player._cur_track < len(new._track_slots) else 0
        self._cur_slot = cur_slot
        self._slot_choice.SetSelection(cur_slot)
        self._apply_auto_input_mode()               # Phase 8 étape 9b1 (K5, K7)
        slot = self._rack.get_slot(cur_slot)
        if slot.plays_notes:                        # synthé ou banque (17d1)
            self._router.load_slot_preview(cur_slot)
        elif slot.type == InstrumentType.KIT and cur_slot not in loaded_kit_slots \
                and not new._rack_mode:
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
            "tracks":     list(cb.tracks),     # pistes d'origine (Phase 8 étape 1h12)
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
            tracks     = d.get("tracks"),     # absent avant la Phase 8 étape 1h12
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
        # Slot joué rétabli s'il a changé (Undo de Ctrl+T, Phase 8 étape
        # 5d5) : préécoute ou kit rechargés ; sinon rien, pour ne pas
        # recharger un kit (et renommer ses pads) à chaque Undo
        if self._router.slot_for_track(self._player._cur_track) != self._cur_slot:
            self._follow_track_slot()
        # Libellés des slots rétablis avec le Rack (Phase 8 étape 7h1, essai) :
        # sans cela, un slot rempli par l'Explorateur (SFZ, Banque, Kit,
        # Patch) puis annulé gardait son nom dans la liste
        self._update_slot_list()
        self._apply_auto_input_mode()    # contenu du slot joué rétabli (9b1, K5)
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
                vol = max(0, min(self.MASTER_VOLUME_MAX, int(v)))
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

    MASTER_VOLUME_MAX = 200     # Phase 8 étape 8c1 (L4) : jusqu'à +6 dB

    @staticmethod
    def master_volume_text(vol):
        """Annonce du volume global (L8) : « 80 », et au-dessus de 100 le
        gain ajouté, « 150 (+3,5 dB) », pour savoir qu'on amplifie."""
        if vol <= 100:
            return str(vol)
        db = 20.0 * math.log10(vol / 100.0)
        return f"{vol} (+{db:.1f} dB)".replace(".", ",")

    def _set_master_volume_undo(self, vol):
        """Volume global avec Undo regroupé (D4) : rien si la valeur ne
        change pas. Retourne le volume."""
        vol = max(0, min(self.MASTER_VOLUME_MAX, int(vol)))
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
