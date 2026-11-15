#python3
"""
    File: src/audio/track_audio_clips.py
    Mixin TrackRouter — lecture des clips audio des pistes audio (Phase 8
    étape 14d1, docs/DESIGN.md § Phase 8 étape 14a A8, A9, A13).
    Un clip (ETYPE_AUDIO) est rejoué à vitesse réelle depuis son pas de
    départ, comme une voix one-shot du Mixer (même chemin à l'écoute et au
    rendu WAV) ; volume, pan, Mute et Solo de la piste ; commencé au bon
    endroit quand la lecture part du milieu du clip.
    - audio_resolver(chemin relatif) → chemin absolu, fourni par la fenêtre
      (dossier du .gvp) ; None : chemins pris tels quels ;
    - fichiers lus une fois (cache par chemin et date de modification) ;
    - un clip qui sonne n'est pas relancé par un événement « en cours »
      (décalage > 0) ; un départ normal (décalage 0, nouveau passage de
      boucle) coupe l'ancienne voix du même clip ;
    - Stop, Mute / Solo, changement de type de piste, Panic : voix coupées.
    Date: Sun, 15/11/2026
    Author: Coolbrother
"""
import os

import numpy as np
import soundfile as sf

from audio.sound_device_driver import SdSound

TRACK_AUDIO = "audio"


class TrackAudioMixin:

    def _init_audio_clips(self):
        self.audio_resolver = None
        self._clip_cache    = {}      # chemin absolu → (date, SdSound)
        self._clip_voices   = {}      # id du clip → (piste, voix)
        self.audio_status   = []      # fichiers introuvables déjà signalés

    # ------------------------------------------------------------------
    # Fichiers
    # ------------------------------------------------------------------

    def _clip_path(self, rel):
        resolver = getattr(self, "audio_resolver", None)
        return resolver(rel) if resolver is not None else rel

    def clip_sound(self, rel):
        """SdSound du fichier du clip (stéréo float32, à la fréquence du
        pilote), lu une fois ; None si le fichier manque ou est illisible
        (signalé une fois)."""
        path = self._clip_path(rel)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            self._clip_missing(rel)
            return None
        cached = self._clip_cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        try:
            data, sr = sf.read(path, dtype="float32", always_2d=True)
        except (RuntimeError, OSError, sf.LibsndfileError):
            self._clip_missing(rel)
            return None
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        data = np.ascontiguousarray(data[:, :2])
        target = self._clip_samplerate()
        if sr != target and len(data):
            n_out = max(1, int(round(len(data) * target / sr)))
            x = np.linspace(0, len(data) - 1, n_out)
            data = np.column_stack([np.interp(x, np.arange(len(data)), data[:, c])
                                    for c in range(2)]).astype(np.float32)
        sound = SdSound(data, target)
        self._clip_cache[path] = (mtime, sound)
        return sound

    def _clip_samplerate(self):
        driver = getattr(self, "_driver", None)
        return getattr(driver, "samplerate", 44100) if driver is not None else 44100

    def _clip_missing(self, rel):
        if rel not in self.audio_status:
            self.audio_status.append(rel)
            if self._status_cb:
                self._status_cb(f"Prise audio introuvable : {rel}")

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    def on_audio_clip(self, track_idx, rel, gain=1.0, clip_id=None, offset=0.0):
        """Joue le clip (Phase 8 étape 14d1) ; offset : secondes déjà passées
        du clip (lecture partie du milieu). Rien sur une piste qui n'est pas
        audio, muette ou hors solo, ni sans pilote."""
        driver = getattr(self, "_driver", None)
        if driver is None or not self._track_is_audible(track_idx):
            return None
        kinds = getattr(self, "_track_kinds", None)
        if not kinds or kinds[track_idx] != TRACK_AUDIO:
            return None
        playing = self._clip_voices.get(clip_id)
        if offset > 0 and playing is not None and self._voice_alive(playing[1]):
            return None                       # déjà en train de sonner
        sound = self.clip_sound(rel)
        if sound is None:
            return None
        start = int(round(offset * sound.samplerate))
        if start >= len(sound.data):
            return None                       # clip déjà fini à cette position
        if playing is not None:               # nouveau départ : l'ancienne voix s'arrête
            driver.stop_voice(playing[1])
        vol = max(0.0, float(gain)) * self._track_volumes[track_idx] / 100.0
        voice = driver.play(sound, vol, self._track_pans[track_idx])
        if voice is None:
            return None
        voice.pos = float(start)
        self._clip_voices[clip_id] = (track_idx, voice)
        return voice

    def _voice_alive(self, voice):
        driver = getattr(self, "_driver", None)
        voices = getattr(driver, "_voices", None)
        if voices is None:
            return voice.pos < len(voice.data)
        return any(v is voice for v in voices)

    def stop_audio_clips(self, track_idx=None):
        """Coupe les clips qui sonnent — d'une piste, ou de toutes."""
        driver = getattr(self, "_driver", None)
        voices = getattr(self, "_clip_voices", None) or {}
        for clip_id, (t, voice) in list(voices.items()):
            if track_idx is None or t == track_idx:
                if driver is not None:
                    driver.stop_voice(voice)
                del voices[clip_id]

    def clip_duration_secs(self, rel):
        """Durée du fichier d'un clip en secondes (0 si introuvable)."""
        sound = self.clip_sound(rel)
        return len(sound.data) / sound.samplerate if sound is not None else 0.0
