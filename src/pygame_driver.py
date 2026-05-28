#python3
"""
    File: src/pygame_driver.py
    Driver audio pygame.mixer — backend optionnel / legacy.
    Même interface que SoundDeviceDriver. Conservé pour référence et tests ;
    n'est plus le driver par défaut de l'application (remplacé par SoundDeviceDriver).
    Date: Thu, 28/05/2026
    Author: Coolbrother
"""

import numpy as np
import pygame


class PygameDriver:
    """
    Backend audio basé sur pygame.mixer.

    Interface
    ---------
    load(wav_path)              → pygame.Sound
    make_silent()               → pygame.Sound silencieux
    play(sound, vol, pan)       → lecture polyphonique
    set_sound_volume(sound, v)  → volume persistant sur un son (0.0..1.0)
    set_master_volume(vol)      → no-op (pygame n'a pas de master vol global)
    stop_all()                  → pygame.mixer.stop()
    close()                     → no-op
    """

    def __init__(self):
        pygame.init()
        self._mixer_freq = None   # détecté au premier make_sound_from_array

    # ------------------------------------------------------------------
    # Chargement
    # ------------------------------------------------------------------

    def load(self, wav_path: str) -> pygame.mixer.Sound:
        """Charge un fichier WAV et retourne un pygame.Sound."""
        return pygame.mixer.Sound(wav_path)

    def make_silent(self) -> pygame.mixer.Sound:
        """Retourne un pygame.Sound silencieux (1 frame stéréo)."""
        arr = np.zeros((2, 2), dtype=np.int16)
        return pygame.sndarray.make_sound(arr)

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    def play(self, sound: pygame.mixer.Sound, vol: float = 1.0, pan: int = 0):
        """Joue un pygame.Sound avec volume et panoramique.

        vol : float  0.0..1.0
        pan : int    -100..+100
        """
        channel = sound.play()
        if channel is not None and (vol != 1.0 or pan != 0):
            pan_norm = pan / 100.0
            left  = vol * (1.0 - max(0.0, pan_norm))
            right = vol * (1.0 + min(0.0, pan_norm))
            channel.set_volume(left, right)

    # ------------------------------------------------------------------
    # Contrôle du volume
    # ------------------------------------------------------------------

    def make_sound_from_array(self, data: np.ndarray, sr: int) -> pygame.mixer.Sound:
        """Convertit un tableau numpy en pygame.Sound (resampling + int16 + stéréo)."""
        if self._mixer_freq is None:
            self._mixer_freq, _, _ = pygame.mixer.get_init()
            pygame.mixer.set_num_channels(32)
        # Resampling si le taux diffère du mixer
        if sr != self._mixer_freq and self._mixer_freq:
            ratio = self._mixer_freq / sr
            n_out = max(1, round(len(data) * ratio))
            if data.ndim == 1:
                data = np.interp(
                    np.linspace(0, len(data) - 1, n_out),
                    np.arange(len(data)), data,
                )
            else:
                data = np.column_stack([
                    np.interp(np.linspace(0, len(data) - 1, n_out),
                              np.arange(len(data)), data[:, ch])
                    for ch in range(data.shape[1])
                ])
        # Normalisation douce
        peak = np.max(np.abs(data))
        if peak > 0:
            data = data / peak * 0.5
        arr = (data * 32767).clip(-32768, 32767).astype(np.int16)
        # Forcer stéréo
        if arr.ndim == 1:
            arr = np.column_stack([arr, arr])
        elif arr.shape[1] == 1:
            arr = np.column_stack([arr[:, 0], arr[:, 0]])
        elif arr.shape[1] > 2:
            arr = arr[:, :2]
        return pygame.sndarray.make_sound(np.ascontiguousarray(arr))

    def stop_sound(self, sound: pygame.mixer.Sound):
        """Arrête la lecture du pygame.Sound donné."""
        sound.stop()

    def set_sound_volume(self, sound: pygame.mixer.Sound, vol_norm: float):
        """Règle le volume d'un son de façon persistante (0.0..1.0)."""
        sound.set_volume(vol_norm)

    def set_master_volume(self, vol):
        """No-op : pygame n'expose pas de volume maître global."""
        pass

    # ------------------------------------------------------------------
    # Contrôle
    # ------------------------------------------------------------------

    def stop_all(self):
        """Stoppe tous les sons en cours (pygame.mixer.stop)."""
        pygame.mixer.stop()

    def close(self):
        """No-op : pygame est géré globalement par l'application."""
        pass
