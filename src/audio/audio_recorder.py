#python3
"""
    File: src/audio/audio_recorder.py
    Enregistrement d'une prise audio (Phase 8 étape 14f1, docs/DESIGN.md
    § Phase 8 étape 14f1 — point préalable) : flux d'entrée PortAudio séparé,
    blocs copiés dans une file par le callback de la carte, écrits en WAV
    24 bits par un fil à part ; datation du premier échantillon par l'heure
    de capture de la carte ramenée à l'horloge du lecteur ; placement de la
    prise dans le pattern (compensation de latence, fenêtre start / length).
    Prototype Python, cible C/C++ : fonctions pures sur des nombres
    (capture_time, place_take), une file de blocs (tampon circulaire en
    C/C++), aucun appel à l'interface.
    Date: Mon, 16/11/2026
    Author: Coolbrother
"""
import math
import queue
import threading
import time

import soundfile as sf

SUBTYPE = "PCM_24"          # WAV 24 bits (§ 14a A7)


# ---------------------------------------------------------------------------
# Datation et placement (fonctions pures)
# ---------------------------------------------------------------------------

def capture_time(now, stream_time, adc_time, frames, samplerate, in_latency=0.0):
    """Heure de capture (horloge du lecteur) du premier échantillon d'un bloc.
    now : horloge du lecteur à l'arrivée du bloc ; stream_time, adc_time :
    currentTime et inputBufferAdcTime de PortAudio (même horloge, celle du
    flux). Pilote qui ne les donne pas (0) : la durée du bloc et la latence
    d'entrée annoncée."""
    if adc_time and stream_time and stream_time >= adc_time:
        return now - (stream_time - adc_time)
    return now - frames / float(samplerate) - in_latency


def place_take(heard_at, frames, samplerate, t_start, measure_start, lp_start,
               secs_of, steps_of, window_end=None):
    """Placement d'une prise (§ 14f1, calage par la fenêtre de 14e3).
    heard_at : heure (horloge du lecteur) du moment de la lecture qu'on
    entendait quand le premier échantillon a été capté — heure de capture −
    latence de sortie − compensation manuelle ; t_start : début effectif de
    l'enregistrement (ce qui précède est sauté par start) ; measure_start :
    heure du pas lp_start ; secs_of(pas) → secondes, steps_of(secondes) →
    pas (carte de tempo) ; window_end : heure de fin de la fenêtre de boucle
    (la prise s'y arrête), None sans boucle.
    Retourne (pas de départ, start, length, pas de fin) — start et length en
    échantillons du fichier —, ou None si rien ne reste."""
    skip = max(0, int(math.ceil((t_start - heard_at) * samplerate - 1e-6)))
    last = frames
    if window_end is not None:
        last = min(frames, int(math.floor((window_end - heard_at) * samplerate + 1e-6)))
    length = last - skip
    if length <= 0:
        return None
    t_clip = heard_at + skip / float(samplerate)
    base = secs_of(lp_start)
    start_step = steps_of(base + (t_clip - measure_start))
    end_step = steps_of(base + (t_clip + length / float(samplerate) - measure_start))
    return start_step, skip, length, end_step


def bars_for(end_step, num_steps):
    """Nombre de mesures qu'il faut pour contenir une prise finissant au pas
    end_step (pattern allongé, R3)."""
    return max(1, int(math.ceil(end_step / float(num_steps) - 1e-9)))


# ---------------------------------------------------------------------------
# Prise
# ---------------------------------------------------------------------------

class TakeResult:
    """Prise terminée : fichier, nombre d'échantillons, heure de capture du
    premier (None si rien n'a été capté), fréquence, canaux."""
    __slots__ = ("path", "frames", "t0", "samplerate", "channels")

    def __init__(self, path, frames, t0, samplerate, channels):
        self.path, self.frames, self.t0 = path, frames, t0
        self.samplerate, self.channels = samplerate, channels


def _default_stream(**kwargs):
    import sounddevice as sd
    return sd.InputStream(**kwargs)


class AudioRecorder:
    """Une prise : start(chemin, …) puis stop() → TakeResult.
    stream_factory(**kwargs) → flux d'entrée (sd.InputStream par défaut),
    clock → horloge du lecteur (time.perf_counter)."""

    def __init__(self, stream_factory=None, clock=time.perf_counter):
        self._factory = stream_factory or _default_stream
        self._clock   = clock
        self._stream  = None
        self._thread  = None
        self._queue   = None
        self._file    = None
        self._path    = ""
        self._frames  = 0
        self._t0      = None
        self._sr      = 44100
        self._channels = 1
        self.errors   = []              # anomalies du flux (débordements…)
        self._in_latency = 0.0

    @property
    def active(self):
        return self._stream is not None

    def start(self, path, device=None, samplerate=44100, channels=1):
        """Ouvre le fichier et le flux d'entrée ; relève l'erreur de
        PortAudio ou du disque (rien ne reste ouvert)."""
        self._path, self._sr, self._channels = path, int(samplerate), int(channels)
        self._frames, self._t0, self.errors = 0, None, []
        self._queue = queue.Queue()
        self._file = sf.SoundFile(path, "w", self._sr, self._channels, SUBTYPE)
        self._thread = threading.Thread(target=self._write_loop, daemon=True)
        self._thread.start()
        try:
            stream = self._factory(device=device, samplerate=self._sr,
                                   channels=self._channels, dtype="float32",
                                   callback=self._callback)
            self._in_latency = float(getattr(stream, "latency", 0.0) or 0.0)
            stream.start()
        except Exception:
            self._finish_writer()
            raise
        self._stream = stream

    def _callback(self, indata, frames, time_info, status):
        """Thread de la carte : datation du premier bloc, copie dans la file
        (rien d'autre : pas d'écriture disque ici)."""
        if status:
            self.errors.append(str(status))
        if self._t0 is None:
            self._t0 = capture_time(self._clock(),
                                    getattr(time_info, "currentTime", 0.0),
                                    getattr(time_info, "inputBufferAdcTime", 0.0),
                                    frames, self._sr, self._in_latency)
        self._queue.put(indata.copy())

    def _write_loop(self):
        while True:
            block = self._queue.get()
            if block is None:
                return
            self._file.write(block)
            self._frames += len(block)

    def _finish_writer(self):
        if self._queue is not None:
            self._queue.put(None)
        if self._thread is not None:
            self._thread.join()
        if self._file is not None:
            self._file.close()
        self._thread = self._file = None

    def stop(self):
        """Arrête le flux, vide la file, ferme le fichier."""
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as e:          # carte débranchée en cours de prise
                self.errors.append(str(e))
        self._finish_writer()
        return TakeResult(self._path, self._frames, self._t0, self._sr, self._channels)
