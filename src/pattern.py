import random
import threading
from collections import namedtuple

# Événement enregistré dans _tape.
# etype: "G" = grille (pad de la séquence), "K" = kit (note MIDI brute), "P" = patch synth (note + bend)
TapeEvent = namedtuple("TapeEvent", ["etype", "note", "vel", "dur", "bend"])


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

        # Capture MIDI brute unifiée : {(track, bar, step): [TapeEvent]}
        self._tape = {}
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

    def _make_empty(self):
        return [
            [
                [[0] * self._num_steps for _ in range(self._num_bars)]
                for _ in range(self._num_pads)
            ]
            for _ in range(self._num_tracks)
        ]

    #--------------------------------------------------------------------------
    # API grille — façade au-dessus de _tape (etype "G"), remplace l'indexation
    # directe d'un grand tableau [track][pad][bar][step].
    #--------------------------------------------------------------------------

    def get_cell(self, track, pad, bar, step):
        """Vélocité (0..127) de la note grille (track,pad) à (bar,step). 0 si absente."""
        for ev in self._tape.get((track, bar, step), ()):
            if ev.etype == "G" and ev.note == pad:
                return ev.vel
        return 0

    def set_cell(self, track, pad, bar, step, value):
        """Écrit (value>0) ou efface (value<=0) la note grille (track,pad) à (bar,step)."""
        vel = Pattern._norm_vel(value)
        key = (track, bar, step)
        with self._lock:
            evs = self._tape.get(key)
            if evs is not None:
                evs[:] = [ev for ev in evs if not (ev.etype == "G" and ev.note == pad)]
                if not evs:
                    del self._tape[key]
            if vel > 0:
                self._tape.setdefault(key, []).append(TapeEvent("G", pad, vel, 0, 0))

    def clear_grid_pad(self, track, pad):
        """Efface toutes les notes G d'un pad sur une piste (toutes mesures)."""
        with self._lock:
            for key in list(self._tape.keys()):
                if key[0] != track:
                    continue
                evs = self._tape[key]
                evs[:] = [ev for ev in evs if not (ev.etype == "G" and ev.note == pad)]
                if not evs:
                    del self._tape[key]

    def clear_grid_box(self, tracks, bars, steps):
        """Efface les notes G dans un rectangle track×bar×step.

        Ne filtre que etype=="G" : ne supprime jamais un TapeEvent K/P
        coexistant à la même clé _tape.
        """
        track_set = set(tracks)
        bar_set   = set(bars)
        step_set  = set(steps)
        with self._lock:
            for key in list(self._tape.keys()):
                t, b, s = key
                if t not in track_set or b not in bar_set or s not in step_set:
                    continue
                evs = self._tape[key]
                evs[:] = [ev for ev in evs if ev.etype != "G"]
                if not evs:
                    del self._tape[key]

    def grid_row(self, track, pad, bar):
        """Snapshot list[int] (longueur _num_steps) — lecture seule."""
        return [self.get_cell(track, pad, bar, step) for step in range(self._num_steps)]

    def set_grid_row(self, track, pad, bar, values):
        """Remplace toute la ligne (track,pad,bar) par values (bulk write)."""
        for step, v in enumerate(values):
            self.set_cell(track, pad, bar, step, v)

    def iter_grid(self, track=None):
        """Itère (track, pad, bar, step, vel) sur toutes les notes G (piste filtrée si donnée)."""
        for (t, b, s), evs in self._tape.items():
            if track is not None and t != track:
                continue
            for ev in evs:
                if ev.etype == "G":
                    yield (t, ev.note, b, s, ev.vel)

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
            self._tape = {k: list(v) for k, v in other._tape.items()}
        self._bend_tape = [list(t) for t in other._bend_tape]
        self._mod_tape  = [list(t) for t in other._mod_tape]

    #--------------------------------------------------------------------------

    def new_pattern(self, num_bars=1, num_steps=16):
        self._num_bars  = num_bars
        self._num_steps = num_steps
        self._tape       = {}
        self._bend_tape  = [[] for _ in range(self._num_tracks)]
        self._mod_tape   = [[] for _ in range(self._num_tracks)]

    #--------------------------------------------------------------------------

    def load_pattern(self, pattern):
        """Remplace les notes de grille (etype "G") depuis une matrice dense.

        Laisse les événements K/P intacts (comportement historique : la
        grille et la tape MIDI enregistrée sont deux apports indépendants).
        """
        self._num_tracks = len(pattern)
        self._num_pads   = len(pattern[0])       if pattern                        else Pattern.NUM_PADS
        self._num_bars   = len(pattern[0][0])    if pattern and pattern[0]         else 1
        self._num_steps  = len(pattern[0][0][0]) if pattern and pattern[0] and pattern[0][0] else 16
        nv = Pattern._norm_vel
        with self._lock:
            for key in list(self._tape.keys()):
                evs = self._tape[key]
                evs[:] = [ev for ev in evs if ev.etype != "G"]
                if not evs:
                    del self._tape[key]
            for t, track in enumerate(pattern):
                for pad, pad_data in enumerate(track):
                    for bar, bar_data in enumerate(pad_data):
                        for step, v in enumerate(bar_data):
                            vel = nv(v)
                            if vel > 0:
                                self._tape.setdefault((t, bar, step), []).append(
                                    TapeEvent("G", pad, vel, 0, 0)
                                )

    #--------------------------------------------------------------------------

    def reset_pattern(self):
        self._tape      = {}
        self._bend_tape = [[] for _ in range(self._num_tracks)]
        self._mod_tape  = [[] for _ in range(self._num_tracks)]

    def clear_track(self, track_idx):
        """Efface tous les pas de la piste track_idx (grille + tape MIDI)."""
        with self._lock:
            self._tape = {k: v for k, v in self._tape.items() if k[0] != track_idx}
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
        half       = self._num_bars
        half_steps = half * self._num_steps
        new_tape = dict(self._tape)
        for (t, b, s), events in self._tape.items():
            new_tape[(t, b + half, s)] = events[:]
        self._tape = new_tape
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
        self._tape = {
            (t, b, s): events
            for (t, b, s), events in self._tape.items()
            if b < half
        }
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
        return not self._tape

    #--------------------------------------------------------------------------

    def resize(self, num_bars, num_steps):
        """Étend ou tronque le pattern sans effacer les données existantes."""
        old_steps = self._num_steps
        old_bars  = self._num_bars

        if num_steps != old_steps:
            self._num_steps = num_steps

        if num_bars != old_bars:
            self._num_bars = num_bars

        self._tape = {
            (t, b, s): events
            for (t, b, s), events in self._tape.items()
            if b < self._num_bars and s < self._num_steps
        }
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

        Le format JSON conserve les clés 'kit_tape' et 'patch_tape' séparées
        pour la rétrocompatibilité des presets existants.
        """
        return {
            "name":          self._name,
            "bpm":           self._bpm,
            "num_bars":      self._num_bars,
            "num_steps":     self._num_steps,
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
            "curpattern":    self.to_dense_grid(),
            "voices":        self._voices,
            "kb_scale":      self._kb_scale,
            "kb_root_midi":  self._kb_root_midi,
            "kit_tape": [
                [t, b, s, ev.note, ev.vel, ev.dur]
                for (t, b, s), events in self._tape.items()
                for ev in events if ev.etype == "K"
            ],
            "patch_tape": [
                [t, b, s, ev.note, ev.vel, ev.dur, ev.bend]
                for (t, b, s), events in self._tape.items()
                for ev in events if ev.etype == "P"
            ],
            "bend_tape": [list(t) for t in self._bend_tape],
            "mod_tape":  [list(t) for t in self._mod_tape],
        }

    #--------------------------------------------------------------------------

    def from_dict(self, d):
        """Restaure le pattern depuis un dict (issu de to_dict / JSON).

        Lit les clés 'kit_tape' et 'patch_tape' séparées (format historique)
        et les fusionne dans _tape.
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
        self._tape = {}
        self.load_pattern(d["curpattern"])   # peuple les entrées "G"
        if "track_slots"   in d: self._track_slots   = d["track_slots"]
        if "track_mutes"   in d: self._track_mutes   = d["track_mutes"]
        if "track_solos"   in d: self._track_solos   = d["track_solos"]
        if "track_volumes" in d: self._track_volumes = d["track_volumes"]
        if "track_pans"    in d: self._track_pans    = d["track_pans"]
        if "voices"        in d: self._voices        = d["voices"]
        self._kb_scale     = d.get("kb_scale",     "major")
        self._kb_root_midi = d.get("kb_root_midi", 48)
        for rec in d.get("kit_tape", []):
            t, b, s, note, vel = rec[:5]
            dur = rec[5] if len(rec) > 5 else 0
            self._tape.setdefault((t, b, s), []).append(TapeEvent("K", note, vel, dur, 0))
        for rec in d.get("patch_tape", []):
            t, b, s, note, vel = rec[:5]
            dur  = rec[5] if len(rec) > 5 else 0
            bend = rec[6] if len(rec) > 6 else 0
            self._tape.setdefault((t, b, s), []).append(TapeEvent("P", note, vel, dur, bend))
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
