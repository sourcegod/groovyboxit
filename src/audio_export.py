#python3
"""
    File: src/audio_export.py
    Export audio WAV du pattern courant — Phase 8 étape 1f1, docs/DESIGN.md
    § Phase 8 étape 1a (W1-W7) et § 1d2 (W9). Rendu hors temps réel, à
    l'échantillon près, avec les moteurs de l'appli : copies du routeur et
    de ses moteurs sur un Mixer (TrackRouter.render_copy), fins de note
    posées dans la file des événements par l'ordonnanceur du rendu,
    événements et jeu partagés avec la lecture (player/tape_events.py).

    Deux fins (W1) : END_LOOP, la longueur exacte du pattern, résonance
    repliée en régime établi (W2 : K passages enchaînés, le dernier gardé) ;
    END_TAIL, le pattern puis la résonance jusqu'au silence. Avant le
    rendu, un passage à blanc demande tout ce qui se charge à la volée, et
    le rendu attend la fin des chargements (W9). Gain : atténuer si la
    crête dépasse PEAK_DB, ou normaliser (W3) ; 16 bits avec dither TPDF
    (W4).

    Prototype, cible C/C++ (moteur audio) : aucune dépendance à wx ;
    événements à un indice d'échantillon, rendu par blocs dans un tampon
    float32 (frames, 2) par Mixer.mix.
    Date: Sat, 31/10/2026
    Author: Coolbrother
"""
import heapq
import math
import itertools
from dataclasses import dataclass

import numpy as np
import soundfile as sf

from sound_device_driver import Mixer
from player import tape_events as te

END_LOOP   = "loop"     # boucle exacte, résonance repliée (W1, W2)
END_TAIL   = "tail"     # pattern + résonance jusqu'au silence (W1)

SUBTYPES   = ("PCM_16", "PCM_24", "FLOAT")   # 16 bits (défaut), 24 bits, 32 bits flottant (W4)
TAIL_MAX_S = 30.0       # plafond de la résonance (W7)
PEAK_DB    = -0.3       # crête visée par l'atténuation ou la normalisation (W3)
BLOCK      = Mixer.BLOCKSIZE   # bloc de rendu maximal : celui de l'écoute (LFO identique)

# Ordre à échantillon égal : fins de note avant les événements du pattern
# (comme l'export MIDI, D7), puis l'ordre de sort_events.
_ORDER_SCHEDULED = 0
_ORDER_EVENT     = 1


class RenderCancelled(Exception):
    """Rendu annulé par cancelled()."""


@dataclass
class RenderResult:
    data:            np.ndarray   # float32 (n, 2), non écrêté
    samplerate:      int
    pattern_samples: int          # longueur exacte du pattern, en échantillons
    tail_samples:    int          # résonance après le pattern (mesurée au passage simple)
    tail_cut:        bool         # résonance coupée au plafond TAIL_MAX_S
    passes:          int          # passages rendus pour le fichier (END_LOOP : K)

    @property
    def seconds(self):
        return len(self.data) / self.samplerate


# ---------------------------------------------------------------------------
# Session de rendu : copie du routeur, mixeur, banque, file des événements
# ---------------------------------------------------------------------------

class _Session:
    """Une copie du routeur de l'écoute jouant sur son propre Mixer, avec un
    moteur de banque neuf et une file d'appels datés à l'échantillon."""

    def __init__(self, router, samplerate, master_volume, engines_from=None,
                 status_cb=None):
        self.sr     = samplerate
        self.now    = 0
        self.queue  = []
        self._seq   = itertools.count()
        self.mixer  = Mixer(samplerate)
        self.mixer.set_master_volume(master_volume)
        live_bank   = router.bank_engine
        self.bank   = live_bank.render_copy() if live_bank is not None else None
        self.router = router.render_copy(self.mixer, self.bank, self.schedule,
                                         status_cb=status_cb)
        if engines_from is not None:
            self._adopt_engines(engines_from)
        if self.bank is not None:
            self.mixer.add_render_source(self.bank.render)

    def _adopt_engines(self, other):
        """Reprend les moteurs de synthé d'une autre session (ceux chargés au
        passage à blanc, sons calculés compris), copiés sur ce mixeur."""
        copies = {}
        engines = {}
        for slot_idx, engine in other.router._slot_synths.items():
            if engine is None or not engine.is_loaded():
                continue
            if id(engine) not in copies:
                copies[id(engine)] = engine.render_copy(self.mixer)
            engines[slot_idx] = copies[id(engine)]
        self.router._slot_synths.update(engines)

    def schedule(self, delay_ms, fn, *args):
        """Ordonnanceur des fins de note : fn(*args) dans delay_ms."""
        at = self.now + max(0, round(delay_ms * self.sr / 1000.0))
        heapq.heappush(self.queue, (at, _ORDER_SCHEDULED, next(self._seq), fn, args))

    def push_event(self, at, event, voice_manager, master_pan):
        _, marker, data, vel = event
        heapq.heappush(self.queue, (at, _ORDER_EVENT, next(self._seq), te.play_event,
                                    (self.router, voice_manager, master_pan,
                                     marker, data, vel)))

    def fire_due(self):
        """Exécute les appels dont l'échantillon est atteint."""
        while self.queue and self.queue[0][0] <= self.now:
            _, _, _, fn, args = heapq.heappop(self.queue)
            fn(*args)

    def voices(self):
        n = self.mixer.voice_count()
        if self.bank is not None:
            n += self.bank.active_voices()
        return n

    def close(self):
        self.mixer.stop_all()
        if self.bank is not None:
            self.mixer.remove_render_source(self.bank.render)
            self.bank.close()
            self.bank = None


# ---------------------------------------------------------------------------
# Rendu
# ---------------------------------------------------------------------------

def _snapshot(pattern):
    with pattern._lock:
        return [list(track) for track in pattern._tape]


def _pattern_events(tape, pattern, tempo_map, samplerate):
    """Événements de tout le pattern, triés, en (échantillon, événement) :
    même fenêtre que la lecture (positions 0 à total - 1)."""
    total = pattern._num_bars * pattern._num_steps
    evs = te.sort_events(te.tape_events(tape, 0, total - 1, tempo_map.secs))
    return [(round(ev[0] * samplerate), ev) for ev in evs]


def _dry_pass(session, tape, events, voice_manager, master_pan):
    """Passage à blanc (W9) : tous les événements joués, rien de mixé ;
    déclenche les chargements à la volée, puis les attend."""
    session.router.chase(tape, 0.0)
    for at, ev in events:
        session.now = at
        session.push_event(at, ev, voice_manager, master_pan)
        session.fire_due()
    while session.queue:                       # fins de note restantes
        session.now = session.queue[0][0]
        session.fire_due()
    session.router.wait_loaded()


def _run(session, tape, events, voice_manager, master_pan, length, passes,
         tail, progress, cancelled, prog_from, prog_span):
    """Rend passes passages de length échantillons enchaînés (chaque passage
    à un multiple entier de length : identiques à l'échantillon près),
    puis, si tail, la résonance jusqu'au silence (TAIL_MAX_S au plus).
    Retourne (tampon, échantillons après les passages, coupé au plafond)."""
    sr      = session.sr
    total   = length * passes
    tail_mx = int(TAIL_MAX_S * sr) if tail else 0
    out     = np.zeros((total + tail_mx, 2), dtype=np.float32)
    session.router.chase(tape, 0.0)
    for p in range(passes):
        for at, ev in events:
            session.push_event(p * length + at, ev, voice_manager, master_pan)
    pos, next_report = 0, 0
    session.now = 0
    session.fire_due()
    while True:
        if pos >= total:
            if not tail:
                break
            if not session.queue and session.voices() == 0:
                # Les voix s'éteignent en cours de bloc : la résonance finit
                # au dernier échantillon non nul, pas à la fin du bloc
                rest = np.flatnonzero(np.any(out[total:pos] != 0.0, axis=1))
                pos = total + (int(rest[-1]) + 1 if len(rest) else 0)
                break
            if pos >= total + tail_mx:
                return out[:pos], pos - total, True
        stop = total if pos < total else total + tail_mx
        target = min(pos + BLOCK, stop)
        if session.queue:
            target = min(target, max(pos + 1, session.queue[0][0]))
        session.mixer.mix(out[pos:target])
        pos = session.now = target
        session.fire_due()
        if pos >= next_report:
            next_report = pos + sr
            if cancelled is not None and cancelled():
                raise RenderCancelled()
            if progress is not None:
                progress(prog_from + prog_span * min(1.0, pos / max(1, total)))
    return out[:pos], pos - total, False


def render_pattern(pattern, tempo_map, router, voice_manager, *, end=END_LOOP,
                   master_pan=0, master_volume=1.0, samplerate=Mixer.SAMPLERATE,
                   progress=None, cancelled=None, status_cb=None):
    """Rend le pattern entier (W5) avec les moteurs de router (TrackRouter
    de l'écoute, non modifié). tempo_map : carte de tempo jouée (celle du
    player) ; voice_manager : volume, pan, durée, mute et solo des pads ;
    master_pan, master_volume (0..100 ou 0..1) : pan et volume globaux.
    progress(fraction 0..1) et cancelled() -> bool sont appelés au plus une
    fois par seconde rendue ; status_cb(message) reçoit les messages du
    passage à blanc (patch introuvable…). Retourne un RenderResult non
    écrêté."""
    router.wait_loaded()                       # patchs de l'écoute en chargement
    tape   = _snapshot(pattern)
    events = _pattern_events(tape, pattern, tempo_map, samplerate)
    length = max(1, round(tempo_map.secs(pattern._num_bars * pattern._num_steps) * samplerate))

    dry = _Session(router, samplerate, master_volume, status_cb=status_cb)
    try:
        _dry_pass(dry, tape, events, voice_manager, master_pan)
        # Passage simple + résonance : fichier END_TAIL, mesure de T (W2)
        single = _Session(router, samplerate, master_volume, engines_from=dry)
        try:
            span = 1.0 if end == END_TAIL else 1.0 / 3.0
            data, tail, cut = _run(single, tape, events, voice_manager, master_pan,
                                   length, 1, True, progress, cancelled, 0.0, span)
        finally:
            single.close()
        if end == END_TAIL:
            result = RenderResult(data, samplerate, length, tail, cut, 1)
        else:
            passes = 1 + max(1, math.ceil(tail / length))
            loop = _Session(router, samplerate, master_volume, engines_from=dry)
            try:
                data, _, _ = _run(loop, tape, events, voice_manager, master_pan,
                                  length, passes, False, progress, cancelled,
                                  span, 1.0 - span)
            finally:
                loop.close()
            result = RenderResult(np.ascontiguousarray(data[(passes - 1) * length:]),
                                  samplerate, length, tail, cut, passes)
    finally:
        dry.close()
    if progress is not None:
        progress(1.0)
    return result


# ---------------------------------------------------------------------------
# Gain, dither, écriture
# ---------------------------------------------------------------------------

def apply_gain(data, normalize=False, peak_db=PEAK_DB):
    """Gain du fichier (W3) : la crête est ramenée à peak_db si elle le
    dépasse, ou toujours si normalize. Retourne (données, gain en dB)."""
    peak = float(np.max(np.abs(data))) if len(data) else 0.0
    target = 10.0 ** (peak_db / 20.0)
    if peak == 0.0 or (not normalize and peak <= target):
        return data, 0.0
    gain = target / peak
    return (data * gain).astype(np.float32), 20.0 * math.log10(gain)


def dither_tpdf(data, bits=16, rng=None):
    """Dither TPDF de ±1 LSB avant la réduction à bits bits (W4)."""
    rng = rng if rng is not None else np.random.default_rng()
    lsb = 1.0 / (2 ** (bits - 1))
    noise = (rng.random(data.shape) - rng.random(data.shape)) * lsb
    return (data + noise).astype(np.float32)


def write_wav(path, result, subtype="PCM_16", normalize=False, rng=None):
    """Écrit result (RenderResult) en WAV stéréo à sa fréquence : gain
    (apply_gain), dither en 16 bits, écrêtage final à ±1 pour les formats
    entiers. Retourne le gain appliqué en dB."""
    if subtype not in SUBTYPES:
        raise ValueError(f"format inconnu : {subtype}")
    data, gain_db = apply_gain(result.data, normalize)
    if subtype == "PCM_16":
        data = dither_tpdf(data, 16, rng)
    if subtype != "FLOAT":
        data = np.clip(data, -1.0, 1.0)
    sf.write(path, data, result.samplerate, subtype=subtype, format="WAV")
    return gain_db
