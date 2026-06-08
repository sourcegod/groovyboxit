import time
import threading
import os

from pattern import Pattern, TapeEvent
from voice_manager import VoiceManager

# Fichier de log pitch bend — activé si GROOVY_BEND_LOG=1
_BEND_LOG = os.environ.get("GROOVY_BEND_LOG") == "1"
_BEND_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "bend_log.txt")

def _bend_log(msg):
    if not _BEND_LOG:
        return
    ts = time.strftime("%H:%M:%S")
    with open(_BEND_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


class DrumPlayer:
    NR_EVENT         = -100  # marqueur interne pour les événements Note Repeat dans la liste
    KIT_TAPE_EVENT   = -2   # marqueur interne pour les événements kit_tape (MIDI brut)
    PATCH_TAPE_EVENT = -3   # marqueur interne pour les événements patch_tape (MIDI brut)
    BEND_TAPE_EVENT  = -4   # marqueur interne pour les événements d'automation pitch bend
    MOD_TAPE_EVENT   = -5   # marqueur interne pour les événements d'automation mod wheel

    def __init__(self, sound_manager=None):
        self._play_thread = None
        self.stop_event = threading.Event()
        self._wakeup = threading.Event()   # réveil mid-mesure si clicking/playing change
        self.sound_man = sound_manager
        self.playing = False
        self.clicking = False
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
        self.click_in_recording   = True
        self.count_in_bars        = 1     # 0, 1, 2, 4 ou 8 mesures
        self._click_before_rec    = False  # état du click avant d'entrer en Rec
        self._measure_start       = None
        self._on_recorded_cb      = None  # callback(pad_idx, bar_idx, step_idx) pour l'UI
        self._on_replaced_cb      = None  # callback(pad_idx, bar_idx, step_idx) note effacée
        self._on_kit_tape_cb      = None  # callback(track_idx, midi_note, velocity, duration_ms) lecture kit_tape
        self._on_patch_tape_cb    = None  # callback(track_idx, midi_note, velocity, duration_ms) lecture patch_tape
        self._on_bend_tape_cb     = None  # callback(track_idx, bend_value) lecture automation bend
        self._on_mod_tape_cb      = None  # callback(track_idx, mod_value) lecture automation mod wheel
        self._pending_patch       = {}    # {midi_note: (key, entry_idx, t_start)} — note_on en attente de note_off
        self._count_in            = 0     # mesures de count-in restantes avant Rec
        self._on_count_in_done_cb = None  # callback() quand le count-in est écoulé
        self._quant_in_recording  = True  # caler les hits enregistrés sur la grille de quantize
        self._resume_offset       = None  # float (pas) pour reprendre depuis une pause ; None = début
        self._last_nav_time       = 0.0   # timestamp du dernier navigate_bar (fenêtre 100 ms)
        # Song mode
        self._song_mode          = False
        self._song_sequence      = []    # liste d'indices 0-based dans _pattern_list
        self._song_pos           = 0    # position courante dans _song_sequence
        self._pattern_list_ref   = None  # référence à la liste de patterns (set par main_window)
        self._on_song_advance_cb = None  # callback(next_pat_idx) — -1 = song terminé

    #--------------------------------------------------------------------------

    @property
    def float_offsets(self):
        """Offsets du track courant — alias lecture/écriture dans _all_offsets."""
        return self._all_offsets[self._cur_track]

    @float_offsets.setter
    def float_offsets(self, value):
        self._all_offsets[self._cur_track] = value

    #--------------------------------------------------------------------------

    def start_thread(self):
        if self._play_thread and self._play_thread.is_alive():
            return
        self.stop_event.clear()
        self._play_thread = threading.Thread(target=self._run_thread, daemon=True)
        self._play_thread.start()

    #--------------------------------------------------------------------------

    def stop_thread(self):
        self.stop_event.set()
        self._wakeup.set()   # déverrouille immédiatement tout sleep en cours
        if self._play_thread:
            self._play_thread.join()
            self._play_thread = None

    #--------------------------------------------------------------------------

    def play_pattern(self):
        clicked = 0
        if self.clicking:
            self.stop_thread()
            self.stop_click()
            clicked = 1
        self.playing = True
        if clicked:
            self.play_click()
        self.start_thread()

    #--------------------------------------------------------------------------

    def stop_pattern(self):
        self.playing           = False
        self.clicking          = False
        self._count_in         = 0
        self.recording         = False
        self.replace_recording = False
        self._resume_offset    = None
        self._song_mode        = False
        if not self._note_repeat_active:
            self.stop_thread()
        else:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def play_song(self, sequence, pattern_list_ref):
        """Lance la lecture d'un song (liste ordonnée d'indices de patterns)."""
        if not sequence:
            return
        self._song_sequence    = list(sequence)
        self._pattern_list_ref = pattern_list_ref
        self._song_pos         = 0
        self._song_mode        = True
        self._pattern._looping = False
        self.play_pattern()

    #--------------------------------------------------------------------------

    def pause_pattern(self):
        """Arrête la lecture à la position courante (reprise via play_pattern)."""
        if not self.playing:
            return
        now = time.perf_counter()
        total_steps  = self._pattern._num_bars * self._pattern._num_steps
        measure_secs = total_steps * self.step_duration
        ref = self._measure_start if self._measure_start is not None else now
        self._resume_offset = ((now - ref) % measure_secs) / self.step_duration
        self.playing   = False
        self._count_in = 0
        if not self._note_repeat_active and not self.clicking:
            self.stop_thread()
        else:
            self._wakeup.set()

    #--------------------------------------------------------------------------

    def goto_start(self):
        """Positionne le playhead au début du pattern."""
        self._go_to_offset(None)

    #--------------------------------------------------------------------------

    def goto_end(self):
        """Positionne le playhead à la fin du pattern (dernier pas)."""
        total_steps = self._pattern._num_bars * self._pattern._num_steps
        self._go_to_offset(float(total_steps - 1))

    #--------------------------------------------------------------------------

    def _go_to_offset(self, offset):
        """Déplace le playhead à offset (pas flottants ; None = début).
        Stoppe et redémarre le thread si nécessaire pour garantir la prise en compte."""
        active = self.playing or self.clicking or self._note_repeat_active
        if active:
            self.stop_thread()
        self._resume_offset = offset
        if active:
            self.start_thread()

    #--------------------------------------------------------------------------

    def _current_offset(self):
        """Retourne la position courante du playhead en pas flottants."""
        if not (self.playing or self.clicking or self._note_repeat_active):
            return self._resume_offset or 0.0
        now          = time.perf_counter()
        total_steps  = self._pattern._num_bars * self._pattern._num_steps
        measure_secs = total_steps * self.step_duration
        ref = self._measure_start if self._measure_start is not None else now
        return ((now - ref) % measure_secs) / self.step_duration

    #--------------------------------------------------------------------------

    def position_str(self):
        """Retourne 'bar:beat:tick / Bar:Beat:Tick' (1-based) pour la barre de statut."""
        num_steps      = self._pattern._num_steps
        num_beats      = self._pattern._num_beats
        num_bars       = self._pattern._num_bars
        steps_per_beat = max(1, num_steps // num_beats)
        total_steps    = num_bars * num_steps

        def _fmt(step_idx):
            step_idx = max(0, min(step_idx, total_steps - 1))
            bar  = step_idx // num_steps
            rem  = step_idx % num_steps
            beat = rem // steps_per_beat
            tick = rem % steps_per_beat
            return f"{bar + 1}:{beat + 1}:{tick + 1}"

        cur = int(self._current_offset())
        last = total_steps - 1
        return f"{_fmt(cur)} / {_fmt(last)}"

    #--------------------------------------------------------------------------

    def move_by_ticks(self, ticks):
        """Déplace le playhead de ±ticks pas (clamp, sans wrap)."""
        total   = self._pattern._num_bars * self._pattern._num_steps
        new_off = max(0.0, min(float(total - 1), self._current_offset() + ticks))
        self._go_to_offset(new_off)

    def move_by_beats(self, beats):
        """Déplace le playhead de ±beats battements (clamp via move_by_ticks)."""
        steps_per_beat = self._pattern._num_steps // self._pattern._num_beats
        self.move_by_ticks(beats * steps_per_beat)

    def move_by_seconds(self, seconds):
        """Déplace le playhead de ±seconds secondes (clamp via move_by_ticks)."""
        self.move_by_ticks(seconds / self.step_duration)

    def move_by_bars(self, bars):
        """Déplace le playhead de ±bars mesures (wrapping cyclique, usage interne)."""
        total   = self._pattern._num_bars * self._pattern._num_steps
        new_off = (self._current_offset() + bars * self._pattern._num_steps) % total
        self._go_to_offset(new_off)

    def navigate_bar(self, direction):
        """Navigation par mesure style DAW (sans wrap).

        direction = -1 (PageUp) :
          - en cours de mesure → début de la mesure courante
          - au début de mesure → début de la mesure précédente
          - mesure 0           → reste à 0
        direction = +1 (PageDown) :
          - toujours           → début de la mesure suivante
          - dernière mesure    → dernier tick du pattern (total - 1)
        """
        num_steps = self._pattern._num_steps
        num_bars  = self._pattern._num_bars
        total     = num_bars * num_steps
        cur_off   = self._current_offset()
        cur_bar   = int(cur_off) // num_steps
        bar_start = cur_bar * num_steps
        now       = time.perf_counter()

        if direction < 0:
            # Fenêtre 100 ms : si navigate_bar a été appelé récemment, on
            # considère le playhead « au début de la mesure » même s'il a
            # légèrement avancé depuis.
            in_window = (now - self._last_nav_time < 0.1)
            if cur_off - bar_start > 0.01 and not in_window:
                target = float(bar_start)
            elif cur_bar > 0:
                target = float((cur_bar - 1) * num_steps)
            else:
                target = 0.0
        else:
            next_bar = cur_bar + 1
            if next_bar >= num_bars:
                target = float(total - 1)
            else:
                target = float(next_bar * num_steps)

        self._last_nav_time = now
        self._go_to_offset(target)

    #--------------------------------------------------------------------------

    def play_click(self):
        self.clicking = True
        if not (self._play_thread and self._play_thread.is_alive()):
            self.start_thread()
        else:
            self._wakeup.set()   # réveille le thread pour intégrer le click

    #--------------------------------------------------------------------------

    def stop_click(self):
        self.clicking = False
        if not (self.playing or self._note_repeat_active):
            self.stop_thread()
        else:
            self._wakeup.set()   # réveille le thread pour retirer le click

    #--------------------------------------------------------------------------

    def stop_all(self):
        self.playing             = False
        self.clicking            = False
        self._note_repeat_active = False
        self.recording           = False
        self.replace_recording   = False
        self.erasing             = False
        self._erase_active_pads.clear()
        self._erase_active_midi_notes.clear()
        self._count_in           = 0
        self.stop_thread()
        self.sound_man.stop_all()

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
            # Pendant le count-in, on boucle par mesure unitaire (1 bar)
            # pour déclencher l'enregistrement exactement après 1 mesure musicale.
            if self._count_in > 0:
                loop_bars = 1
            else:
                loop_bars = self._pattern._num_bars
            total_steps  = loop_bars * self._pattern._num_steps
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
                num_steps = self._pattern._num_steps
                for track_idx, track_offsets in enumerate(self._all_offsets):
                    for pad_idx, pad_off in enumerate(track_offsets):
                        for offset in pad_off:
                            t_sec = offset * self.step_duration
                            if t_sec > elapsed - 0.002:
                                step     = int(round(offset)) % total_steps
                                bar_idx  = step // num_steps
                                step_idx = step % num_steps
                                raw      = self._pattern._curpattern[track_idx][pad_idx][bar_idx][step_idx]
                                velocity = 100 if isinstance(raw, bool) and raw else int(raw)
                                events.append((t_sec, track_idx, pad_idx, velocity))
            if self.playing:
                num_steps = self._pattern._num_steps
                # Snapshot atomique sous verrou — immunise contre les modifications
                # concurrentes (record_*, erase_*) pendant l'itération.
                with self._pattern._lock:
                    tape_snap = {k: list(v) for k, v in self._pattern._tape.items()}
                for (t_idx, bar_idx, step_idx), note_list in tape_snap.items():
                    float_off = bar_idx * num_steps + step_idx
                    t_sec = float_off * self.step_duration
                    if t_sec > elapsed - 0.002:
                        for ev in note_list:
                            if ev.etype == "K":
                                events.append((t_sec, self.KIT_TAPE_EVENT,
                                               (t_idx, ev.note, ev.dur), ev.vel))
                            else:
                                events.append((t_sec, self.PATCH_TAPE_EVENT,
                                               (t_idx, ev.note, ev.dur, ev.bend), ev.vel))
                for t_idx, track_bends in enumerate(self._pattern._bend_tape):
                    for float_off, bend_val in list(track_bends):
                        t_sec = float_off * self.step_duration
                        if t_sec > elapsed - 0.002:
                            events.append((t_sec, self.BEND_TAPE_EVENT, (t_idx, bend_val), 0))
                for t_idx, track_mods in enumerate(self._pattern._mod_tape):
                    for float_off, mod_val in list(track_mods):
                        t_sec = float_off * self.step_duration
                        if t_sec > elapsed - 0.002:
                            events.append((t_sec, self.MOD_TAPE_EVENT, (t_idx, mod_val), 0))
            if self.clicking:
                steps_per_beat = self._pattern._num_steps // self._pattern._num_beats
                for bar_idx in range(loop_bars):
                    for beat in range(self._pattern._num_beats):
                        t_sec = (bar_idx * self._pattern._num_steps + beat * steps_per_beat) * self.step_duration
                        if t_sec > elapsed - 0.002:
                            events.append((t_sec, -1, beat, 0))
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
                if track_or_type >= 0:
                    track_idx = track_or_type
                    pad_idx   = evt_data
                    if track_idx == self._cur_track \
                            and pad_idx in self._erase_active_pads:
                        self._clear_offset(pad_idx, t_sec / self.step_duration)
                    elif self.voice_manager.is_audible(pad_idx):
                        vol = min(1.0, self.voice_manager.get_volume_factor(pad_idx)
                                  * velocity / 100.0)
                        pan = self._mix_pan(self.voice_manager.get_pan(pad_idx))
                        dur = self.voice_manager.get_duration_ms(pad_idx)
                        if self._on_track_play_cb:
                            self._on_track_play_cb(track_idx, pad_idx, vol, pan, dur)
                        else:
                            self.sound_man.play_sound(pad_idx, vol, pan)
                        if track_idx == self._cur_track and self.replace_recording:
                            self._clear_offset(pad_idx, t_sec / self.step_duration)
                elif track_or_type == self.KIT_TAPE_EVENT:
                    t_idx, midi_note, dur = evt_data
                    if self.erasing and t_idx == self._cur_track \
                            and midi_note in self._erase_active_midi_notes:
                        self._erase_tape_event(t_idx, midi_note, t_sec, "K")
                    elif self._on_kit_tape_cb:
                        self._on_kit_tape_cb(t_idx, midi_note, velocity, dur)
                    else:
                        self.sound_man.play_note(midi_note, velocity / 127.0)
                elif track_or_type == self.PATCH_TAPE_EVENT:
                    t_idx, midi_note, dur, bend = evt_data
                    if self.erasing and t_idx == self._cur_track \
                            and midi_note in self._erase_active_midi_notes:
                        self._erase_tape_event(t_idx, midi_note, t_sec, "P")
                    elif self._on_patch_tape_cb:
                        self._on_patch_tape_cb(t_idx, midi_note, velocity, dur, bend)
                elif track_or_type == self.BEND_TAPE_EVENT:
                    t_idx, bend_val = evt_data
                    if self._on_bend_tape_cb:
                        self._on_bend_tape_cb(t_idx, bend_val)
                elif track_or_type == self.MOD_TAPE_EVENT:
                    t_idx, mod_val = evt_data
                    if self._on_mod_tape_cb:
                        self._on_mod_tape_cb(t_idx, mod_val)
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
                else:
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
                    self.playing        = True
                    self.recording      = True
                    self._measure_start = next_measure_start
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
                        if was_last_count_in:
                            measure_start = next_measure_start
                        else:
                            self.playing   = True
                            self.recording = True
                            measure_start  = time.perf_counter()
                            if self._on_count_in_done_cb:
                                self._on_count_in_done_cb()
                elif not self._wakeup.is_set() and not self.stop_event.is_set():
                    if not self._pattern._looping and self.playing:
                        if (self._song_mode and self._pattern_list_ref
                                and self._song_pos + 1 < len(self._song_sequence)):
                            self._song_pos += 1
                            next_idx = self._song_sequence[self._song_pos]
                            next_pat = self._pattern_list_ref[next_idx]
                            self._pattern.load_pattern(next_pat._curpattern)
                            self._pattern._looping = False
                            with self._pattern._lock:
                                self._pattern._tape = dict(next_pat._tape)
                            self._pattern._bend_tape = [list(t) for t in next_pat._bend_tape]
                            self._pattern._mod_tape  = [list(t) for t in next_pat._mod_tape]
                            if next_pat._bpm != self.bpm:
                                self.bpm           = next_pat._bpm
                                self.step_duration = 60.0 / self.bpm / 4
                            self._compute_offsets()
                            measure_start = next_measure_start
                            if self._on_song_advance_cb:
                                self._on_song_advance_cb(next_idx)
                        else:
                            self.playing = False
                            if self._song_mode:
                                self._song_mode = False
                                if self._on_song_advance_cb:
                                    self._on_song_advance_cb(-1)

    #--------------------------------------------------------------------------

    def apply_quant_row(self, quant_idx, row):
        denom     = Pattern.QUANT_STEPS[quant_idx]
        num_steps = self._pattern._num_steps
        grid      = [i * num_steps / denom for i in range(denom)]
        pad       = self._pattern._curpattern[self._cur_track][row]
        for c in range(num_steps):
            pad[0][c] = False
        for fp in grid:
            c = min(num_steps - 1, round(fp))
            pad[0][c] = True
        self.float_offsets[row] = sorted(grid)

    #--------------------------------------------------------------------------

    def double_pattern(self):
        """Double les mesures du pattern courant. Retourne False si impossible."""
        half_steps = self._pattern._num_bars * self._pattern._num_steps
        if not self._pattern.double_bars():
            return False
        for track_offsets in self._all_offsets:
            for pad_idx in range(len(track_offsets)):
                orig    = track_offsets[pad_idx]
                shifted = [f + half_steps for f in orig]
                track_offsets[pad_idx] = sorted(orig + shifted)
        self._wakeup.set()
        return True

    #--------------------------------------------------------------------------

    def halve_pattern(self):
        """Divise par deux les mesures du pattern. Retourne False si impossible."""
        if self._pattern._num_bars < 2:
            return False
        half_steps = (self._pattern._num_bars // 2) * self._pattern._num_steps
        self._pattern.halve_bars()
        for track_offsets in self._all_offsets:
            for pad_idx in range(len(track_offsets)):
                track_offsets[pad_idx] = [
                    f for f in track_offsets[pad_idx] if f < half_steps
                ]
        self._wakeup.set()
        return True

    #--------------------------------------------------------------------------

    def apply_quant_to_pattern(self, quant_idx=None):
        if quant_idx is None:
            quant_idx = self.quant_idx
        if quant_idx < 0:
            return
        denom     = Pattern.QUANT_STEPS[quant_idx]
        num_steps = self._pattern._num_steps
        # grille de quantisation par mesure (positions flottantes)
        grid_per_bar = [i * num_steps / denom for i in range(denom)]
        # grille étendue sur toutes les mesures
        full_grid = [
            bar_idx * num_steps + gp
            for bar_idx in range(self._pattern._num_bars)
            for gp in grid_per_bar
        ]

        for pad_idx in range(self._pattern._num_pads):
            pad    = self._pattern._curpattern[self._cur_track][pad_idx]
            active = self.float_offsets[pad_idx]
            # effacer
            for bar in pad:
                bar[:] = [False] * len(bar)
            if not active:
                continue
            # snap chaque float vers le point de grille le plus proche
            snapped = set()
            for pos in active:
                nearest = min(full_grid, key=lambda p: abs(p - pos))
                snapped.add(nearest)
            # écrire dans le pattern
            for fp in snapped:
                bar_idx  = int(fp // num_steps)
                step_idx = round(fp % num_steps) % num_steps
                if bar_idx < self._pattern._num_bars:
                    pad[bar_idx][step_idx] = True
            self.float_offsets[pad_idx] = sorted(snapped)

    #--------------------------------------------------------------------------

    def _compute_offsets(self):
        num_tracks = self._pattern._num_tracks
        all_offsets = []
        for track_idx in range(num_tracks):
            track_offsets = []
            for pad in self._pattern._curpattern[track_idx]:
                offsets = []
                base = 0
                for bar in pad:
                    for step_idx, active in enumerate(bar):
                        if active:
                            offsets.append(float(base + step_idx))
                    base += len(bar)
                track_offsets.append(offsets)
            all_offsets.append(track_offsets)
        self._all_offsets = all_offsets   # assignation atomique
        if self.playing or self.clicking or self._note_repeat_active:
            self._wakeup.set()

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

    def record_pattern(self):
        self._click_before_rec = self.clicking
        self.recording = True
        if self.click_in_recording and not self.clicking:
            self.play_click()
        if not self.playing:
            self.play_pattern()

    #--------------------------------------------------------------------------

    def record_pattern_with_count_in(self, bars=None):
        bars = self.count_in_bars if bars is None else bars
        if bars == 0:
            self.record_pattern()
            return
        self._click_before_rec = self.clicking
        self.recording = False
        self.playing   = False
        self._count_in = bars
        self.clicking  = True
        self.stop_thread()
        self.start_thread()

    #--------------------------------------------------------------------------

    def stop_record(self):
        self.recording         = False
        self.replace_recording = False
        self._count_in         = 0
        if self.click_in_recording and not self._click_before_rec:
            self.stop_click()

    #--------------------------------------------------------------------------

    def start_replace_recording(self):
        self._click_before_rec = self.clicking
        self.replace_recording = True
        self.recording         = True
        if self.click_in_recording and not self.clicking:
            self.play_click()
        if not self.playing:
            self.play_pattern()

    #--------------------------------------------------------------------------

    def toggle_erase(self):
        """Bascule le mode Erase. Retourne True si Erase vient d'être activé."""
        if self.erasing:
            self.erasing = False
            self._erase_active_pads.clear()
            self._erase_active_midi_notes.clear()
            if self._erase_was_recording:
                self.recording         = True
                self.replace_recording = self._erase_was_replace
        else:
            self._erase_was_recording = self.recording
            self._erase_was_replace   = self.replace_recording
            self.erasing = True
            self._erase_active_midi_notes.clear()
            if self.recording:
                self.stop_record()
        return self.erasing

    #--------------------------------------------------------------------------

    def _erase_tape_event(self, track_idx, midi_note, t_sec, etype):
        """Efface un événement tape au passage (appelé par _run_thread en mode Erase)."""
        total_steps = self._pattern._num_bars * self._pattern._num_steps
        float_off   = t_sec / self.step_duration
        step        = round(float_off) % total_steps
        bar_idx     = step // self._pattern._num_steps
        step_idx    = step % self._pattern._num_steps
        key         = (track_idx, bar_idx, step_idx)
        with self._pattern._lock:
            events = self._pattern._tape.get(key)
            if events is None:
                return
            events[:] = [e for e in events
                         if not (e.note == midi_note and e.etype == etype)]
            if not events:
                self._pattern._tape.pop(key, None)

    def erase_hit(self, pad_idx):
        if not self.float_offsets[pad_idx]:
            return None
        now = time.perf_counter()
        total_steps  = self._pattern._num_bars * self._pattern._num_steps
        measure_secs = total_steps * self.step_duration
        ref = self._measure_start if self._measure_start is not None else now
        current = ((now - ref) % measure_secs) / self.step_duration

        def circ_dist(a):
            d = abs(a - current) % total_steps
            return min(d, total_steps - d)

        idx = min(range(len(self.float_offsets[pad_idx])),
                  key=lambda i: circ_dist(self.float_offsets[pad_idx][i]))
        removed = self.float_offsets[pad_idx].pop(idx)

        step     = min(round(removed), total_steps - 1)
        bar_idx  = step // self._pattern._num_steps
        step_idx = step % self._pattern._num_steps

        if not any(min(round(f), total_steps - 1) == step for f in self.float_offsets[pad_idx]):
            self._pattern._curpattern[self._cur_track][pad_idx][bar_idx][step_idx] = False

        return bar_idx, step_idx

    def erase_patch_tape_note(self, track_idx, midi_note):
        """Efface l'événement patch tape le plus proche du temps courant pour midi_note."""
        total_steps  = self._pattern._num_bars * self._pattern._num_steps

        if self._measure_start is not None:
            measure_secs = total_steps * self.step_duration
            now     = time.perf_counter()
            current = ((now - self._measure_start) % measure_secs) / self.step_duration
        else:
            current = 0.0   # hors lecture : efface le premier événement trouvé

        def circ_dist(step_f):
            d = abs(step_f - current) % total_steps
            return min(d, total_steps - d)

        best_dist = float('inf')
        best_key  = None
        best_i    = None

        for (t, b, s), events in self._pattern._tape.items():
            if t != track_idx:
                continue
            dist = circ_dist(b * self._pattern._num_steps + s)
            for i, ev in enumerate(events):
                if ev.etype == "P" and ev.note == midi_note and dist < best_dist:
                    best_dist = dist
                    best_key  = (t, b, s)
                    best_i    = i

        if best_key is None:
            return None

        with self._pattern._lock:
            events = self._pattern._tape.get(best_key)
            if events:
                events.pop(best_i)
                if not events:
                    del self._pattern._tape[best_key]

        return best_key[1], best_key[2]   # bar_idx, step_idx

    #--------------------------------------------------------------------------

    def _record_nr_hit(self, pad_idx, float_offset):
        total_steps  = self._pattern._num_bars * self._pattern._num_steps
        float_offset = float_offset % total_steps

        if round(float_offset) >= total_steps:
            float_offset = 0.0
        step     = round(float_offset) % total_steps
        bar_idx  = step // self._pattern._num_steps
        step_idx = step % self._pattern._num_steps
        self._pattern._curpattern[self._cur_track][pad_idx][bar_idx][step_idx] = 100

        if not any(abs(f - float_offset) < 0.5 for f in self.float_offsets[pad_idx]):
            self.float_offsets[pad_idx].append(float_offset)
            self.float_offsets[pad_idx].sort()

        if self._on_recorded_cb:
            self._on_recorded_cb(pad_idx, bar_idx, step_idx)

    #--------------------------------------------------------------------------

    def _clear_offset(self, pad_idx, float_offset):
        if not self.float_offsets[pad_idx]:
            return
        total_steps = self._pattern._num_bars * self._pattern._num_steps
        num_steps   = self._pattern._num_steps
        idx = min(range(len(self.float_offsets[pad_idx])),
                  key=lambda i: abs(self.float_offsets[pad_idx][i] - float_offset))
        removed  = self.float_offsets[pad_idx].pop(idx)
        step     = round(removed) % total_steps
        bar_idx  = step // num_steps
        step_idx = step % num_steps
        if not any(round(f) % total_steps == step for f in self.float_offsets[pad_idx]):
            self._pattern._curpattern[self._cur_track][pad_idx][bar_idx][step_idx] = 0
        if self._on_replaced_cb:
            self._on_replaced_cb(pad_idx, bar_idx, step_idx)

    #--------------------------------------------------------------------------

    def _compute_record_offset(self):
        """Calcule la position d'enregistrement courante dans le pattern.

        Retourne (float_offset, bar_idx, step_idx) en tenant compte de la
        quantisation si _quant_in_recording est actif.
        float_offset = 0.0 pour les frappes anticipées (count-in pré-armé).
        """
        now          = time.perf_counter()
        total_steps  = self._pattern._num_bars * self._pattern._num_steps
        measure_secs = total_steps * self.step_duration
        ref          = self._measure_start if self._measure_start is not None else now
        float_offset = 0.0 if now < ref else \
                       ((now - ref) % measure_secs) / self.step_duration
        if self._quant_in_recording and self.quant_idx >= 0:
            quant_size   = self._pattern._num_steps / Pattern.QUANT_STEPS[self.quant_idx]
            float_offset = round(float_offset / quant_size) * quant_size % total_steps
        if round(float_offset) >= total_steps:
            float_offset = 0.0
        step     = round(float_offset) % total_steps
        bar_idx  = step // self._pattern._num_steps
        step_idx = step % self._pattern._num_steps
        return float_offset, bar_idx, step_idx

    #--------------------------------------------------------------------------

    def record_hit(self, pad_idx, velocity=100):
        float_offset, bar_idx, step_idx = self._compute_record_offset()
        self._pattern._curpattern[self._cur_track][pad_idx][bar_idx][step_idx] = \
            max(1, min(127, int(velocity)))
        if not any(abs(f - float_offset) < 0.5 for f in self.float_offsets[pad_idx]):
            self.float_offsets[pad_idx].append(float_offset)
            self.float_offsets[pad_idx].sort()
        return bar_idx, step_idx

    #--------------------------------------------------------------------------

    def record_patch_note(self, midi_note, velocity=100, duration_ms=None, bend=0):
        """Enregistre une note MIDI brute dans _tape (etype="P").

        duration_ms=None → durée mesurée jusqu'au note_off via record_patch_note_off().
        duration_ms>=0   → durée fixe (numpad).
        bend             → valeur pitch bend au moment du note_on (-8192..+8191).
        """
        float_offset, bar_idx, step_idx = self._compute_record_offset()
        now = time.perf_counter()
        vel = max(1, min(127, int(velocity)))
        dur = 0 if duration_ms is None else max(0, int(duration_ms))
        key = (self._cur_track, bar_idx, step_idx)
        with self._pattern._lock:
            events = self._pattern._tape.setdefault(key, [])
            for i, ev in enumerate(events):
                if ev.etype == "P" and ev.note == midi_note:
                    events[i] = TapeEvent("P", midi_note, vel, dur, bend)
                    entry_idx = i
                    break
            else:
                events.append(TapeEvent("P", midi_note, vel, dur, bend))
                entry_idx = len(events) - 1
        if duration_ms is None:
            self._pending_patch[midi_note] = (key, entry_idx, now)
        else:
            self._pending_patch.pop(midi_note, None)
        _bend_log(f"REC note_on  note={midi_note} vel={vel} dur={dur} bend={bend} "
                  f"→ bar={bar_idx} step={step_idx} track={self._cur_track}")
        return bar_idx, step_idx

    def record_patch_note_off(self, midi_note):
        """Finalise la durée d'une note patch dans _tape après le note_off MIDI."""
        pending = self._pending_patch.pop(midi_note, None)
        if pending is None:
            return
        key, entry_idx, t_start = pending
        with self._pattern._lock:
            events = self._pattern._tape.get(key)
            if events is None or entry_idx >= len(events):
                return
            duration_ms = max(1, int((time.perf_counter() - t_start) * 1000))
            ev = events[entry_idx]
            events[entry_idx] = TapeEvent("P", ev.note, ev.vel, duration_ms, ev.bend)
        _bend_log(f"REC note_off note={midi_note} dur_finale={duration_ms}ms")

    #--------------------------------------------------------------------------

    def record_bend(self, bend_value):
        """Enregistre un point d'automation pitch bend dans _bend_tape de la piste courante."""
        now          = time.perf_counter()
        total_steps  = self._pattern._num_bars * self._pattern._num_steps
        measure_secs = total_steps * self.step_duration
        ref          = self._measure_start if self._measure_start is not None else now
        float_offset = 0.0 if now < ref else ((now - ref) % measure_secs) / self.step_duration
        track_bends  = self._pattern._bend_tape[self._cur_track]
        track_bends.append((float_offset, bend_value))

    #--------------------------------------------------------------------------

    def record_mod(self, mod_value):
        """Enregistre un point d'automation mod wheel dans _mod_tape de la piste courante."""
        now          = time.perf_counter()
        total_steps  = self._pattern._num_bars * self._pattern._num_steps
        measure_secs = total_steps * self.step_duration
        ref          = self._measure_start if self._measure_start is not None else now
        float_offset = 0.0 if now < ref else ((now - ref) % measure_secs) / self.step_duration
        track_mods   = self._pattern._mod_tape[self._cur_track]
        track_mods.append((float_offset, mod_value))

    #--------------------------------------------------------------------------

    def record_kit_note(self, midi_note, velocity=100):
        """Enregistre une note MIDI brute dans _tape (etype="K") sans passer par la grille."""
        _, bar_idx, step_idx = self._compute_record_offset()
        vel = max(1, min(127, int(velocity)))
        key = (self._cur_track, bar_idx, step_idx)
        with self._pattern._lock:
            events = self._pattern._tape.setdefault(key, [])
            if not any(ev.etype == "K" and ev.note == midi_note for ev in events):
                events.append(TapeEvent("K", midi_note, vel, 0, 0))
        return bar_idx, step_idx

    #--------------------------------------------------------------------------

    def set_bpm(self, bpm):
        if 5 <= bpm <= 600:
            self.bpm = bpm
            self.step_duration = 60.0 / self.bpm / 4
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
