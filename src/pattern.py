class Track:
    DRUM  = "drum"
    SYNTH = "synth"
    MIDI  = "midi"

    def __init__(self, sample_index=0):
        self._name            = ""
        self._sample_index    = sample_index
        self._instrument_type = Track.DRUM
        self._mute            = False
        self._solo            = False
        self._volume          = 100


class Pattern:
    VALID_NUM_STEPS   = (16, 32, 64, 128)
    VALID_QUANT_STEPS = (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128)
    MAX_PATTERNS      = 99
    MAX_BARS          = 999
    MAX_TRACKS        = 8
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
        self._quant_steps = 16    # 1,2,3,4,6,8,12,16,24,32,48,64,96,128
        self._swing       = 0     # décalage groove 0..100 %
        self._denumerator = 4     # dénominateur de la signature rythmique
        self._looping     = False

        self._tracks = [Track(i) for i in range(self._num_tracks)]

        # [track][bar][step]
        self._curpattern = [
            [[False] * self._num_steps for _ in range(self._num_bars)]
            for _ in range(self._num_tracks)
        ]

    #--------------------------------------------------------------------------

    def new_pattern(self, num_bars=1, num_steps=16):
        self._num_bars  = num_bars
        self._num_steps = num_steps
        self._curpattern = [
            [[False] * self._num_steps for _ in range(self._num_bars)]
            for _ in range(self._num_tracks)
        ]

    #--------------------------------------------------------------------------

    def load_pattern(self, pattern):
        self._num_tracks = len(pattern)
        self._num_bars   = len(pattern[0])    if pattern          else 1
        self._num_steps  = len(pattern[0][0]) if pattern and pattern[0] else 16
        self._curpattern = [[bar[:] for bar in track] for track in pattern]

    #--------------------------------------------------------------------------

    def reset_pattern(self):
        for track in self._curpattern:
            for bar in track:
                bar[:] = [False] * len(bar)
