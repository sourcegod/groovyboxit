#python3
"""
    File: src/audio/audio_export.py
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
    le rendu attend la fin des chargements (W9). Gain : normalisation à un
    niveau visé en crête, RMS ou LUFS-I (W11, § 1h6), puis limiteur
    brickwall à anticipation au-dessus de PEAK_DB, circulaire en boucle
    (W10, § 1h3) ; 16 bits avec dither TPDF (W4).

    Song (Phase 8 étape 2h1, docs/DESIGN.md § 2a E1, E2, E11) : rendu
    continu des patterns du song, chacun à sa place, l'état de son pattern
    (slots, mix, canaux, gamme, voix, banques) appliqué à sa frontière à
    l'échantillon près ; les voix en cours continuent. Mêmes deux fins.

    Pistes séparées (stems, Phase 8 étape 2l1, § 2a E3, E4, E12, E13) : un
    rendu par piste, à la longueur du mix ; gain de normalisation et
    enveloppe du limiteur calculés sur le mix (Gain), appliqués tels quels
    à chaque piste ; fichiers dans un sous-dossier du nom du fichier.

    Prototype, cible C/C++ (moteur audio) : aucune dépendance à wx ;
    événements à un indice d'échantillon, rendu par blocs dans un tampon
    float32 (frames, 2) par Mixer.mix.
    Date: Sat, 31/10/2026
    Author: Coolbrother
"""
import copy
import heapq
import math
import os
import re
import itertools
from dataclasses import dataclass

import numpy as np
import soundfile as sf

from audio.sound_device_driver import Mixer
from player import tape_events as te
from rack import InstrumentType

END_LOOP   = "loop"     # boucle exacte, résonance repliée (W1, W2)
END_TAIL   = "tail"     # pattern + résonance jusqu'au silence (W1)

SUBTYPES   = ("PCM_16", "PCM_24", "FLOAT")   # 16 bits (défaut), 24 bits, 32 bits flottant (W4)
TAIL_MAX_S = 30.0       # plafond de la résonance (W7)
PEAK_DB    = -0.3       # seuil du limiteur et crête de la normalisation (W3, W10)
LOOKAHEAD_S = 0.005     # anticipation du limiteur (W10)
RELEASE_S   = 0.05      # constante de temps du retour du limiteur (W10)

# Normalisation à un niveau visé (W11, § Phase 8 étape 1h6)
MEASURES      = ("peak", "rms", "lufs")   # Crête, RMS, LUFS-I
LEVEL_MIN_DB  = -24
LEVEL_MAX_DB  = 0        # jusqu'à 0 dB, saturation acceptée (W12, § 1h8)
LEVEL_DEFAULT = -14
BLOCK      = Mixer.BLOCKSIZE   # bloc de rendu maximal : celui de l'écoute (LFO identique)

# Ordre à échantillon égal : fins de note avant les événements du pattern
# (comme l'export MIDI, D7), puis l'ordre de sort_events. À une frontière
# du song, l'état du pattern suivant entre les deux (E11).
_ORDER_SCHEDULED = 0
_ORDER_STATE     = 1
_ORDER_EVENT     = 2


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
    looped:          bool = False # fichier en boucle (END_LOOP) : limiteur circulaire (W10)

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
        # Moteur sfizz des slots Synth SFZ (Phase 8 étape 7d1, § 7a2 Z12) :
        # copie hors temps réel, chargement bloquant à la sélection des canaux
        live_sfz    = router.sfz_engine
        self.sfz    = live_sfz.render_copy() if live_sfz is not None else None
        self.router = router.render_copy(self.mixer, self.bank, self.schedule,
                                         status_cb=status_cb, sfz_engine=self.sfz)
        if engines_from is not None:
            self._adopt_engines(engines_from)
        if self.bank is not None:
            self.mixer.add_render_source(self.bank.render)
        if self.sfz is not None:
            self.mixer.add_render_source(self.sfz.render)

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

    def push_state(self, at, state, load=False):
        """État d'un pattern du song à appliquer à l'échantillon at (E11)."""
        heapq.heappush(self.queue, (at, _ORDER_STATE, next(self._seq), state.apply,
                                    (self.router, load)))

    def push(self, at, item, master_pan, load=False):
        """Un élément de la ligne de temps : (événement, voice_manager) ou
        _PatternState."""
        if isinstance(item, _PatternState):
            self.push_state(at, item, load)
        else:
            event, voice_manager = item
            self.push_event(at, event, voice_manager, master_pan)

    def fire_due(self):
        """Exécute les appels dont l'échantillon est atteint."""
        while self.queue and self.queue[0][0] <= self.now:
            _, _, _, fn, args = heapq.heappop(self.queue)
            fn(*args)

    def voices(self):
        n = self.mixer.voice_count()
        if self.bank is not None:
            n += self.bank.active_voices()
        if self.sfz is not None:
            n += self.sfz.active_voices()
        return n

    def close(self):
        self.mixer.stop_all()
        if self.bank is not None:
            self.mixer.remove_render_source(self.bank.render)
            self.bank.close()
            self.bank = None
        if self.sfz is not None:
            self.mixer.remove_render_source(self.sfz.render)
            self.sfz.close()
            self.sfz = None


# ---------------------------------------------------------------------------
# Rendu
# ---------------------------------------------------------------------------

def _snapshot(pattern):
    with pattern._lock:
        return [list(track) for track in pattern._tape]


class _PatternState:
    """État d'un pattern du song (copie figée : song.frozen_pattern),
    appliqué au routeur du rendu à sa frontière (E11), comme
    MainWindow._on_song_advance à la lecture : slots, mute, solo, volume,
    pan et canal des pistes, gamme de lecture, poursuite des banques au
    début du pattern. load (passage à blanc seulement) : demande aussi le
    moteur des slots de synthé pas encore chargés ; les sessions de rendu
    reprennent ensuite les moteurs chargés (W9)."""

    def __init__(self, pattern, tape):
        self.pattern = pattern
        self.tape    = tape

    def apply(self, router, load=False):
        p = self.pattern
        router._track_slots[:]    = p._track_slots
        router._track_mutes[:]    = p._track_mutes
        router._track_solos[:]    = p._track_solos
        router._track_volumes[:]  = p._track_volumes
        router._track_pans[:]     = p._track_pans
        router._track_channels[:] = p._track_channels
        router._track_midi_outs[:] = p._track_midi_outs    # 12b1 (rendu : son interne)
        router._track_midi_ins[:]  = p._track_midi_ins
        router.rack_mode          = p._rack_mode     # Phase 8 étape 5b1, M13
        router.set_playback_kb(p._kb_scale, p._kb_root_midi)
        if load:
            for slot_idx in sorted(set(p._track_slots)):
                if slot_idx not in router._slot_synths and \
                        router._rack.get_slot(slot_idx).type == InstrumentType.SYNTH:
                    router._ensure_slot_synth(slot_idx)
        router.chase(self.tape, 0.0)


def _segment_voices(voice_manager, pattern):
    """Voix des pads d'un pattern du song : celles du voice_manager de
    l'écoute (groupes de mute du kit compris), réglées d'après le pattern
    (from_list, comme MainWindow._on_song_advance)."""
    vm = copy.deepcopy(voice_manager)
    vm.from_list(pattern._voices)
    return vm


def _pattern_events(tape, pattern, tempo_map, samplerate, window=None):
    """Événements triés, en (échantillon, événement). Sans fenêtre : tout le
    pattern, avec la fenêtre de la lecture (positions 0 à total - 1). Avec
    window = (début, fin) en pas : temps début ≤ t < fin, en secondes depuis
    début (W17, § 1h11)."""
    if window is None:
        total = pattern._num_bars * pattern._num_steps
        evs = te.tape_events(tape, 0, total - 1, tempo_map.secs)
    else:
        start, end = window
        base = tempo_map.secs(start)
        end_sec = tempo_map.secs(end) - base
        evs = [ev for ev in te.tape_events(tape, start, end,
                                           lambda rel: tempo_map.secs(start + rel) - base)
               if ev[0] < end_sec]
    return [(round(ev[0] * samplerate), ev) for ev in te.sort_events(evs)]


def selection_window(lim_left, lim_right):
    """Fenêtre [G, D + 1) de la sélection (W18) : le pas D compris en
    entier, comme l'effacement par plage (§ 6g2)."""
    return (lim_left, lim_right + 1)


def _bucket_time(bar, step, ev, num_steps):
    """Temps d'un événement de presse-papier à partir de sa clé (mesure
    relative, pas) et de la fraction de pas de ev.time, comme le collage
    (TrackEditor.paste) : le temps absolu n'est pas gardé dans un
    presse-papier relu d'un .gvp."""
    return bar * num_steps + step + (ev.time - int(ev.time))


def _render_copy_of(pattern):
    """Pattern neuf aux réglages de pattern (tempo, signature, résolution),
    sans événement. copy_from laisse le tempo de départ au player : il est
    recopié ici (1h13)."""
    from pattern import Pattern
    pat = Pattern()
    pat.copy_from(pattern)
    pat._bpm = pattern._bpm
    pat._tape = [[] for _ in range(max(pattern._num_tracks, len(pattern._tape)))]
    return pat


def clipboard_pattern(clipboard, pattern):
    """Pattern de rendu du presse-papier des pistes (W19, W14) : réglages
    du pattern courant, num_bars mesures à partir de 0, chaque événement sur
    sa piste d'origine (clipboard.tracks), temps mis à l'échelle si les
    résolutions diffèrent. Les événements sont copiés, pas partagés."""
    from pattern import TapeEvent
    pat = _render_copy_of(pattern)
    pat._num_bars = max(1, clipboard.num_bars)
    scale = pattern._num_steps / clipboard.num_steps
    for (rel, bar, step), events in clipboard.tape.items():
        if rel >= len(clipboard.tracks):
            continue
        track = clipboard.tracks[rel]
        pat._ensure_track_count(track + 1)
        for ev in events:
            t = _bucket_time(bar, step, ev, clipboard.num_steps) * scale
            pat._tape[track].append(TapeEvent(ev.etype, dur=ev.dur, channel=ev.channel,
                                              payload=dict(ev.payload or {}), time=t))
    for track in pat._tape:
        track.sort(key=lambda e: e.time)
    return pat


def event_clipboard_pattern(events, pattern):
    """Pattern de rendu du presse-papier des notes de l'éditeur MIDI (W20) :
    réglages du pattern courant, du début de la mesure de la première note
    à la fin de celle de la dernière ; chaque note sur sa piste d'origine,
    à sa place dans la mesure. Notes seulement : pas de CC ni de Pitch
    Bend. None si events est vide."""
    from pattern import TapeEvent, ETYPE_GRID
    notes = [e for e in events if e.get("type", "note") == "note"]
    if not notes:
        return None
    ns = pattern._num_steps
    first_bar = int(min(e["offset"] for e in notes) // ns)
    last_bar  = int(max(e["offset"] for e in notes) // ns)
    pat = _render_copy_of(pattern)
    pat._num_bars = last_bar - first_bar + 1
    for e in notes:
        track = e["track"]
        pat._ensure_track_count(track + 1)
        t = e["offset"] - first_bar * ns
        if e["etype"] == ETYPE_GRID:
            ev = TapeEvent(ETYPE_GRID, dur=e.get("dur_override", 0), channel=e.get("channel", 0),
                           payload={"pad": e["pad"], "vel": e["vel"]}, time=t)
        else:
            ev = TapeEvent(e["etype"], dur=e.get("dur", 0), channel=e.get("channel", 0),
                           payload={"note": e["pad"], "vel": e["vel"]}, time=t)
        pat._tape[track].append(ev)
    for track in pat._tape:
        track.sort(key=lambda e: e.time)
    return pat


def _dry_pass(session, start, timeline, master_pan):
    """Passage à blanc (W9) : tous les événements joués, rien de mixé ;
    déclenche les chargements à la volée, puis les attend. start() prépare
    le routeur (poursuite des banques) ; timeline : [(échantillon,
    élément)], voir _Session.push."""
    start()
    for at, item in timeline:
        session.now = at
        session.push(at, item, master_pan, load=True)
        session.fire_due()
    while session.queue:                       # fins de note restantes
        session.now = session.queue[0][0]
        session.fire_due()
    session.router.wait_loaded()


def _run(session, start, timeline, master_pan, length, passes,
         tail, progress, cancelled, prog_from, prog_span):
    """Rend passes passages de length échantillons enchaînés (chaque passage
    à un multiple entier de length : identiques à l'échantillon près),
    puis, si tail, la résonance jusqu'au silence (TAIL_MAX_S au plus).
    start() prépare le routeur ; timeline : voir _dry_pass.
    Retourne (tampon, échantillons après les passages, coupé au plafond)."""
    sr      = session.sr
    total   = length * passes
    tail_mx = int(TAIL_MAX_S * sr) if tail else 0
    out     = np.zeros((total + tail_mx, 2), dtype=np.float32)
    start()
    for p in range(passes):
        for at, item in timeline:
            session.push(p * length + at, item, master_pan)
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
                   progress=None, cancelled=None, status_cb=None,
                   window=None, tracks=None):
    """Rend le pattern entier (W5) avec les moteurs de router (TrackRouter
    de l'écoute, non modifié). window = (début, fin) en pas : seulement
    cette fenêtre, état des banques poursuivi à début, notes commencées
    avant ignorées (W15, W17) ; tracks : pistes rendues (les autres sont
    vidées), None = toutes. tempo_map : carte de tempo jouée (celle du
    player) ; voice_manager : volume, pan, durée, mute et solo des pads ;
    master_pan, master_volume (entier 0..200 en %, ou réel en rapport) : pan
    et volume globaux.
    progress(fraction 0..1) et cancelled() -> bool sont appelés au plus une
    fois par seconde rendue ; status_cb(message) reçoit les messages du
    passage à blanc (patch introuvable…). Retourne un RenderResult non
    écrêté."""
    router.wait_loaded()                       # patchs de l'écoute en chargement
    tape   = _snapshot(pattern)
    if tracks is not None:
        tape = [lst if i in tracks else [] for i, lst in enumerate(tape)]
    events = _pattern_events(tape, pattern, tempo_map, samplerate, window)
    timeline = [(at, (ev, voice_manager)) for at, ev in events]
    if window is None:
        chase_pos = 0.0
        secs = tempo_map.secs(pattern._num_bars * pattern._num_steps)
    else:
        chase_pos = float(window[0])
        secs = tempo_map.secs(window[1]) - tempo_map.secs(window[0])
    length = max(1, round(secs * samplerate))
    return _render(router, lambda r: r.chase(tape, chase_pos), timeline, length,
                   end=end, master_pan=master_pan, master_volume=master_volume,
                   samplerate=samplerate, progress=progress, cancelled=cancelled,
                   status_cb=status_cb)


def render_song(segments, router, voice_manager, *, end=END_TAIL,
                master_pan=0, master_volume=1.0, samplerate=Mixer.SAMPLERATE,
                progress=None, cancelled=None, status_cb=None, tracks=None):
    """Rend un song (Phase 8 étape 2h1, docs/DESIGN.md § 2a E1, E2, E11) :
    segments = song.song_segments(…), chacun joué une fois en entier, à
    sa place, par la carte de tempo de son pattern. À chaque frontière, à
    l'échantillon près (après les fins de note, avant les événements),
    l'état du pattern est appliqué à la copie du routeur (_PatternState) ;
    les voix en cours continuent (E1). Les voix des pads de chaque segment
    partent de voice_manager (groupes de mute du kit), réglées d'après son
    pattern. Le passage à blanc parcourt tout le song et charge tous les
    patchs. Deux fins (E2) : END_LOOP, boucle exacte du song, l'état du
    premier pattern rétabli à chaque reprise (comme le song en boucle à la
    lecture) ; END_TAIL, song + résonance. Le router de l'écoute n'est pas
    modifié. tracks : pistes rendues dans chaque pattern (les autres sont
    vidées, l'état des patterns restant appliqué), None = toutes (stems,
    2l1). Autres paramètres : voir render_pattern."""
    if not segments:
        raise ValueError("song vide")
    router.wait_loaded()                       # patchs de l'écoute en chargement
    timeline = []
    for seg in segments:
        pat   = seg.pattern
        tape  = _snapshot(pat)
        state = _PatternState(pat, tape)           # banques : toutes les pistes
        if tracks is not None:
            tape = [lst if i in tracks else [] for i, lst in enumerate(tape)]
        base  = seg.start_secs
        vm    = _segment_voices(voice_manager, pat)
        timeline.append((round(base * samplerate), state))
        evs = te.tape_events(tape, 0, seg.total_steps - 1, seg.tempo_map().secs)
        timeline.extend((round((base + ev[0]) * samplerate), (ev, vm))
                        for ev in te.sort_events(evs))
    length = max(1, round(segments[-1].end_secs * samplerate))
    # Les états entrent dans la file : rien à préparer avant (pas de
    # poursuite avec l'état de l'écoute)
    return _render(router, lambda r: None, timeline, length,
                   end=end, master_pan=master_pan, master_volume=master_volume,
                   samplerate=samplerate, progress=progress, cancelled=cancelled,
                   status_cb=status_cb)


def _render(router, start, timeline, length, *, end, master_pan, master_volume,
            samplerate, progress, cancelled, status_cb):
    """Passage à blanc, puis passage simple + résonance (END_TAIL, et
    mesure de T), puis au besoin les passages du régime établi (END_LOOP,
    W2). start(routeur) prépare chaque copie du routeur ; timeline :
    [(échantillon, élément)], voir _Session.push."""
    dry = _Session(router, samplerate, master_volume, status_cb=status_cb)
    try:
        _dry_pass(dry, lambda: start(dry.router), timeline, master_pan)
        # Passage simple + résonance : fichier END_TAIL, mesure de T (W2)
        single = _Session(router, samplerate, master_volume, engines_from=dry)
        try:
            span = 1.0 if end == END_TAIL else 1.0 / 3.0
            data, tail, cut = _run(single, lambda: start(single.router), timeline,
                                   master_pan, length, 1, True, progress, cancelled,
                                   0.0, span)
        finally:
            single.close()
        if end == END_TAIL:
            result = RenderResult(data, samplerate, length, tail, cut, 1)
        else:
            passes = 1 + max(1, math.ceil(tail / length))
            loop = _Session(router, samplerate, master_volume, engines_from=dry)
            try:
                data, _, _ = _run(loop, lambda: start(loop.router), timeline,
                                  master_pan, length, passes, False, progress, cancelled,
                                  span, 1.0 - span)
            finally:
                loop.close()
            result = RenderResult(np.ascontiguousarray(data[(passes - 1) * length:]),
                                  samplerate, length, tail, cut, passes, looped=True)
    finally:
        dry.close()
    if progress is not None:
        progress(1.0)
    return result


# ---------------------------------------------------------------------------
# Gain, dither, écriture
# ---------------------------------------------------------------------------

def _sliding_min_forward(a, w):
    """out[n] = min(a[n:n + w]), en O(n) (blocs de w : minimum préfixe et
    suffixe, van Herk / Gil-Werman) ; a est complété par des 1."""
    n = len(a)
    nb = -(-(n + w) // w)
    pad = np.ones(nb * w, dtype=np.float64)
    pad[:n] = a
    blocks = pad.reshape(nb, w)
    prefix = np.minimum.accumulate(blocks, axis=1).ravel()
    suffix = np.minimum.accumulate(blocks[:, ::-1], axis=1)[:, ::-1].ravel()
    idx = np.arange(n)
    return np.minimum(suffix[idx], prefix[idx + w - 1])


def _release(g, tau):
    """g'[n] = min(g[n], 1 - (1 - g'[n-1]) · c), c = exp(-1/tau) : retour
    exponentiel vers 1. Vectorisé : z = 1 - g' vérifie z[n] = max(d[n],
    c · z[n-1]) avec d = 1 - g, soit z[n] = max sur k ≤ n de d[k] · c^(n-k),
    un maximum cumulé en logarithmes."""
    d = 1.0 - g
    with np.errstate(divide="ignore"):
        logd = np.log(np.maximum(d, 0.0))
    k = np.arange(len(g), dtype=np.float64) / tau          # -k · log c
    z = np.exp(np.maximum.accumulate(logd + k) - k)
    return 1.0 - z


def limit_peaks(data, threshold, samplerate, loop=False):
    """Limiteur brickwall à anticipation (W10) : aucun échantillon ne dépasse
    threshold (amplitude) ; gain à 1 hors des crêtes, même gain sur les deux
    canaux. loop : le fichier est une boucle (sa fin précède son début).
    Retourne (données, plus forte réduction en dB, ≤ 0)."""
    gain = limit_envelope(data, threshold, samplerate, loop)
    if gain is None:
        return data, 0.0
    out = (data * gain[:, None]).astype(np.float32)
    return out, 20.0 * math.log10(float(gain.min()))


def limit_envelope(data, threshold, samplerate, loop=False):
    """Enveloppe de gain du limiteur (voir limit_peaks), un gain par
    échantillon ; None si aucune crête ne dépasse threshold. Calculée sur le
    mix, elle s'applique aussi à ses pistes séparées (E4, 2l1)."""
    n = len(data)
    peak = np.max(np.abs(data), axis=1).astype(np.float64) if n else np.zeros(0)
    if n == 0 or peak.max() <= threshold:
        return None
    a = max(1, round(LOOKAHEAD_S * samplerate))
    tau = RELEASE_S * samplerate
    before = a + int(5 * tau) if loop else 0           # passé : retour presque complet
    idx = np.arange(-before, n + a)
    if loop:
        ext = peak[idx % n]
    else:
        ext = np.zeros(len(idx))
        ext[before:before + n] = peak
    with np.errstate(divide="ignore"):
        req = np.minimum(1.0, threshold / ext)
    g = _sliding_min_forward(req, a + 1)               # crêtes des a prochains échantillons
    g = _release(g, tau)
    c = np.concatenate([np.zeros(1), np.cumsum(g)])    # moyenne sur [n - a + 1, n]
    lo = np.maximum(np.arange(len(g)) - a + 1, 0)
    avg = (c[np.arange(1, len(g) + 1)] - c[lo]) / (np.arange(len(g)) + 1 - lo)
    return np.minimum(avg, 1.0)[before:before + n]


def _biquad_response(b, a, w):
    """Réponse en fréquence d'un biquad (b0, b1, b2) / (1, a1, a2) aux
    pulsations w (radians par échantillon)."""
    z1, z2 = np.exp(-1j * w), np.exp(-2j * w)
    return (b[0] + b[1] * z1 + b[2] * z2) / (1.0 + a[0] * z1 + a[1] * z2)


def k_weighting(samplerate):
    """Coefficients des deux biquads de la pondération K (UIT-R BS.1770-4) à
    samplerate : filtre en plateau, puis passe-haut RLB. Formules de
    libebur128, exactes à 48 kHz. Retourne ((b, a), (b, a)), a = (a1, a2)."""
    f0, g, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = math.tan(math.pi * f0 / samplerate)
    vh = 10.0 ** (g / 20.0)
    vb = vh ** 0.4996667741545416
    a0 = 1.0 + k / q + k * k
    shelf = ((( vh + vb * k / q + k * k) / a0, 2.0 * (k * k - vh) / a0,
              (vh - vb * k / q + k * k) / a0),
             (2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0))
    f0, q = 38.13547087602444, 0.5003270373238773
    k = math.tan(math.pi * f0 / samplerate)
    a0 = 1.0 + k / q + k * k
    highpass = ((1.0, -2.0, 1.0),
                (2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0))
    return shelf, highpass


def _k_filter(x, samplerate, chunk=1 << 18):
    """Signal x (1-D) filtré par la pondération K, par FFT avec
    recouvrement-addition (la réponse impulsionnelle est tronquée à chunk
    échantillons : 6 s à 44,1 kHz, bien après son extinction). Sans scipy :
    la FFT évite une boucle Python par échantillon."""
    n = len(x)
    nfft = 2 * chunk
    w = 2.0 * math.pi * np.arange(nfft // 2 + 1) / nfft
    (b1, a1), (b2, a2) = k_weighting(samplerate)
    h = _biquad_response(b1, a1, w) * _biquad_response(b2, a2, w)
    y = np.zeros(n + nfft, dtype=np.float64)
    for start in range(0, n, chunk):
        seg = x[start:start + chunk].astype(np.float64)
        y[start:start + nfft] += np.fft.irfft(np.fft.rfft(seg, nfft) * h, nfft)
    return y[:n]


def loudness_lufs(data, samplerate):
    """Loudness intégrée (LUFS-I, UIT-R BS.1770-4) de data (frames, 2) :
    pondération K, blocs de 400 ms recouverts à 75 %, porte absolue à
    −70 LUFS puis porte relative à −10 LU. Un fichier plus court qu'un bloc
    compte pour un seul bloc. None : rien au-dessus de la porte absolue."""
    n = len(data)
    if n == 0:
        return None
    size = int(round(0.4 * samplerate))
    step = int(round(0.1 * samplerate))
    power = np.zeros(n, dtype=np.float64)
    for ch in range(data.shape[1]):               # G = 1 pour la gauche et la droite
        power += _k_filter(data[:, ch], samplerate) ** 2
    if n <= size:
        z = np.array([power.mean()])
    else:
        c = np.concatenate([np.zeros(1), np.cumsum(power)])
        starts = np.arange(0, n - size + 1, step)
        z = (c[starts + size] - c[starts]) / size
    with np.errstate(divide="ignore"):
        lj = -0.691 + 10.0 * np.log10(z)
    z = z[lj > -70.0]
    if len(z) == 0:
        return None
    rel = -0.691 + 10.0 * math.log10(z.mean()) - 10.0
    z = z[-0.691 + 10.0 * np.log10(z) > rel]
    return -0.691 + 10.0 * math.log10(z.mean())


def measure_level(data, measure, samplerate):
    """Niveau de data en dB selon measure : "peak" (dBFS crête), "rms"
    (dBFS, moyenne de x² sur les deux canaux) ou "lufs" (LUFS-I). None
    pour un silence."""
    if len(data) == 0:
        return None
    if measure == "peak":
        peak = float(np.max(np.abs(data)))
        return 20.0 * math.log10(peak) if peak > 0 else None
    if measure == "rms":
        ms = float(np.mean(data.astype(np.float64) ** 2))
        return 10.0 * math.log10(ms) if ms > 0 else None
    if measure == "lufs":
        return loudness_lufs(data, samplerate)
    raise ValueError(f"mesure inconnue : {measure}")


@dataclass
class Gain:
    """Gain d'un fichier (W10, W11) : normalisation (scaled : facteur
    appliqué, gain_db) puis enveloppe du limiteur (None : aucune crête).
    Calculé une fois sur le mix, il s'applique aussi tel quel à ses pistes
    séparées, de même longueur (E4, E13)."""
    scaled:   bool
    gain_db:  float
    envelope: object         # np.ndarray (n,) ou None
    limit_db: float

    def apply(self, data):
        if self.scaled:
            data = (data * 10.0 ** (self.gain_db / 20.0)).astype(np.float32)
        if self.envelope is not None:
            data = (data * self.envelope[:, None]).astype(np.float32)
        return data


def compute_gain(data, normalize=False, measure="lufs", level_db=LEVEL_DEFAULT,
                 peak_db=PEAK_DB, samplerate=Mixer.SAMPLERATE, loop=False):
    """Gain du fichier data (voir apply_gain), sans l'appliquer."""
    gain_db, scaled = 0.0, False
    if normalize:
        level = measure_level(data, measure, samplerate)
        if level is not None:
            gain_db, scaled = level_db - level, True
            data = (data * 10.0 ** (gain_db / 20.0)).astype(np.float32)
    peak = float(np.max(np.abs(data))) if len(data) else 0.0
    target = 10.0 ** (peak_db / 20.0)
    envelope = limit_envelope(data, target, samplerate, loop) if peak > target else None
    limit_db = 20.0 * math.log10(float(envelope.min())) if envelope is not None else 0.0
    return Gain(scaled, gain_db, envelope, limit_db)


def mix_gain(result, normalize=False, measure="lufs", level_db=LEVEL_DEFAULT):
    """Gain d'un rendu (RenderResult), limiteur circulaire s'il boucle :
    celui que write_wav appliquerait au mix, à passer à ses stems."""
    return compute_gain(result.data, normalize, measure, level_db,
                        samplerate=result.samplerate, loop=result.looped)


def apply_gain(data, normalize=False, measure="lufs", level_db=LEVEL_DEFAULT,
               peak_db=PEAK_DB, samplerate=Mixer.SAMPLERATE, loop=False):
    """Gain du fichier (W10, W11) : si normalize, le niveau mesuré (measure)
    est amené à level_db, vers le haut ou vers le bas ; puis, toujours, le
    limiteur tient les crêtes à peak_db (limit_peaks, circulaire si loop).
    Retourne (données, gain de normalisation en dB, réduction du limiteur
    en dB ≤ 0)."""
    gain = compute_gain(data, normalize, measure, level_db, peak_db, samplerate, loop)
    return gain.apply(data), gain.gain_db, gain.limit_db


def dither_tpdf(data, bits=16, rng=None):
    """Dither TPDF de ±1 LSB avant la réduction à bits bits (W4)."""
    rng = rng if rng is not None else np.random.default_rng()
    lsb = 1.0 / (2 ** (bits - 1))
    noise = (rng.random(data.shape) - rng.random(data.shape)) * lsb
    return (data + noise).astype(np.float32)


def write_wav(path, result, subtype="PCM_16", normalize=False, measure="lufs",
              level_db=LEVEL_DEFAULT, rng=None, gain=None):
    """Écrit result (RenderResult) en WAV stéréo à sa fréquence :
    normalisation au niveau visé si normalize, puis limiteur (apply_gain ;
    limiteur circulaire si result.looped), dither en 16 bits, écrêtage
    final de sécurité à ±1 pour les formats entiers. gain : Gain déjà
    calculé (celui du mix, pour une piste séparée de même longueur, E13),
    à la place de normalize, measure et level_db. Retourne (gain de
    normalisation en dB, réduction du limiteur en dB)."""
    if subtype not in SUBTYPES:
        raise ValueError(f"format inconnu : {subtype}")
    if gain is None:
        gain = mix_gain(result, normalize, measure, level_db)
    data, gain_db, limit_db = gain.apply(result.data), gain.gain_db, gain.limit_db
    if subtype == "PCM_16":
        data = dither_tpdf(data, 16, rng)
    if subtype != "FLOAT":
        data = np.clip(data, -1.0, 1.0)
    sf.write(path, data, result.samplerate, subtype=subtype, format="WAV")
    return gain_db, limit_db


# ---------------------------------------------------------------------------
# Pistes séparées (stems) — Phase 8 étape 2l1, docs/DESIGN.md § 2a (E3, E12)
# ---------------------------------------------------------------------------

def nonempty_tracks(patterns, tracks=None):
    """Pistes à rendre en stems : non vides dans au moins un des patterns,
    parmi tracks (None = toutes), dans l'ordre. Une piste muette ou hors
    solo donne un rendu silencieux, omis ensuite (is_silent)."""
    found = set()
    for pat in patterns:
        for t, lst in enumerate(_snapshot(pat)):
            if lst and (tracks is None or t in tracks):
                found.add(t)
    return sorted(found)


def is_silent(result):
    return not result.data.any()


def fit_length(result, n):
    """Rendu ramené à n échantillons (complété de silence ou coupé), pour
    qu'une piste séparée ait la longueur du mix et reçoive son gain (E13)."""
    data = result.data
    if len(data) < n:
        data = np.concatenate([data, np.zeros((n - len(data), data.shape[1]), np.float32)])
    elif len(data) > n:
        data = data[:n]
    return RenderResult(np.ascontiguousarray(data), result.samplerate, result.pattern_samples,
                        result.tail_samples, result.tail_cut, result.passes, result.looped)


def stem_folder(path):
    """Sous-dossier des stems (E3) : le chemin du fichier sans .wav."""
    return os.path.splitext(path)[0]


def stem_path(path, track, name=""):
    """Fichier du stem de la piste track (0-based) : dossier/base_NN_nom.wav,
    nom nettoyé, Track_NN s'il est vide (E3)."""
    folder = stem_folder(path)
    base = os.path.basename(folder)
    clean = re.sub(r"[^\w\-]+", "_", name or "").strip("_") or f"Track_{track + 1:02d}"
    return os.path.join(folder, f"{base}_{track + 1:02d}_{clean}.wav")

