import random
import threading

# Événement enregistré dans _tape (liste plate par piste, position = time).
# etype: ETYPE_GRID = grille (pad de la séquence), ETYPE_KIT = kit (note MIDI brute),
#        ETYPE_PATCH = patch synth (note + bend)
ETYPE_GRID  = "GRID"
ETYPE_KIT   = "KIT"
ETYPE_PATCH = "PATCH"


class TapeEvent:
    """Événement de _tape : id (identifiant unique, incrémenté à chaque
    création — jamais préservé lors d'une reconstruction représentant la
    même note modifiée, jamais sérialisé dans .gvp, comme Pattern._id),
    time (position, steps cumulés sur la piste), etype, dur, channel,
    payload (champs propres au type — {"pad":,"vel":} pour GRID,
    {"note":,"vel":} pour KIT, {"note":,"vel":,"bend":} pour PATCH).
    """

    __slots__ = ("id", "etype", "time", "dur", "channel", "payload")

    _counter = 0

    def __init__(self, etype, dur=0, channel=0, payload=None, time=None):
        TapeEvent._counter += 1
        self.id      = TapeEvent._counter
        self.etype   = etype
        self.time    = time
        self.dur     = dur
        self.channel = channel
        self.payload = dict(payload) if payload is not None else {}

    def __eq__(self, other):
        if not isinstance(other, TapeEvent):
            return NotImplemented
        return (self.etype == other.etype and self.dur == other.dur
                and self.channel == other.channel and self.payload == other.payload)

    def __hash__(self):
        return hash((self.etype, self.dur, self.channel, tuple(sorted(self.payload.items()))))

    def __repr__(self):
        return (f"TapeEvent(id={self.id!r}, {self.etype!r}, time={self.time!r}, dur={self.dur!r}, "
                f"channel={self.channel!r}, payload={self.payload!r})")


class Track:
    DRUM  = "drum"
    SYNTH = "synth"
    MIDI  = "midi"

    def __init__(self, sample_index=0):
        self._name            = ""
        self._sample_index    = sample_index  # 0..15
        self._instrument_type = Track.DRUM
        self._mute            = False
        self._solo            = False
        self._volume          = 100


class Pattern:
    VALID_NUM_STEPS = (16, 32, 64, 128)
    QUANT_LIST  = ["1/1", "1/2", "1/3", "1/4", "1/6", "1/8", "1/12", "1/16",
                   "1/24", "1/32", "1/48", "1/64", "1/96", "1/128"]
    QUANT_STEPS      = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128]
    QUANT_LABELS     = [f"Quant_{i + 1:02d} - {q}" for i, q in enumerate(QUANT_LIST)]
    QUANT_DIRECTIONS = ["Direction: Proche", "Direction: Précédente", "Direction: Suivante"]

    # Grille globale : (label, type, valeur)
    # "bars"  → valeur = nombre de mesures par division (grille grossière)
    # "snaps" → valeur = nombre de divisions par mesure (grille fine)
    GRID_RESOLUTIONS = [
        ("4 mes.",  "bars",  4),
        ("3 mes.",  "bars",  3),
        ("2 mes.",  "bars",  2),
        ("1 mes.",  "snaps", 1),
        ("1/2",     "snaps", 2),
        ("1/3",     "snaps", 3),
        ("1/4",     "snaps", 4),
        ("1/6",     "snaps", 6),
        ("1/8",     "snaps", 8),
        ("1/12",    "snaps", 12),
        ("1/16",    "snaps", 16),
        ("1/24",    "snaps", 24),
        ("1/32",    "snaps", 32),
        ("1/48",    "snaps", 48),
        ("1/64",    "snaps", 64),
        ("1/96",    "snaps", 96),
        ("1/128",   "snaps", 128),
    ]
    GRID_LABELS      = [r[0] for r in GRID_RESOLUTIONS]
    GRID_DEFAULT_IDX = 10  # 1/16

    @staticmethod
    def grid_step_size(grid_idx, num_steps):
        """Taille d'un pas de grille en steps (float).

        grid_idx  : index dans GRID_RESOLUTIONS
        num_steps : steps par mesure du pattern courant
        """
        _, kind, val = Pattern.GRID_RESOLUTIONS[grid_idx]
        if kind == "bars":
            return val * num_steps   # ex. 4 mes × 16 steps = 64 steps
        return num_steps / val       # ex. 16 / 16 = 1.0 step
    MAX_PATTERNS      = 99
    MAX_BARS          = 999
    MAX_TRACKS        = 16
    NUM_PADS          = 16
    _counter          = 0

    def __init__(self):
        Pattern._counter += 1
        self._id          = Pattern._counter
        self._name        = ""
        self._bpm         = 100
        self._num_beats   = 4     # numérateur de la signature rythmique
        self._num_steps   = 16    # pas par mesure : 16, 32, 64, 128
        self._num_bars    = 1     # nombre de mesures : 1..999
        self._num_tracks  = 8
        self._num_pads    = Pattern.NUM_PADS
        self._quant_steps = 16    # 1,2,3,4,6,8,12,16,24,32,48,64,96,128
        self._swing       = 0     # décalage groove 0..100 %
        self._denumerator = 4     # dénominateur de la signature rythmique
        self._looping     = True
        self._start_bar   = 0     # mesure de départ (0-indexed, 0 = mesure 1)
        self._loop_start  = None  # step de début de boucle (None = début du pattern)
        self._loop_end    = None  # step de fin de boucle   (None = fin du pattern)
        self._loop_count  = 0     # répétitions (0 = infini)

        self._tracks = [Track(i) for i in range(self._num_tracks)]

        # slot d'instrument assigné à chaque piste (indice dans le Rack)
        self._track_slots   = [0]     * self._num_tracks

        # état mixage par piste : mute, solo, volume (0..100), pan (-100..+100)
        self._track_mutes   = [False] * self._num_tracks
        self._track_solos   = [False] * self._num_tracks
        self._track_volumes = [100]   * self._num_tracks
        self._track_pans    = [0]     * self._num_tracks

        # état des voix par pad : name, volume, pan, mute, solo, duration_ms
        self._voices = [
            {"name": "", "volume": 100, "pan": 0, "mute": False, "solo": False, "duration_ms": 500}
            for _ in range(self._num_pads)
        ]

        # Capture MIDI brute unifiée : liste plate par piste, position = TapeEvent.time
        self._tape = [[] for _ in range(self._num_tracks)]
        # Verrou pour les accès concurrents _run_thread / thread UI
        self._lock = threading.RLock()

        # Automation pitch bend : liste par piste de (float_offset, bend_value)
        self._bend_tape  = [[] for _ in range(self._num_tracks)]
        # Automation mod wheel : liste par piste de (float_offset, mod_value)
        self._mod_tape   = [[] for _ in range(self._num_tracks)]

        # Gamme utilisée lors de l'enregistrement (lecture indépendante de l'UI)
        self._kb_scale     = "major"   # défaut "major" pour rétrocompat anciens patterns
        self._kb_root_midi = 48        # C3

    #--------------------------------------------------------------------------

    @staticmethod
    def _norm_vel(v):
        """Normalise une cellule : bool→int, clamp 0-127."""
        if isinstance(v, bool):
            return 100 if v else 0
        return max(0, min(127, int(v)))

    def _bar_step_to_time(self, bar, step):
        """Position (bar,step) → time (steps cumulés), convention _bend_tape/_mod_tape."""
        return bar * self._num_steps + step

    def _time_to_bar_step(self, time):
        """time (steps cumulés) → (bar, step), inverse de _bar_step_to_time."""
        bar, step = divmod(int(time), self._num_steps)
        return bar, step

    def _ensure_track_count(self, n):
        """Étend _tape (liste de listes) pour couvrir au moins n pistes."""
        while len(self._tape) < n:
            self._tape.append([])

    def _make_empty(self):
        return [
            [
                [[0] * self._num_steps for _ in range(self._num_bars)]
                for _ in range(self._num_pads)
            ]
            for _ in range(self._num_tracks)
        ]

    #--------------------------------------------------------------------------
    # API grille — façade au-dessus de _tape (etype ETYPE_GRID), remplace l'indexation
    # directe d'un grand tableau [track][pad][bar][step].
    #--------------------------------------------------------------------------

    def get_cell(self, track, pad, bar, step):
        """Vélocité (0..127) de la note grille (track,pad) à (bar,step). 0 si absente."""
        if track >= len(self._tape):
            return 0
        time = self._bar_step_to_time(bar, step)
        for ev in self._tape[track]:
            if ev.time == time and ev.etype == ETYPE_GRID and ev.payload.get("pad") == pad:
                return ev.payload.get("vel")
        return 0

    def set_cell(self, track, pad, bar, step, value, channel=0, dur=0):
        """Écrit (value>0) ou efface (value<=0) la note grille (track,pad) à (bar,step).

        dur : durée propre à cet événement (ms), 0 = pas d'override, la
        durée vient de voice_manager.get_duration_ms(pad) comme avant
        (Phase 7 étape 1k)."""
        vel = Pattern._norm_vel(value)
        time = self._bar_step_to_time(bar, step)
        with self._lock:
            self._ensure_track_count(track + 1)
            track_list = self._tape[track]
            track_list[:] = [ev for ev in track_list
                              if not (ev.time == time and ev.etype == ETYPE_GRID and ev.payload.get("pad") == pad)]
            if vel > 0:
                track_list.append(TapeEvent(ETYPE_GRID, dur=dur, channel=channel,
                                             payload={"pad": pad, "vel": vel}, time=time))

    def clear_grid_pad(self, track, pad):
        """Efface toutes les notes GRID d'un pad sur une piste (toutes mesures)."""
        with self._lock:
            if track >= len(self._tape):
                return
            track_list = self._tape[track]
            track_list[:] = [ev for ev in track_list
                              if not (ev.etype == ETYPE_GRID and ev.payload.get("pad") == pad)]

    def clear_grid_box(self, tracks, bars, steps):
        """Efface les notes GRID dans un rectangle track×bar×step.

        Ne filtre que etype==ETYPE_GRID : ne supprime jamais un TapeEvent KIT/PATCH
        coexistant à la même position dans _tape.
        """
        time_set = {self._bar_step_to_time(b, s) for b in bars for s in steps}
        with self._lock:
            for t in tracks:
                if t >= len(self._tape):
                    continue
                track_list = self._tape[t]
                track_list[:] = [ev for ev in track_list
                                  if not (ev.etype == ETYPE_GRID and ev.time in time_set)]

    def grid_row(self, track, pad, bar):
        """Snapshot list[int] (longueur _num_steps) — lecture seule."""
        return [self.get_cell(track, pad, bar, step) for step in range(self._num_steps)]

    def set_grid_row(self, track, pad, bar, values):
        """Remplace toute la ligne (track,pad,bar) par values (bulk write)."""
        for step, v in enumerate(values):
            self.set_cell(track, pad, bar, step, v)

    def iter_grid(self, track=None):
        """Itère (track, pad, bar, step, vel) sur toutes les notes GRID (piste filtrée si donnée)."""
        tracks = range(len(self._tape)) if track is None else (track,)
        for t in tracks:
            if t >= len(self._tape):
                continue
            for ev in self._tape[t]:
                if ev.etype == ETYPE_GRID:
                    bar, step = self._time_to_bar_step(ev.time)
                    yield (t, ev.payload.get("pad"), bar, step, ev.payload.get("vel"))

    def to_dense_grid(self):
        """Reconstruit [track][pad][bar][step] à la demande — pour to_dict()/compat uniquement."""
        grid = self._make_empty()
        for t, pad, b, s, vel in self.iter_grid():
            if (t < len(grid) and pad < len(grid[t])
                    and b < len(grid[t][pad]) and s < len(grid[t][pad][b])):
                grid[t][pad][b][s] = vel
        return grid

    def copy_from(self, other):
        """Clone entièrement l'état grille + tape + automation d'un autre Pattern.

        Remplace le duo load_pattern(other.to_dense_grid()) + copies manuelles de
        _tape/_bend_tape/_mod_tape historiquement dispersées dans l'UI.
        """
        self._num_tracks = other._num_tracks
        self._num_pads   = other._num_pads
        self._num_bars   = other._num_bars
        self._num_steps  = other._num_steps
        with self._lock:
            self._tape = [list(track_list) for track_list in other._tape]
        self._bend_tape = [list(t) for t in other._bend_tape]
        self._mod_tape  = [list(t) for t in other._mod_tape]

    #--------------------------------------------------------------------------

    def new_pattern(self, num_bars=1, num_steps=16):
        self._num_bars  = num_bars
        self._num_steps = num_steps
        self._tape       = [[] for _ in range(self._num_tracks)]
        self._bend_tape  = [[] for _ in range(self._num_tracks)]
        self._mod_tape   = [[] for _ in range(self._num_tracks)]

    #--------------------------------------------------------------------------

    def load_pattern(self, pattern):
        """Remplace les notes de grille (etype ETYPE_GRID) depuis une matrice dense.

        Laisse les événements KIT/PATCH intacts (comportement historique : la
        grille et la tape MIDI enregistrée sont deux apports indépendants).
        """
        self._num_tracks = len(pattern)
        self._num_pads   = len(pattern[0])       if pattern                        else Pattern.NUM_PADS
        self._num_bars   = len(pattern[0][0])    if pattern and pattern[0]         else 1
        self._num_steps  = len(pattern[0][0][0]) if pattern and pattern[0] and pattern[0][0] else 16
        nv = Pattern._norm_vel
        with self._lock:
            self._ensure_track_count(self._num_tracks)
            for t in range(self._num_tracks):
                track_list = self._tape[t]
                track_list[:] = [ev for ev in track_list if ev.etype != ETYPE_GRID]
            for t, track in enumerate(pattern):
                for pad, pad_data in enumerate(track):
                    for bar, bar_data in enumerate(pad_data):
                        for step, v in enumerate(bar_data):
                            vel = nv(v)
                            if vel > 0:
                                time = self._bar_step_to_time(bar, step)
                                self._tape[t].append(
                                    TapeEvent(ETYPE_GRID, payload={"pad": pad, "vel": vel}, time=time)
                                )

    #--------------------------------------------------------------------------

    def reset_pattern(self):
        self._tape      = [[] for _ in range(self._num_tracks)]
        self._bend_tape = [[] for _ in range(self._num_tracks)]
        self._mod_tape  = [[] for _ in range(self._num_tracks)]

    def clear_track(self, track_idx):
        """Efface tous les pas de la piste track_idx (grille + tape MIDI)."""
        with self._lock:
            if track_idx < len(self._tape):
                self._tape[track_idx] = []
        if track_idx < len(self._bend_tape):
            self._bend_tape[track_idx] = []
        if track_idx < len(self._mod_tape):
            self._mod_tape[track_idx] = []

    #--------------------------------------------------------------------------

    def gen_pattern(self, track=0):
        self.reset_pattern()
        num_pads = random.randint(1, 4)
        pads     = random.sample(range(self._num_pads), num_pads)
        for pad in pads:
            num_steps = random.randint(1, 8)
            steps     = random.sample(range(self._num_steps), num_steps)
            for step in steps:
                self.set_cell(track, pad, 0, step, 100)

    #--------------------------------------------------------------------------

    def double_bars(self):
        """Duplique les mesures existantes (pattern deux fois plus long)."""
        if self._num_bars * 2 > self.MAX_BARS:
            return False
        half_steps = self._num_bars * self._num_steps
        self._tape = [
            track_list + [
                TapeEvent(ev.etype, dur=ev.dur, channel=ev.channel,
                          payload=ev.payload, time=ev.time + half_steps)
                for ev in track_list
            ]
            for track_list in self._tape
        ]
        self._bend_tape = [
            track_bends + [(off + half_steps, b) for off, b in track_bends]
            for track_bends in self._bend_tape
        ]
        self._mod_tape = [
            track_mods + [(off + half_steps, m) for off, m in track_mods]
            for track_mods in self._mod_tape
        ]
        self._num_bars *= 2
        return True

    #--------------------------------------------------------------------------

    def halve_bars(self):
        """Garde la première moitié des mesures (pattern deux fois plus court)."""
        if self._num_bars < 2:
            return False
        half       = self._num_bars // 2
        half_steps = half * self._num_steps
        self._tape = [
            [ev for ev in track_list if ev.time < half_steps]
            for track_list in self._tape
        ]
        self._bend_tape = [
            [(off, b) for off, b in track_bends if off < half_steps]
            for track_bends in self._bend_tape
        ]
        self._mod_tape = [
            [(off, m) for off, m in track_mods if off < half_steps]
            for track_mods in self._mod_tape
        ]
        self._num_bars = half
        return True

    #--------------------------------------------------------------------------

    def build_pattern_01(self):
        self.reset_pattern()
        for step in (0, 4, 8, 12):
            self.set_cell(0, 0, 0, step, 100)
        for step in (2, 6, 10):
            self.set_cell(0, 4, 0, step, 100)
        for step in (*range(1, 4), *range(5, 8), *range(9, 12), *range(13, 16)):
            self.set_cell(0, 5, 0, step, 100)
        self.set_cell(0, 7,  0, 15, 100)
        self.set_cell(0, 8,  0, 14, 100)
        self.set_cell(0, 9,  0, 13, 100)
        self.set_cell(0, 10, 0, 0,  100)

    #--------------------------------------------------------------------------

    def is_empty(self):
        return not any(self._tape)

    #--------------------------------------------------------------------------

    def resize(self, num_bars, num_steps):
        """Étend ou tronque le pattern sans effacer les données existantes."""
        old_steps = self._num_steps
        old_bars  = self._num_bars

        # ev.time encode bar*old_steps+step : décoder avec l'ancienne résolution
        # avant de changer _num_steps, puis ré-encoder avec la nouvelle — sinon
        # un changement de num_steps réinterpréterait mal les positions stockées.
        new_tape = []
        for track_list in self._tape:
            new_list = []
            for ev in track_list:
                bar, step = divmod(int(ev.time), old_steps)
                if bar < num_bars and step < num_steps:
                    new_time = bar * num_steps + step
                    new_list.append(TapeEvent(ev.etype, dur=ev.dur, channel=ev.channel,
                                               payload=ev.payload, time=new_time))
            new_tape.append(new_list)
        self._tape = new_tape

        if num_steps != old_steps:
            self._num_steps = num_steps

        if num_bars != old_bars:
            self._num_bars = num_bars

        total_steps = self._num_bars * self._num_steps
        self._bend_tape = [
            [(off, b) for off, b in track_bends if off < total_steps]
            for track_bends in self._bend_tape
        ]
        self._mod_tape = [
            [(off, m) for off, m in track_mods if off < total_steps]
            for track_mods in self._mod_tape
        ]

    #--------------------------------------------------------------------------

    def to_dict(self):
        """Sérialise le pattern en dict JSON-compatible.

        Format 'tape_v2' (Phase 7 étape 1e) : une seule structure unifiée
        GRID/KIT/PATCH, une liste par piste d'événements
        [time, etype, dur, channel, payload]. Remplace les anciennes clés
        'curpattern'/'kit_tape'/'patch_tape' — plus de double écriture ;
        from_dict() sait encore lire l'ancien format pour les presets existants.
        """
        return {
            "name":          self._name,
            "bpm":           self._bpm,
            "num_bars":      self._num_bars,
            "num_steps":     self._num_steps,
            "num_tracks":    self._num_tracks,
            "num_pads":      self._num_pads,
            "start_bar":     self._start_bar,
            "looping":       self._looping,
            "loop_start":    self._loop_start,
            "loop_end":      self._loop_end,
            "loop_count":    self._loop_count,
            "track_slots":   self._track_slots,
            "track_mutes":   self._track_mutes,
            "track_solos":   self._track_solos,
            "track_volumes": self._track_volumes,
            "track_pans":    self._track_pans,
            "voices":        self._voices,
            "kb_scale":      self._kb_scale,
            "kb_root_midi":  self._kb_root_midi,
            "tape_v2": [
                [
                    [ev.time, ev.etype, ev.dur, ev.channel, ev.payload]
                    for ev in track_list
                ]
                for track_list in self._tape
            ],
            "bend_tape": [list(t) for t in self._bend_tape],
            "mod_tape":  [list(t) for t in self._mod_tape],
        }

    #--------------------------------------------------------------------------

    def from_dict(self, d):
        """Restaure le pattern depuis un dict (issu de to_dict / JSON).

        Si 'tape_v2' est présent (format Phase 7 étape 1e), c'est la seule
        source de vérité pour _tape (GRID+KIT+PATCH unifiés). Sinon, lit
        l'ancien format ('curpattern' + 'kit_tape' + 'patch_tape' séparées,
        rétrocompatibilité des presets existants).
        """
        self._name       = d.get("name", "")
        self._bpm        = d.get("bpm", 100)
        self._num_bars   = d.get("num_bars", 1)
        self._num_steps  = d.get("num_steps", 16)
        self._start_bar  = d.get("start_bar", 0)
        self._looping    = d.get("looping", True)
        self._loop_start = d.get("loop_start", None)
        self._loop_end   = d.get("loop_end", None)
        self._loop_count = d.get("loop_count", 0)
        if "tape_v2" in d:
            self._num_tracks = d.get("num_tracks", len(d["tape_v2"]))
            self._num_pads   = d.get("num_pads", Pattern.NUM_PADS)
            self._tape = []
            self._ensure_track_count(self._num_tracks)
            for t, track_events in enumerate(d["tape_v2"]):
                self._ensure_track_count(t + 1)
                for rec in track_events:
                    ev_time, etype, dur, channel, payload = rec
                    self._tape[t].append(
                        TapeEvent(etype, dur=dur, channel=channel, payload=payload, time=ev_time)
                    )
        else:
            self._tape = []
            self.load_pattern(d["curpattern"])   # peuple les entrées ETYPE_GRID
            for rec in d.get("kit_tape", []):
                t, b, s, note, vel = rec[:5]
                dur = rec[5] if len(rec) > 5 else 0
                self._ensure_track_count(t + 1)
                self._tape[t].append(TapeEvent(ETYPE_KIT, dur=dur,
                                                payload={"note": note, "vel": vel},
                                                time=self._bar_step_to_time(b, s)))
            for rec in d.get("patch_tape", []):
                t, b, s, note, vel = rec[:5]
                dur  = rec[5] if len(rec) > 5 else 0
                bend = rec[6] if len(rec) > 6 else 0
                self._ensure_track_count(t + 1)
                self._tape[t].append(TapeEvent(ETYPE_PATCH, dur=dur,
                                                payload={"note": note, "vel": vel, "bend": bend},
                                                time=self._bar_step_to_time(b, s)))
        if "track_slots"   in d: self._track_slots   = d["track_slots"]
        if "track_mutes"   in d: self._track_mutes   = d["track_mutes"]
        if "track_solos"   in d: self._track_solos   = d["track_solos"]
        if "track_volumes" in d: self._track_volumes = d["track_volumes"]
        if "track_pans"    in d: self._track_pans    = d["track_pans"]
        if "voices"        in d: self._voices        = d["voices"]
        self._kb_scale     = d.get("kb_scale",     "major")
        self._kb_root_midi = d.get("kb_root_midi", 48)
        raw_bends = d.get("bend_tape", [])
        self._bend_tape = [
            [tuple(p) for p in track_bends]
            for track_bends in raw_bends
        ]
        while len(self._bend_tape) < self._num_tracks:
            self._bend_tape.append([])
        raw_mods = d.get("mod_tape", [])
        self._mod_tape = [
            [tuple(p) for p in track_mods]
            for track_mods in raw_mods
        ]
        while len(self._mod_tape) < self._num_tracks:
            self._mod_tape.append([])
