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

import math
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
    """Une voix active (lecture one-shot avec interpolation linéaire).
    phase_incr=1.0 → lecture normale ; >1.0 → plus aigu ; <1.0 → plus grave.
    Modifiable depuis le thread principal (GIL garantit l'atomicité float)."""
    __slots__ = ("data", "pos", "vol_l", "vol_r", "phase_incr",
                 "lfo_depth", "lfo_phase", "lfo_freq")

    def __init__(self, data: np.ndarray, vol_l: float, vol_r: float,
                 phase_incr: float = 1.0, lfo_depth: float = 0.0,
                 lfo_freq: float = 5.0):
        self.data        = data
        self.pos         = 0.0       # position flottante dans data
        self.vol_l       = vol_l
        self.vol_r       = vol_r
        self.phase_incr  = phase_incr
        self.lfo_depth   = lfo_depth  # amplitude LFO (0=off) ; modifiable depuis thread principal
        self.lfo_phase   = 0.0        # phase LFO courante (radians)
        self.lfo_freq    = lfo_freq   # fréquence LFO en Hz


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

    Release :
      - Déclenché par stop_sound() → releasing=True
      - Fondu linéaire sur rel_len échantillons, puis la voix est retirée.
    """
    __slots__ = ("data", "pos", "ls", "le", "xf", "loop_len", "vol_l", "vol_r",
                 "releasing", "rel_pos", "rel_len", "phase_incr",
                 "lfo_depth", "lfo_phase", "lfo_freq")

    def __init__(self, data: np.ndarray, ls: int, le: int,
                 xf: int, vol_l: float, vol_r: float,
                 phase_incr: float = 1.0, lfo_depth: float = 0.0,
                 lfo_freq: float = 5.0):
        self.data       = data
        self.pos        = 0.0        # position flottante dans data
        self.ls         = float(ls)
        self.le         = float(le)
        self.xf         = float(max(2, xf))
        self.loop_len   = float(le - ls)
        self.vol_l      = vol_l
        self.vol_r      = vol_r
        self.releasing  = False
        self.rel_pos    = 0
        self.rel_len    = 0
        self.phase_incr = phase_incr
        self.lfo_depth  = lfo_depth  # amplitude LFO (0=off) ; modifiable depuis thread principal
        self.lfo_phase  = 0.0        # phase LFO courante (radians)
        self.lfo_freq   = lfo_freq   # fréquence LFO en Hz


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

    SAMPLERATE    = 44100
    BLOCKSIZE     = 512
    CHANNELS      = 2
    DTYPE         = "float32"
    END_FADE_MS   = 20    # fondu de fin baked dans les sons one-shot (ms)
    RELEASE_MS    = 80    # durée du release des voix bouclantes après stop() (ms)
    LFO_DEPTH_MAX = 2.0 ** (2.0 / 12.0) - 1.0  # ±2 semitones à mod_wheel=127

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
            # ── Voix one-shot (interpolation linéaire vectorisée) ──────
            alive = []
            for v in self._voices:
                self._mix_voice(v, mix, frames)
                if v.pos < len(v.data):
                    alive.append(v)
            self._voices = alive

            # ── Voix bouclantes (FluidSynth-style) ────────────────────
            alive_lv = []
            for v in self._loop_voices:
                self._mix_loop_voice(v, mix, frames)
                if not v.releasing or v.rel_pos < v.rel_len:
                    alive_lv.append(v)
            self._loop_voices = alive_lv

        np.clip(mix * self._master_vol, -1.0, 1.0, out=outdata)

    def _mix_voice(self, v: _Voice, mix: np.ndarray, frames: int):
        """Mélange une _Voice dans mix (vectorisé, interp linéaire, phase_incr variable)."""
        n_src = len(v.data)
        if n_src < 2:
            return
        # LFO vibrato : valeur constante sur le bloc (LFO ≈5 Hz << sr, approximation correcte)
        lfo_val  = v.lfo_depth * math.sin(v.lfo_phase)
        eff_incr = v.phase_incr * (1.0 + lfo_val)
        v.lfo_phase = (v.lfo_phase + 2.0 * math.pi * v.lfo_freq * frames / self._sr) % (2.0 * math.pi)
        # positions source pour chaque frame de sortie
        src = v.pos + np.arange(frames, dtype=np.float64) * eff_incr
        ip  = src.astype(np.int32)
        valid = (ip >= 0) & (ip < n_src - 1)
        if not np.any(valid):
            v.pos = float(src[-1]) + eff_incr
            return
        ip_c  = np.where(valid, ip, 0)
        ip_c1 = np.minimum(ip_c + 1, n_src - 1)
        frac  = (src - ip).astype(np.float32)
        frac  = np.where(valid, frac, 0.0).astype(np.float32)
        sl = v.data[ip_c, 0] + (v.data[ip_c1, 0] - v.data[ip_c, 0]) * frac
        sr = v.data[ip_c, 1] + (v.data[ip_c1, 1] - v.data[ip_c, 1]) * frac
        sl[~valid] = 0.0
        sr[~valid] = 0.0
        mix[:, 0] += sl * v.vol_l
        mix[:, 1] += sr * v.vol_r
        v.pos = float(src[-1]) + eff_incr

    def _mix_loop_voice(self, v: _LoopVoice,
                        mix: np.ndarray, frames: int):
        """Mélange une _LoopVoice dans mix (per-sample, interp linéaire, phase_incr variable)."""
        data        = v.data
        n_data      = len(data)
        ls          = v.ls
        le          = v.le
        llen        = v.loop_len
        xf          = v.xf
        pos         = v.pos        # float
        phase_incr  = v.phase_incr # float, modifiable depuis le thread principal
        vl          = v.vol_l
        vr          = v.vol_r
        releasing   = v.releasing
        rel_pos     = v.rel_pos
        rel_len     = v.rel_len
        lfo_depth   = v.lfo_depth  # float, modifiable depuis le thread principal
        lfo_phase   = v.lfo_phase
        lfo_incr    = 2.0 * math.pi * v.lfo_freq / self._sr
        use_lfo     = lfo_depth != 0.0

        for i in range(frames):
            if releasing and rel_pos >= rel_len:
                break

            # Interpolation linéaire à position flottante
            ip   = int(pos)
            frac = pos - ip
            if ip + 1 < n_data:
                sl = data[ip, 0] + (data[ip + 1, 0] - data[ip, 0]) * frac
                sr = data[ip, 1] + (data[ip + 1, 1] - data[ip, 1]) * frac
            elif ip < n_data:
                sl = data[ip, 0]
                sr = data[ip, 1]
            else:
                sl = sr = 0.0

            # Crossfade : zone [le-xf, le)
            dist = le - pos
            if 0 < dist <= xf:
                alpha = 1.0 - dist / xf
                prev  = pos - llen
                ip_p  = int(prev)
                fr_p  = prev - ip_p
                if ip_p + 1 < n_data and ip_p >= 0:
                    pl = data[ip_p, 0] + (data[ip_p + 1, 0] - data[ip_p, 0]) * fr_p
                    pr = data[ip_p, 1] + (data[ip_p + 1, 1] - data[ip_p, 1]) * fr_p
                    sl = sl * (1.0 - alpha) + pl * alpha
                    sr = sr * (1.0 - alpha) + pr * alpha

            # Enveloppe de release
            if releasing:
                gain     = 1.0 - rel_pos / rel_len
                rel_pos += 1
            else:
                gain = 1.0

            mix[i, 0] += sl * vl * gain
            mix[i, 1] += sr * vr * gain

            # LFO vibrato : modulation per-sample (qualité maximale)
            if use_lfo:
                eff_incr   = phase_incr * (1.0 + lfo_depth * math.sin(lfo_phase))
                lfo_phase += lfo_incr
            else:
                eff_incr = phase_incr

            pos += eff_incr
            if pos >= le:
                # wrap avec gestion du dépassement (phase_incr > 1 possible)
                pos = ls + (pos - le) % llen

        v.pos      = pos
        v.rel_pos  = rel_pos
        if use_lfo:
            v.lfo_phase = lfo_phase % (2.0 * math.pi)

    # ------------------------------------------------------------------
    # Chargement
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_end_fade(data: np.ndarray, fade_ms: float, sr: int) -> np.ndarray:
        """Fondu de sortie linéaire baked sur les dernières fade_ms ms du buffer."""
        n = min(int(fade_ms / 1000 * sr), len(data))
        if n < 2:
            return data
        data = data.copy()
        data[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)[:, np.newaxis]
        return data

    def load(self, wav_path: str) -> SdSound:
        """Charge un fichier WAV en mémoire (float32 stéréo, resample si besoin)."""
        data, sr = sf.read(wav_path, dtype="float32", always_2d=True)
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        if sr != self._sr:
            data = self._resample(data, sr, self._sr)
        data = self._apply_end_fade(data, self.END_FADE_MS, self._sr)
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
        data = self._apply_end_fade(data, self.END_FADE_MS, self._sr)
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

    def play(self, sound: SdSound, vol: float = 1.0, pan: int = 0,
             phase_incr: float = 1.0, lfo_depth: float = 0.0):
        """Lance la lecture d'un SdSound. Retourne la voix créée (_Voice ou _LoopVoice).

        phase_incr : vitesse de lecture (1.0=normal, 2^(1/12)≈1.0595 = +1 demi-ton).
        lfo_depth  : amplitude LFO vibrato (0=off, LFO_DEPTH_MAX=±0.5 st à 5 Hz).
        La voix retournée permet de modifier phase_incr/lfo_depth après coup.
        """
        if sound is None or len(sound.data) == 0:
            return None
        pan_norm = max(-1.0, min(1.0, pan / 100.0))
        vol_l    = vol * (1.0 - max(0.0, pan_norm))
        vol_r    = vol * (1.0 + min(0.0, pan_norm))
        with self._lock:
            if sound.loop_start is not None:
                voice = _LoopVoice(sound.data, sound.loop_start, sound.loop_end,
                                   sound.xf_samples, vol_l, vol_r, phase_incr, lfo_depth)
                self._loop_voices.append(voice)
            else:
                voice = _Voice(sound.data, vol_l, vol_r, phase_incr, lfo_depth)
                self._voices.append(voice)
        return voice

    # ------------------------------------------------------------------
    # Contrôle
    # ------------------------------------------------------------------

    def stop_all(self):
        """Stoppe toutes les voix (one-shot et bouclantes)."""
        with self._lock:
            self._voices.clear()
            self._loop_voices.clear()

    def stop_sound(self, sound: SdSound):
        """Stoppe un SdSound par correspondance de données (compatibilité SoundManager)."""
        with self._lock:
            self._voices = [v for v in self._voices
                            if v.data is not sound.data]
            rel_len = int(self.RELEASE_MS / 1000 * self._sr)
            for v in self._loop_voices:
                if v.data is sound.data and not v.releasing:
                    v.releasing = True
                    v.rel_pos   = 0
                    v.rel_len   = rel_len

    def stop_voice(self, voice):
        """Stoppe une voix par référence directe (utilisé par SynthEngine)."""
        with self._lock:
            if isinstance(voice, _Voice):
                self._voices = [v for v in self._voices if v is not voice]
            elif isinstance(voice, _LoopVoice) and not voice.releasing:
                rel_len        = int(self.RELEASE_MS / 1000 * self._sr)
                voice.releasing = True
                voice.rel_pos   = 0
                voice.rel_len   = rel_len

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
