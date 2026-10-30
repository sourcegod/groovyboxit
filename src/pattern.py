import random
import threading

from tempo_map import TempoMap, normalize_changes

# Événement enregistré dans _tape (liste plate par piste, position = time).
# etype: ETYPE_GRID = grille (pad de la séquence), ETYPE_KIT = kit (note MIDI brute),
#        ETYPE_PATCH = patch synth (note + bend), ETYPE_CC = Control Change
#        générique, ETYPE_PGM = Program Change (Phase 7 étape 4b),
#        ETYPE_BEND = Pitch Bend (automation, Phase 7 étape 6b1)
ETYPE_GRID  = "GRID"
ETYPE_KIT   = "KIT"
ETYPE_PATCH = "PATCH"
ETYPE_CC    = "CC"
ETYPE_PGM   = "PGM"
ETYPE_BEND  = "BEND"


class TapeEvent:
    """Événement de _tape : id (identifiant unique, incrémenté à chaque
    création — jamais préservé lors d'une reconstruction représentant la
    même note modifiée, jamais sérialisé dans .gvp, comme Pattern._id),
    time (position, steps cumulés sur la piste), etype, dur, channel,
    payload (champs propres au type — {"pad":,"vel":} pour GRID,
    {"note":,"vel":} pour KIT, {"note":,"vel":} pour PATCH (plus de
    "bend" par note depuis la Phase 7 étape 7f1 : le bend est un état de
    canal, porté par les ETYPE_BEND),
    {"cc_num":,"value":} pour CC, {"program":} pour PGM, {"value":} pour
    BEND (-8192..+8191, 0=centre) ; dur=0 pour CC/PGM/BEND, événements
    instantanés).
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


# Entête d'une piste sur slot Banque (Phase 7 étape 17h1, docs/DESIGN.md
# § 17e3 O2, O5) : CC0, CC32 et Program Change à 1.1.1 (time 0).

def _is_header_event(ev):
    return ev.time == 0 and (ev.etype == ETYPE_PGM or (
        ev.etype == ETYPE_CC and ev.payload.get("cc_num") in (0, 32)))


def bank_header(events):
    """(canal, programme, MSB, LSB) de l'entête de la piste, ou None sans
    Program Change à 1.1.1 ; MSB / LSB absents : 0."""
    header = {"pgm": None, 0: 0, 32: 0}
    for ev in events:
        if not _is_header_event(ev):
            continue
        if ev.etype == ETYPE_PGM:
            header["pgm"] = (ev.channel, ev.payload.get("program", 0))
        else:
            header[ev.payload["cc_num"]] = ev.payload.get("value", 0)
    if header["pgm"] is None:
        return None
    channel, program = header["pgm"]
    return channel, program, header[0], header[32]


def with_bank_header(events, channel, program, msb, lsb):
    """Nouvelle liste : events sans l'ancien entête, précédés de CC0, CC32
    et Program Change à 1.1.1 sur channel (rejoués dans cet ordre)."""
    head = [TapeEvent(ETYPE_CC, channel=channel, payload={"cc_num": 0, "value": msb}, time=0),
            TapeEvent(ETYPE_CC, channel=channel, payload={"cc_num": 32, "value": lsb}, time=0),
            TapeEvent(ETYPE_PGM, channel=channel, payload={"program": program}, time=0)]
    return head + [ev for ev in events if not _is_header_event(ev)]


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
    VALID_NUM_STEPS = (16, 32, 64, 128)     # pas par mesure en 4/4 = résolutions
    VALID_RESOLUTIONS = VALID_NUM_STEPS       # pas par ronde : 1/16 … 1/128 (20b1, S2)
    VALID_DENOMINATORS = (2, 4, 8, 16)        # valeur du temps (20b1, S4)
    MAX_NUMERATOR      = 16
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
    def grid_step_size(grid_idx, num_steps, resolution=None):
        """Taille d'un pas de grille en steps (float).

        grid_idx   : index dans GRID_RESOLUTIONS
        num_steps  : steps par mesure du pattern courant
        resolution : pas par ronde (Pattern.resolution()) ; « 1/16 » est une
                     double croche quelle que soit la signature (Phase 7
                     étape 20b1, § 20a1 S6) ; None = num_steps (4/4)
        """
        _, kind, val = Pattern.GRID_RESOLUTIONS[grid_idx]
        if kind == "bars":
            return val * num_steps   # ex. 4 mes × 16 steps = 64 steps
        if val == 1:
            return num_steps         # « 1 mes. » : une mesure
        return (num_steps if resolution is None else resolution) / val
    MAX_PATTERNS      = 99
    MAX_BARS          = 999
    MAX_TRACKS        = 16
    DEFAULT_NUM_TRACKS = 16   # un canal MIDI par piste (Phase 7 étape 10d1)
    KIT_CHANNEL        = 9    # canal 10 (batterie GM), 0-based

    @staticmethod
    def default_channel(track_idx):
        """Canal MIDI par défaut (0-based) de la piste : piste N → canal N,
        canal 16 au-delà de la 16e (Phase 7 étape 10f1)."""
        return min(track_idx, 15)
    NUM_PADS          = 16
    _counter          = 0

    def __init__(self):
        Pattern._counter += 1
        self._id          = Pattern._counter
        self._name        = ""
        self._bpm         = 100   # tempo de départ (T2, Phase 7 étape 19b1)
        # Changements de tempo [(position en pas, BPM)], positions > 0
        # (docs/DESIGN.md § 19a1 T2) ; vide = tempo unique
        self._tempo_changes = []
        self._num_beats   = 4     # numérateur de la signature rythmique
        self._num_steps   = 16    # pas par mesure : 16, 32, 64, 128
        self._num_bars    = 1     # nombre de mesures : 1..999
        self._num_tracks  = Pattern.DEFAULT_NUM_TRACKS
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
        # canal MIDI (0..15) de chaque piste, utilisé par l'export (10f1)
        self._track_channels = [Pattern.default_channel(t) for t in range(self._num_tracks)]
        # Vrai après from_dict d'un preset sans track_channels : les pistes
        # sur un kit restent à passer sur le canal 10 (apply_kit_channels,
        # le Pattern ne connaissant pas le Rack — Phase 7 étape 10h7)
        self._needs_kit_channels = False

        # état des voix par pad : name, volume, pan, mute, solo, duration_ms
        self._voices = [
            {"name": "", "volume": 100, "pan": 0, "mute": False, "solo": False, "duration_ms": 500}
            for _ in range(self._num_pads)
        ]

        # Capture MIDI brute unifiée : liste plate par piste, position = TapeEvent.time
        self._tape = [[] for _ in range(self._num_tracks)]
        # Verrou pour les accès concurrents _run_thread / thread UI
        self._lock = threading.RLock()

        # _mod_tape (mod wheel) supprimé en Phase 7 étape 5h : CC#1 vit dans
        # _tape (ETYPE_CC) depuis l'étape 5b, comme n'importe quel CC.
        # _bend_tape (pitch bend) supprimé en Phase 7 étape 6h1 : le Pitch
        # Bend vit dans _tape (ETYPE_BEND) depuis l'étape 6b1.

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
        """Position (bar,step) → time (steps cumulés)."""
        return bar * self._num_steps + step

    def _time_to_bar_step(self, time):
        """time (steps cumulés) → (bar, step), inverse de _bar_step_to_time."""
        bar, step = divmod(int(time), self._num_steps)
        return bar, step

    def _ensure_track_count(self, n):
        """Étend _tape (liste de listes) pour couvrir au moins n pistes."""
        while len(self._tape) < n:
            self._tape.append([])

    def _bend_state_at(self, track, time):
        """État de Pitch Bend de la piste à `time` : valeur du dernier
        ETYPE_BEND de temps <= time (à temps égal, le dernier dans _tape),
        0 (centre) s'il n'y en a aucun. Appelant sous self._lock."""
        state, state_time = 0, None
        if track < len(self._tape):
            for ev in self._tape[track]:
                if ev.etype == ETYPE_BEND and ev.time <= time \
                        and (state_time is None or ev.time >= state_time):
                    state, state_time = ev.payload.get("value", 0), ev.time
        return state

    def _chase_bend(self, track, time, bend, channel=0):
        """Pose un ETYPE_BEND `bend` à `time` si l'état de bend de la piste à
        cet instant diffère (Phase 7 étape 7f1). Le bend est un état de canal,
        comme en MIDI : une note ne porte plus son bend, c'est ce point qui
        reproduit un bend tenu au note-on. Retourne True si un point a été
        posé. Appelant sous self._lock."""
        if self._bend_state_at(track, time) == bend:
            return False
        self._ensure_track_count(track + 1)
        self._tape[track].append(
            TapeEvent(ETYPE_BEND, channel=channel, payload={"value": bend}, time=time))
        return True

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
        """Snapshot list[int] (longueur _num_steps) — lecture seule.

        Un seul passage sur la piste (même résultat que get_cell case par
        case : la première note GRID trouvée à un pas l'emporte). Case par
        case, une piste importée de milliers de notes coûtait 300 ms au
        thread de l'UI à chaque changement de piste, et la lecture sautait
        (Phase 7 étape 18d3)."""
        num_steps = self._num_steps
        row = [0] * num_steps
        if track >= len(self._tape):
            return row
        start = self._bar_step_to_time(bar, 0)
        found = [False] * num_steps
        for ev in self._tape[track]:
            if ev.etype != ETYPE_GRID or ev.payload.get("pad") != pad:
                continue
            step = ev.time - start
            if 0 <= step < num_steps and step == int(step) and not found[int(step)]:
                found[int(step)] = True
                row[int(step)] = ev.payload.get("vel")
        return row

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
        _tape (et des anciennes structures d'automation, supprimées en Phase 7
        étapes 5h/6h1) historiquement dispersées dans l'UI.
        """
        self._num_tracks = other._num_tracks
        self._num_pads   = other._num_pads
        self._num_bars   = other._num_bars
        self._num_steps  = other._num_steps
        self._num_beats   = other._num_beats                   # signature (20b1, S8)
        self._denumerator = other._denumerator
        self._tempo_changes = list(other._tempo_changes)       # 19b1, T2
        with self._lock:
            self._tape = [list(track_list) for track_list in other._tape]

    #--------------------------------------------------------------------------

    def new_pattern(self, num_bars=1, num_steps=16):
        self._num_bars  = num_bars
        self._num_steps = num_steps
        self._tape       = [[] for _ in range(self._num_tracks)]
        self._tempo_changes = []          # pattern neuf : tempo unique (19b1)

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

    def clear_track(self, track_idx):
        """Efface tous les pas de la piste track_idx (grille + tape MIDI)."""
        with self._lock:
            if track_idx < len(self._tape):
                self._tape[track_idx] = []

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
        # Seconde moitié : repart du tempo de départ (19b1, T2)
        self._tempo_changes = normalize_changes(
            self._bpm, self._tempo_changes + [(half_steps, self._bpm)]
            + [(pos + half_steps, bpm) for pos, bpm in self._tempo_changes])
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
        self._tempo_changes = [(pos, bpm) for pos, bpm in self._tempo_changes
                               if pos < half_steps]
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
    # Carte de tempo (Phase 7 étape 19b1, docs/DESIGN.md § 19a1 T2, T4)

    # Signature (Phase 7 étape 20b1, docs/DESIGN.md § 20a1 S2-S5) : le
    # temps est le dénominateur (position affichée, métronome) ; le tempo
    # se compte en noires.

    def steps_per_beat(self):
        """Pas par temps de la signature (la croche en 6/8)."""
        return self._num_steps / self._num_beats

    def quarters_per_bar(self):
        return 4.0 * self._num_beats / self._denumerator

    def steps_per_quarter(self):
        """Pas par noire (tempo)."""
        return self._num_steps / self.quarters_per_bar()

    def resolution(self):
        """Pas par ronde : 16 = « 1/16 » (S2)."""
        return self._num_steps * self._denumerator / self._num_beats

    def note_steps(self, value):
        """Pas d'une valeur de note 1/value (S6) : 1/16 = une double croche."""
        return self.resolution() / value

    @staticmethod
    def steps_for(resolution, num_beats, denominator):
        """Pas par mesure d'une résolution et d'une signature (S2), ou None
        si ce n'est pas un nombre entier."""
        steps = resolution * num_beats / denominator
        return int(steps) if steps == int(steps) and steps >= 1 else None

    def set_signature(self, num_beats, denominator):
        """Change la signature en gardant les notes à leur place dans le
        temps (S3) : à résolution égale, les positions en pas ne bougent
        pas ; seuls les pas par mesure changent, et le nombre de mesures est
        recalculé pour garder la longueur (mesure supérieure). Retourne
        False si la signature est refusée."""
        if denominator not in self.VALID_DENOMINATORS \
                or not 1 <= num_beats <= self.MAX_NUMERATOR:
            return False
        steps = self.steps_for(self.resolution(), num_beats, denominator)
        if steps is None:
            return False
        total = self._num_bars * self._num_steps
        self._num_beats, self._denumerator, self._num_steps = num_beats, denominator, steps
        self._num_bars = max(1, min(self.MAX_BARS, -(-total // steps)))
        return True

    def tempo_map(self, start_bpm=None):
        """TempoMap du pattern ; start_bpm remplace le tempo de départ
        (celui du player, qui peut avoir changé depuis le dernier flush)."""
        return TempoMap(self._bpm if start_bpm is None else start_bpm,
                        self._tempo_changes, self.steps_per_quarter())

    def ms_per_step_at(self, pos):
        """Millisecondes par pas au tempo en vigueur à la position pos
        (Phase 7 étape 19d1, § 19a1 T5)."""
        return 60000.0 / (self.tempo_map().bpm_at(pos) * self.steps_per_quarter())

    def set_tempo_changes(self, changes):
        """Remplace les changements de tempo (normalisés, T2)."""
        self._tempo_changes = normalize_changes(self._bpm, changes)

    #--------------------------------------------------------------------------

    def resize(self, num_bars, num_steps):
        """Étend ou tronque le pattern sans effacer les données existantes."""
        old_steps = self._num_steps
        old_bars  = self._num_bars

        # ev.time encode bar*old_steps+step : décoder avec l'ancienne résolution
        # avant de changer _num_steps, puis ré-encoder avec la nouvelle — sinon
        # un changement de num_steps réinterpréterait mal les positions stockées.
        # La fraction de pas (CC en temps flottant, Phase 7 étape 5b) est
        # reportée telle quelle sur la nouvelle position.
        new_tape = []
        for track_list in self._tape:
            new_list = []
            for ev in track_list:
                bar, step = divmod(int(ev.time), old_steps)
                if bar < num_bars and step < num_steps:
                    new_time = bar * num_steps + step + (ev.time - int(ev.time))
                    new_list.append(TapeEvent(ev.etype, dur=ev.dur, channel=ev.channel,
                                               payload=ev.payload, time=new_time))
            new_tape.append(new_list)
        self._tape = new_tape
        # Changements de tempo recalés comme les événements (19b1, T2)
        tempo = []
        for pos, bpm in self._tempo_changes:
            bar, step = divmod(int(pos), old_steps)
            if bar < num_bars and step < num_steps:
                tempo.append((bar * num_steps + step + (pos - int(pos)), bpm))
        self._tempo_changes = normalize_changes(self._bpm, tempo)

        if num_steps != old_steps:
            self._num_steps = num_steps

        if num_bars != old_bars:
            self._num_bars = num_bars

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
            "tempo_changes": [[pos, bpm] for pos, bpm in self._tempo_changes],
            "num_beats":     self._num_beats,                  # signature (20b1, S8)
            "denominator":   self._denumerator,
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
            "track_channels": self._track_channels,
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
        }

    #--------------------------------------------------------------------------

    def from_dict(self, d):
        """Restaure le pattern depuis un dict (issu de to_dict / JSON).

        Si 'tape_v2' est présent (format Phase 7 étape 1e), c'est la seule
        source de vérité pour _tape (GRID+KIT+PATCH unifiés). Sinon, lit
        l'ancien format ('curpattern' + 'kit_tape' + 'patch_tape' séparées,
        rétrocompatibilité des presets existants).

        Migration 'mod_tape' → ETYPE_CC (Phase 7 étape 5h) : to_dict n'écrit
        plus cette clé depuis 5h, mais from_dict la lit encore pour les
        presets sauvés avant (dont ceux sauvés entre 4f et 5h, qui
        contiennent un doublon — CC#1 à la fois dans 'mod_tape' et dans
        'tape_v2' en ETYPE_CC cc_num=1). Pour une piste dont 'mod_tape' est
        non vide, 'mod_tape' gagne (c'est la copie précise, en temps
        flottant) : les ETYPE_CC cc_num=1 déjà présents dans _tape pour
        cette piste sont retirés avant d'y recréer les points depuis
        'mod_tape'. Piste dont 'mod_tape' est vide ou absente → ses
        ETYPE_CC cc_num=1 (s'il y en a) sont gardés tels quels.

        Migration 'bend_tape' → ETYPE_BEND (Phase 7 étape 6h1) : to_dict
        n'écrit plus cette clé depuis 6h1. Chaque point (off, val) d'un
        preset plus ancien devient un TapeEvent ETYPE_BEND (payload
        {"value": val}, time=off flottant conservé, channel=0 faute
        d'information) ajouté à _tape[piste]. Pas de doublon à retirer :
        contrairement au CC#1, le Pitch Bend n'avait aucune copie dans
        'tape_v2' avant 6b1.

        Migration du champ "bend" des notes PATCH (Phase 7 étape 7h1) : voir
        _migrate_patch_note_bends, appliquée en dernier (après 'bend_tape')
        pour tenir compte des ETYPE_BEND déjà présents.
        """
        self._name       = d.get("name", "")
        self._bpm        = d.get("bpm", 100)
        # Absente (projet d'avant 19b1) : tempo unique
        self._tempo_changes = normalize_changes(
            self._bpm, [tuple(c) for c in d.get("tempo_changes") or []])
        self._num_bars   = d.get("num_bars", 1)
        self._num_steps  = d.get("num_steps", 16)
        # Signature (Phase 7 étape 20b1, S8) : absente = 4/4
        self._num_beats   = d.get("num_beats", 4)
        self._denumerator = d.get("denominator", 4)
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
                # "bend" converti en ETYPE_BEND par _migrate_patch_note_bends
                self._tape[t].append(TapeEvent(ETYPE_PATCH, dur=dur,
                                                payload={"note": note, "vel": vel, "bend": bend},
                                                time=self._bar_step_to_time(b, s)))
        if "track_slots"   in d: self._track_slots   = d["track_slots"]
        if "track_mutes"   in d: self._track_mutes   = d["track_mutes"]
        if "track_solos"   in d: self._track_solos   = d["track_solos"]
        if "track_volumes" in d: self._track_volumes = d["track_volumes"]
        if "track_pans"    in d: self._track_pans    = d["track_pans"]
        # Clé absente (tout preset d'avant 10f1) : canaux par défaut, pas ceux
        # que l'objet portait déjà — Ctrl+O recharge dans les Pattern existants.
        self._track_channels = list(d.get("track_channels") or
                                    [Pattern.default_channel(t) for t in range(self._num_tracks)])
        self._needs_kit_channels = "track_channels" not in d
        if "voices"        in d: self._voices        = d["voices"]
        self._kb_scale     = d.get("kb_scale",     "major")
        self._kb_root_midi = d.get("kb_root_midi", 48)
        for t, track_bends in enumerate(d.get("bend_tape", [])):
            if not track_bends:
                continue
            self._ensure_track_count(t + 1)
            for off, val in track_bends:
                self._tape[t].append(
                    TapeEvent(ETYPE_BEND, channel=0, payload={"value": val}, time=off)
                )
        for t, track_mods in enumerate(d.get("mod_tape", [])):
            if not track_mods:
                continue   # piste vide → ETYPE_CC cc_num=1 existants gardés tels quels
            self._ensure_track_count(t + 1)
            self._tape[t] = [
                ev for ev in self._tape[t]
                if not (ev.etype == ETYPE_CC and ev.payload.get("cc_num") == 1)
            ]
            for off, val in track_mods:
                self._tape[t].append(
                    TapeEvent(ETYPE_CC, channel=0, payload={"cc_num": 1, "value": val}, time=off)
                )
        self._migrate_patch_note_bends()
        self._extend_tracks(Pattern.DEFAULT_NUM_TRACKS)

    def _extend_tracks(self, n):
        """Porte le pattern à au moins n pistes (migration des presets à 8
        pistes, Phase 7 étape 10d1) : _tape complété par des pistes vides,
        listes track_* complétées par leurs valeurs par défaut (canal par
        défaut selon l'index pour track_channels, 10f1). Listes
        reconstruites, pas étendues en place : elles peuvent venir du dict
        JSON de l'appelant (cache d'undo)."""
        self._num_tracks = max(self._num_tracks, n)
        nt = self._num_tracks
        with self._lock:
            self._ensure_track_count(nt)
        pad = lambda lst, default: list(lst) + [default] * (nt - len(lst))
        self._track_slots   = pad(self._track_slots,   0)
        self._track_mutes   = pad(self._track_mutes,   False)
        self._track_solos   = pad(self._track_solos,   False)
        self._track_volumes = pad(self._track_volumes, 100)
        self._track_pans    = pad(self._track_pans,    0)
        self._track_channels = list(self._track_channels) + [
            Pattern.default_channel(t) for t in range(len(self._track_channels), nt)]

    def apply_kit_channels(self, is_kit_slot):
        """Migration des presets d'avant 10f1 (Phase 7 étape 10h7) : les
        pistes dont le slot est un kit (is_kit_slot(slot_idx)) passent sur le
        canal 10, comme si le kit leur avait été assigné. Sans effet si le
        preset avait déjà ses canaux. Retourne les pistes changées."""
        if not self._needs_kit_channels:
            return []
        self._needs_kit_channels = False
        changed = []
        for t, slot_idx in enumerate(self._track_slots):
            if t < len(self._track_channels) and is_kit_slot(slot_idx):
                self._track_channels[t] = Pattern.KIT_CHANNEL
                changed.append(t)
        return changed

    def _migrate_patch_note_bends(self):
        """Convertit le champ "bend" des notes PATCH (presets sauvés avant la
        Phase 7 étape 7h1) en ETYPE_BEND, puis le retire des payloads.

        Avant 7f1, chaque note imposait son bend (0 compris) au moteur le
        temps de son note-on. Par piste, les notes portant ce champ sont
        parcourues par temps croissant et la même règle qu'à la capture leur
        est appliquée (Pattern._chase_bend) : un ETYPE_BEND n'est posé au
        temps de la note que si l'état de bend de la piste y diffère — une
        note à 0 après une note pliée remet donc l'état à 0. Différence
        assumée : deux notes qui se chevauchent partagent désormais le même
        bend, comme en MIDI. Payload remplacé (pas modifié en place : il
        peut venir du dict JSON de l'appelant).
        """
        with self._lock:
            for t, track_list in enumerate(self._tape):
                old = sorted((ev for ev in track_list
                              if ev.etype == ETYPE_PATCH and "bend" in ev.payload),
                             key=lambda ev: ev.time)
                for ev in old:
                    bend = ev.payload.get("bend", 0)
                    ev.payload = {k: v for k, v in ev.payload.items() if k != "bend"}
                    self._chase_bend(t, ev.time, bend, ev.channel)
