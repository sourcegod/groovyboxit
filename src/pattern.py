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
    VALID_NUM_STEPS   = (16, 32, 64, 128)
    VALID_QUANT_STEPS = (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128)
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
        self._looping     = False

        self._tracks = [Track(i) for i in range(self._num_tracks)]

        # [track][pad][bar][step]
        self._curpattern = self._make_empty()

    #--------------------------------------------------------------------------

    def _make_empty(self):
        return [
            [
                [[False] * self._num_steps for _ in range(self._num_bars)]
                for _ in range(self._num_pads)
            ]
            for _ in range(self._num_tracks)
        ]

    #--------------------------------------------------------------------------

    def new_pattern(self, num_bars=1, num_steps=16):
        self._num_bars  = num_bars
        self._num_steps = num_steps
        self._curpattern = self._make_empty()

    #--------------------------------------------------------------------------

    def load_pattern(self, pattern):
        self._num_tracks = len(pattern)
        self._num_pads   = len(pattern[0])       if pattern                        else Pattern.NUM_PADS
        self._num_bars   = len(pattern[0][0])    if pattern and pattern[0]         else 1
        self._num_steps  = len(pattern[0][0][0]) if pattern and pattern[0] and pattern[0][0] else 16
        self._curpattern = [[[bar[:] for bar in pad] for pad in track] for track in pattern]

    #--------------------------------------------------------------------------

    def reset_pattern(self):
        for track in self._curpattern:
            for pad in track:
                for bar in pad:
                    bar[:] = [False] * len(bar)

    #--------------------------------------------------------------------------

    def build_pattern_01(self):
        self.reset_pattern()
        p = self._curpattern
        # Piste 0 — pad = son du kit (0..15)
        p[0][0][0][0]  = p[0][0][0][4]  = p[0][0][0][8]  = p[0][0][0][12] = True
        p[0][4][0][2]  = p[0][4][0][6]  = p[0][4][0][10] = True
        p[0][5][0][1:4]  = [True] * 3
        p[0][5][0][5:8]  = [True] * 3
        p[0][5][0][9:12] = [True] * 3
        p[0][5][0][13:16] = [True] * 3
        p[0][7][0][15] = True
        p[0][8][0][14] = True
        p[0][9][0][13] = True
        p[0][10][0][0] = True
