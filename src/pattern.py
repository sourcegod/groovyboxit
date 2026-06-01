import random


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
    QUANT_STEPS = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128]
    QUANT_LABELS = [f"Quant_{i + 1:02d} - {q}" for i, q in enumerate(QUANT_LIST)]
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

        self._tracks = [Track(i) for i in range(self._num_tracks)]

        # [track][pad][bar][step]
        self._curpattern = self._make_empty()

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

        # Capture MIDI brute pour les kits : {(track, bar, step): [(note, vel), ...]}
        self._kit_tape   = {}
        # Capture MIDI brute pour les patchs synth : même structure
        self._patch_tape = {}

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

    def new_pattern(self, num_bars=1, num_steps=16):
        self._num_bars  = num_bars
        self._num_steps = num_steps
        self._curpattern = self._make_empty()
        self._kit_tape   = {}
        self._patch_tape = {}

    #--------------------------------------------------------------------------

    def load_pattern(self, pattern):
        self._num_tracks = len(pattern)
        self._num_pads   = len(pattern[0])       if pattern                        else Pattern.NUM_PADS
        self._num_bars   = len(pattern[0][0])    if pattern and pattern[0]         else 1
        self._num_steps  = len(pattern[0][0][0]) if pattern and pattern[0] and pattern[0][0] else 16
        nv = Pattern._norm_vel
        self._curpattern = [
            [[[ nv(v) for v in bar] for bar in pad] for pad in track]
            for track in pattern
        ]

    #--------------------------------------------------------------------------

    def reset_pattern(self):
        for track in self._curpattern:
            for pad in track:
                for bar in pad:
                    bar[:] = [0] * len(bar)
        self._kit_tape   = {}
        self._patch_tape = {}

    def clear_track(self, track_idx):
        """Efface tous les pas de la piste track_idx (grille + tapes MIDI)."""
        for pad in self._curpattern[track_idx]:
            for bar in pad:
                bar[:] = [0] * len(bar)
        self._patch_tape = {k: v for k, v in self._patch_tape.items() if k[0] != track_idx}
        self._kit_tape   = {k: v for k, v in self._kit_tape.items()   if k[0] != track_idx}

    #--------------------------------------------------------------------------

    def gen_pattern(self, track=0):
        self.reset_pattern()
        num_pads = random.randint(1, 4)
        pads     = random.sample(range(self._num_pads), num_pads)
        for pad in pads:
            num_steps = random.randint(1, 8)
            steps     = random.sample(range(self._num_steps), num_steps)
            for step in steps:
                self._curpattern[track][pad][0][step] = 100

    #--------------------------------------------------------------------------

    def double_bars(self):
        """Duplique les mesures existantes (pattern deux fois plus long)."""
        if self._num_bars * 2 > self.MAX_BARS:
            return False
        half = self._num_bars
        for track in self._curpattern:
            for pad in track:
                pad.extend([bar[:] for bar in pad])
        new_tape = dict(self._kit_tape)
        for (t, b, s), events in self._kit_tape.items():
            new_tape[(t, b + half, s)] = events[:]
        self._kit_tape = new_tape
        new_ptape = dict(self._patch_tape)
        for (t, b, s), events in self._patch_tape.items():
            new_ptape[(t, b + half, s)] = events[:]
        self._patch_tape = new_ptape
        self._num_bars *= 2
        return True

    #--------------------------------------------------------------------------

    def halve_bars(self):
        """Garde la première moitié des mesures (pattern deux fois plus court)."""
        if self._num_bars < 2:
            return False
        half = self._num_bars // 2
        for track in self._curpattern:
            for pad in track:
                del pad[half:]
        self._kit_tape = {
            (t, b, s): events
            for (t, b, s), events in self._kit_tape.items()
            if b < half
        }
        self._patch_tape = {
            (t, b, s): events
            for (t, b, s), events in self._patch_tape.items()
            if b < half
        }
        self._num_bars = half
        return True

    #--------------------------------------------------------------------------

    def build_pattern_01(self):
        self.reset_pattern()
        p = self._curpattern
        # Piste 0 — pad = son du kit (0..15)
        p[0][0][0][0]  = p[0][0][0][4]  = p[0][0][0][8]  = p[0][0][0][12] = 100
        p[0][4][0][2]  = p[0][4][0][6]  = p[0][4][0][10] = 100
        p[0][5][0][1:4]  = [100] * 3
        p[0][5][0][5:8]  = [100] * 3
        p[0][5][0][9:12] = [100] * 3
        p[0][5][0][13:16] = [100] * 3
        p[0][7][0][15] = 100
        p[0][8][0][14] = 100
        p[0][9][0][13] = 100
        p[0][10][0][0] = 100

    #--------------------------------------------------------------------------

    def is_empty(self):
        return not any(
            step
            for track in self._curpattern
            for pad in track
            for bar in pad
            for step in bar
        )

    #--------------------------------------------------------------------------

    def resize(self, num_bars, num_steps):
        """Étend ou tronque _curpattern sans effacer les données existantes."""
        old_steps = self._num_steps
        old_bars  = self._num_bars

        if num_steps != old_steps:
            for track in self._curpattern:
                for pad in track:
                    for bar in pad:
                        if num_steps > old_steps:
                            bar.extend([0] * (num_steps - old_steps))
                        else:
                            del bar[num_steps:]
            self._num_steps = num_steps

        if num_bars != old_bars:
            for track in self._curpattern:
                for pad in track:
                    if num_bars > old_bars:
                        pad.extend(
                            [[0] * num_steps for _ in range(num_bars - old_bars)]
                        )
                    else:
                        del pad[num_bars:]
            self._num_bars = num_bars

        self._kit_tape = {
            (t, b, s): events
            for (t, b, s), events in self._kit_tape.items()
            if b < self._num_bars and s < self._num_steps
        }
        self._patch_tape = {
            (t, b, s): events
            for (t, b, s), events in self._patch_tape.items()
            if b < self._num_bars and s < self._num_steps
        }

    #--------------------------------------------------------------------------

    def to_dict(self):
        """Sérialise le pattern en dict JSON-compatible."""
        return {
            "name":          self._name,
            "bpm":           self._bpm,
            "num_bars":      self._num_bars,
            "num_steps":     self._num_steps,
            "start_bar":     self._start_bar,
            "looping":       self._looping,
            "track_slots":   self._track_slots,
            "track_mutes":   self._track_mutes,
            "track_solos":   self._track_solos,
            "track_volumes": self._track_volumes,
            "track_pans":    self._track_pans,
            "curpattern":    self._curpattern,
            "voices":        self._voices,
            "kb_scale":      self._kb_scale,
            "kb_root_midi":  self._kb_root_midi,
            "kit_tape":   [
                [t, b, s, note, vel, dur]
                for (t, b, s), events in self._kit_tape.items()
                for note, vel, dur in events
            ],
            "patch_tape": [
                [t, b, s, note, vel, dur]
                for (t, b, s), events in self._patch_tape.items()
                for note, vel, dur in events
            ],
        }

    #--------------------------------------------------------------------------

    def from_dict(self, d):
        """Restaure le pattern depuis un dict (issu de to_dict / JSON)."""
        self._name      = d.get("name", "")
        self._bpm       = d.get("bpm", 100)
        self._num_bars  = d.get("num_bars", 1)
        self._num_steps = d.get("num_steps", 16)
        self._start_bar = d.get("start_bar", 0)
        self._looping   = d.get("looping", True)
        self.load_pattern(d["curpattern"])
        if "track_slots"   in d: self._track_slots   = d["track_slots"]
        if "track_mutes"   in d: self._track_mutes   = d["track_mutes"]
        if "track_solos"   in d: self._track_solos   = d["track_solos"]
        if "track_volumes" in d: self._track_volumes = d["track_volumes"]
        if "track_pans"    in d: self._track_pans    = d["track_pans"]
        if "voices"        in d: self._voices        = d["voices"]
        self._kb_scale     = d.get("kb_scale",     "major")
        self._kb_root_midi = d.get("kb_root_midi", 48)
        self._kit_tape = {}
        for rec in d.get("kit_tape", []):
            t, b, s, note, vel = rec[:5]
            dur = rec[5] if len(rec) > 5 else 0
            self._kit_tape.setdefault((t, b, s), []).append((note, vel, dur))
        self._patch_tape = {}
        for rec in d.get("patch_tape", []):
            t, b, s, note, vel = rec[:5]
            dur = rec[5] if len(rec) > 5 else 0
            self._patch_tape.setdefault((t, b, s), []).append((note, vel, dur))
