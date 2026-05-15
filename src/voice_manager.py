class Voice:
    def __init__(self):
        self.volume   = 100   # 0-100
        self.velocity = 100   # 0-127 (réservé MIDI / sounddevice)
        self.pan      = 0     # -100 (gauche) … 0 (centre) … +100 (droite)
        self.mute     = False
        self.solo     = False


class VoiceManager:
    def __init__(self, num_pads=16):
        self._num_pads = num_pads
        self._voices   = [Voice() for _ in range(num_pads)]

    # ------------------------------------------------------------------
    # Lecture d'état

    def is_audible(self, pad_idx):
        """True si le pad doit produire du son (solo/mute pris en compte)."""
        v = self._voices[pad_idx]
        if v.mute:
            return False
        if any(vx.solo for vx in self._voices):
            return v.solo
        return True

    def get_volume_factor(self, pad_idx):
        """Facteur de volume 0.0–1.0."""
        return self._voices[pad_idx].volume / 100.0

    def get_pan(self, pad_idx):
        return self._voices[pad_idx].pan

    def get_velocity(self, pad_idx):
        return self._voices[pad_idx].velocity

    def get_voice(self, pad_idx):
        return self._voices[pad_idx]

    # ------------------------------------------------------------------
    # Setters avec validation

    def set_volume(self, pad_idx, value):
        self._voices[pad_idx].volume = max(0, min(100, int(value)))

    def set_velocity(self, pad_idx, value):
        self._voices[pad_idx].velocity = max(0, min(127, int(value)))

    def set_pan(self, pad_idx, value):
        self._voices[pad_idx].pan = max(-100, min(100, int(value)))

    def set_mute(self, pad_idx, value):
        self._voices[pad_idx].mute = bool(value)

    def set_solo(self, pad_idx, value):
        self._voices[pad_idx].solo = bool(value)

    def toggle_mute(self, pad_idx):
        self._voices[pad_idx].mute = not self._voices[pad_idx].mute
        return self._voices[pad_idx].mute

    def toggle_solo(self, pad_idx):
        self._voices[pad_idx].solo = not self._voices[pad_idx].solo
        return self._voices[pad_idx].solo

    # ------------------------------------------------------------------
    # Utilitaires

    def reset(self):
        for v in self._voices:
            v.volume   = 100
            v.velocity = 100
            v.pan      = 0
            v.mute     = False
            v.solo     = False

    def reset_pad(self, pad_idx):
        v = self._voices[pad_idx]
        v.volume   = 100
        v.velocity = 100
        v.pan      = 0
        v.mute     = False
        v.solo     = False

    def set_mute_all(self, value):
        for v in self._voices:
            v.mute = bool(value)

    def set_solo_all(self, value):
        for v in self._voices:
            v.solo = bool(value)

    def any_solo(self):
        return any(v.solo for v in self._voices)

    def any_mute(self):
        return any(v.mute for v in self._voices)

    def solo_pads(self):
        return [i for i, v in enumerate(self._voices) if v.solo]

    def muted_pads(self):
        return [i for i, v in enumerate(self._voices) if v.mute]
