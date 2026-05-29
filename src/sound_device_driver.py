#python3
"""
    File: src/sound_device_driver.py
    Moteur de playback audio polyphonique via sounddevice (PortAudio).
    Driver audio principal de l'application (remplace pygame.mixer).

    Deux types de voix :
      _Voice     : lecture one-shot d'un buffer pré-rendu
      _LoopVoice : boucle temps réel style FluidSynth — crossfade de quelques
                   samples au point de boucle, sans pre-rendu de buffer de sustain

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
    Si loop_start / loop_end sont renseignés, le driver crée une _LoopVoice
    (boucle temps réel) au lieu d'une _Voice (one-shot).
    """
    __slots__ = ("data", "samplerate", "loop_start", "loop_end", "xf_samples")

    def __init__(self, data: np.ndarray, samplerate: int,
                 loop_start: int = None, loop_end: int = None,
                 xf_samples: int = 8):
        self.data        = data          # shape (N, 2), dtype float32
        self.samplerate  = samplerate
        self.loop_start  = loop_start    # en échantillons (None = one-shot)
        self.loop_end    = loop_end      # en échantillons
        self.xf_samples  = xf_samples    # longueur crossfade en échantillons


# ---------------------------------------------------------------------------
# _Voice — lecture one-shot
# ---------------------------------------------------------------------------

class _Voice:
    """Une voix active (lecture d'un buffer pré-rendu en cours)."""
    __slots__ = ("data", "pos", "vol_l", "vol_r")

    def __init__(self, data: np.ndarray, vol_l: float, vol_r: float):
        self.data  = data
        self.pos   = 0
        self.vol_l = vol_l
        self.vol_r = vol_r


# ---------------------------------------------------------------------------
# _LoopVoice — boucle temps réel (style FluidSynth)
# ---------------------------------------------------------------------------

class _LoopVoice:
    """
    Voix bouclante FluidSynth-style.

    Lecture :
      - De pos=0 jusqu'à pos=le (attaque + déclin avant le point de boucle)
      - Puis boucle indéfiniment sur [ls, le)

    Crossfade au point de boucle :
      - Dans les xf derniers échantillons avant le (zone [le-xf, le)),
        on blende la position courante avec la position correspondante dans
        le cycle PRÉCÉDENT (pos - loop_len), soit data[ls-N:ls].
      - À pos=le-1 : output ≈ data[ls-1] → saut à data[ls] = enchaînement normal.
    """
    __slots__ = ("data", "pos", "ls", "le", "xf", "loop_len", "vol_l", "vol_r")

    def __init__(self, data: np.ndarray, ls: int, le: int,
                 xf: int, vol_l: float, vol_r: float):
        self.data     = data
        self.pos      = 0
        self.ls       = ls
        self.le       = le
        self.xf       = max(2, xf)
        self.loop_len = le - ls
        self.vol_l    = vol_l
        self.vol_r    = vol_r


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
    drv.close()

    Paramètres audio
    ----------------
    SAMPLERATE : 44 100 Hz
    BLOCKSIZE  : 512 échantillons (~11.6 ms de latence)
    CHANNELS   : 2 (stéréo)
    DTYPE      : float32

    Méthodes
    --------
    load(wav_path)                    → SdSound
    make_silent()                     → SdSound silencieux
    make_sound_from_array(data, sr)   → SdSound one-shot
    make_loop_sound(data, sr, ls, le) → SdSound bouclant
    play(sound, vol, pan)             → _Voice ou _LoopVoice selon sound
    stop_all()
    stop_sound(sound)
    set_master_volume(vol)
    voice_count()
    close()
    """

    SAMPLERATE = 44100
    BLOCKSIZE  = 512
    CHANNELS   = 2
    DTYPE      = "float32"

    def __init__(self, samplerate: int = SAMPLERATE, blocksize: int = BLOCKSIZE):
        self._sr          = samplerate
        self._blocksize   = blocksize
        self._voices: list[_Voice]     = []
        self._loop_voices: list[_LoopVoice] = []
        self._lock        = threading.Lock()
        self._master_vol  = 1.0

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
            # ── Voix one-shot ──────────────────────────────────────────
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

            # ── Voix bouclantes (FluidSynth-style) ────────────────────
            for v in self._loop_voices:
                self._mix_loop_voice(v, mix, frames)

        np.clip(mix * self._master_vol, -1.0, 1.0, out=outdata)

    def _mix_loop_voice(self, v: _LoopVoice,
                        mix: np.ndarray, frames: int):
        """Mélange une _LoopVoice dans mix (per-sample, style FluidSynth)."""
        data     = v.data
        n_data   = len(data)
        ls       = v.ls
        le       = v.le
        llen     = v.loop_len
        xf       = v.xf
        pos      = v.pos
        vl       = v.vol_l
        vr       = v.vol_r

        for i in range(frames):
            # Lecture de la position courante
            if pos < n_data:
                sl = data[pos, 0]
                sr = data[pos, 1]
            else:
                sl = sr = 0.0

            # Crossfade : zone [le-xf, le)
            dist = le - pos
            if 0 < dist <= xf:
                # alpha : 0 en début de zone, 1 juste avant le
                alpha = 1.0 - dist / xf
                prev  = pos - llen            # position dans le cycle précédent
                if 0 <= prev < n_data:
                    sl = sl * (1.0 - alpha) + data[prev, 0] * alpha
                    sr = sr * (1.0 - alpha) + data[prev, 1] * alpha

            mix[i, 0] += sl * vl
            mix[i, 1] += sr * vr

            # Avance et wrap
            pos += 1
            if pos >= le:
                pos = ls

        v.pos = pos

    # ------------------------------------------------------------------
    # Chargement
    # ------------------------------------------------------------------

    def load(self, wav_path: str) -> SdSound:
        """Charge un fichier WAV en mémoire (float32 stéréo, resample si besoin)."""
        data, sr = sf.read(wav_path, dtype="float32", always_2d=True)
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        if sr != self._sr:
            data = self._resample(data, sr, self._sr)
        return SdSound(data, self._sr)

    def _resample(self, data: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
        """Resample par interpolation linéaire."""
        ratio = sr_out / sr_in
        n_out = int(len(data) * ratio)
        x_in  = np.linspace(0, len(data) - 1, n_out)
        cols  = [
            np.interp(x_in, np.arange(len(data)), data[:, c])
            for c in range(data.shape[1])
        ]
        return np.column_stack(cols).astype(np.float32)

    def make_silent(self, duration_samples: int = 2) -> SdSound:
        """Crée un SdSound silencieux."""
        return SdSound(np.zeros((duration_samples, 2), dtype=np.float32), self._sr)

    def make_sound_from_array(self, data: np.ndarray, sr: int) -> SdSound:
        """Convertit un tableau numpy en SdSound one-shot (normalisation + stéréo)."""
        data = data.astype(np.float32)
        peak = np.max(np.abs(data))
        if peak > 0:
            data = data / peak * 0.5
        if data.ndim == 1:
            data = np.column_stack([data, data])
        elif data.shape[1] == 1:
            data = np.column_stack([data[:, 0], data[:, 0]])
        elif data.shape[1] > 2:
            data = data[:, :2]
        if sr != self._sr:
            data = self._resample(data, sr, self._sr)
        return SdSound(data, self._sr)

    def make_loop_sound(self, data: np.ndarray, sr: int,
                         loop_start: int, loop_end: int,
                         xf_samples: int = 8) -> SdSound:
        """Convertit un tableau numpy en SdSound bouclant (pour _LoopVoice).

        Paramètres
        ----------
        loop_start : int   premier échantillon de la zone de boucle
        loop_end   : int   dernier échantillon exclu (le)
        xf_samples : int   longueur du crossfade en échantillons (défaut 8)
        """
        data = data.astype(np.float32)
        peak = np.max(np.abs(data))
        if peak > 0:
            data = (data / peak * 0.5).astype(np.float32)
        if data.ndim == 1:
            data = np.column_stack([data, data])
        elif data.shape[1] == 1:
            data = np.column_stack([data[:, 0], data[:, 0]])
        elif data.shape[1] > 2:
            data = data[:, :2]
        if sr != self._sr:
            ratio      = self._sr / sr
            data       = self._resample(data, sr, self._sr)
            loop_start = int(loop_start * ratio)
            loop_end   = int(loop_end   * ratio)
        return SdSound(data, self._sr,
                       loop_start=loop_start,
                       loop_end=loop_end,
                       xf_samples=xf_samples)

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    def play(self, sound: SdSound, vol: float = 1.0, pan: int = 0):
        """Lance la lecture d'un SdSound.

        Si sound.loop_start est renseigné → crée une _LoopVoice (boucle infinie).
        Sinon → crée une _Voice (one-shot).
        """
        if sound is None or len(sound.data) == 0:
            return
        pan_norm = max(-1.0, min(1.0, pan / 100.0))
        vol_l    = vol * (1.0 - max(0.0, pan_norm))
        vol_r    = vol * (1.0 + min(0.0, pan_norm))
        with self._lock:
            if sound.loop_start is not None:
                self._loop_voices.append(
                    _LoopVoice(sound.data, sound.loop_start, sound.loop_end,
                               sound.xf_samples, vol_l, vol_r)
                )
            else:
                self._voices.append(_Voice(sound.data, vol_l, vol_r))

    # ------------------------------------------------------------------
    # Contrôle
    # ------------------------------------------------------------------

    def stop_all(self):
        """Stoppe toutes les voix (one-shot et bouclantes)."""
        with self._lock:
            self._voices.clear()
            self._loop_voices.clear()

    def stop_sound(self, sound: SdSound):
        """Arrête la lecture du SdSound donné (toutes les voix correspondantes)."""
        with self._lock:
            self._voices      = [v for v in self._voices
                                 if v.data is not sound.data]
            self._loop_voices = [v for v in self._loop_voices
                                 if v.data is not sound.data]

    def set_sound_volume(self, sound, vol_norm: float):
        """No-op : le volume est appliqué au moment de play()."""
        pass

    def set_master_volume(self, vol):
        """Volume global : 0..100 (entier) ou 0.0..1.0 (float)."""
        v = vol / 100.0 if vol > 1.0 else float(vol)
        self._master_vol = max(0.0, min(1.0, v))

    def voice_count(self) -> int:
        """Nombre total de voix actives (one-shot + bouclantes)."""
        with self._lock:
            return len(self._voices) + len(self._loop_voices)

    def loop_voice_count(self) -> int:
        """Nombre de voix bouclantes actives (utile pour les tests)."""
        with self._lock:
            return len(self._loop_voices)

    def close(self):
        """Ferme le flux PortAudio."""
        self._stream.stop()
        self._stream.close()
