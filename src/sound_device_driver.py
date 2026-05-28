#python3
"""
    File: src/sound_device_driver.py
    Moteur de playback audio polyphonique via sounddevice (PortAudio).
    Driver audio principal de l'application (remplace pygame.mixer).
    Date: Thu, 28/05/2026
    Author: Coolbrother
"""

import threading
import numpy as np
import soundfile as sf
import sounddevice as sd


# ---------------------------------------------------------------------------
# SdSound — sample chargé en mémoire
# ---------------------------------------------------------------------------

class SdSound:
    """
    Sample audio résidant en mémoire sous forme de tableau numpy float32 stéréo.
    Créé par SoundDeviceDriver.load() ou SoundDeviceDriver.make_silent().
    """
    __slots__ = ("data", "samplerate")

    def __init__(self, data: np.ndarray, samplerate: int):
        self.data       = data        # shape (N, 2), dtype float32
        self.samplerate = samplerate


# ---------------------------------------------------------------------------
# _Voice — instance de lecture en cours
# ---------------------------------------------------------------------------

class _Voice:
    """Une voix active (lecture d'un SdSound en cours)."""
    __slots__ = ("data", "pos", "vol_l", "vol_r")

    def __init__(self, data: np.ndarray, vol_l: float, vol_r: float):
        self.data  = data    # référence directe sur SdSound.data
        self.pos   = 0       # position courante en échantillons
        self.vol_l = vol_l
        self.vol_r = vol_r


# ---------------------------------------------------------------------------
# SoundDeviceDriver
# ---------------------------------------------------------------------------

class SoundDeviceDriver:
    """
    Moteur de playback polyphonique via sounddevice.

    Usage minimal
    -------------
    drv = SoundDeviceDriver()
    snd = drv.load("kick.wav")
    drv.play(snd, vol=0.9, pan=-20)
    drv.stop_all()
    drv.close()          # à l'arrêt de l'application

    Paramètres audio
    ----------------
    SAMPLERATE : 44 100 Hz
    BLOCKSIZE  : 512 échantillons (~11.6 ms de latence)
    CHANNELS   : 2 (stéréo)
    DTYPE      : float32

    Méthodes
    --------
    load(wav_path)          → SdSound   charge un WAV (resample si nécessaire)
    make_silent()           → SdSound   sample silencieux (pads vides)
    play(sound, vol, pan)               lecture polyphonique
    stop_all()                          stoppe toutes les voix
    set_master_volume(vol)              volume global (0..100 ou 0.0..1.0)
    close()                             ferme le flux PortAudio
    """

    SAMPLERATE = 44100
    BLOCKSIZE  = 512
    CHANNELS   = 2
    DTYPE      = "float32"

    def __init__(self, samplerate: int = SAMPLERATE, blocksize: int = BLOCKSIZE):
        self._sr         = samplerate
        self._blocksize  = blocksize
        self._voices: list[_Voice] = []
        self._lock       = threading.Lock()
        self._master_vol = 1.0

        self._stream = sd.OutputStream(
            samplerate = self._sr,
            blocksize  = self._blocksize,
            channels   = self.CHANNELS,
            dtype      = self.DTYPE,
            callback   = self._callback,
        )
        self._stream.start()

    # ------------------------------------------------------------------
    # Callback audio (thread PortAudio)
    # ------------------------------------------------------------------

    def _callback(self, outdata: np.ndarray, frames: int, time_info, status):
        """Mélange toutes les voix actives dans outdata (float32, shape (frames, 2))."""
        mix = np.zeros((frames, 2), dtype=np.float32)

        with self._lock:
            alive = []
            for v in self._voices:
                end   = v.pos + frames
                chunk = v.data[v.pos:end]
                n     = len(chunk)
                if n > 0:
                    mix[:n, 0] += chunk[:, 0] * v.vol_l
                    mix[:n, 1] += chunk[:, 1] * v.vol_r
                    v.pos = end
                if v.pos < len(v.data):
                    alive.append(v)
            self._voices = alive

        np.clip(mix * self._master_vol, -1.0, 1.0, out=outdata)

    # ------------------------------------------------------------------
    # Chargement
    # ------------------------------------------------------------------

    def load(self, wav_path: str) -> SdSound:
        """Charge un fichier WAV en mémoire.

        - Convertit en float32 stéréo.
        - Resample par interpolation linéaire si le taux diffère de SAMPLERATE.
        Retourne un SdSound prêt à être passé à play().
        """
        data, sr = sf.read(wav_path, dtype="float32", always_2d=True)

        # Mono → stéréo
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)

        # Resample si nécessaire
        if sr != self._sr:
            data = self._resample(data, sr, self._sr)

        return SdSound(data, self._sr)

    def _resample(self, data: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
        """Resample par interpolation linéaire (qualité acceptable pour un driver de base)."""
        ratio  = sr_out / sr_in
        n_out  = int(len(data) * ratio)
        x_in   = np.linspace(0, len(data) - 1, n_out)
        cols   = [
            np.interp(x_in, np.arange(len(data)), data[:, c])
            for c in range(data.shape[1])
        ]
        return np.column_stack(cols).astype(np.float32)

    def make_silent(self, duration_samples: int = 2) -> SdSound:
        """Crée un SdSound silencieux (remplace _silent_sound() de SoundManager)."""
        return SdSound(
            np.zeros((duration_samples, 2), dtype=np.float32),
            self._sr,
        )

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    def play(self, sound: SdSound, vol: float = 1.0, pan: int = 0):
        """Lance la lecture d'un SdSound de façon polyphonique.

        Paramètres
        ----------
        vol : float  0.0..1.0
        pan : int    -100 (gauche) .. 0 (centre) .. +100 (droite)
        """
        if sound is None or len(sound.data) == 0:
            return
        pan_norm = max(-1.0, min(1.0, pan / 100.0))
        vol_l    = vol * (1.0 - max(0.0, pan_norm))
        vol_r    = vol * (1.0 + min(0.0, pan_norm))
        with self._lock:
            self._voices.append(_Voice(sound.data, vol_l, vol_r))

    # ------------------------------------------------------------------
    # Contrôle
    # ------------------------------------------------------------------

    def stop_all(self):
        """Stoppe toutes les voix en cours de lecture."""
        with self._lock:
            self._voices.clear()

    def make_sound_from_array(self, data: np.ndarray, sr: int) -> "SdSound":
        """Convertit un tableau numpy en SdSound (float32 stéréo, resample si besoin)."""
        data = data.astype(np.float32)
        # Normalisation douce
        peak = np.max(np.abs(data))
        if peak > 0:
            data = data / peak * 0.5
        # Forcer stéréo
        if data.ndim == 1:
            data = np.column_stack([data, data])
        elif data.shape[1] == 1:
            data = np.column_stack([data[:, 0], data[:, 0]])
        elif data.shape[1] > 2:
            data = data[:, :2]
        # Resample si nécessaire
        if sr != self._sr:
            data = self._resample(data, sr, self._sr)
        return SdSound(data, self._sr)

    def stop_sound(self, sound: "SdSound"):
        """Arrête la lecture du SdSound donné (retire les voix correspondantes)."""
        with self._lock:
            self._voices = [v for v in self._voices if v.data is not sound.data]

    def set_sound_volume(self, sound, vol_norm: float):
        """No-op : le volume est appliqué au moment de play(), pas de façon persistante."""
        pass

    def set_master_volume(self, vol):
        """Règle le volume global.

        Accepte 0..100 (entier) ou 0.0..1.0 (float normalisé).
        """
        v = vol / 100.0 if vol > 1.0 else float(vol)
        self._master_vol = max(0.0, min(1.0, v))

    def voice_count(self) -> int:
        """Nombre de voix actuellement actives (utile pour les tests)."""
        with self._lock:
            return len(self._voices)

    def close(self):
        """Ferme le flux PortAudio (appeler à la fermeture de l'application)."""
        self._stream.stop()
        self._stream.close()
