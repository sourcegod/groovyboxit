import copy

from pattern import Pattern


class Song:
    MAX_SONGS = 16

    def __init__(self, idx=0):
        self._idx      = idx
        self._name     = ""
        self._sequence = []  # liste d'indices 0-based dans _pattern_list (0..98)
        self._looping  = False

    def label(self):
        base = self._name if self._name else f"Song_{self._idx + 1:02d}"
        n = len(self._sequence)
        return f"{base} ({n})" if n else base

    def to_dict(self):
        return {"name": self._name, "sequence": self._sequence[:], "looping": self._looping}

    def from_dict(self, d):
        self._name     = d.get("name", "")
        self._sequence = [int(i) for i in d.get("sequence", [])]
        self._looping  = bool(d.get("looping", False))


# ---------------------------------------------------------------------------
# Segments d'un song — Phase 8 étape 2b1, docs/DESIGN.md § 2a (E5, E6)
# ---------------------------------------------------------------------------

def frozen_pattern(pat):
    """Copie d'un pattern du store pour un export : tape, mesures, pas,
    signature, carte de tempo (copy_from), BPM, nom, et l'état propre au
    pattern — slots, mute, solo, volume, pan et canal des pistes, voix des
    pads, gamme (MainWindow._on_song_advance). Les listes sont copiées : la
    copie ne bouge plus si le store change. Joué une fois en entier, comme
    en song : pas de boucle, points de boucle ignorés."""
    out = Pattern()
    out.copy_from(pat)
    out._name           = pat._name
    out._bpm            = pat._bpm
    out._looping        = False
    out._loop_start     = None
    out._loop_end       = None
    out._loop_count     = 0
    out._track_slots    = list(pat._track_slots)
    out._track_mutes    = list(pat._track_mutes)
    out._track_solos    = list(pat._track_solos)
    out._track_volumes  = list(pat._track_volumes)
    out._track_pans     = list(pat._track_pans)
    out._track_channels = list(pat._track_channels)
    out._track_midi_ins  = list(pat._track_midi_ins)       # 12b1
    out._track_midi_outs = list(pat._track_midi_outs)
    out._voices         = copy.deepcopy(pat._voices)
    out._kb_scale       = pat._kb_scale
    out._kb_root_midi   = pat._kb_root_midi
    return out


class SongSegment:
    """Un pattern du song, figé en données pures (E5) : sa copie (pattern,
    voir frozen_pattern), sa place dans le song et son début, en secondes et
    en noires depuis le début du song. Chaque segment garde son BPM, sa
    carte de tempo et sa signature (E6)."""

    def __init__(self, position, pattern_idx, pattern, start_secs, start_quarters):
        self.position       = position        # rang dans le song (0-based)
        self.pattern_idx    = pattern_idx     # indice dans _pattern_list
        self.pattern        = pattern         # copie figée (frozen_pattern)
        self.start_secs     = start_secs
        self.start_quarters = start_quarters

    @property
    def label(self):
        """Libellé du pattern : son nom, sinon Pat_NN (comme l'export MIDI)."""
        return self.pattern._name or f"Pat_{self.pattern_idx + 1:02d}"

    @property
    def bpm(self):
        return self.pattern._bpm

    @property
    def total_steps(self):
        return self.pattern._num_bars * self.pattern._num_steps

    def tempo_map(self):
        return self.pattern.tempo_map()

    @property
    def secs(self):
        """Durée du segment en secondes, par sa carte de tempo."""
        return self.tempo_map().secs(self.total_steps)

    @property
    def quarters(self):
        """Durée du segment en noires, par sa signature."""
        return self.pattern._num_bars * self.pattern.quarters_per_bar()

    @property
    def end_secs(self):
        return self.start_secs + self.secs

    @property
    def end_quarters(self):
        return self.start_quarters + self.quarters


def song_segments(song, pattern_list):
    """Segments du song, dans l'ordre de sa séquence (E5). pattern_list est
    le store des patterns ; le pattern courant doit y avoir été rangé
    (MainWindow._store_current_pattern). Un indice hors du store est ignoré.
    Liste vide pour un song vide."""
    segments = []
    secs = quarters = 0.0
    for idx in song._sequence:
        if not 0 <= idx < len(pattern_list):
            continue
        seg = SongSegment(len(segments), idx, frozen_pattern(pattern_list[idx]),
                          secs, quarters)
        segments.append(seg)
        secs, quarters = seg.end_secs, seg.end_quarters
    return segments


def song_secs(segments):
    """Durée du song en secondes (E6)."""
    return segments[-1].end_secs if segments else 0.0
