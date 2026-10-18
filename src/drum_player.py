import time
import threading

from metronome import Metronome
from pattern import Pattern, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH, ETYPE_CC, ETYPE_PGM, ETYPE_BEND
from voice_manager import VoiceManager
from quantize_manager import QuantizeManager
from loop_manager import LoopManager, LoopWindow
from player.dp_transport import TransportMixin
from player.dp_position  import PositionMixin
from player.dp_recording import RecordingMixin
from player.dp_erase     import EraseMixin


class DrumPlayer(TransportMixin, PositionMixin, RecordingMixin, EraseMixin):
    NR_EVENT         = -100  # marqueur interne pour les événements Note Repeat dans la liste
    GRID_EVENT       = -6   # marqueur interne pour les événements grille (etype ETYPE_GRID de _tape)
    KIT_TAPE_EVENT   = -2   # marqueur interne pour les événements kit_tape (MIDI brut)
    PATCH_TAPE_EVENT = -3   # marqueur interne pour les événements patch_tape (MIDI brut)
    BEND_TAPE_EVENT  = -4   # marqueur interne pour les événements Pitch Bend (etype ETYPE_BEND de _tape)
    # MOD_TAPE_EVENT (-5) supprimé en Phase 7 étape 5h : CC#1 rejoué via
    # CC_TAPE_EVENT (_tape), qui délègue déjà à on_mod_tape (TrackRouter.on_cc_tape).
    CC_TAPE_EVENT    = -7   # marqueur interne pour les événements CC générique (etype ETYPE_CC de _tape)
    PGM_TAPE_EVENT   = -8   # marqueur interne pour les événements Program Change (etype ETYPE_PGM de _tape)

    def __init__(self, sound_manager=None):
        self._play_thread = None
        self.stop_event = threading.Event()
        self._wakeup = threading.Event()   # réveil mid-mesure si clicking/playing change
        self.sound_man = sound_manager
        self.playing = False
        self._metro  = Metronome()
        self.bpm = 100
        self.volume = 80
        self.pan = 0
        self._pattern      = Pattern()
        self._cur_track       = 0
        self._all_offsets     = [
            [[] for _ in range(self._pattern._num_pads)]
            for _ in range(self._pattern._num_tracks)
        ]
        self._on_track_play_cb = None  # callback(track_idx, pad_idx, vol, pan)
        self.last_played_pad = None
        self.voice_manager = VoiceManager(self._pattern._num_pads)
        self.step_duration = 60.0 / self.bpm / 4
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

    def _run_thread(self):
        if self._resume_offset is not None:
            measure_start = time.perf_counter() - self._resume_offset * self.step_duration
            self._resume_offset = None
        else:
            measure_start = time.perf_counter()

        while (self.playing or self.clicking or self._note_repeat_active) \
                and not self.stop_event.is_set():
            self._wakeup.clear()
            num_steps = self._pattern._num_steps
            # Pendant le count-in, on boucle par mesure unitaire (1 bar)
            # pour déclencher l'enregistrement exactement après 1 mesure musicale.
            if self._count_in > 0:
                lp_start    = 0
                lp_end      = num_steps - 1
                total_steps = num_steps
                loop_bars   = 1
                self._cur_lp_start   = 0
                self._cur_loop_steps = 0
            else:
                win = self._lm.compute_window(self._pattern)
                lp_start, lp_end       = win.lp_start, win.lp_end
                total_steps, loop_bars = win.total_steps, win.loop_bars
                self._cur_lp_start   = win.cur_lp_start
                self._cur_loop_steps = win.cur_loop_steps
            measure_secs = total_steps * self.step_duration
            now = time.perf_counter()

            # Avancer measure_start si la mesure précédente est terminée
            while measure_start + measure_secs <= now:
                measure_start += measure_secs
            self._measure_start = measure_start
            elapsed = now - measure_start

            # Construire les événements restants dans cette mesure
            # (on exclut ceux déjà passés avec une petite tolérance)
            events = []
            if self.playing:
                # Snapshot atomique sous verrou — immunise contre les modifications
                # concurrentes (record_*, erase_*) pendant l'itération.
                with self._pattern._lock:
                    tape_snap = [list(track_list) for track_list in self._pattern._tape]
                for t_idx, note_list in enumerate(tape_snap):
                    for ev in note_list:
                        float_off = ev.time
                        if not (lp_start <= float_off <= lp_end):
                            continue
                        t_sec = (float_off - lp_start) * self.step_duration
                        if t_sec > elapsed - 0.002:
                            if ev.etype == ETYPE_GRID:
                                events.append((t_sec, self.GRID_EVENT,
                                               (t_idx, ev.payload.get("pad"), ev.dur), ev.payload.get("vel")))
                            elif ev.etype == ETYPE_KIT:
                                events.append((t_sec, self.KIT_TAPE_EVENT,
                                               (t_idx, ev.payload.get("note"), ev.dur), ev.payload.get("vel")))
                            elif ev.etype == ETYPE_PATCH:
                                events.append((t_sec, self.PATCH_TAPE_EVENT,
                                               (t_idx, ev.payload.get("note"), ev.dur),
                                               ev.payload.get("vel")))
                            elif ev.etype == ETYPE_CC:
                                events.append((t_sec, self.CC_TAPE_EVENT,
                                               (t_idx, ev.payload.get("cc_num"), ev.payload.get("value")), 0))
                            elif ev.etype == ETYPE_PGM:
                                events.append((t_sec, self.PGM_TAPE_EVENT,
                                               (t_idx, ev.payload.get("program")), 0))
                            elif ev.etype == ETYPE_BEND:
                                events.append((t_sec, self.BEND_TAPE_EVENT,
                                               (t_idx, ev.payload.get("value")), 0))
            events.extend(self._metro.build_events(
                loop_bars, self._pattern._num_steps, self._pattern._num_beats,
                self.step_duration, elapsed))
            if self._note_repeat_active:
                denom    = Pattern.QUANT_STEPS[self._nr_quant_idx]
                nr_step  = 0.0
                interval = 16.0 / denom   # en pas (float)
                while nr_step < total_steps:
                    t_sec = nr_step * self.step_duration
                    if t_sec > elapsed - 0.002:
                        events.append((t_sec, self.NR_EVENT, 0, 100))
                    nr_step += interval
            events.sort()

            for t_sec, track_or_type, evt_data, velocity in events:
                if self.stop_event.is_set():
                    return
                if self._wakeup.is_set():
                    break   # état changé → reconstruire les événements
                target = measure_start + t_sec
                while not self.stop_event.is_set() and not self._wakeup.is_set():
                    remaining = target - time.perf_counter()
                    if remaining <= 0:
                        break
                    time.sleep(min(remaining, 0.005))
                if self.stop_event.is_set():
                    return
                if self._wakeup.is_set():
                    break
                if track_or_type == self.GRID_EVENT:
                    t_idx, pad_idx, dur_override = evt_data
                    if t_idx == self._cur_track \
                            and pad_idx in self._erase_active_pads:
                        self._clear_offset(pad_idx, t_sec / self.step_duration)
                    elif self.voice_manager.is_audible(pad_idx):
                        vol = min(1.0, self.voice_manager.get_volume_factor(pad_idx)
                                  * velocity / 100.0)
                        pan = self._mix_pan(self.voice_manager.get_pan(pad_idx))
                        # dur_override>0 (Numpad1/3, Phase 7 étape 1k) prime sur la
                        # durée de la voix, pour cette occurrence uniquement.
                        dur = dur_override if dur_override > 0 else self.voice_manager.get_duration_ms(pad_idx)
                        if self._on_track_play_cb:
                            self._on_track_play_cb(t_idx, pad_idx, vol, pan, dur)
                        else:
                            self.sound_man.play_sound(pad_idx, vol, pan)
                        if t_idx == self._cur_track and self.replace_recording:
                            self._clear_offset(pad_idx, t_sec / self.step_duration)
                elif track_or_type == self.KIT_TAPE_EVENT:
                    t_idx, midi_note, dur = evt_data
                    if self.erasing and t_idx == self._cur_track \
                            and midi_note in self._erase_active_midi_notes:
                        self._erase_tape_event(t_idx, midi_note, t_sec, ETYPE_KIT)
                    elif self._on_kit_tape_cb:
                        self._on_kit_tape_cb(t_idx, midi_note, velocity, dur)
                    else:
                        self.sound_man.play_note(midi_note, velocity / 127.0)
                elif track_or_type == self.PATCH_TAPE_EVENT:
                    # Plus de bend par note (Phase 7 étape 7f1) : un ETYPE_BEND
                    # au même temps est rejoué avant (BEND_TAPE_EVENT=-4 trié
                    # avant PATCH_TAPE_EVENT=-3 par events.sort()).
                    t_idx, midi_note, dur = evt_data
                    if self.erasing and t_idx == self._cur_track \
                            and midi_note in self._erase_active_midi_notes:
                        self._erase_tape_event(t_idx, midi_note, t_sec, ETYPE_PATCH)
                    elif self._on_patch_tape_cb:
                        self._on_patch_tape_cb(t_idx, midi_note, velocity, dur)
                elif track_or_type == self.BEND_TAPE_EVENT:
                    t_idx, bend_val = evt_data
                    if self._on_bend_tape_cb:
                        self._on_bend_tape_cb(t_idx, bend_val)
                elif track_or_type == self.CC_TAPE_EVENT:
                    t_idx, cc_num, value = evt_data
                    if self._on_cc_tape_cb:
                        self._on_cc_tape_cb(t_idx, cc_num, value)
                elif track_or_type == self.PGM_TAPE_EVENT:
                    t_idx, program = evt_data
                    if self._on_program_change_tape_cb:
                        self._on_program_change_tape_cb(t_idx, program)
                elif track_or_type == self.NR_EVENT:
                    pad = self._nr_get_pad() if self._nr_get_pad else self.last_played_pad
                    if pad is not None and self.voice_manager.is_audible(pad):
                        if self._nr_play_cb:
                            self._nr_play_cb(pad)
                        else:
                            self.sound_man.play_sound(
                                pad,
                                self.voice_manager.get_volume_factor(pad),
                                self._mix_pan(self.voice_manager.get_pan(pad)),
                            )
                        if self.recording:
                            self._record_nr_hit(pad, t_sec / self.step_duration)
                elif track_or_type == Metronome.METRO_EVENT:
                    self.sound_man.play_metronome(evt_data)
            else:
                # Pré-armer l'enregistrement sur le DERNIER bar de count-in
                # (avant l'attente) pour capturer les frappes anticipées sur
                # le premier temps : l'utilisateur réagit au dernier click
                # (~150-300 ms avant la fin de mesure) donc recording doit
                # être True AVANT que la mesure se termine.
                was_last_count_in  = (self._count_in == 1)
                next_measure_start = measure_start + measure_secs
                if was_last_count_in:
                    self.playing   = True
                    self.recording = True
                    offset_secs    = (self._count_in_resume_offset or 0.0) * self.step_duration
                    self._measure_start = next_measure_start - offset_secs
                    if self._on_count_in_done_cb:
                        self._on_count_in_done_cb()

                # Tous les événements joués → attendre la fin de mesure
                while not self.stop_event.is_set() and not self._wakeup.is_set():
                    remaining = next_measure_start - time.perf_counter()
                    if remaining <= 0:
                        break
                    time.sleep(min(remaining, 0.010))
                if self._count_in > 0 and not self._wakeup.is_set() and not self.stop_event.is_set():
                    self._count_in -= 1
                    if self._count_in == 0:
                        offset_secs = (self._count_in_resume_offset or 0.0) * self.step_duration
                        self._count_in_resume_offset = None
                        if was_last_count_in:
                            measure_start = next_measure_start - offset_secs
                        else:
                            self.playing   = True
                            self.recording = True
                            measure_start  = time.perf_counter() - offset_secs
                            if self._on_count_in_done_cb:
                                self._on_count_in_done_cb()
                elif not self._wakeup.is_set() and not self.stop_event.is_set():
                    # Décrémenter le compteur de boucle si actif (loop_count > 0)
                    if self._lm.remaining > 0 and self.playing:
                        if self._lm.on_measure_end():
                            self._resume_offset = float(lp_start)
                            self.playing = False
                            if self._song_mode:
                                self._song_mode = False
                                if self._on_song_advance_cb:
                                    self._on_song_advance_cb(-1)
                    elif not self._pattern._looping and self.playing:
                        if (self._song_mode and self._pattern_list_ref
                                and self._song_pos + 1 < len(self._song_sequence)):
                            self._song_pos += 1
                            next_idx = self._song_sequence[self._song_pos]
                            next_pat = self._pattern_list_ref[next_idx]
                            self._pattern.copy_from(next_pat)
                            self._pattern._looping = False
                            if next_pat._bpm != self.bpm:
                                self.bpm           = next_pat._bpm
                                self.step_duration = 60.0 / self.bpm / 4
                            self._compute_offsets()
                            measure_start = next_measure_start
                            if self._on_song_advance_cb:
                                self._on_song_advance_cb(next_idx)
                        else:
                            if self._song_mode and self._song_looping and self._pattern_list_ref:
                                # Boucle : repart du 1er pattern sans interruption
                                self._song_pos = 0
                                first_idx = self._song_sequence[0]
                                first_pat = self._pattern_list_ref[first_idx]
                                self._pattern.copy_from(first_pat)
                                self._pattern._looping = False
                                if first_pat._bpm != self.bpm:
                                    self.bpm           = first_pat._bpm
                                    self.step_duration = 60.0 / self.bpm / 4
                                self._compute_offsets()
                                measure_start = next_measure_start
                                if self._on_song_advance_cb:
                                    self._on_song_advance_cb(first_idx)
                            else:
                                # Pause à la fin (dernier tick) plutôt qu'arrêt complet :
                                # _resume_offset conserve la position → navigate_bar fonctionne.
                                total_steps = self._pattern._num_bars * self._pattern._num_steps
                                self._resume_offset = float(total_steps - 1)
                                self.playing = False
                                if self._song_mode:
                                    self._song_mode = False
                                    if self._on_song_advance_cb:
                                        self._on_song_advance_cb(-1)

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

    def load_pattern(self, pattern):
        self._pattern.load_pattern(pattern)
        self._compute_offsets()

    #--------------------------------------------------------------------------

    def play_sound(self, index, velocity=100):
        self.last_played_pad = index
        if self.voice_manager.is_audible(index):
            vol = min(1.0, self.voice_manager.get_volume_factor(index) * velocity / 100.0)
            self.sound_man.play_sound(
                index,
                vol,
                self._mix_pan(self.voice_manager.get_pan(index)),
            )

    #--------------------------------------------------------------------------

    def start_note_repeat(self, quant_idx, get_pad_func=None, play_cb=None):
        self._nr_quant_idx       = quant_idx
        self._nr_get_pad         = get_pad_func or (lambda: self.last_played_pad)
        self._nr_play_cb         = play_cb
        self._note_repeat_active = True
        if not (self._play_thread and self._play_thread.is_alive()):
            self.start_thread()
        else:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def stop_note_repeat(self):
        self._note_repeat_active = False
        self._nr_play_cb         = None
        if not (self.playing or self.clicking):
            self.stop_thread()
        else:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def update_nr_rate(self, quant_idx):
        """Change le taux NR à chaud sans modifier le pad en cours."""
        self._nr_quant_idx = quant_idx
        if self._note_repeat_active:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def set_volume(self, volume):
        if 0 <= volume <= 100:
            self.volume = volume
            self.sound_man.set_volume(volume)

    def set_pan(self, pan):
        self.pan = max(-100, min(100, int(pan)))

    def _mix_pan(self, pad_pan):
        return max(-100, min(100, self.pan + pad_pan))

    #--------------------------------------------------------------------------
