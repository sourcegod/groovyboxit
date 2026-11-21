#python3
"""
    File: src/audio/input_monitor.py
    Monitoring de l'entrée audio (Phase 8 étape 20d1, docs/DESIGN.md
    § Phase 8 étape 20a, M5) : ce qui rentre par une entrée est rejoué tout
    de suite dans le mix, au volume et au pan de la piste.
    - un flux d'entrée PortAudio à petit bloc (BLOCKSIZE) remplit un tampon
      circulaire (feed) ; une source de rendu du Mixer le vide (render) ;
    - pendant une prise, le flux propre est fermé et les blocs viennent de
      l'AudioRecorder (crochet on_block) : un seul flux par entrée, ALSA en
      refuse souvent un second sur le même périphérique ;
    - dérive entre deux cartes : au-delà de MAX_LAG échantillons en attente,
      les plus anciens sont jetés (la latence ne grandit pas) ; tampon vide :
      silence jusqu'au retour de PRIME échantillons (pas de grésillement) ;
    - gain (volume, pan) par la loi et la rampe de 10 ms des voix du Mixer
      (pan_gains, étape 18) ; mono → les deux côtés.
    Sans wx. Prototype Python, cible C/C++ : tampon alloué au départ, aucune
    allocation dans le callback de la carte en C/C++ (ici, une copie par
    bloc, comme l'enregistreur).
    Date: Sat, 21/11/2026
    Author: Coolbrother
"""
import threading

import numpy as np

from audio.sound_device_driver import Mixer, pan_gains, _init_ramp, _block_gains


def _default_stream(**kwargs):
    import sounddevice as sd
    return sd.InputStream(**kwargs)


class _Gain:
    """Gain courant et visé (mêmes champs qu'une voix du Mixer)."""
    __slots__ = ("vol_l", "vol_r", "tgt_l", "tgt_r", "step_l", "step_r", "ramp")

    def __init__(self):
        self.vol_l = self.vol_r = 0.0
        _init_ramp(self)


class InputMonitor:
    """Tampon entrée → mix. start(device, channels) ouvre le flux propre,
    stop() le ferme ; feed(bloc) peut aussi venir de l'enregistreur ;
    render(mix) est branché par Mixer.add_render_source."""

    BLOCKSIZE = 256                 # flux d'entrée : ≈ 6 ms à 44,1 kHz
    CAPACITY  = 16384               # tampon circulaire (échantillons)
    MAX_LAG   = 3 * Mixer.BLOCKSIZE  # en attente au-delà : les plus anciens jetés
    PRIME     = BLOCKSIZE           # après un vide : silence jusqu'à ce niveau

    def __init__(self, samplerate=Mixer.SAMPLERATE, stream_factory=None):
        self._sr      = int(samplerate)
        self._factory = stream_factory or _default_stream
        self._stream  = None
        self._lock    = threading.Lock()
        self._buf     = np.zeros((self.CAPACITY, 2), dtype=np.float32)
        self._read    = 0           # indices absolus (modulo CAPACITY au tampon)
        self._write   = 0
        self._starved = True
        self._gain    = _Gain()
        self.errors   = []          # anomalies du flux (débordements…)
        self.dropped  = 0           # échantillons jetés (dérive, débordement)

    # -- flux propre ----------------------------------------------------

    @property
    def active(self):
        """Flux propre ouvert."""
        return self._stream is not None

    @property
    def samplerate(self):
        return self._sr

    def start(self, device=None, channels=1):
        """Ouvre le flux d'entrée (device : indice PortAudio, None = défaut) ;
        relève l'erreur de PortAudio (rien ne reste ouvert)."""
        self.stop()
        self.clear()
        stream = self._factory(device=device, samplerate=self._sr,
                               channels=max(1, min(2, int(channels))), dtype="float32",
                               blocksize=self.BLOCKSIZE, latency="low",
                               callback=self._callback)
        try:
            stream.start()
        except Exception:
            try:
                stream.close()
            except Exception:
                pass
            raise
        self._stream = stream

    def stop(self):
        """Ferme le flux propre (le tampon garde ce qui reste à jouer)."""
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as e:          # carte débranchée
                self.errors.append(str(e))

    def _callback(self, indata, frames, time_info, status):
        if status:
            self.errors.append(str(status))
        self.feed(indata)

    # -- tampon -----------------------------------------------------------

    def clear(self):
        with self._lock:
            self._read = self._write = 0
            self._starved = True

    def pending(self):
        """Échantillons en attente d'être joués."""
        with self._lock:
            return self._write - self._read

    def feed(self, block):
        """Bloc (trames, 1 ou 2 canaux) ajouté au tampon — thread de la carte
        (flux propre ou enregistreur). Au-delà de MAX_LAG en attente, les
        plus anciens échantillons sont jetés."""
        block = np.asarray(block, dtype=np.float32)
        if block.ndim == 1:
            block = block[:, None]
        n = len(block)
        if n == 0:
            return
        if n > self.CAPACITY:
            self.dropped += n - self.CAPACITY
            block, n = block[-self.CAPACITY:], self.CAPACITY
        left = block[:, 0]
        right = block[:, 1] if block.shape[1] >= 2 else left
        with self._lock:
            pos = self._write % self.CAPACITY
            first = min(n, self.CAPACITY - pos)
            self._buf[pos:pos + first, 0] = left[:first]
            self._buf[pos:pos + first, 1] = right[:first]
            if first < n:
                self._buf[:n - first, 0] = left[first:]
                self._buf[:n - first, 1] = right[first:]
            self._write += n
            excess = self._write - self._read - self.MAX_LAG
            if excess > 0:
                self._read += excess
                self.dropped += excess

    # -- gain ---------------------------------------------------------------

    def set_gain(self, vol, pan=0):
        """Volume (rapport, 1.0 = 100 %) et pan −100..100 visés ; le mix y va
        par une rampe de Mixer.GAIN_RAMP_MS."""
        tl, tr = pan_gains(max(0.0, float(vol)), pan)
        g = self._gain
        with self._lock:
            if (tl, tr) == (g.tgt_l, g.tgt_r):
                return
            n = max(1, int(self._sr * Mixer.GAIN_RAMP_MS / 1000))
            g.tgt_l, g.tgt_r = tl, tr
            g.step_l = (tl - g.vol_l) / n
            g.step_r = (tr - g.vol_r) / n
            g.ramp = n

    def target_gain(self):
        """(gauche, droite) visés."""
        return self._gain.tgt_l, self._gain.tgt_r

    # -- rendu ----------------------------------------------------------------

    def render(self, mix):
        """Source de rendu du Mixer : ajoute à mix (frames, 2) ce qui est en
        attente, au gain courant ; silence (et rien de consommé) tant que le
        tampon n'a pas retrouvé PRIME échantillons après un vide."""
        frames = len(mix)
        with self._lock:
            avail = self._write - self._read
            if self._starved:
                if avail < self.PRIME:
                    _block_gains(self._gain, frames)            # la rampe avance
                    return
                self._starved = False
            n = min(frames, avail)
            pos = self._read % self.CAPACITY
            first = min(n, self.CAPACITY - pos)
            chunk = np.empty((n, 2), dtype=np.float32)
            chunk[:first] = self._buf[pos:pos + first]
            if first < n:
                chunk[first:] = self._buf[:n - first]
            self._read += n
            if n < frames:
                self._starved = True
            gl, gr = _block_gains(self._gain, frames)
        if n == 0:
            return
        gl = gl[:n] if isinstance(gl, np.ndarray) else gl
        gr = gr[:n] if isinstance(gr, np.ndarray) else gr
        mix[:n, 0] += chunk[:, 0] * gl
        mix[:n, 1] += chunk[:, 1] * gr
