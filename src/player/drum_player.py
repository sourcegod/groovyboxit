import threading

from metronome import Metronome
from pattern import Pattern
from tempo_map import normalize_changes, clamp_bpm
from voice_manager import VoiceManager
from quantize_manager import QuantizeManager
from loop_manager import LoopManager, LoopWindow
from player.dp_transport import TransportMixin
from player.dp_position  import PositionMixin
from player.dp_playback  import PlaybackLoopMixin
from player.dp_live      import LivePlayMixin
from player.dp_recording import RecordingMixin
from player.dp_erase     import EraseMixin


class DrumPlayer(TransportMixin, PositionMixin, PlaybackLoopMixin, LivePlayMixin,
                 RecordingMixin, EraseMixin):
    """Lecteur de patterns : l'état est ici (__init__), le code dans les mixins
    de src/player/ (Phase 7 étape 8, docs/DESIGN.md § 8a1)."""

    def __init__(self, sound_manager=None):
        self._play_thread = None
        self.stop_event = threading.Event()
        self._wakeup = threading.Event()   # réveil mid-mesure si clicking/playing change
        self.sound_man = sound_manager
        self.playing = False
        self._metro  = Metronome()
        self.bpm = 100
        self.volume = 100   # volume maître réel du pilote au démarrage (Phase 7 étape 15a2)
        self.pan = 0
        self._pattern      = Pattern()
        self._cur_track       = 0
        self._all_offsets     = [
            [[] for _ in range(self._pattern._num_pads)]
            for _ in range(self._pattern._num_tracks)
        ]
        self._on_track_play_cb = None  # callback(track_idx, pad_idx, vol, pan)
        self._on_play_start_cb = None  # callback(tape, pos) au début de la lecture et à chaque saut (17d1, 17f1)
        self._on_play_stop_cb  = None  # callback() à la fin de la lecture : arrêt, pause, fin (18d3)
        self.last_played_pad = None
        self.voice_manager = VoiceManager(self._pattern._num_pads)
        self._tmap     = None     # carte de tempo du pattern joué (19d1), en cache
        self._tmap_key = None
        self._on_stopped_move_cb = None   # callback() : position déplacée à l'arrêt (19d1, T7)
        self._resync_offset      = None   # position à garder après un changement de tempo (19d1)
        self._on_tempo_cb        = None   # callback(bpm) : changement de tempo franchi en lecture (19d3)
        self._update_step_duration()
        self.quant_idx = 7  # défaut: 1/16
        self._grid_idx = Pattern.GRID_DEFAULT_IDX   # grille globale (navigation + quantise)
        # État du dialog Quantiser (post-processing)
        self._quant_res_idx      = -1   # -2=grille courante, -1=aucune, 0..13=QUANT_LIST
        self._quant_force_idx    = 4    # 100 %
        self._quant_swing_idx    = 0    # 50 % (pas de swing)
        self._quant_window_idx   = 4    # 100 % (pas de filtrage par fenêtre)
        self._quant_starts       = True
        self._quant_durations    = False
        self._quant_direction_idx = 0   # 0=Proche, 1=Précédente, 2=Suivante
        # État du dialog Filtre d'événements (Ctrl+Shift+F, éditeur MIDI)
        self._event_filter_state = None   # dict de critères, ou None = jamais ouvert
        # Note Repeat (intégré dans _run_thread, synchronisé sur l'horloge de mesure)
        self._nr_quant_idx       = 7
        self._nr_get_pad         = None
        self._nr_play_cb         = None   # callback(pad_idx) optionnel pour le NR (ex. Synth)
        self._note_repeat_active = False
        self.recording            = False
        self.replace_recording    = False
        self._erase_active_pads   = set()   # pads MIDI tenus en mode Erase
        self.erasing                  = False
        self._erase_active_midi_notes = set()   # notes MIDI tenues en Erase (patch_tape)
        self._erase_was_recording = False
        self._erase_was_replace   = False
        self.count_in_bars        = 1     # 0, 1, 2, 4 ou 8 mesures
        self._measure_start       = None
        self._on_recorded_cb      = None  # callback(pad_idx, bar_idx, step_idx) pour l'UI
        self._on_replaced_cb      = None  # callback(pad_idx, bar_idx, step_idx) note effacée
        self._on_kit_tape_cb      = None  # callback(track_idx, midi_note, velocity, duration_ms) lecture kit_tape
        self._on_patch_tape_cb    = None  # callback(track_idx, midi_note, velocity, duration_ms) lecture patch_tape
        self._on_bend_tape_cb     = None  # callback(track_idx, bend_value) lecture automation bend
        self._on_cc_tape_cb              = None  # callback(track_idx, cc_num, value) lecture CC générique
        self._on_program_change_tape_cb  = None  # callback(track_idx, program) lecture Program Change
        self._pending_patch       = {}    # {midi_note: (track, TapeEvent.id, t_start)} — note_on en attente de note_off
        self._count_in            = 0     # mesures de count-in restantes avant Rec
        self._on_count_in_done_cb = None  # callback() quand le count-in est écoulé
        self._quant_in_recording  = True  # caler les hits enregistrés sur la grille de quantize
        self._resume_offset          = None  # float (pas) pour reprendre depuis une pause ; None = début
        self._count_in_resume_offset = None  # position de départ après count-in
        self._last_nav_time       = 0.0   # timestamp du dernier navigate_bar (fenêtre 100 ms)
        # Song mode
        self._song_mode          = False
        self._song_sequence      = []    # liste d'indices 0-based dans _pattern_list
        self._song_pos           = 0    # position courante dans _song_sequence
        self._pattern_list_ref   = None  # référence à la liste de patterns (set par main_window)
        self._on_song_advance_cb   = None  # callback(next_pat_idx) — -1 = song terminé
        self._on_song_cross_nav_cb = None  # callback(direction) — navigation inter-patterns
        self._song_looping         = False  # boucler le song entier
        # Loop window (plage de boucle définie sur le pattern)
        self._cur_lp_start    = 0   # lp_start actuel (mis à jour par _run_thread)
        self._cur_loop_steps  = 0   # longueur de la fenêtre (0 = pas de fenêtre)
        self._qm = QuantizeManager(self)
        self._lm = LoopManager()

    #--------------------------------------------------------------------------

    @property
    def _loop_remaining(self):
        return self._lm.remaining

    @_loop_remaining.setter
    def _loop_remaining(self, value):
        self._lm._remaining = value

    @property
    def float_offsets(self):
        """Offsets du track courant — alias lecture/écriture dans _all_offsets."""
        return self._all_offsets[self._cur_track]

    @float_offsets.setter
    def float_offsets(self, value):
        self._all_offsets[self._cur_track] = value

    #--------------------------------------------------------------------------

    @property
    def clicking(self):
        return self._metro.active

    @clicking.setter
    def clicking(self, value):
        self._metro.active = value

    @property
    def click_in_recording(self):
        return self._metro.click_in_recording

    @click_in_recording.setter
    def click_in_recording(self, value):
        self._metro.click_in_recording = value

    #--------------------------------------------------------------------------

    def apply_quant_row(self, quant_idx, row):
        self._qm.apply_quant_row(quant_idx, row)

    #--------------------------------------------------------------------------

    def double_pattern(self):
        """Double les mesures du pattern courant. Retourne False si impossible."""
        return self._qm.double_pattern()

    #--------------------------------------------------------------------------

    def halve_pattern(self):
        """Divise par deux les mesures du pattern. Retourne False si impossible."""
        return self._qm.halve_pattern()

    #--------------------------------------------------------------------------

    def apply_quant_to_pattern(self, quant_idx=None, **kwargs):
        self._qm.apply_quant_to_pattern(quant_idx, **kwargs)

    #--------------------------------------------------------------------------

    def _compute_offsets(self):
        self._qm.compute_offsets()

    #--------------------------------------------------------------------------

    def _update_step_duration(self):
        """Durée d'un pas en secondes au tempo de départ : un temps (noire)
        dure 60/bpm, quelle que soit la résolution _num_steps (Phase 7 étape
        10b1). Le minutage passe par tempo_map() depuis la Phase 7 étape
        19d1 ; step_duration reste la durée d'un pas au tempo de départ."""
        pat = self._pattern
        self.step_duration = 60.0 * pat._num_beats / (self.bpm * pat._num_steps)

    #--------------------------------------------------------------------------
    # Carte de tempo (Phase 7 étape 19d1, docs/DESIGN.md § 19a1 T4, T7)

    def tempo_map(self):
        """TempoMap du pattern joué, tempo de départ = self.bpm ; reconstruite
        seulement si le tempo, les changements ou la résolution ont changé."""
        pat = self._pattern
        key = (self.bpm, tuple(pat._tempo_changes), pat._num_steps, pat._num_beats)
        if key != self._tmap_key:
            self._tmap     = pat.tempo_map(start_bpm=self.bpm)
            self._tmap_key = key
        return self._tmap

    def tempo_at(self, pos=None):
        """Tempo en vigueur à la position pos (défaut : position courante)."""
        return self.tempo_map().bpm_at(self._current_offset() if pos is None else pos)

    def scale_tempos(self, ratio):
        """Multiplie le tempo de départ et tous les changements par ratio,
        chaque tempo borné à 1..600 (Phase 7 étape 19d3, § 19d2 R2). En
        lecture, la position musicale est gardée."""
        pat = self._pattern
        self._keep_position()
        start   = clamp_bpm(self.bpm * ratio)
        changes = [(at, clamp_bpm(bpm * ratio)) for at, bpm in pat._tempo_changes]
        self.bpm = pat._bpm = start
        pat._tempo_changes = normalize_changes(start, changes)
        self._update_step_duration()
        self._wakeup.set()

    def set_tempo_scaled(self, bpm, pos=None):
        """Champ BPM, Tap Tempo, ±5 (§ 19d2 R2) : le tempo en vigueur à pos
        (défaut : position courante) devient bpm, et tous les tempos changent
        dans la même proportion. Retourne le tempo atteint à pos, ou None
        hors de 1..600."""
        if not 1 <= bpm <= 600:
            return None
        self.scale_tempos(bpm / self.tempo_at(pos))
        return self.tempo_at(pos)

    # Liste des tempos (dialogue Tempo, liste des événements — Phase 7 étape
    # 19f1, § 19a1 T8, T9, § 19d2 R3). Indice -1 = tempo de départ (1.1.1),
    # 0.. = changements du pattern, dans l'ordre.

    def tempo_items(self):
        """[(indice, position, bpm)] : départ puis changements."""
        return [(-1, 0, self.bpm)] + [(i, at, bpm) for i, (at, bpm)
                                      in enumerate(self._pattern._tempo_changes)]

    def _set_changes(self, changes):
        self._keep_position()
        pat = self._pattern
        pat._tempo_changes = normalize_changes(self.bpm, changes)
        self._wakeup.set()

    def insert_tempo(self, pos, bpm):
        """Nouveau tempo à pos (> 0 ; à 1.1.1 : le tempo de départ). Un
        changement déjà à cette position est remplacé. Retourne True si la
        carte a changé."""
        before = (self.bpm, list(self._pattern._tempo_changes))
        if pos <= 0:
            self.set_bpm(clamp_bpm(bpm))
            self._set_changes(self._pattern._tempo_changes)
        else:
            self._set_changes(self._pattern._tempo_changes + [(pos, clamp_bpm(bpm))])
        return (self.bpm, self._pattern._tempo_changes) != before

    # Portée d'une modification (dialogue Tempo, § 19d2 R3, précisée à
    # l'essai de 19f1)
    SCOPE_RECENT    = "recent"      # « Changer le tempo le plus récent »
    SCOPE_SET_ALL   = "set_all"     # « Changer tous les tempos à cette valeur »
    SCOPE_SCALE_ALL = "scale_all"   # « Changer tous les tempos proportionnellement »

    def modify_tempo(self, idx, pos, bpm, scope=SCOPE_RECENT):
        """Modifie le tempo idx (-1 = départ) selon scope :
        SCOPE_RECENT    ce tempo seul, position comprise (pas pour le départ) ;
        SCOPE_SET_ALL   tous les tempos à bpm : le pattern n'a plus qu'un
                        tempo ;
        SCOPE_SCALE_ALL tous les tempos dans la même proportion que celui-ci.
        Avec les deux derniers, la position n'est pas touchée. Retourne True
        si la carte a changé."""
        changes = list(self._pattern._tempo_changes)
        before  = (self.bpm, list(changes))
        old_bpm = self.bpm if idx < 0 else changes[idx][1]
        if scope == self.SCOPE_SCALE_ALL:
            self.scale_tempos(clamp_bpm(bpm) / old_bpm)
        elif scope == self.SCOPE_SET_ALL:
            self.set_bpm(clamp_bpm(bpm))
            self._set_changes([])
        elif idx < 0:
            self.set_bpm(clamp_bpm(bpm))
            self._set_changes(changes)
        else:
            del changes[idx]
            self._set_changes(changes + [(pos, clamp_bpm(bpm))] if pos > 0 else changes)
            if pos <= 0:                     # déplacé à 1.1.1 : devient le départ
                self.set_bpm(clamp_bpm(bpm))
                self._set_changes(self._pattern._tempo_changes)
        return (self.bpm, self._pattern._tempo_changes) != before

    def delete_tempo(self, idx):
        """Supprime le changement idx (le départ ne se supprime pas).
        Retourne True si supprimé."""
        changes = list(self._pattern._tempo_changes)
        if not 0 <= idx < len(changes):
            return False
        del changes[idx]
        self._set_changes(changes)
        return True

    def set_tempo_at(self, bpm, pos=None):
        """Modifie le tempo en vigueur à la position pos (défaut : position
        courante) : le tempo de départ avant le premier changement, sinon le
        changement en vigueur (le « modifier le tempo en vigueur » de Sonar,
        T7). Retourne le BPM appliqué, ou None hors de 1..600."""
        if not 1 <= bpm <= 600:
            return None
        pos = self._current_offset() if pos is None else pos
        pat = self._pattern
        bpm = clamp_bpm(bpm)
        idx = None
        for i, (at, _old) in enumerate(pat._tempo_changes):
            if at <= pos:
                idx = i
        if idx is None:
            self.set_bpm(bpm)
            pat._tempo_changes = normalize_changes(bpm, pat._tempo_changes)
        else:
            self._keep_position()
            changes = list(pat._tempo_changes)
            changes[idx] = (changes[idx][0], bpm)
            pat._tempo_changes = normalize_changes(self.bpm, changes)
            self._wakeup.set()
        return bpm

    #--------------------------------------------------------------------------

    def load_pattern(self, pattern):
        self._pattern.load_pattern(pattern)
        self._update_step_duration()
        self._compute_offsets()

    #--------------------------------------------------------------------------
