"""Volume et pan de piste en temps réel (Phase 8 étape 18b1,
docs/DESIGN.md § Phase 8 étape 18a, V1-V6).

Registre « piste → voix en cours » du TrackRouter : chaque voix lancée sur
le Mixer pour une piste Wave, Kit ou audio y garde ses valeurs de départ
hors piste ; à un changement de volume ou de pan de la piste, ou du pan
global, son gain est recalculé avec la même formule qu'à son départ, et le
Mixer y va par une rampe courte (Mixer.set_voice_gain).

Formule (live_gain) :
    vol = facteur × volume de piste / 100, borné à 1 si cap,
          passé par la courbe GM si gm ;
    pan = pan de base + pan de piste (+ pan global − pan global au départ,
          si master_ref n'est pas None), borné à ±100.

Prototype, cible C/C++ : quelques nombres par voix, aucune allocation au
mixage ; les voix finies sont oubliées au fil des départs.
"""

import threading

from midi.midi_constants import gm_gain


class LiveVoice:
    """Une voix suivie : son Mixer, la voix, ses valeurs de départ hors piste."""
    __slots__ = ("mixer", "voice", "factor", "base_pan", "master_ref", "gm", "cap")

    def __init__(self, mixer, voice, factor, base_pan=0, master_ref=None,
                 gm=True, cap=False):
        self.mixer      = mixer
        self.voice      = voice
        self.factor     = float(factor)
        self.base_pan   = base_pan
        self.master_ref = master_ref
        self.gm         = gm
        self.cap        = cap


def live_gain(entry, track_volume, track_pan, master_pan):
    """(volume passé au Mixer, pan) d'une voix suivie, pour ces réglages."""
    vol = entry.factor * track_volume / 100.0
    if entry.cap:
        vol = min(1.0, vol)
    if entry.gm:
        vol = gm_gain(vol)
    pan = entry.base_pan + track_pan
    if entry.master_ref is not None:
        pan += master_pan - entry.master_ref
    return vol, max(-100, min(100, pan))


class TrackLiveMixMixin:

    LIVE_PRUNE_AT = 32      # voix gardées par piste avant d'oublier les finies

    def _init_live_mix(self):
        self._live_voices = {}              # piste → [LiveVoice]
        self._live_lock   = threading.Lock()

    def _track_voice(self, track_idx, mixer, voice, factor, base_pan=0,
                     master_ref=None, gm=True, cap=False):
        """Suit voice (lancée sur mixer pour la piste) ; rien sans voix."""
        if voice is None or mixer is None or not hasattr(mixer, "set_voice_gain"):
            return
        entry = LiveVoice(mixer, voice, factor, base_pan, master_ref, gm, cap)
        with self._live_lock:
            voices = self._live_voices.setdefault(track_idx, [])
            voices.append(entry)
            if len(voices) > self.LIVE_PRUNE_AT:
                self._live_voices[track_idx] = self._prune_live(voices)

    @staticmethod
    def _prune_live(voices):
        """Les voix qui sonnent encore (une lecture par Mixer)."""
        alive = {}
        for e in voices:
            if id(e.mixer) not in alive:
                alive[id(e.mixer)] = e.mixer.live_voice_ids()
        return [e for e in voices if id(e.voice) in alive[id(e.mixer)]]

    def live_voices(self, track_idx):
        """Voix suivies de la piste (copie), finies comprises jusqu'au tri."""
        with self._live_lock:
            return list(self._live_voices.get(track_idx, ()))

    def refresh_track_voices(self, track_idx=None):
        """Recalcule le gain des voix de la piste (de toutes sans piste) avec
        le volume et le pan courants ; les voix finies sont oubliées."""
        with self._live_lock:
            tracks = [track_idx] if track_idx is not None else list(self._live_voices)
            work = []
            for t in tracks:
                voices = self._live_voices.get(t)
                if not voices:
                    continue
                voices = self._prune_live(voices)
                self._live_voices[t] = voices
                work.append((t, voices))
        for t, voices in work:
            vol_t, pan_t = self._track_volumes[t], self._track_pans[t]
            for e in voices:
                vol, pan = live_gain(e, vol_t, pan_t, self.master_pan)
                e.mixer.set_voice_gain(e.voice, vol, pan)

    def forget_track_voices(self, track_idx=None):
        """Oublie les voix suivies (arrêt de tout, changement de projet)."""
        with self._live_lock:
            if track_idx is None:
                self._live_voices.clear()
            else:
                self._live_voices.pop(track_idx, None)
